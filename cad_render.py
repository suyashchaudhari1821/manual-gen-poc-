"""
cad_renderer.py
================
Renders REAL images straight from CAD geometry (the mesh/bounding-box data
that cad_parser.py already extracts from the uploaded STEP/STL file) — no
AI image generation, no hardcoded flowchart/step-diagram templates.

Two render modes, chosen automatically per part:

1. Real mesh render — used when the part dict has a non-empty
   part["mesh"]["vertices"] / ["triangles"] (this is now populated by
   cad_parser._analyze_part() and the STL parsers). Draws the actual
   triangulated surface of the part in an isometric view.

2. Bounding-box fallback — used only when no mesh is available (e.g. the
   regex-based STEP fallback parser with no pythonocc-core installed).
   Draws a labelled wireframe box using the real width/height/depth from
   the CAD file, so it is still derived from actual data, not a template.

Public entry point: render_part_image(part, out_path, title=None) -> bool
"""

from __future__ import annotations
import os
import logging
logger = logging.getLogger(__name__)
import matplotlib
matplotlib.use("Agg")  # headless — no display needed
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 (registers 3d projection)
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import random


def _has_real_mesh(part: dict) -> bool:
    mesh = part.get("mesh") or {}
    return bool(mesh.get("vertices")) and bool(mesh.get("triangles"))


def _render_mesh(part: dict, out_path: str, title: str) -> bool:

    mesh = part["mesh"]
    verts = mesh["vertices"]
    tris = mesh["triangles"]
    face_colors = mesh.get("face_colors")

    # Cap triangle count for a fast, readable render — sample evenly rather
    # than truncating, so the silhouette stays representative.
    max_tris = 20000
    if len(tris) > max_tris:
        step = len(tris) // max_tris
        tris = tris[::step]
        if face_colors:
            face_colors = face_colors[::step]

    polys = []
    for (i1, i2, i3) in tris:
        try:
            polys.append([verts[i1], verts[i2], verts[i3]])
        except IndexError:
            continue

    fig = plt.figure(figsize=(6, 5), dpi=200)
    ax = fig.add_subplot(111, projection="3d")
    print(
        title,
        "face_colors:",
        face_colors is not None
    )
    coll = Poly3DCollection(
        polys, facecolors=face_colors if face_colors is not None else "#c9d6e3", edgecolors="#5a5a5a",
        linewidths=0.20, alpha=1.0
    )
    coll.set_zsort("average")
    fig.patch.set_facecolor("#f5f5f5")
    ax.set_facecolor("#f5f5f5")
    ax.add_collection3d(coll)
    if not verts or not polys:
     plt.close(fig)
     return False

    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]

    ax.set_xlim(min(xs), max(xs))
    ax.set_ylim(min(ys), max(ys))
    ax.set_zlim(min(zs), max(zs))

    # Equal aspect ratio so the part isn't visually distorted
    max_range = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) / 2.0
    mid_x, mid_y, mid_z = (max(xs)+min(xs))/2, (max(ys)+min(ys))/2, (max(zs)+min(zs))/2
    ax.set_xlim(mid_x - max_range, mid_x + max_range)
    ax.set_ylim(mid_y - max_range, mid_y + max_range)
    ax.set_zlim(mid_z - max_range, mid_z + max_range)

    ax.view_init(elev=35, azim=-45)  # isometric-style view
    ax.set_axis_off()
    ax.set_title(title, fontsize=10, fontname="DejaVu Sans")

    fig.tight_layout(pad=0.2)
    fig.savefig(out_path, transparent=False, facecolor="white")
    plt.close(fig)
    return os.path.exists(out_path)


def _render_bbox(part: dict, out_path: str, title: str) -> bool:
    """Wireframe box fallback, drawn from the real width/height/depth values
    only (used when no tessellated mesh is available for this part)."""
    bb = part.get("bounding_box") or {}
    w = bb.get("width", 0) or 1
    h = bb.get("height", 0) or 1
    d = bb.get("depth", 0) or 1

    fig = plt.figure(figsize=(6, 5), dpi=200)
    ax = fig.add_subplot(111, projection="3d")

    # 8 corners of the box
    pts = [(x, y, z) for x in (0, w) for y in (0, h) for z in (0, d)]
    edges = [
        (0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3),
        (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7),
    ]
    for a, b in edges:
        xs = [pts[a][0], pts[b][0]]
        ys = [pts[a][1], pts[b][1]]
        zs = [pts[a][2], pts[b][2]]
        ax.plot(xs, ys, zs, color="#2b3a4a", linewidth=1.2)

    ax.set_box_aspect((w, h, d))
    ax.view_init(elev=22, azim=-60)
    ax.set_axis_off()
    ax.set_title(f"{title}\n(dimensions only — no tessellated mesh available)",
                 fontsize=9, fontname="DejaVu Sans")

    fig.tight_layout(pad=0.2)
    fig.savefig(out_path, transparent=False, facecolor="white")
    plt.close(fig)
    return os.path.exists(out_path)


