from self_rag import generate_from_context

from image_generation import (
    extract_parts_from_content,
    match_parts_with_bom,
    match_parts_with_cad,
    get_geometry_for_matches,
    generate_snapshot
)

# =========================
# LOAD ENGINEERING DATA
# =========================

from unified_structured_data import knowledge

# CAD GEOMETRY
from cad_handler import (
    load_step_xde,
    extract_named_parts,
    tessellate_named_parts
)

STEP_FILE = r"ENGINE POC ASSY (2).stp"

doc, shape_tool = load_step_xde(STEP_FILE)

named_parts = extract_named_parts(
    shape_tool
)

merged_parts = tessellate_named_parts(
    named_parts
)

print(
    f"\nGeometry Parts Loaded: "
    f"{len(merged_parts)}"
)

# =========================
# TEST PROCEDURE
# =========================

answer = """
Install the belt over the drive pully.
Secure using bolt.
"""

# =========================
# EXTRACT PARTS
# =========================

parts = extract_parts_from_content(
    answer
)

print("\nPARTS")
print(parts)

# =========================
# BOM MATCHING
# =========================

bom_matches = match_parts_with_bom(
    parts,
    knowledge.bom
)

print("\nBOM MATCHES")

for x in bom_matches:
    print(
        x["bom_name"]
    )

# =========================
# PREPARE CAD PARTS
# =========================

cad_parts = []

for part in merged_parts:

    cad_parts.append(
        {
            "part_id":
                part["cad_part_id"],

            "name":
                part["cad_name"],

            "description":
                ""
        }
    )

# =========================
# CAD MATCHING
# =========================

from rapidfuzz import fuzz

cad_matches = []

for bom_part in bom_matches:

    search_text = (
        bom_part["bom_name"]
        .lower()
    )

    best_match = None
    best_score = 0

    for cad_part in merged_parts:

        cad_name = (
            cad_part["cad_name"]
            .rsplit(".", 1)[0]
            .lower()
        )

        score = fuzz.token_sort_ratio(
            search_text,
            cad_name
        )

        if score > best_score:

            best_score = score
            best_match = cad_part

    if best_match:

        cad_matches.append(
            {
                **bom_part,

                "cad_match":
                    True,

                "cad_match_score":
                    best_score,

                "cad_part_id":
                    best_match["cad_part_id"],

                "cad_name":
                    best_match["cad_name"]
            }
        )

print("\nCAD MATCHES")

for x in cad_matches:

    print(
        x["cad_name"],
        x["cad_match_score"]
    )

# =========================
# GET GEOMETRY
# =========================

matched_geometry = (
    get_geometry_for_matches(
        cad_matches,
        merged_parts
    )
)

print("\nGEOMETRY")

print(
    len(matched_geometry)
)

# =========================
# GENERATE SNAPSHOT
# =========================

if len(matched_geometry) > 0:

    generate_snapshot(
        matched_geometry,
        output_file="step_01.png"
    )

    print(
        "\nSnapshot generated successfully."
    )

else:

    print(
        "\nParts matching did not happen."
    )

    print(
        "\nExtracted Parts:"
    )

    for p in parts:

        print("-", p)