from pathlib import Path

from cad_handler import load_step_xde, extract_named_parts, tessellate_named_parts
from cad_render import _render_mesh

STEP_FILE = r"C:\Users\pgavhane\OneDrive - Expleo France\Documents\PROJECT\ENGINE POC ASSY (2).stp"

# create output folder
output_dir = Path("renders")
output_dir.mkdir(exist_ok=True)
COLORS = [
    "#FF6B6B",
    "#4ECDC4",
    "#F9C74F",
    "#90BE6D",
    "#577590",
    "#F3722C",
    "#43AA8B",
    "#9D4EDD",
]

# load CAD
doc, shape_tool = load_step_xde(STEP_FILE)

named_parts = extract_named_parts(shape_tool)
geometry_parts = tessellate_named_parts(named_parts)

for idx, part in enumerate(geometry_parts):

    color = COLORS[idx % len(COLORS)]

    faces = part["mesh"]["triangles"]

    part["mesh"]["face_colors"] = [color] * len(faces)

all_vertices = []
all_faces = []
all_colors = []

vertex_offset = 0

for idx, part in enumerate(geometry_parts):

    verts = part["mesh"]["vertices"]
    faces = part["mesh"]["triangles"]
    color = COLORS[idx % len(COLORS)]

    all_vertices.extend(verts)

    for tri in faces:
        all_faces.append([
            tri[0] + vertex_offset,
            tri[1] + vertex_offset,
            tri[2] + vertex_offset
        ])
        all_colors.append(color)

    vertex_offset += len(verts)

assembly_mesh = {
    "cad_name": "ENGINE POC ASSY",
    "mesh": {
        "vertices": all_vertices,
        "triangles": all_faces,
        "face_colors": all_colors
    }
}

_render_mesh(
    assembly_mesh,
    str(output_dir / "00_ENGINE_POC_ASSY.png"),
    "ENGINE POC ASSY"
)

print(f"Rendering {len(geometry_parts)} parts...")

for part in geometry_parts:

    clean_name = (
        part["cad_name"]
        .replace("/", "_")
        .replace("\\", "_")
    )

    output_file = output_dir / f"{clean_name}.png"

    print(f"Rendering {clean_name}")

    success = _render_mesh(
        part,
        str(output_file),
        clean_name
    )

    print(
        "SUCCESS" if success else "FAILED"
    )