def render_part_image(part: dict, out_path: str, title: str | None = None) -> bool:
    """
    Render a real image of a single CAD part to out_path (PNG).

    part      : one entry from cad_parser.parse_step_file(...)["parts"]
    out_path  : destination .png path
    title     : caption text; defaults to the part's name from the CAD file

    Returns True on success, False if nothing could be rendered (e.g. an
    empty/degenerate part) — callers should skip inserting an image in
    that case rather than substituting a placeholder.
    """
    title = title or part.get("name") or "CAD Part"
    try:
        if _has_real_mesh(part):
            return _render_mesh(part, out_path, title)
        bb = part.get("bounding_box") or {}
        if any(bb.get(k) for k in ("width", "height", "depth")):
            return _render_bbox(part, out_path, title)
        logger.warning(
    "No mesh or bounding box for part '%s' - skipping image",
    title,
)
        return False
    except Exception as e:
        logger.exception(
    "Render failed for part '%s'",
    title,
)
        return False


def render_parts_for_spec(spec_card, cad_data: dict, out_dir: str,
                           max_images: int = 3) -> list[str]:
    """
    Render real CAD images for the components a SpecCard actually resolved
    (spec_resolver.build_spec_card()) — this is far more precise than
    guessing from section-title word overlap (see render_parts_for_section
    below, kept as a fallback for when no spec card is available):

      1. card.highlighted_parts   — AI-declared parts, validated against
                                     real CAD part names in ai_assistant.py
      2. card.matched_parts       — per-component BOM+CAD cross-matches
                                     (each carries a "cad_part_name")
      3. card.source_cad_part     — the single top-level CAD match

    Returns up to max_images PNG file paths, most-relevant first.
    """
    parts = (cad_data or {}).get("parts") or []
    if not parts or spec_card is None:
        return []
    by_name = {p.get("name"): p for p in parts if p.get("name")}

    wanted_names = []
    for n in (getattr(spec_card, "highlighted_parts", None) or []):
        if n not in wanted_names:
            wanted_names.append(n)
    for comp in (getattr(spec_card, "matched_parts", None) or []):
        n = comp.get("cad_part_name") or comp.get("name")
        if n and n in by_name and n not in wanted_names:
            wanted_names.append(n)
    src = getattr(spec_card, "source_cad_part", "")
    if src and src in by_name and src not in wanted_names:
        wanted_names.append(src)

    os.makedirs(out_dir, exist_ok=True)
    out_paths = []
    for i, name in enumerate(wanted_names[:max_images]):
        part = by_name.get(name)
        if not part:
            continue
        safe_name = "".join(c if c.isalnum() else "_" for c in name)[:40]
        out_path = os.path.join(out_dir, f"cad_render_{safe_name}_{i}.png")
        if render_part_image(part, out_path, title=name):
            out_paths.append(out_path)

    return out_paths


def render_parts_for_section(cad_data: dict, section_title: str, out_dir: str,
                              max_images: int = 2) -> list[str]:
    """
    Pick the CAD part(s) most relevant to a manual section (simple name
    match against section_title, falling back to the largest parts by
    surface area) and render real images for them.

    Returns a list of PNG file paths (0 to max_images entries).
    """
    parts = (cad_data or {}).get("parts") or []
    if not parts:
        return []

    os.makedirs(out_dir, exist_ok=True)

    words = {w.lower() for w in section_title.replace("/", " ").split() if len(w) > 3}

    def _score(p):
        name = (p.get("name") or "").lower()
        return sum(1 for w in words if w in name)

    ranked = sorted(parts, key=lambda p: (_score(p), p.get("surface_area", 0)), reverse=True)

    out_paths = []
    for i, part in enumerate(ranked[:max_images]):
        safe_name = "".join(c if c.isalnum() else "_" for c in (part.get("name") or f"part{i}"))[:40]
        out_path = os.path.join(out_dir, f"cad_render_{safe_name}_{i}.png")
        if render_part_image(part, out_path, title=part.get("name")):
            out_paths.append(out_path)

    return out_paths