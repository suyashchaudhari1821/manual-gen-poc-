"""
cad_service.py
==============
Service layer connecting CAD parsing, Three.js 3D model conversion,
PartsManager unique part renaming, and manual generation integration.
"""

import os
import base64
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from cad_converter_v2 import convert_cad_to_gltf, rename_glb_meshes
from parts_manager import PartsManager
from cad_models import CADAssembly, CADPart, BoundingBox, CenterOfMass

logger = logging.getLogger(__name__)


def process_cad_file(
    file_path: str,
    output_dir: str = "converted_cad",
    bom_doc = None
) -> Dict[str, Any]:
    """
    Converts and parses a CAD file (.stp, .step, .stl, .obj):
    1. Converts CAD geometry into high-performance glTF/GLB with full hierarchy.
    2. Uses PartsManager to detect duplicates and generate unique names (BOLT_1, BOLT_2, etc.).
    3. Renames GLB meshes to match unique part names for Three.js picking.
    4. Correlates parts with BOM (if available).
    5. Returns CADAssembly object + GLB base64 for browser rendering.
    """
    os.makedirs(output_dir, exist_ok=True)
    file_name = os.path.basename(file_path)
    
    # 1. Convert CAD to GLB
    conv_result = convert_cad_to_gltf(file_path, output_dir)
    glb_path = conv_result["glb_path"]
    original_parts = conv_result["parts"]
    
    # 2. Rename duplicates using PartsManager
    parts_mgr = PartsManager()
    unique_parts = parts_mgr.parse_and_rename_parts(original_parts)
    dup_report = parts_mgr.get_duplicate_report()
    
    # 3. Rename meshes inside the GLB binary so Three.js raycasting matches
    try:
        rename_glb_meshes(glb_path, original_parts, unique_parts)
    except Exception as e:
        logger.warning(f"Could not rename meshes in GLB: {e}")
        
    # 4. Load GLB as base64 for browser rendering
    with open(glb_path, "rb") as f:
        glb_b64 = base64.b64encode(f.read()).decode("utf-8")
        
    # 5. Build structured parts list and correlate with BOM if present
    bom_items_by_name = {}
    bom_items_by_num = {}
    if bom_doc and hasattr(bom_doc, "items"):
        for item in bom_doc.items:
            if hasattr(item, "name") and item.name:
                bom_items_by_name[item.name.strip().lower()] = item
            if hasattr(item, "part_number") and item.part_number:
                bom_items_by_num[item.part_number.strip().lower()] = item
                
    structured_parts = []
    seen_counts = {}
    for i, (orig, uniq) in enumerate(zip(original_parts, unique_parts)):
        seen_counts[orig] = seen_counts.get(orig, 0) + 1
        occurrence_idx = seen_counts[orig]
        total_occurrences = parts_mgr.occurrences.get(orig, 1)
        
        # Match with BOM
        matched_bom = None
        orig_clean = orig.strip().lower()
        if orig_clean in bom_items_by_name:
            matched_bom = bom_items_by_name[orig_clean]
        elif orig_clean in bom_items_by_num:
            matched_bom = bom_items_by_num[orig_clean]
        else:
            # Try partial matching
            for b_name, b_item in bom_items_by_name.items():
                if b_name in orig_clean or orig_clean in b_name:
                    matched_bom = b_item
                    break

        part_num = getattr(matched_bom, "part_number", f"P-{i+1:03d}") if matched_bom else f"P-{i+1:03d}"
        desc = getattr(matched_bom, "description", orig) if matched_bom else orig
        
        part_dict = {
            "part_id": f"P{i+1}",
            "name": orig,
            "unique_name": uniq,
            "part_number": part_num,
            "description": desc,
            "is_duplicate": total_occurrences > 1,
            "occurrence": occurrence_idx,
            "total_occurrences": total_occurrences,
            "face_count": 0,
            "edge_count": 0,
            "vertex_count": 0,
            "bounding_box": {"width": 0.0, "height": 0.0, "depth": 0.0},
            "volume": 0.0,
            "surface_area": 0.0,
            "center_of_mass": {"x": 0.0, "y": 0.0, "z": 0.0}
        }
        structured_parts.append(part_dict)
        
    cad_parts_models = [
        CADPart(
            part_id=p["part_id"],
            name=p["name"],
            unique_name=p["unique_name"],
            part_number=p["part_number"],
            description=p["description"],
            is_duplicate=p["is_duplicate"],
            occurrence=p["occurrence"],
            total_occurrences=p["total_occurrences"],
            face_count=p["face_count"],
            edge_count=p["edge_count"],
            vertex_count=p["vertex_count"],
            volume=p["volume"],
            surface_area=p["surface_area"],
            bounding_box=BoundingBox(**p["bounding_box"]),
            center_of_mass=CenterOfMass(**p["center_of_mass"])
        )
        for p in structured_parts
    ]

    # 6. Build CADAssembly model for manual generation pipeline
    cad_doc = CADAssembly(
        filename=file_name,
        parts=cad_parts_models,
        parsing_mode="cadquery-ocp-xde",
        parsing_confidence=0.95,
        parse_duration=conv_result["stats"]["conversion_time"],
        total_parts=len(structured_parts),
        total_faces=0,
        total_edges=0,
        total_surface_area=0.0,
        total_volume=0.0,
        bounding_box={"width": 0.0, "height": 0.0, "depth": 0.0},
        face_type_summary={}
    )
    
    return {
        "cad_doc": cad_doc,
        "glb_path": glb_path,
        "glb_b64": glb_b64,
        "parts_list": original_parts,
        "unique_parts_list": unique_parts,
        "duplicate_report": dup_report,
        "structured_parts": structured_parts,
        "stats": conv_result["stats"]
    }
