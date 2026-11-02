from typing import List
import json
from langchain_groq import ChatGroq
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from typing import List, Dict
import requests
import json
import re
from typing import List


llm = ChatGroq(
    model="openai/gpt-oss-20b",
    api_key="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",
    temperature=0,
    max_tokens=300
)

def extract_parts_from_content(
    content: str
) -> List[str]:

    prompt = f"""
Extract all physical engineering components
mentioned in the procedure below.

Rules:
- Return only physical parts/components.
- Ignore actions and instructions.
- Ignore warnings and operating modes.
- Return JSON only.

Format:

{{
  "parts": [
    "part1",
    "part2"
  ]
}}

Procedure:
{content}
"""

    response = llm.invoke(prompt)

    raw_response = response.content.strip()

    try:

        data = json.loads(raw_response)

        return sorted(
            list(
                set(
                    p.strip().lower()
                    for p in data.get("parts", [])
                )
            )
        )

    except Exception as e:

        print("JSON PARSE ERROR:", e)
        print("RAW RESPONSE:", raw_response)

        # Fallback extraction

        parts = re.findall(
            r'"([^"]+)"',
            raw_response
        )

        cleaned_parts = [
            p.strip().lower()
            for p in parts
            if len(p.strip()) > 2
            and p.lower() != "parts"
        ]

        if cleaned_parts:

            print(
                "USING REGEX FALLBACK:"
            )
            print(cleaned_parts)

            return sorted(
                list(
                    set(cleaned_parts)
                )
            )

        return []
from rapidfuzz import process, fuzz

def match_parts_with_bom(
    extracted_parts: list[str],
    bom_document,
    threshold: int = 80
) -> list[dict]:

    results = []

    bom_names = [
        item.name
        for item in bom_document.items
        if item.name
    ]

    for part in extracted_parts:

        match = process.extractOne(
            part,
            bom_names,
            scorer=fuzz.token_sort_ratio
        )

        if not match:
            continue

        matched_name, score, index = match

        if score >= threshold:

            bom_item = [
                item
                for item in bom_document.items
                if item.name == matched_name
            ][0]

            results.append(
                {
                    "extracted_part": part,
                    "bom_item_no": bom_item.item_no,
                    "bom_part_number": bom_item.part_number,
                    "bom_name": bom_item.name,
                    "quantity": bom_item.quantity,
                    "confidence": score
                }
            )

    return results

def match_parts_with_cad(
    matched_bom_parts: list[dict],
    cad_parts: list,
    threshold: float = 75.0
) -> list[dict]:
    """
    Match BOM-matched parts against CAD parts.

    Parameters
    ----------
    matched_bom_parts : list[dict]
        Output from match_parts_with_bom()

    cad_parts : list[CADPart]
        knowledge.cad.parts

    threshold : float
        Minimum fuzzy matching score.

    Returns
    -------
    list[dict]
    """

    results = []

    for bom_part in matched_bom_parts:

        search_text = (
            bom_part.get("bom_name")
            or bom_part.get("extracted_part")
            or ""
        )

        best_match = None
        best_score = 0

        for cad_part in cad_parts:

            candidate = " ".join(
                [
                    cad_part.name or "",
                    cad_part.description or "",
                    cad_part.part_id or ""
                ]
            ).strip()

            score = fuzz.token_sort_ratio(
                search_text.lower(),
                candidate.lower()
            )

            if score > best_score:
                best_score = score
                best_match = cad_part

        if best_match and best_score >= threshold:

            results.append({
                **bom_part,

                "cad_match": True,
                "cad_match_score": round(best_score, 2),

                "cad_part_id": best_match.part_id,
                "cad_name": best_match.name,
                "cad_description": best_match.description,

                # Optional geometry metadata
                "face_count": getattr(
                     best_match,
                     "face_count",
                     None
                ),
                 "edge_count": getattr(
                     best_match,
                     "edge_count",
                     None
                 ),
                 "vertex_count": getattr(
                     best_match,
                     "vertex_count",
                      None
                 ),
                 "volume": getattr(
                     best_match,
                     "volume",
                      None
                 ),
                 "surface_area": getattr(
                     best_match,
                      "surface_area",
                      None
                 ),
                 "bounding_box": (
                     best_match.bounding_box.model_dump()
                     if getattr(
                         best_match,
                         "bounding_box",
                         None
                     )
                     else None
                 ),
                 "center_of_mass": (
                     best_match.center_of_mass.model_dump()
                     if getattr(
                         best_match,
                         "center_of_mass",
                         None
                     )
                     else None
                 )
            }
            )

        else:

            results.append({
                **bom_part,

                "cad_match": False,
                "cad_match_score": round(best_score, 2),

                "cad_part_id": None,
                "cad_name": None,
                "cad_description": None
            })

    return results
def get_geometry_for_matches(
    cad_matches,
    merged_parts
):
    geometries = []

    for match in cad_matches:

        if not match["cad_match"]:
            continue

        part = next(
            (
                p
                for p in merged_parts
                if p["cad_part_id"]
                == match["cad_part_id"]
            ),
            None
        )

        if part:
            geometries.append(part)

    return geometries
def generate_snapshot(
    matched_geometry,
    output_file="snapshot.png"
):
    """
    Generate snapshot from matched CAD geometry.

    Parameters
    ----------
    matched_geometry : list[dict]

    output_file : str
    """

    fig = plt.figure(figsize=(10, 8))

    ax = fig.add_subplot(
        111,
        projection="3d"
    )

    colors = [
        "red",
        "blue",
        "green",
        "orange",
        "purple"
    ]

    for idx, part in enumerate(
        matched_geometry
    ):

        vertices = np.asarray(
           part["mesh"]["vertices"]
        )

        faces = np.asarray(
            part["mesh"]["triangles"]
        )

        color = colors[
            idx % len(colors)
        ]

        mesh_faces = [
            vertices[face]
            for face in faces
        ]

        collection = Poly3DCollection(
            mesh_faces,
            alpha=0.8
        )

        collection.set_facecolor(
            color
        )

        collection.set_edgecolor(
            "black"
        )

        collection.set_linewidth(
            0.1
        )

        ax.add_collection3d(
            collection
        )

    all_vertices = np.vstack(
        [
            np.asarray(
                p["mesh"]["vertices"]
            )
            for p in matched_geometry
        ]
    )

    x = all_vertices[:, 0]
    y = all_vertices[:, 1]
    z = all_vertices[:, 2]

    ax.set_xlim(
        x.min(),
        x.max()
    )

    ax.set_ylim(
        y.min(),
        y.max()
    )

    ax.set_zlim(
        z.min(),
        z.max()
    )

    ax.set_axis_off()

    plt.tight_layout()

    plt.savefig(
        output_file,
        dpi=300,
        bbox_inches="tight"
    )

    plt.close()

    return output_file
