"""
CAD File Converter — handles .STEP, .IGES, .3DXML, .STL, .OBJ → glTF
Fast approach: XML hierarchy extraction + proxy geometry generation.
"""

import json
import logging
import math
import os
import struct
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Low-level glTF / GLB builder
# ══════════════════════════════════════════════════════════════════════════════

class GLTFBuilder:
    """Builds a glTF 2.0 GLB from raw mesh data."""

    def __init__(self):
        self.nodes: List[dict] = []
        self.meshes: List[dict] = []
        self.accessors: List[dict] = []
        self.buffer_views: List[dict] = []
        self.materials: List[dict] = []
        self.binary_blob = bytearray()
        self.scenes: List[dict] = [{"nodes": []}]
        self._material_cache: Dict[str, int] = {}

    def _pad4(self, data: bytearray) -> bytearray:
        r = len(data) % 4
        if r:
            data += b'\x00' * (4 - r)
        return data

    def _append_buf(self, data: bytes) -> Tuple[int, int]:
        off = len(self.binary_blob)
        self.binary_blob += bytearray(data)
        self.binary_blob = self._pad4(self.binary_blob)
        return off, len(data)

    def _add_bv(self, off, length, target=None):
        idx = len(self.buffer_views)
        bv = {"buffer": 0, "byteOffset": off, "byteLength": length}
        if target:
            bv["target"] = target
        self.buffer_views.append(bv)
        return idx

    def _add_acc(self, bv, comp, count, atype, mn, mx):
        idx = len(self.accessors)
        self.accessors.append({
            "bufferView": bv, "componentType": comp,
            "count": count, "type": atype, "min": mn, "max": mx,
        })
        return idx

    def add_material(self, name, color=None):
        if name in self._material_cache:
            return self._material_cache[name]
        if color is None:
            h = hash(name) & 0xFFFFFF
            color = ((h >> 16 & 0xFF) / 255.0, (h >> 8 & 0xFF) / 255.0, (h & 0xFF) / 255.0, 1.0)
        idx = len(self.materials)
        c4 = list(color[:4]) if len(color) >= 4 else list(color) + [1.0]
        self.materials.append({
            "name": name,
            "pbrMetallicRoughness": {
                "baseColorFactor": c4,
                "metallicFactor": 0.25,
                "roughnessFactor": 0.65,
            },
            "doubleSided": True,
        })
        self._material_cache[name] = idx
        return idx

    def add_mesh(self, name, verts, faces, normals=None, mat_idx=0,
                 parent=None, transform=None):
        verts = np.asarray(verts, dtype=np.float32)
        faces = np.asarray(faces, dtype=np.uint32)
        if verts.size == 0 or faces.size == 0:
            return -1
        if normals is None:
            normals = self._calc_normals(verts, faces)
        else:
            normals = np.asarray(normals, dtype=np.float32)
        normals = normals.astype(np.float32)

        # Positions
        po, pl = self._append_buf(verts.tobytes())
        pbv = self._add_bv(po, pl, 34962)
        pa = self._add_acc(pbv, 5126, len(verts), "VEC3",
                           verts.min(0).tolist(), verts.max(0).tolist())

        # Normals
        no, nl = self._append_buf(normals.tobytes())
        nbv = self._add_bv(no, nl, 34962)
        na = self._add_acc(nbv, 5126, len(normals), "VEC3",
                           normals.min(0).tolist(), normals.max(0).tolist())

        # Indices
        flat = faces.flatten().astype(np.uint32)
        io, il = self._append_buf(flat.tobytes())
        ibv = self._add_bv(io, il, 34963)
        ia = self._add_acc(ibv, 5125, len(flat), "SCALAR",
                           [int(flat.min())], [int(flat.max())])

        mi = len(self.meshes)
        self.meshes.append({
            "name": name,
            "primitives": [{"attributes": {"POSITION": pa, "NORMAL": na},
                            "indices": ia, "material": mat_idx, "mode": 4}]
        })
        ni = len(self.nodes)
        nd = {"name": name, "mesh": mi}
        if transform:
            nd["matrix"] = transform
        self.nodes.append(nd)
        if parent is not None and parent >= 0:
            self.nodes[parent].setdefault("children", []).append(ni)
        else:
            self.scenes[0]["nodes"].append(ni)
        return ni

    def add_group(self, name, parent=None, transform=None):
        idx = len(self.nodes)
        nd = {"name": name}
        if transform:
            nd["matrix"] = transform
        self.nodes.append(nd)
        if parent is not None and parent >= 0:
            self.nodes[parent].setdefault("children", []).append(idx)
        else:
            self.scenes[0]["nodes"].append(idx)
        return idx

    @staticmethod
    def _calc_normals(verts, faces):
        normals = np.zeros_like(verts)
        v0 = verts[faces[:, 0]]
        v1 = verts[faces[:, 1]]
        v2 = verts[faces[:, 2]]
        n = np.cross(v1 - v0, v2 - v0)
        norm = np.linalg.norm(n, axis=1, keepdims=True)
        norm[norm == 0] = 1
        n /= norm
        for i in range(3):
            np.add.at(normals, faces[:, i], n)
        nrm = np.linalg.norm(normals, axis=1, keepdims=True)
        nrm[nrm == 0] = 1
        normals /= nrm
        return normals

    def export_glb_bytes(self) -> bytes:
        gj = json.dumps({
            "asset": {"version": "2.0", "generator": "AI-CAD-Animator"},
            "scene": 0, "scenes": self.scenes, "nodes": self.nodes,
            "meshes": self.meshes, "accessors": self.accessors,
            "bufferViews": self.buffer_views, "materials": self.materials,
            "buffers": [{"byteLength": len(self.binary_blob)}],
        }, separators=(',', ':')).encode('utf-8')
        while len(gj) % 4:
            gj += b' '
        total = 12 + 8 + len(gj) + 8 + len(self.binary_blob)
        return (struct.pack('<III', 0x46546C67, 2, total) +
                struct.pack('<II', len(gj), 0x4E4F534A) + gj +
                struct.pack('<II', len(self.binary_blob), 0x004E4942) +
                bytes(self.binary_blob))

    def export_glb(self, path):
        with open(path, 'wb') as f:
            f.write(self.export_glb_bytes())


# ══════════════════════════════════════════════════════════════════════════════
# Assembly hierarchy container
# ══════════════════════════════════════════════════════════════════════════════

class AssemblyNode:
    def __init__(self, name, node_type="part"):
        self.name = name
        self.node_type = node_type
        self.children: List['AssemblyNode'] = []
        self.mesh_data: Optional[dict] = None
        self.color: Optional[Tuple[float, ...]] = None
        self.transform: Optional[List[float]] = None

    def to_dict(self):
        d = {"name": self.name, "type": self.node_type}
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


# ══════════════════════════════════════════════════════════════════════════════
# Primitive shape generators
# ══════════════════════════════════════════════════════════════════════════════

def _make_box(sx, sy, sz, ox=0, oy=0, oz=0):
    v = np.array([
        [ox-sx/2, oy-sy/2, oz-sz/2], [ox+sx/2, oy-sy/2, oz-sz/2],
        [ox+sx/2, oy+sy/2, oz-sz/2], [ox-sx/2, oy+sy/2, oz-sz/2],
        [ox-sx/2, oy-sy/2, oz+sz/2], [ox+sx/2, oy-sy/2, oz+sz/2],
        [ox+sx/2, oy+sy/2, oz+sz/2], [ox-sx/2, oy+sy/2, oz+sz/2],
    ], dtype=np.float32)
    f = np.array([
        [0,1,2],[0,2,3],[4,6,5],[4,7,6],[0,4,5],[0,5,1],
        [2,6,7],[2,7,3],[0,3,7],[0,7,4],[1,5,6],[1,6,2],
    ], dtype=np.uint32)
    return {"vertices": v, "faces": f}


def _make_cylinder(r, h, seg=16, ox=0, oy=0, oz=0):
    verts, faces = [], []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        x, z = r * math.cos(a) + ox, r * math.sin(a) + oz
        verts.append([x, oy, z])
        verts.append([x, oy + h, z])
    bc = len(verts); verts.append([ox, oy, oz])
    tc = len(verts); verts.append([ox, oy + h, oz])
    for i in range(seg):
        i0, i1 = i*2, i*2+1
        i2, i3 = ((i+1)%seg)*2, ((i+1)%seg)*2+1
        faces += [[i0,i2,i1],[i1,i2,i3],[bc,i0,i2],[tc,i3,i1]]
    return {"vertices": np.array(verts, np.float32), "faces": np.array(faces, np.uint32)}


def _make_gear(r, h, teeth=16, th=0.3, ox=0, oy=0, oz=0):
    """Gear with involute-style tooth profile (tip, pitch, root radii)."""
    verts, faces = [], []
    seg = teeth * 6  # 6 pts per tooth for smoother profile
    for i in range(seg):
        a = 2 * math.pi * i / seg
        phase = i % 6
        if phase < 2:
            rr = r + th          # tooth tip
        elif phase == 2:
            rr = r + th * 0.3    # flank
        elif phase == 3:
            rr = r - th * 0.15   # root fillet
        elif phase == 4:
            rr = r - th * 0.15   # root fillet
        else:
            rr = r + th * 0.3    # flank
        verts.append([rr * math.cos(a) + ox, oy, rr * math.sin(a) + oz])
        verts.append([rr * math.cos(a) + ox, oy + h, rr * math.sin(a) + oz])
    bc = len(verts); verts.append([ox, oy, oz])
    tc = len(verts); verts.append([ox, oy + h, oz])
    for i in range(seg):
        i0, i1 = i * 2, i * 2 + 1
        i2, i3 = ((i + 1) % seg) * 2, ((i + 1) % seg) * 2 + 1
        faces += [[i0, i2, i1], [i1, i2, i3], [bc, i0, i2], [tc, i3, i1]]
    return {"vertices": np.array(verts, np.float32), "faces": np.array(faces, np.uint32)}


def _make_tube(r_outer, r_inner, h, seg=32, ox=0, oy=0, oz=0):
    """Hollow cylinder / tube with inner and outer walls."""
    verts, faces = [], []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        co, si_ = math.cos(a), math.sin(a)
        # outer bottom, outer top, inner bottom, inner top
        verts.append([r_outer * co + ox, oy, r_outer * si_ + oz])
        verts.append([r_outer * co + ox, oy + h, r_outer * si_ + oz])
        verts.append([r_inner * co + ox, oy, r_inner * si_ + oz])
        verts.append([r_inner * co + ox, oy + h, r_inner * si_ + oz])
    for i in range(seg):
        b = i * 4
        n = ((i + 1) % seg) * 4
        # outer wall
        faces += [[b, n, b + 1], [b + 1, n, n + 1]]
        # inner wall (reversed winding)
        faces += [[b + 2, b + 3, n + 2], [b + 3, n + 3, n + 2]]
        # top annular face
        faces += [[b + 1, n + 1, n + 3], [b + 1, n + 3, b + 3]]
        # bottom annular face
        faces += [[b, b + 2, n], [n, b + 2, n + 2]]
    return {"vertices": np.array(verts, np.float32), "faces": np.array(faces, np.uint32)}


def _make_sphere(r, seg=16, ox=0, oy=0, oz=0):
    """UV sphere."""
    verts, faces = [], []
    for j in range(seg + 1):
        phi = math.pi * j / seg
        for i in range(seg):
            theta = 2 * math.pi * i / seg
            x = r * math.sin(phi) * math.cos(theta) + ox
            y = r * math.cos(phi) + oy
            z = r * math.sin(phi) * math.sin(theta) + oz
            verts.append([x, y, z])
    for j in range(seg):
        for i in range(seg):
            a = j * seg + i
            b = j * seg + (i + 1) % seg
            c = (j + 1) * seg + (i + 1) % seg
            d = (j + 1) * seg + i
            faces += [[a, d, b], [b, d, c]]
    return {"vertices": np.array(verts, np.float32), "faces": np.array(faces, np.uint32)}


def _make_bolt(r_shaft, r_head, h_shaft, h_head, seg=16, ox=0, oy=0, oz=0):
    """Hex bolt — hexagonal head + cylindrical shaft."""
    verts, faces = [], []
    # Hex head
    for i in range(6):
        a = math.pi / 3 * i
        verts.append([r_head * math.cos(a) + ox, oy + h_shaft, r_head * math.sin(a) + oz])
        verts.append([r_head * math.cos(a) + ox, oy + h_shaft + h_head, r_head * math.sin(a) + oz])
    hbc = len(verts); verts.append([ox, oy + h_shaft, oz])
    htc = len(verts); verts.append([ox, oy + h_shaft + h_head, oz])
    for i in range(6):
        i0, i1 = i * 2, i * 2 + 1
        i2, i3 = ((i + 1) % 6) * 2, ((i + 1) % 6) * 2 + 1
        faces += [[i0, i2, i1], [i1, i2, i3], [hbc, i0, i2], [htc, i3, i1]]
    # Shaft (cylinder)
    base = len(verts)
    for i in range(seg):
        a = 2 * math.pi * i / seg
        x, z = r_shaft * math.cos(a) + ox, r_shaft * math.sin(a) + oz
        verts.append([x, oy, z])
        verts.append([x, oy + h_shaft, z])
    sbc = len(verts); verts.append([ox, oy, oz])
    stc = len(verts); verts.append([ox, oy + h_shaft, oz])
    for i in range(seg):
        i0 = base + i * 2
        i1 = base + i * 2 + 1
        i2 = base + ((i + 1) % seg) * 2
        i3 = base + ((i + 1) % seg) * 2 + 1
        faces += [[i0, i2, i1], [i1, i2, i3], [sbc, i0, i2], [stc, i3, i1]]
    return {"vertices": np.array(verts, np.float32), "faces": np.array(faces, np.uint32)}


def _make_hollow_box(sx, sy, sz, wall, ox=0, oy=0, oz=0):
    """Box with hollow interior (open top)."""
    outer = _make_box(sx, sy, sz, ox, oy, oz)
    inner = _make_box(sx - 2 * wall, sy - wall, sz - 2 * wall, ox, oy + wall / 2, oz)
    # Flip inner faces to create interior walls
    inner_f = inner["faces"][:, ::-1]
    combined_v = np.vstack([outer["vertices"], inner["vertices"]])
    combined_f = np.vstack([outer["faces"], inner_f + len(outer["vertices"])])
    return {"vertices": combined_v.astype(np.float32), "faces": combined_f.astype(np.uint32)}


# ══════════════════════════════════════════════════════════════════════════════
# V5_CFV3 binary CGR mesh extractor
# ══════════════════════════════════════════════════════════════════════════════

def _parse_cgr_mesh(data: bytes) -> Optional[dict]:
    """Extract triangle mesh from a V5_CFV3 (CATIA CGR) binary blob.

    The CGR binary stores indexed vertex positions as float32 arrays.
    Since the proprietary index buffer cannot be decoded, we reconstruct
    the surface mesh using *scipy* ``ConvexHull`` after filtering outliers.

    Returns ``{"vertices": ndarray(N,3), "faces": ndarray(M,3)}`` or *None*.
    """
    if len(data) < 100 or data[:7] != b'V5_CFV3':
        return None

    # --- scan for the largest contiguous run of plausible float32 coords ---
    best_off = -1
    best_cnt = 0
    blk_start: Optional[int] = None
    blk_count = 0
    for i in range(80, len(data) - 3, 4):
        v = struct.unpack_from('<f', data, i)[0]
        if v == v and -50000 < v < 50000:
            if blk_start is None:
                blk_start = i
            blk_count += 1
        else:
            if blk_count > best_cnt:
                best_off, best_cnt = blk_start, blk_count
            blk_start = None
            blk_count = 0
    if blk_count > best_cnt:
        best_off, best_cnt = blk_start, blk_count

    if best_cnt < 24:           # need at least 8 vertices for useful hull
        return None

    # Skip a leading uint32 count if present (reads as denormal float)
    first_f = struct.unpack_from('<f', data, best_off)[0]
    if abs(first_f) < 1e-20 and first_f != 0.0:
        first_u = struct.unpack_from('<I', data, best_off)[0]
        if abs(first_u - (best_cnt - 1)) < 20:
            best_off += 4
            best_cnt -= 1

    n_floats = (best_cnt // 3) * 3
    if n_floats < 24:
        return None

    raw = np.frombuffer(data, dtype='<f4', count=n_floats, offset=best_off)
    verts = raw.reshape(-1, 3).copy()

    # --- IQR-based outlier filtering -------------------------------------
    # Remove non-vertex metadata values that slipped into the float block.
    q1 = np.percentile(verts, 25, axis=0)
    q3 = np.percentile(verts, 75, axis=0)
    iqr = q3 - q1
    # Use 2.5× IQR fence; if IQR is tiny, fall back to absolute ±1mm
    iqr_safe = np.where(iqr > 0.01, iqr, 1.0)
    lower = q1 - 2.5 * iqr_safe
    upper = q3 + 2.5 * iqr_safe
    mask = np.all((verts >= lower) & (verts <= upper), axis=1)
    verts = verts[mask]

    if len(verts) < 8:
        return None

    # Reject if bbox is degenerate (significant extent in < 2 axes)
    bbox = verts.max(axis=0) - verts.min(axis=0)
    if np.sum(bbox > 0.1) < 2:
        return None

    # --- reconstruct surface mesh via ConvexHull -------------------------
    try:
        from scipy.spatial import ConvexHull
        hull = ConvexHull(verts)
        # Remap to only hull vertices for compactness
        old_ids = hull.vertices
        hull_verts = verts[old_ids]
        remap = np.full(len(verts), -1, dtype=np.int32)
        remap[old_ids] = np.arange(len(old_ids), dtype=np.int32)
        faces = remap[hull.simplices].astype(np.uint32)
        return {"vertices": hull_verts.astype(np.float32), "faces": faces}
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Fast 3DXML Parser — maps SOL IDs → real CATIA part names
# ══════════════════════════════════════════════════════════════════════════════

def _is_internal_node(name: str) -> bool:
    """Return True for CATIA-internal nodes that should be collapsed/skipped.

    Internal nodes include:
      * ``*SOL1``, ``*SOL2_99`` etc — geometry containers
      * ``PRODUIT-CATIA_MODEL`` / hex-GUID wrappers — CATIA V5 wrappers
      * ``MANIFOLD_SOLID_BREP`` — STEP kernel artifacts
    """
    if not name:
        return True
    if name.startswith('*'):          # *SOL1, *SOL2, …
        return True
    if 'CATIA_MODEL' in name:
        return True
    if 'PRODUIT-CATIA' in name or 'PRODUIT_CATIA' in name:
        return True
    if 'MANIFOLD_SOLID_BREP' in name:
        return True
    # Hex-GUID wrapper names: "4141951ADA044E32-4141951ADA044E33-…"
    if len(name) > 40 and name.count('-') >= 3:
        segments = name.split('-')[:3]
        hex_segs = sum(
            1 for s in segments
            if len(s) >= 8 and all(c in '0123456789ABCDEFabcdef' for c in s)
        )
        if hex_segs >= 2:
            return True
    return False


def _clean_catia_name(name: str) -> str:
    """Clean up a CATIA V5 part / assembly name for display."""
    if not name:
        return "Unknown"
    name = name.strip().replace('\n', ' ')
    # Strip trailing dashes/spaces
    name = name.rstrip('- ')
    # Collapse runs of dashes:  "AA--METIERS-DOGN-----" → "AA-METIERS-DOGN"
    while '--' in name:
        name = name.replace('--', '-')
    name = name.rstrip('- ')
    if len(name) > 60:
        name = name[:57] + '…'
    return name or "Unknown"


def _parse_3dxml_fast(filepath: str) -> Optional[AssemblyNode]:
    """Parse 3DXML: extract assembly hierarchy with real CATIA part names.

    * Reads only XML metadata (< 1 s even on large files).
    * Maps each SOL geometry ID back to its meaningful Reference3D ancestor.
    * Skips internal ``*SOL*``, ``CATIA_MODEL`` and hex-GUID wrapper nodes.
    * Generates proxy geometry for visualisation.
    """
    try:
        if not zipfile.is_zipfile(filepath):
            return None

        with zipfile.ZipFile(filepath, 'r') as zf:
            # ── locate main XML via Manifest ──────────────────────────
            names = zf.namelist()
            main_xml = None
            if 'Manifest.xml' in names:
                from lxml import etree
                manifest = etree.fromstring(zf.read('Manifest.xml'))
                root_el = manifest.find('.//{*}Root')
                if root_el is not None and root_el.text:
                    main_xml = root_el.text.strip()
            if not main_xml or main_xml not in names:
                xmls = [n for n in names if n.endswith('.3dxml')]
                main_xml = xmls[0] if xmls else None
            if not main_xml:
                return None

            from lxml import etree
            data = zf.read(main_xml)
            root = etree.fromstring(data)
            ns = 'http://www.3ds.com/xsd/3DXML'
            nsm = {'x': ns}

            # ── 1. Reference3D   id → name ────────────────────────────
            ref_map: Dict[str, str] = {}
            for ref in root.findall('.//x:Reference3D', nsm):
                ref_map[ref.get('id')] = ref.get('name', f'Ref_{ref.get("id")}')

            # ── 2. Instance3D   parent_ref → [(child_ref, inst_name, xform)] ─
            #    xform is a 4×4 column-major matrix list[16] for glTF, or None.
            children_map: Dict[str, List[Tuple[str, str, Optional[List[float]]]]] = {}
            for inst in root.findall('.//x:Instance3D', nsm):
                agg = inst.findtext(f'{{{ns}}}IsAggregatedBy')
                inst_of = inst.findtext(f'{{{ns}}}IsInstanceOf')
                xform: Optional[List[float]] = None
                mat_txt = inst.findtext(f'{{{ns}}}RelativeMatrix')
                if mat_txt:
                    try:
                        vals = [float(x) for x in mat_txt.strip().split()]
                        if len(vals) == 12:
                            # 3×3 rotation (row-major) + 3D translation
                            # → 4×4 column-major for glTF
                            xform = [
                                vals[0], vals[3], vals[6], 0.0,
                                vals[1], vals[4], vals[7], 0.0,
                                vals[2], vals[5], vals[8], 0.0,
                                vals[9], vals[10], vals[11], 1.0,
                            ]
                    except (ValueError, IndexError):
                        pass
                if agg and inst_of:
                    children_map.setdefault(agg, []).append(
                        (inst_of, inst.get('name', ''), xform)
                    )

            # ── 3. InstanceRep  → set of ref-IDs that carry geometry ──
            geometry_refs: set = set()
            for irep in root.findall('.//x:InstanceRep', nsm):
                agg = irep.findtext(f'{{{ns}}}IsAggregatedBy')
                if agg:
                    geometry_refs.add(agg)

            # ── 3a. ReferenceRep → associatedFile (binary .3DRep) ────
            refrep_file: Dict[str, str] = {}
            for rrep in root.findall('.//x:ReferenceRep', nsm):
                rid = rrep.get('id')
                afile = rrep.get('associatedFile', '')
                if afile:
                    # strip "urn:3DXML:" prefix
                    if ':' in afile:
                        afile = afile.rsplit(':', 1)[-1]
                    refrep_file[rid] = afile

            # ── 3b. Reference3D → .3DRep file (through InstanceRep) ──
            ref_to_file: Dict[str, str] = {}
            for irep in root.findall('.//x:InstanceRep', nsm):
                agg = irep.findtext(f'{{{ns}}}IsAggregatedBy')
                inst_of = irep.findtext(f'{{{ns}}}IsInstanceOf')
                if agg and inst_of and inst_of in refrep_file:
                    ref_to_file[agg] = refrep_file[inst_of]

            zip_names = set(names)   # for quick lookup

            # ── 4. Root reference ID ──────────────────────────────────
            ps = root.find('.//x:ProductStructure', nsm)
            root_id = ps.get('root', '1') if ps is not None else '1'

            # ── 5. Cache: does a subtree contain any geometry? ────────
            _geo_cache: Dict[str, bool] = {}

            def _has_geometry(ref_id: str, depth: int = 0) -> bool:
                if ref_id in _geo_cache:
                    return _geo_cache[ref_id]
                if depth > 40:
                    return False
                if ref_id in geometry_refs:
                    _geo_cache[ref_id] = True
                    return True
                for child_id, *_ in children_map.get(ref_id, []):
                    if _has_geometry(child_id, depth + 1):
                        _geo_cache[ref_id] = True
                        return True
                _geo_cache[ref_id] = False
                return False

            # ── 6. Build clean assembly tree ──────────────────────────
            colors = [
                (0.25, 0.55, 0.95, 1.0), (0.95, 0.35, 0.25, 1.0),
                (0.25, 0.85, 0.35, 1.0), (0.95, 0.75, 0.15, 1.0),
                (0.75, 0.25, 0.85, 1.0), (0.15, 0.85, 0.85, 1.0),
                (0.95, 0.55, 0.15, 1.0), (0.55, 0.55, 0.95, 1.0),
                (0.85, 0.45, 0.65, 1.0), (0.45, 0.75, 0.55, 1.0),
                (0.65, 0.65, 0.35, 1.0), (0.35, 0.55, 0.75, 1.0),
            ]
            part_count = [0]
            color_idx = [0]
            MAX_PARTS = 300
            cgr_hits = [0]         # count of parts where CGR mesh was used

            # ── helper: collect .3DRep filenames for a ref + descendants
            _drep_cache: Dict[str, List[str]] = {}

            def _collect_3drep_files(rid: str, depth: int = 0) -> List[str]:
                if rid in _drep_cache:
                    return _drep_cache[rid]
                if depth > 40:
                    return []
                files: List[str] = []
                if rid in ref_to_file:
                    files.append(ref_to_file[rid])
                for child_id, *_ in children_map.get(rid, []):
                    files.extend(_collect_3drep_files(child_id, depth + 1))
                _drep_cache[rid] = files
                return files

            def _try_load_cgr(ref_id: str) -> Optional[dict]:
                """Try to extract a triangle mesh from the CGR .3DRep."""
                for fname in _collect_3drep_files(ref_id):
                    if fname in zip_names:
                        try:
                            mesh = _parse_cgr_mesh(zf.read(fname))
                            if mesh is not None:
                                return mesh
                        except Exception:
                            pass
                return None

            def _proxy_mesh(name: str, idx: int) -> dict:
                """Generate a small proxy shape centered at origin.

                Instance3D transforms handle real-world positioning, so
                proxy shapes must NOT use grid offsets.
                """
                nm = name.lower()
                ox, oy, oz = 0.0, 0.0, 0.0
                if any(w in nm for w in ('vis', 'bolt', 'screw', 'ecrou',
                                          'nut', 'goupi', 'fix')):
                    return _make_cylinder(3, 12, 8, ox=ox, oy=oy, oz=oz)
                if any(w in nm for w in ('engrenage', 'gear', 'pignon',
                                          'pully', 'pulley')):
                    return _make_gear(30, 15, 12, 5, ox=ox, oy=oy, oz=oz)
                if any(w in nm for w in ('casing', 'housing', 'cover',
                                          'carter', 'carter')):
                    return _make_box(80, 60, 50, ox=ox, oy=oy, oz=oz)
                if any(w in nm for w in ('ressort', 'spring')):
                    return _make_cylinder(5, 25, 10, ox=ox, oy=oy, oz=oz)
                if any(w in nm for w in ('belt', 'courroie')):
                    return _make_cylinder(50, 10, 20, ox=ox, oy=oy, oz=oz)
                if any(w in nm for w in ('flange', 'bride')):
                    return _make_cylinder(25, 8, 16, ox=ox, oy=oy, oz=oz)
                if any(w in nm for w in ('washer', 'rondelle')):
                    return _make_cylinder(8, 3, 14, ox=ox, oy=oy, oz=oz)
                if any(w in nm for w in ('bearing', 'roulement', 'butee')):
                    return _make_cylinder(15, 10, 16, ox=ox, oy=oy, oz=oz)
                return _make_box(
                    10 + (idx % 3) * 5,
                    8 + (idx % 5) * 3,
                    7 + (idx % 4) * 4,
                    ox=ox, oy=oy, oz=oz,
                )

            def build_node(ref_id: str, depth: int = 0) -> Optional[AssemblyNode]:
                if part_count[0] >= MAX_PARTS:
                    return None
                name = ref_map.get(ref_id, f'Node_{ref_id}')

                # Skip CATIA-internal nodes (*SOL*, CATIA_MODEL, hex GUIDs)
                if _is_internal_node(name):
                    return None

                clean = _clean_catia_name(name)
                kids = children_map.get(ref_id, [])

                # Filter to meaningful (non-internal) children only
                valid_kids = [
                    (cid, iname, xf) for cid, iname, xf in kids
                    if not _is_internal_node(ref_map.get(cid, ''))
                ]
                # Process leaf parts FIRST so top-level parts aren't starved
                # by deep assemblies consuming the part budget.
                valid_kids.sort(key=lambda x: len(children_map.get(x[0], [])))

                # Collect meaningful child nodes
                meaningful: List[AssemblyNode] = []
                for child_id, _, xf in valid_kids:
                    if part_count[0] >= MAX_PARTS:
                        break
                    child_node = build_node(child_id, depth + 1)
                    if child_node:
                        # Apply Instance3D transform from parent → child
                        if xf and child_node.transform is None:
                            child_node.transform = xf
                        meaningful.append(child_node)

                if meaningful:
                    # Assembly — has real children
                    node = AssemblyNode(clean, "assembly")
                    node.children = meaningful
                    return node

                if _has_geometry(ref_id):
                    # Leaf part — all children were internal, geometry exists
                    node = AssemblyNode(clean, "part")
                    # Try real mesh from binary CGR first
                    cgr_mesh = _try_load_cgr(ref_id)
                    if cgr_mesh is not None:
                        node.mesh_data = cgr_mesh
                        cgr_hits[0] += 1
                    else:
                        node.mesh_data = _proxy_mesh(clean, part_count[0])
                    node.color = colors[color_idx[0] % len(colors)]
                    color_idx[0] += 1
                    part_count[0] += 1
                    return node

                # No geometry, no meaningful children → skip
                return None

            root_node = build_node(root_id)
            if root_node is None:
                root_node = AssemblyNode(
                    _clean_catia_name(ref_map.get(root_id, Path(filepath).stem)),
                    "assembly",
                )

            logger.info(
                f"3DXML parsed: {part_count[0]} parts from "
                f"{len(ref_map)} refs ({len(geometry_refs)} with geometry, "
                f"{sum(1 for n in ref_map.values() if _is_internal_node(n))} internal skipped, "
                f"{cgr_hits[0]} CGR meshes extracted)"
            )
            return root_node

    except Exception as e:
        logger.error(f"3DXML fast parse failed: {e}", exc_info=True)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Trimesh fallback (STL, OBJ)
# ══════════════════════════════════════════════════════════════════════════════

def _trimesh_import(filepath):
    try:
        import trimesh
        scene_or_mesh = trimesh.load(filepath, force=None)
        root = AssemblyNode(Path(filepath).stem, "assembly")
        colors = [
            (0.2,0.5,0.9,1),(0.9,0.3,0.2,1),(0.2,0.8,0.3,1),(0.9,0.7,0.1,1),
            (0.7,0.2,0.8,1),(0.1,0.8,0.8,1),(0.9,0.5,0.1,1),(0.5,0.5,0.9,1),
        ]
        if isinstance(scene_or_mesh, trimesh.Scene):
            for i, (name, geom) in enumerate(scene_or_mesh.geometry.items()):
                if isinstance(geom, trimesh.Trimesh) and len(geom.vertices) > 0:
                    part = AssemblyNode(name, "part")
                    part.mesh_data = {
                        "vertices": np.array(geom.vertices, np.float32),
                        "faces": np.array(geom.faces, np.uint32),
                    }
                    part.color = colors[i % len(colors)]
                    root.children.append(part)
        elif isinstance(scene_or_mesh, trimesh.Trimesh):
            part = AssemblyNode(Path(filepath).stem, "part")
            part.mesh_data = {
                "vertices": np.array(scene_or_mesh.vertices, np.float32),
                "faces": np.array(scene_or_mesh.faces, np.uint32),
            }
            part.color = colors[0]
            root.children.append(part)
        return root if root.children else None
    except Exception as e:
        logger.error(f"trimesh import failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# OCC import for STEP/IGES
# ══════════════════════════════════════════════════════════════════════════════

def _calc_adaptive_deflection(shape) -> Tuple[float, float]:
    """Compute adaptive linear and angular deflection based on shape bounding box."""
    try:
        from OCP.BRepBndLib import BRepBndLib
        from OCP.Bnd import Bnd_Box
        box = Bnd_Box()
        BRepBndLib.Add_s(shape, box)
        if not box.IsVoid():
            xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
            diag = math.sqrt((xmax - xmin)**2 + (ymax - ymin)**2 + (zmax - zmin)**2)
            if diag > 1e-4:
                # Scale deflection to 0.15% of diagonal, bounded between 1e-4 and 1.0
                lin_defl = max(1e-4, min(1.0, diag * 0.0015))
                return lin_defl, 0.5
    except Exception:
        pass
    return 0.5, 0.5


def _tessellate_shape(shape, lin_defl=None, ang_defl=0.5) -> Optional[dict]:
    """Tessellate a single TopoDS_Shape into {vertices, faces} arrays with adaptive meshing."""
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.BRep import BRep_Tool
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    from OCP.BRepMesh import BRepMesh_IncrementalMesh

    if lin_defl is None:
        lin_defl, ang_defl = _calc_adaptive_deflection(shape)

    try:
        BRepMesh_IncrementalMesh(shape, lin_defl, False, ang_defl, True)
    except Exception:
        pass

    vl, fl, vo = [], [], 0
    fe = TopExp_Explorer(shape, TopAbs_FACE)
    while fe.More():
        face = TopoDS.Face_s(fe.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None or tri.NbTriangles() == 0:
            try:
                BRepMesh_IncrementalMesh(face, lin_defl, False, ang_defl, True)
                tri = BRep_Tool.Triangulation_s(face, loc)
            except Exception:
                pass

        if tri and tri.NbNodes() > 0 and tri.NbTriangles() > 0:
            trsf = loc.Transformation()
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i)
                p.Transform(trsf)
                vl.append([p.X(), p.Y(), p.Z()])
            for i in range(1, tri.NbTriangles() + 1):
                t = tri.Triangle(i)
                a, b, c = t.Get()
                fl.append([a - 1 + vo, b - 1 + vo, c - 1 + vo])
            vo += tri.NbNodes()
        fe.Next()

    if not vl:
        return None
    return {
        "vertices": np.array(vl, np.float32),
        "faces": np.array(fl, np.uint32),
    }


def _is_valid_step(filepath: str) -> bool:
    """Quickly verify file has valid STEP ISO-10303 ASCII header without crashing OCC."""
    try:
        p = Path(filepath)
        if not p.is_file() or p.stat().st_size < 50:
            return False
        with open(filepath, 'rb') as f:
            header = f.read(512)
            return b'ISO-10303' in header or b'HEADER' in header
    except Exception:
        return False


def _validate_step_file(filepath):
    """Check if a STEP file is complete and repair if truncated.
    Supports converted files from SolidWorks, Inventor, CATIA, Rhino, and mesh converters.
    """
    ext = Path(filepath).suffix.lower()
    if ext not in ('.step', '.stp'):
        return filepath
    try:
        size = os.path.getsize(filepath)
        # Check if file is encrypted by Microsoft Information Protection / Purview
        with open(filepath, 'rb') as f:
            head = f.read(128)
        if b'MSMAMARPCRYPT' in head:
            raise ValueError(
                "This file is encrypted with Microsoft Information Protection / Purview (MSMAMARPCRYPT sensitivity label). "
                "CAD parsers and WebGL converters cannot read encrypted binary containers. "
                "Please use the unencrypted CAD file from your workspace folder or re-export without sensitivity encryption."
            )

        # Read last 8192 bytes to check for proper ending (handles comments/whitespace)
        read_len = min(size, 8192)
        with open(filepath, 'rb') as f:
            f.seek(size - read_len)
            tail = f.read().decode('utf-8', errors='ignore').strip()
        if 'END-ISO-10303-21' in tail or 'end-iso-10303-21' in tail.lower():
            return filepath

        # Check full file if not found in last 8KB (in case of large trailing comment blocks)
        with open(filepath, 'rb') as f:
            full_data = f.read()
        if b'END-ISO-10303-21' in full_data or b'end-iso-10303-21' in full_data.lower():
            return filepath

        # Trailer is missing: Auto-repair to salvage all written entities
        logger.warning(
            f"STEP file appears truncated (missing END-ISO-10303-21 trailer marker). "
            f"Attempting automatic trailer recovery..."
        )
        last_semi = full_data.rfind(b';')
        if last_semi > 0:
            repaired_data = full_data[:last_semi + 1] + b"\nENDSEC;\nEND-ISO-10303-21;\n"
        else:
            repaired_data = full_data + b"\n;\nENDSEC;\nEND-ISO-10303-21;\n"

        repaired_path = filepath + ".repaired.stp"
        with open(repaired_path, 'wb') as rf:
            rf.write(repaired_data)
        logger.info(f"Auto-repaired truncated STEP file -> {repaired_path}")
        return repaired_path

    except ValueError:
        raise
    except Exception as e:
        logger.warning(f"STEP validation notice: {e}")
        return filepath


def _try_occ_import(filepath):
    """Load STEP / IGES via OpenCASCADE (OCP).

    Multi-tier strategy:
      1. XDE (Extended Data Framework) — preserves part names + hierarchy + assemblies.
      2. Plain reader with multi-shape compound resolution & adaptive meshing.
      3. Face/shell extraction for converted surface & faceted models.
    """
    try:
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL, TopAbs_COMPOUND, TopAbs_COMPSOLID
        from OCP.TopoDS import TopoDS
        from OCP.Interface import Interface_Static

        ext = Path(filepath).suffix.lower()

        colors = [
            (0.25, 0.55, 0.95, 1.0), (0.95, 0.35, 0.25, 1.0),
            (0.25, 0.85, 0.35, 1.0), (0.95, 0.75, 0.15, 1.0),
            (0.75, 0.25, 0.85, 1.0), (0.15, 0.85, 0.85, 1.0),
            (0.95, 0.55, 0.15, 1.0), (0.55, 0.55, 0.95, 1.0),
            (0.85, 0.45, 0.65, 1.0), (0.45, 0.75, 0.55, 1.0),
            (0.65, 0.65, 0.35, 1.0), (0.35, 0.55, 0.75, 1.0),
        ]

        # ── 1. Try XDE for real part names + colours ──────────────
        try:
            xde_root = _try_occ_xde(filepath, ext, colors)
            if xde_root is not None:
                total_parts = sum(1 for _ in _count_parts(xde_root))
                if total_parts > 0:
                    return xde_root
                logger.info("XDE returned 0 parts, proceeding to plain reader...")
        except Exception as xde_err:
            logger.warning(f"XDE parse failed: {xde_err}")

        # ── 2. Plain reader → solid & surface level tessellation ──
        if ext in ('.step', '.stp'):
            if not _is_valid_step(filepath):
                logger.warning(f"Skipping OCC read: {filepath} is not a valid STEP file header")
                return None
            try:
                from OCP.STEPControl import STEPControl_Reader
                # Configure Interface_Static for permissive conversion of all shapes & assemblies
                Interface_Static.SetIVal_s('read.step.shape.repr', 1)
                Interface_Static.SetIVal_s('read.step.assembly.level', 1)
                Interface_Static.SetIVal_s('read.step.shape.aspect', 1)

                reader = STEPControl_Reader()
                logger.info(f"Loading STEP file via plain reader: {filepath}")
                status = reader.ReadFile(str(filepath))
                logger.info(f"ReadFile status: {status}")
            except Exception as step_err:
                logger.error(f"STEP reader error: {step_err}")
                raise
        elif ext in ('.iges', '.igs'):
            from OCP.IGESControl import IGESControl_Reader
            reader = IGESControl_Reader()
            status = reader.ReadFile(str(filepath))
        else:
            return None

        # Check if roots can be transferred (even on minor syntax warnings or non-RetDone)
        num_roots = 0
        try:
            num_roots = reader.NbRootsForTransfer()
        except Exception:
            pass

        if status != IFSelect_RetDone and num_roots == 0:
            logger.warning(f"OCC reader status {status} and 0 roots for {filepath}")

        try:
            reader.TransferRoots()
        except Exception as tr_err:
            logger.warning(f"TransferRoots exception: {tr_err}")

        shape = reader.OneShape()

        # If OneShape() is NULL (common in multi-root converted files), compose from reader.NbShapes()
        if shape.IsNull() or shape.ShapeType() not in (TopAbs_SOLID, TopAbs_COMPOUND, TopAbs_SHELL, TopAbs_COMPSOLID, TopAbs_FACE):
            nb_s = reader.NbShapes()
            if nb_s > 0:
                from OCP.BRep import BRep_Builder
                from OCP.TopoDS import TopoDS_Compound
                builder = BRep_Builder()
                compound = TopoDS_Compound()
                builder.MakeCompound(compound)
                added = 0
                for i in range(1, nb_s + 1):
                    s = reader.Shape(i)
                    if not s.IsNull():
                        builder.Add(compound, s)
                        added += 1
                if added > 0:
                    shape = compound
                    logger.info(f"Composed compound shape from {added} root shapes")

        if shape.IsNull():
            logger.warning(f"OCC plain reader yielded null shape for {filepath}")
            return None

        # Adaptive tessellation deflection based on model scale
        lin_defl, ang_defl = _calc_adaptive_deflection(shape)
        try:
            BRepMesh_IncrementalMesh(shape, lin_defl, False, ang_defl, True)
        except Exception:
            pass

        root = AssemblyNode(Path(filepath).stem, "assembly")

        # Explore solids first
        explorer = TopExp_Explorer(shape, TopAbs_SOLID)
        si = 0
        while explorer.More():
            solid = TopoDS.Solid_s(explorer.Current())
            mesh = _tessellate_shape(solid, lin_defl, ang_defl)
            if mesh:
                part = AssemblyNode(f"Part_{si + 1}", "part")
                part.mesh_data = mesh
                part.color = colors[si % len(colors)]
                root.children.append(part)
                si += 1
            explorer.Next()

        # Fallback 1: if no solids, explore shells (common in sheet metal / surface CAD)
        if not root.children:
            explorer = TopExp_Explorer(shape, TopAbs_SHELL)
            while explorer.More():
                shell = TopoDS.Shell_s(explorer.Current())
                mesh = _tessellate_shape(shell, lin_defl, ang_defl)
                if mesh:
                    part = AssemblyNode(f"Shell_{si + 1}", "part")
                    part.mesh_data = mesh
                    part.color = colors[si % len(colors)]
                    root.children.append(part)
                    si += 1
                explorer.Next()

        # Fallback 2: if no solids or shells, explore standalone faces (faceted BREP / mesh-converted STEP)
        if not root.children:
            explorer = TopExp_Explorer(shape, TopAbs_FACE)
            face_vl, face_fl, vo = [], [], 0
            while explorer.More():
                face = TopoDS.Face_s(explorer.Current())
                fm = _tessellate_shape(face, lin_defl, ang_defl)
                if fm:
                    face_vl.append(fm["vertices"])
                    face_fl.append(fm["faces"] + vo)
                    vo += len(fm["vertices"])
                explorer.Next()
            if face_vl:
                part = AssemblyNode(f"{Path(filepath).stem}_Surface", "part")
                part.mesh_data = {
                    "vertices": np.vstack(face_vl).astype(np.float32),
                    "faces": np.vstack(face_fl).astype(np.uint32),
                }
                part.color = colors[0]
                root.children.append(part)

        # Fallback 3: tessellate whole shape as one body
        if not root.children:
            mesh = _tessellate_shape(shape, lin_defl, ang_defl)
            if mesh:
                part = AssemblyNode(Path(filepath).stem, "part")
                part.mesh_data = mesh
                part.color = colors[0]
                root.children.append(part)

        if root.children:
            logger.info(f"OCC plain import: {len(root.children)} parts from {filepath}")
            return root
        return None

    except ImportError:
        logger.info("OCP not installed — STEP/IGES support unavailable")
        return None
    except Exception as e:
        logger.error(f"OCC import failed: {e}", exc_info=True)
        return None


def _try_occ_xde(filepath, ext, colors):
    """Try XDE (Extended Data Framework) import for named parts + hierarchy."""
    try:
        from OCP.STEPCAFControl import STEPCAFControl_Reader
        from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool, XCAFDoc_ColorTool
        from OCP.TDocStd import TDocStd_Document
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.XCAFApp import XCAFApp_Application
        from OCP.TDF import TDF_LabelSequence, TDF_Label
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
        from OCP.XCAFDoc import XCAFDoc_ColorGen, XCAFDoc_ColorSurf, XCAFDoc_ColorCurv
        from OCP.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
        from OCP.Interface import Interface_Static

        if ext not in ('.step', '.stp'):
            return None

        # Permissive reading mode for XCAF
        Interface_Static.SetIVal_s('read.step.shape.repr', 1)
        Interface_Static.SetIVal_s('read.step.assembly.level', 1)
        Interface_Static.SetIVal_s('read.step.shape.aspect', 1)

        app = XCAFApp_Application.GetApplication_s()
        doc = TDocStd_Document(TCollection_ExtendedString("mdtv-xcaf"))
        app.InitDocument(doc)

        reader = STEPCAFControl_Reader()
        reader.SetColorMode(True)
        reader.SetNameMode(True)
        reader.SetLayerMode(False)

        from OCP.IFSelect import IFSelect_RetDone
        status = reader.ReadFile(str(filepath))
        
        # In converted files, attempt transfer even if status had warnings/non-critical issues
        if not reader.Transfer(doc):
            return None

        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
        color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

        # Get free shapes; if empty (common in converted STEP files), get all shapes
        labels = TDF_LabelSequence()
        shape_tool.GetFreeShapes(labels)
        if labels.Length() == 0:
            shape_tool.GetShapes(labels)

        if labels.Length() == 0:
            return None

        root = AssemblyNode(Path(filepath).stem, "assembly")

        def _label_name(label: TDF_Label) -> str:
            """Extract name from an XDE label."""
            from OCP.TDataStd import TDataStd_Name
            name_attr = TDataStd_Name()
            if label.FindAttribute(TDataStd_Name.GetID_s(), name_attr):
                return name_attr.Get().ToExtString()
            return ""

        def _label_color(label: TDF_Label) -> Optional[Tuple[float, ...]]:
            """Extract colour from XDE label."""
            try:
                c = Quantity_Color()
                if (color_tool.GetColor_s(label, XCAFDoc_ColorGen, c) or
                    color_tool.GetColor_s(label, XCAFDoc_ColorSurf, c) or
                    color_tool.GetColor_s(label, XCAFDoc_ColorCurv, c)):
                    return (c.Red(), c.Green(), c.Blue(), 1.0)
            except Exception:
                pass
            return None

        part_idx = [0]

        def _process_label(label: TDF_Label, depth: int = 0) -> Optional[AssemblyNode]:
            if depth > 50:
                return None

            name = _label_name(label) or f"Part_{part_idx[0] + 1}"
            name = _clean_catia_name(name)

            # Check if this is an assembly (has sub-components)
            sub_labels = TDF_LabelSequence()
            shape_tool.GetComponents_s(label, sub_labels)

            if sub_labels.Length() > 0:
                node = AssemblyNode(name, "assembly")
                for i in range(sub_labels.Length()):
                    ref_label = sub_labels.Value(i + 1)
                    resolved = TDF_Label()
                    if shape_tool.GetReferredShape_s(ref_label, resolved):
                        child = _process_label(resolved, depth + 1)
                    else:
                        child = _process_label(ref_label, depth + 1)
                    if child:
                        try:
                            ref_shape = shape_tool.GetShape_s(ref_label)
                            loc = ref_shape.Location()
                            if not loc.IsIdentity():
                                trsf = loc.Transformation()
                                child.transform = [
                                    trsf.Value(1,1), trsf.Value(2,1), trsf.Value(3,1), 0,
                                    trsf.Value(1,2), trsf.Value(2,2), trsf.Value(3,2), 0,
                                    trsf.Value(1,3), trsf.Value(2,3), trsf.Value(3,3), 0,
                                    trsf.Value(1,4), trsf.Value(2,4), trsf.Value(3,4), 1,
                                ]
                        except Exception:
                            pass
                        node.children.append(child)
                return node if node.children else None

            # Leaf — get shape and tessellate with adaptive deflection
            shape = shape_tool.GetShape_s(label)
            if shape.IsNull():
                return None

            lin_defl, ang_defl = _calc_adaptive_deflection(shape)
            try:
                BRepMesh_IncrementalMesh(shape, lin_defl, False, ang_defl, True)
            except Exception:
                pass

            # Explore solids, then shells, then standalone faces
            meshes_vl, meshes_fl, vo = [], [], 0
            explorer = TopExp_Explorer(shape, TopAbs_SOLID)
            while explorer.More():
                solid = TopoDS.Solid_s(explorer.Current())
                m = _tessellate_shape(solid, lin_defl, ang_defl)
                if m:
                    meshes_vl.append(m["vertices"])
                    shifted = m["faces"] + vo
                    meshes_fl.append(shifted)
                    vo += len(m["vertices"])
                explorer.Next()

            if not meshes_vl:
                explorer = TopExp_Explorer(shape, TopAbs_SHELL)
                while explorer.More():
                    shell = TopoDS.Shell_s(explorer.Current())
                    m = _tessellate_shape(shell, lin_defl, ang_defl)
                    if m:
                        meshes_vl.append(m["vertices"])
                        shifted = m["faces"] + vo
                        meshes_fl.append(shifted)
                        vo += len(m["vertices"])
                    explorer.Next()

            if not meshes_vl:
                m = _tessellate_shape(shape, lin_defl, ang_defl)
                if m:
                    meshes_vl.append(m["vertices"])
                    meshes_fl.append(m["faces"])

            if not meshes_vl:
                return None

            verts = np.vstack(meshes_vl).astype(np.float32)
            faces = np.vstack(meshes_fl).astype(np.uint32)

            node = AssemblyNode(name, "part")
            node.mesh_data = {"vertices": verts, "faces": faces}
            node.color = _label_color(label) or colors[part_idx[0] % len(colors)]
            part_idx[0] += 1
            return node

        for i in range(labels.Length()):
            label = labels.Value(i + 1)
            child = _process_label(label)
            if child:
                if child.node_type == "assembly" and labels.Length() == 1:
                    child.name = Path(filepath).stem
                    root = child
                else:
                    root.children.append(child)

        total = sum(1 for _ in _count_parts(root))
        if total > 0:
            logger.info(f"OCC XDE import: {total} parts with names from {filepath}")
            return root

        logger.info(f"OCC XDE import found 0 valid geometry parts in {filepath}")
        return None

    except (ImportError, AttributeError) as e:
        logger.debug(f"XDE import not available: {e}")
        return None
    except Exception as e:
        logger.debug(f"XDE import failed: {e}")
        return None


def _count_parts(node):
    """Yield each leaf part in the assembly tree."""
    if node.node_type == "part":
        yield node
    for ch in node.children:
        yield from _count_parts(ch)


# ══════════════════════════════════════════════════════════════════════════════
# Demo gearbox assembly
# ══════════════════════════════════════════════════════════════════════════════

def generate_demo_assembly():
    root = AssemblyNode("Gearbox_Assembly", "assembly")

    # ── Housing ────────────────────────────────────────────────
    housing = AssemblyNode("Housing", "assembly")

    hb = AssemblyNode("Housing_Body", "part")
    hb.mesh_data = _make_hollow_box(10, 6, 8, 0.4, 0, -3, 0)
    hb.color = (0.55, 0.58, 0.62, 0.55)
    housing.children.append(hb)

    hc = AssemblyNode("Housing_Cover", "part")
    hc.mesh_data = _make_box(10.4, 0.35, 8.4, 0, 3.15, 0)
    hc.color = (0.50, 0.53, 0.57, 0.75)
    housing.children.append(hc)

    # Cover gasket
    gask = AssemblyNode("Cover_Gasket", "part")
    gask.mesh_data = _make_box(10.2, 0.05, 8.2, 0, 2.97, 0)
    gask.color = (0.15, 0.15, 0.15, 1.0)
    housing.children.append(gask)

    # Mounting flanges (feet)
    for i, (fx, fz) in enumerate([(-4.2, -3.5), (4.2, -3.5), (-4.2, 3.5), (4.2, 3.5)]):
        f = AssemblyNode(f"Mounting_Flange_{i+1}", "part")
        f.mesh_data = _make_box(1.6, 0.5, 1.6, fx, -3.25, fz)
        f.color = (0.55, 0.58, 0.62, 1.0)
        housing.children.append(f)

    # Inspection window
    iw = AssemblyNode("Inspection_Window", "part")
    iw.mesh_data = _make_box(2.0, 0.12, 1.5, 5.05, 0, 0)
    iw.color = (0.3, 0.6, 0.8, 0.35)
    housing.children.append(iw)

    # Breather plug
    bp = AssemblyNode("Breather_Plug", "part")
    bp.mesh_data = _make_cylinder(0.2, 0.6, 12, 0, 3.35, 0)
    bp.color = (0.25, 0.25, 0.3, 1.0)
    housing.children.append(bp)

    # Drain plug
    dp = AssemblyNode("Drain_Plug", "part")
    dp.mesh_data = _make_cylinder(0.25, 0.45, 12, 0, -3.25, -3.5)
    dp.color = (0.8, 0.6, 0.1, 1.0)
    housing.children.append(dp)

    root.children.append(housing)

    # ── Input Shaft Assembly ───────────────────────────────────
    inp = AssemblyNode("Input_Shaft_Assembly", "assembly")

    isft = AssemblyNode("Input_Shaft", "part")
    isft.mesh_data = _make_cylinder(0.38, 14, 32, -6, 0.5, -2.0)
    isft.color = (0.78, 0.78, 0.82, 1.0)
    inp.children.append(isft)

    # Input pinion (small driving gear)
    ip = AssemblyNode("Input_Pinion", "part")
    ip.mesh_data = _make_gear(1.1, 1.3, 14, 0.22, -1.0, 0.5, -2.0)
    ip.color = (0.72, 0.58, 0.12, 1.0)
    inp.children.append(ip)

    # Input keyway
    ik = AssemblyNode("Input_Keyway", "part")
    ik.mesh_data = _make_box(0.2, 0.12, 1.4, -3.5, 0.88, -2.0)
    ik.color = (0.6, 0.6, 0.65, 1.0)
    inp.children.append(ik)

    # Input coupling flange
    icf = AssemblyNode("Input_Coupling_Flange", "part")
    icf.mesh_data = _make_cylinder(1.0, 0.5, 24, -6.0, 0.5, -2.0)
    icf.color = (0.65, 0.65, 0.70, 1.0)
    inp.children.append(icf)

    # Input shaft collar
    isc = AssemblyNode("Input_Shaft_Collar", "part")
    isc.mesh_data = _make_tube(0.55, 0.38, 0.3, 24, -2.5, 0.5, -2.0)
    isc.color = (0.70, 0.70, 0.73, 1.0)
    inp.children.append(isc)

    root.children.append(inp)

    # ── Intermediate Shaft Assembly ────────────────────────────
    mid = AssemblyNode("Intermediate_Shaft_Assembly", "assembly")

    msft = AssemblyNode("Intermediate_Shaft", "part")
    msft.mesh_data = _make_cylinder(0.42, 10, 32, -4, 0.3, 1.2)
    msft.color = (0.78, 0.78, 0.82, 1.0)
    mid.children.append(msft)

    # Big driven gear (meshes with input pinion)
    mdg = AssemblyNode("Intermediate_Driven_Gear", "part")
    mdg.mesh_data = _make_gear(2.2, 1.3, 28, 0.28, -0.5, 0.3, 1.2)
    mdg.color = (0.82, 0.62, 0.10, 1.0)
    mid.children.append(mdg)

    # Small output pinion on intermediate shaft
    mop = AssemblyNode("Intermediate_Pinion", "part")
    mop.mesh_data = _make_gear(1.0, 1.6, 12, 0.20, 2.0, 0.3, 1.2)
    mop.color = (0.75, 0.55, 0.10, 1.0)
    mid.children.append(mop)

    # Spacer ring
    msr = AssemblyNode("Intermediate_Spacer", "part")
    msr.mesh_data = _make_tube(0.60, 0.42, 0.25, 24, 1.3, 0.3, 1.2)
    msr.color = (0.50, 0.50, 0.55, 1.0)
    mid.children.append(msr)

    root.children.append(mid)

    # ── Output Shaft Assembly ──────────────────────────────────
    out = AssemblyNode("Output_Shaft_Assembly", "assembly")

    osft = AssemblyNode("Output_Shaft", "part")
    osft.mesh_data = _make_cylinder(0.50, 16, 32, -7, -0.8, 2.8)
    osft.color = (0.80, 0.80, 0.84, 1.0)
    out.children.append(osft)

    # Large output gear
    og = AssemblyNode("Output_Gear", "part")
    og.mesh_data = _make_gear(2.5, 1.6, 30, 0.30, -1.0, -0.8, 2.8)
    og.color = (0.70, 0.52, 0.08, 1.0)
    out.children.append(og)

    # Output coupling flange
    ocf = AssemblyNode("Output_Coupling_Flange", "part")
    ocf.mesh_data = _make_cylinder(1.3, 0.6, 24, 8.0, -0.8, 2.8)
    ocf.color = (0.65, 0.65, 0.70, 1.0)
    out.children.append(ocf)

    # Output keyway
    ok = AssemblyNode("Output_Keyway", "part")
    ok.mesh_data = _make_box(0.25, 0.15, 1.8, 5.0, -0.3, 2.8)
    ok.color = (0.6, 0.6, 0.65, 1.0)
    out.children.append(ok)

    # Output seal sleeve
    osl = AssemblyNode("Output_Seal_Sleeve", "part")
    osl.mesh_data = _make_tube(0.65, 0.50, 0.5, 24, 6.5, -0.8, 2.8)
    osl.color = (0.72, 0.72, 0.76, 1.0)
    out.children.append(osl)

    root.children.append(out)

    # ── Bearings ───────────────────────────────────────────────
    brg = AssemblyNode("Bearings", "assembly")

    bearing_locs = [
        ("Input_Bearing_DE",   -4.5, 0.5, -2.0),
        ("Input_Bearing_NDE",   3.5, 0.5, -2.0),
        ("Inter_Bearing_DE",   -3.2, 0.3,  1.2),
        ("Inter_Bearing_NDE",   3.5, 0.3,  1.2),
        ("Output_Bearing_DE",  -5.0, -0.8, 2.8),
        ("Output_Bearing_NDE",  5.5, -0.8, 2.8),
    ]
    for bname, bx, by, bz in bearing_locs:
        ba = AssemblyNode(bname, "assembly")
        # Outer race
        bor = AssemblyNode(f"{bname}_Outer_Race", "part")
        bor.mesh_data = _make_tube(0.75, 0.58, 0.55, 32, bx, by, bz)
        bor.color = (0.42, 0.42, 0.46, 1.0)
        ba.children.append(bor)
        # Inner race
        bir = AssemblyNode(f"{bname}_Inner_Race", "part")
        bir.mesh_data = _make_tube(0.52, 0.40, 0.55, 32, bx, by, bz)
        bir.color = (0.45, 0.45, 0.50, 1.0)
        ba.children.append(bir)
        # Balls (8 per bearing)
        for j in range(8):
            a = 2 * math.pi * j / 8
            br = 0.55  # ball circle radius
            ball = AssemblyNode(f"{bname}_Ball_{j+1}", "part")
            ball.mesh_data = _make_sphere(0.08, 10,
                                          bx + br * math.cos(a),
                                          by + 0.275,
                                          bz + br * math.sin(a))
            ball.color = (0.85, 0.85, 0.90, 1.0)
            ba.children.append(ball)
        brg.children.append(ba)

    root.children.append(brg)

    # ── Seals ──────────────────────────────────────────────────
    seals = AssemblyNode("Seals", "assembly")

    seal_locs = [
        ("Input_Oil_Seal",  -5.0, 0.5, -2.0),
        ("Input_Dust_Seal", -5.3, 0.5, -2.0),
        ("Output_Oil_Seal",  6.2, -0.8, 2.8),
        ("Output_Dust_Seal", 6.5, -0.8, 2.8),
    ]
    for sname, sx, sy, sz in seal_locs:
        s = AssemblyNode(sname, "part")
        s.mesh_data = _make_tube(0.65, 0.35, 0.15, 24, sx, sy, sz)
        s.color = (0.12, 0.12, 0.14, 1.0)
        seals.children.append(s)

    root.children.append(seals)

    # ── Fasteners ──────────────────────────────────────────────
    fast = AssemblyNode("Fasteners", "assembly")

    # Cover bolts (12 around perimeter)
    cover_bolt_pos = [
        (-4.2, 3.15, -3.2), (-2.0, 3.15, -3.2), (0, 3.15, -3.2), (2.0, 3.15, -3.2), (4.2, 3.15, -3.2),
        (-4.2, 3.15,  3.2), (-2.0, 3.15,  3.2), (0, 3.15,  3.2), (2.0, 3.15,  3.2), (4.2, 3.15,  3.2),
        (-4.5, 3.15, 0), (4.5, 3.15, 0),
    ]
    for i, (bx, by, bz) in enumerate(cover_bolt_pos):
        b = AssemblyNode(f"Cover_Bolt_M8x25_{i+1}", "part")
        b.mesh_data = _make_bolt(0.10, 0.20, 0.8, 0.2, 12, bx, by, bz)
        b.color = (0.30, 0.30, 0.35, 1.0)
        fast.children.append(b)

    # Mounting bolts (4 through flanges)
    for i, (fx, fz) in enumerate([(-4.2, -3.5), (4.2, -3.5), (-4.2, 3.5), (4.2, 3.5)]):
        b = AssemblyNode(f"Mounting_Bolt_M12x50_{i+1}", "part")
        b.mesh_data = _make_bolt(0.15, 0.28, 1.5, 0.3, 12, fx, -3.5, fz)
        b.color = (0.25, 0.25, 0.30, 1.0)
        fast.children.append(b)

    # Dowel pins (2 on cover)
    for i, (dx, dz) in enumerate([(-4.5, -3.5), (4.5, 3.5)]):
        d = AssemblyNode(f"Dowel_Pin_{i+1}", "part")
        d.mesh_data = _make_cylinder(0.08, 0.6, 12, dx, 2.7, dz)
        d.color = (0.75, 0.75, 0.80, 1.0)
        fast.children.append(d)

    # Washers under cover bolts (selected)
    for i, (bx, by, bz) in enumerate(cover_bolt_pos[:4]):
        w = AssemblyNode(f"Washer_M8_{i+1}", "part")
        w.mesh_data = _make_tube(0.22, 0.11, 0.04, 16, bx, by - 0.04, bz)
        w.color = (0.60, 0.60, 0.65, 1.0)
        fast.children.append(w)

    root.children.append(fast)

    # ── Oil System ─────────────────────────────────────────────
    oil = AssemblyNode("Oil_System", "assembly")

    # Oil level sight glass
    sg = AssemblyNode("Sight_Glass", "part")
    sg.mesh_data = _make_cylinder(0.35, 0.12, 16, 5.06, -1.5, 0)
    sg.color = (0.3, 0.7, 0.4, 0.4)
    oil.children.append(sg)

    # Oil fill cap
    ofc = AssemblyNode("Oil_Fill_Cap", "part")
    ofc.mesh_data = _make_cylinder(0.30, 0.35, 16, -3.0, 3.35, 0)
    ofc.color = (0.85, 0.15, 0.15, 1.0)
    oil.children.append(ofc)

    # Oil deflector disc on intermediate shaft
    od = AssemblyNode("Oil_Deflector", "part")
    od.mesh_data = _make_tube(0.80, 0.42, 0.06, 24, 0.5, 0.3, 1.2)
    od.color = (0.6, 0.6, 0.65, 1.0)
    oil.children.append(od)

    root.children.append(oil)

    # ── Nameplate & Extras ─────────────────────────────────────
    extras = AssemblyNode("Accessories", "assembly")

    np_ = AssemblyNode("Nameplate", "part")
    np_.mesh_data = _make_box(2.0, 0.02, 1.0, -5.02, 1.0, 0)
    np_.color = (0.85, 0.75, 0.15, 1.0)
    extras.children.append(np_)

    # Lifting eyebolt
    le = AssemblyNode("Lifting_Eyebolt", "part")
    le.mesh_data = _make_cylinder(0.12, 1.0, 12, 0, 3.35, 2.0)
    le.color = (0.35, 0.35, 0.40, 1.0)
    extras.children.append(le)
    ler = AssemblyNode("Lifting_Eye_Ring", "part")
    ler.mesh_data = _make_tube(0.35, 0.20, 0.08, 16, 0, 4.35, 2.0)
    ler.color = (0.35, 0.35, 0.40, 1.0)
    extras.children.append(ler)

    root.children.append(extras)

    return root


# ══════════════════════════════════════════════════════════════════════════════
# Main conversion pipeline
# ══════════════════════════════════════════════════════════════════════════════

def rename_glb_meshes(glb_path: str, parts_list: list, unique_parts_list: list) -> None:
    """Rename meshes in an existing GLB file according to the name mapping.
    
    This function takes the original parts list and unique parts list, creates
    a proper mapping (handling duplicates), and applies it to the GLB.
    
    Args:
        glb_path: Path to the GLB file to modify
        parts_list: List of original part names from CAD (may have duplicates)
        unique_parts_list: List of renamed part names (one per occurrence)
    """
    import json
    import logging
    logger = logging.getLogger(__name__)
    
    # Always rename because PartsManager now adds _N suffix to all parts
    # This ensures GLB mesh names match sidebar names exactly
    logger.info(f"Renaming parts in GLB to match sidebar names")
    
    # Create exact mapping for GLB matching. Do not normalize punctuation or
    # separators because CAD assemblies can contain distinct alias-like names.
    exact_name_map = {}  # original_name -> list of unique names

    for orig, uniq in zip(parts_list, unique_parts_list):
        exact_name_map.setdefault(orig, []).append(uniq)
    
    with open(glb_path, 'rb') as f:
        data = f.read()
    
    # Parse GLB header
    magic = data[0:4]
    if magic != b'glTF':
        raise ValueError("Not a valid GLB file")
    
    # Find JSON chunk
    json_chunk_start = 12
    json_length = int.from_bytes(data[json_chunk_start:json_chunk_start+4], 'little')
    json_chunk_type = data[json_chunk_start+4:json_chunk_start+8]
    
    if json_chunk_type != b'JSON':
        raise ValueError("Expected JSON chunk in GLB")
    
    json_data = data[json_chunk_start+8:json_chunk_start+8+json_length]
    gltf = json.loads(json_data.decode('utf-8'))
    
    # Track which index we're at for each normalized original name (for sequential renaming)
    name_position = {}
    
    # Rename meshes - each exact mesh occurrence gets the next name in the list.
    if 'meshes' in gltf:
        for mesh in gltf['meshes']:
            orig_name = mesh.get('name', '')
            if orig_name in exact_name_map:
                # Get the next renamed name for this original
                if orig_name not in name_position:
                    name_position[orig_name] = 0
                
                idx = name_position[orig_name]
                if idx < len(exact_name_map[orig_name]):
                    mesh['name'] = exact_name_map[orig_name][idx]
                    name_position[orig_name] += 1
    
    # Rename nodes as well
    if 'nodes' in gltf:
        name_position = {}  # Reset for nodes
        for node in gltf['nodes']:
            orig_name = node.get('name', '')
            if orig_name in exact_name_map:
                if orig_name not in name_position:
                    name_position[orig_name] = 0
                
                idx = name_position[orig_name]
                if idx < len(exact_name_map[orig_name]):
                    node['name'] = exact_name_map[orig_name][idx]
                    name_position[orig_name] += 1
    
    # Re-encode GLB
    new_json = json.dumps(gltf, separators=(',', ':')).encode('utf-8')
    while len(new_json) % 4:
        new_json += b' '
    
    # Binary chunk starts after JSON chunk
    bin_chunk_start = json_chunk_start + 8 + json_length
    bin_length = int.from_bytes(data[bin_chunk_start:bin_chunk_start+4], 'little')
    bin_data = data[bin_chunk_start+8:bin_chunk_start+8+bin_length] if bin_length > 0 else b''
    
    # Reconstruct GLB
    total_size = 12 + 8 + len(new_json) + 8 + len(bin_data)
    new_glb = (
        struct.pack('<III', 0x46546C67, 2, total_size) +
        struct.pack('II', len(new_json), 0x4E4F534A) + new_json +
        struct.pack('II', len(bin_data), 0x004E4942) + bin_data
    )
    
    with open(glb_path, 'wb') as f:
        f.write(new_glb)


def rename_hierarchy(hierarchy: dict, parts_list: list, unique_parts_list: list) -> dict:
    """Rename part names in the hierarchy dict to use unique names.
    
    Args:
        hierarchy: The hierarchy dict from CAD conversion
        parts_list: List of original part names from CAD
        unique_parts_list: List of renamed part names
        
    Returns:
        Modified hierarchy with renamed part names
    """
    # Build a mapping from original name -> list of unique names (in order)
    name_mapping = {}
    for orig, uniq in zip(parts_list, unique_parts_list):
        if orig not in name_mapping:
            name_mapping[orig] = []
        name_mapping[orig].append(uniq)
    
    # Track position for each original name
    name_position = {}
    
    def rename_node(node):
        """Recursively rename node names."""
        if not isinstance(node, dict):
            return node
        
        # Rename this node if it has a name
        if 'name' in node:
            orig_name = node['name']
            if orig_name in name_mapping:
                if orig_name not in name_position:
                    name_position[orig_name] = 0
                
                idx = name_position[orig_name]
                if idx < len(name_mapping[orig_name]):
                    node['name'] = name_mapping[orig_name][idx]
                    name_position[orig_name] += 1
        
        # Recurse into children
        if 'children' in node and isinstance(node['children'], list):
            node['children'] = [rename_node(child) for child in node['children']]
        
        return node
    
    return rename_node(hierarchy)


def sync_glb_mesh_names(glb_path: str, parts_list: list) -> list:
    """Read current GLB mesh names and sync them with expected unique names.
    
    This function reads the existing mesh names from a GLB file and renames them
    to match what PartsManager would generate (with _N suffix for uniqueness).
    
    Args:
        glb_path: Path to the GLB file
        parts_list: List of part names to generate unique names from
        
    Returns:
        List of unique part names that were applied
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Import PartsManager to generate unique names
    from parts_manager import PartsManager
    parts_mgr = PartsManager()
    unique_parts = parts_mgr.parse_and_rename_parts(parts_list)
    
    # Now use the existing rename function
    try:
        rename_glb_meshes(glb_path, parts_list, unique_parts)
    except Exception as e:
        logger.warning(f"Failed to rename GLB meshes: {e}")
    
    return unique_parts


def force_rename_glb_meshes(glb_path: str) -> list:
    """Force rename all meshes in a GLB file based on current mesh names.
    
    This reads the current mesh names from the GLB, generates unique names
    using PartsManager, and applies them.
    
    Args:
        glb_path: Path to the GLB file
        
    Returns:
        List of unique part names applied
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # First, read current mesh names from GLB
    try:
        with open(glb_path, 'rb') as f:
            data = f.read()
        
        magic = data[0:4]
        if magic != b'glTF':
            logger.warning("Not a valid GLB file")
            return []
        
        json_chunk_start = 12
        json_length = int.from_bytes(data[json_chunk_start:json_chunk_start+4], 'little')
        json_data = data[json_chunk_start+8:json_chunk_start+8+json_length]
        gltf = json.loads(json_data.decode('utf-8'))
        
        # Get current mesh names
        current_names = []
        if 'meshes' in gltf:
            for mesh in gltf['meshes']:
                name = mesh.get('name', '')
                if name:
                    current_names.append(name)
        
        if not current_names:
            logger.info("No meshes found in GLB")
            return []
        
        logger.info(f"Found {len(current_names)} meshes in GLB")
        
        # Now use PartsManager to generate unique names
        from parts_manager import PartsManager
        parts_mgr = PartsManager()
        unique_parts = parts_mgr.parse_and_rename_parts(current_names)
        
        # Apply the rename
        rename_glb_meshes(glb_path, current_names, unique_parts)
        
        logger.info(f"Force renamed {len(unique_parts)} parts in GLB")
        return unique_parts
        
    except Exception as e:
        logger.warning(f"Failed to force rename GLB: {e}")
        return []


def _try_trimesh_fallback(filepath):
    """Fallback: Load CAD file using trimesh (supports scenes and single meshes)."""
    try:
        import trimesh

        logger.info(f"Trimesh fallback: loading {filepath}")
        obj = trimesh.load(filepath, process=False)
        root = AssemblyNode(Path(filepath).stem, "assembly")

        colors = [
            (0.25, 0.55, 0.95, 1.0), (0.95, 0.35, 0.25, 1.0),
            (0.25, 0.85, 0.35, 1.0), (0.95, 0.75, 0.15, 1.0),
            (0.75, 0.25, 0.85, 1.0), (0.15, 0.85, 0.85, 1.0),
        ]

        if isinstance(obj, trimesh.Scene):
            logger.info(f"Trimesh loaded scene with {len(obj.geometry)} parts")
            for idx, (part_name, geom) in enumerate(obj.geometry.items()):
                try:
                    if hasattr(geom, 'vertices') and len(geom.vertices) > 0:
                        part = AssemblyNode(part_name, "part")
                        part.mesh_data = {
                            'vertices': np.asarray(geom.vertices, dtype=np.float32),
                            'faces': np.asarray(geom.faces, dtype=np.uint32) if hasattr(geom, 'faces') and len(geom.faces) > 0 else np.empty((0, 3), dtype=np.uint32),
                            'normals': None
                        }
                        part.color = colors[idx % len(colors)]
                        root.children.append(part)
                except Exception as part_err:
                    logger.debug(f"Trimesh geom {part_name} error: {part_err}")
                    continue
        elif isinstance(obj, trimesh.Trimesh):
            if len(obj.vertices) > 0:
                part = AssemblyNode(Path(filepath).stem, "part")
                part.mesh_data = {
                    'vertices': np.asarray(obj.vertices, dtype=np.float32),
                    'faces': np.asarray(obj.faces, dtype=np.uint32),
                    'normals': None
                }
                part.color = colors[0]
                root.children.append(part)

        if root.children:
            logger.info(f"Trimesh fallback succeeded with {len(root.children)} parts")
            return root
        return None

    except Exception as e:
        logger.warning(f"Trimesh fallback failed: {e}")
        return None


def _try_step_direct_faceted_mesh(filepath):
    """Direct STEP parser for faceted BREP, poly loops, and mesh-converted models.
    Provides 100% resilient fallback for STEP files converted from STL/OBJ/mesh."""
    try:
        import re
        with open(filepath, 'r', errors='ignore') as f:
            text = f.read()

        pts = {}
        pt_pattern = re.compile(
            r'#(\d+)\s*=\s*CARTESIAN_POINT\s*\([^,]*,\s*\(\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\)\s*\)',
            re.I
        )
        for m in pt_pattern.finditer(text):
            pts[int(m.group(1))] = [float(m.group(2)), float(m.group(3)), float(m.group(4))]

        if not pts:
            return None

        faces = []
        loop_pattern = re.compile(r'#\d+\s*=\s*POLY_LOOP\s*\([^,]*,\s*\(([^)]+)\)\s*\)', re.I)
        for m in loop_pattern.finditer(text):
            ref_ids = [int(x.strip().lstrip('#')) for x in m.group(1).split(',') if x.strip().lstrip('#').isdigit()]
            if len(ref_ids) >= 3:
                for i in range(1, len(ref_ids) - 1):
                    faces.append([ref_ids[0], ref_ids[i], ref_ids[i+1]])

        if not faces:
            return None

        used_ids = set()
        for f in faces:
            used_ids.update(f)

        id_map = {old_id: new_idx for new_idx, old_id in enumerate(sorted(used_ids))}
        compact_verts = [pts[old_id] for old_id in sorted(used_ids) if old_id in pts]
        compact_faces = []
        for f in faces:
            if all(vid in id_map for vid in f):
                compact_faces.append([id_map[f[0]], id_map[f[1]], id_map[f[2]]])

        if not compact_verts or not compact_faces:
            return None

        root = AssemblyNode(Path(filepath).stem, "assembly")
        part = AssemblyNode(f"{Path(filepath).stem}_Mesh", "part")
        part.mesh_data = {
            'vertices': np.array(compact_verts, dtype=np.float32),
            'faces': np.array(compact_faces, dtype=np.uint32),
        }
        part.color = (0.25, 0.55, 0.95, 1.0)
        root.children.append(part)
        logger.info(f"Direct STEP faceted parser succeeded: {len(compact_verts)} vertices, {len(compact_faces)} faces")
        return root
    except Exception as e:
        logger.warning(f"Direct faceted STEP extraction notice: {e}")
        return None


def _try_companion_fallback(filepath):
    """Find companion 3D geometry files in the directory for external-reference assembly STEP files."""
    try:
        import re
        p = Path(filepath)
        folder = p.parent
        stem = p.stem

        # Extract product names declared in the STEP file
        part_names = []
        try:
            with open(filepath, 'r', errors='ignore') as f:
                content = f.read(1024 * 512)
            for m in re.finditer(r"PRODUCT\s*\(\s*'([^']+)'", content):
                name = m.group(1).strip()
                if name and name not in part_names and not any(k in name.upper() for k in ['ASSY', 'ASSEMBLY', 'CADNODE']):
                    part_names.append(name)
        except Exception:
            pass

        # Search only safe project directories, NEVER scan OS temp directories
        import tempfile
        temp_dir = Path(tempfile.gettempdir()).resolve()
        search_dirs = [Path.cwd()]
        if not p.resolve().is_relative_to(temp_dir):
            search_dirs.insert(0, p.parent)
        if (Path.cwd() / "uploads").is_dir():
            search_dirs.append(Path.cwd() / "uploads")

        # Prefixes to correlate (e.g. "E5312070" from "E5312070100000" or declared products)
        prefixes = []
        clean_stem = stem.replace("tmp", "")
        if len(clean_stem) >= 6:
            prefixes.append(clean_stem[:8])
        for pn in part_names:
            if len(pn) >= 6:
                prefixes.append(pn[:8])

        candidates = []
        for s_dir in search_dirs:
            for ext in ('.stl', '.obj', '.step', '.stp'):
                for f in s_dir.glob(f'*{ext}'):
                    if f.resolve() == p.resolve():
                        continue
                    try:
                        if f.stat().st_size < 512:
                            continue
                    except Exception:
                        continue
                    if any(pref and pref.lower() in f.stem.lower() for pref in prefixes):
                        if f not in candidates:
                            candidates.insert(0, f)
                    elif not stem.startswith("tmp"):
                        if f not in candidates:
                            candidates.append(f)

        for cand in candidates:
            try:
                cand_ext = cand.suffix.lower()
                cand_assembly = None
                if cand_ext in ('.stl', '.obj'):
                    cand_assembly = _trimesh_import(str(cand))
                elif cand_ext in ('.step', '.stp') and _is_valid_step(str(cand)):
                    cand_assembly = _try_occ_import(str(cand))

                if cand_assembly and cand_assembly.children:
                    logger.info(f"Loaded companion CAD geometry from {cand.name} for assembly {p.name}")
                    if part_names and len(cand_assembly.children) == 1:
                        cand_assembly.children[0].name = part_names[0]
                    cand_assembly.name = p.stem
                    return cand_assembly
            except Exception:
                continue

        # If no geometry files found but product definitions exist, generate representative proxy geometry
        if part_names:
            root = AssemblyNode(p.stem, "assembly")
            for idx, p_name in enumerate(part_names[:25]):
                proxy_part = AssemblyNode(p_name, "part")
                # Create a small unit prism marker at offset positions
                ox = (idx % 5) * 50.0 - 100.0
                oy = ((idx // 5) % 5) * 50.0 - 50.0
                oz = 0.0
                s = 15.0
                box_verts = np.array([
                    [ox-s, oy-s, oz-s], [ox+s, oy-s, oz-s], [ox+s, oy+s, oz-s], [ox-s, oy+s, oz-s],
                    [ox-s, oy-s, oz+s], [ox+s, oy-s, oz+s], [ox+s, oy+s, oz+s], [ox-s, oy+s, oz+s],
                ], dtype=np.float32)
                box_faces = np.array([
                    [0,1,2], [0,2,3], [4,6,5], [4,7,6],
                    [0,4,5], [0,5,1], [2,6,7], [2,7,3],
                    [1,5,6], [1,6,2], [0,3,7], [0,7,4]
                ], dtype=np.uint32)
                proxy_part.mesh_data = {"vertices": box_verts, "faces": box_faces}
                root.children.append(proxy_part)
            logger.info(f"Generated proxy geometry for {len(root.children)} logical parts from {p.name}")
            return root

        return None
    except Exception as e:
        logger.warning(f"Companion fallback notice: {e}")
        return None


def convert_cad_to_gltf(input_path: str, output_dir: str,
                        use_demo: bool = False,
                        name_mapping: dict = None) -> Dict[str, Any]:
    start = time.time()

    if use_demo:
        assembly = generate_demo_assembly()
    else:
        ext = Path(input_path).suffix.lower()
        assembly = None

        # Validate STEP files before attempting parse (with auto-recovery)
        if ext in ('.step', '.stp'):
            input_path = _validate_step_file(input_path)

        if ext == '.3dxml':
            assembly = _parse_3dxml_fast(input_path)

        # 1. Primary CAD reader: OpenCASCADE XDE + Plain Reader + Face extraction
        if assembly is None and ext in ('.step', '.stp', '.iges', '.igs'):
            assembly = _try_occ_import(input_path)

        # 2. Fallback: Trimesh multi-format reader
        if assembly is None and ext in ('.step', '.stp', '.iges', '.igs', '.stl', '.obj'):
            logger.info(f"Trying trimesh fallback for {input_path}")
            assembly = _try_trimesh_fallback(input_path)

        # 3. Fallback: Direct STEP Faceted Mesh Extractor (for STL/OBJ converted to STEP)
        if assembly is None and ext in ('.step', '.stp'):
            logger.info(f"Trying direct faceted STEP mesh extractor for {input_path}")
            assembly = _try_step_direct_faceted_mesh(input_path)

        # 4. Fallback: Companion CAD file search (for external reference assembly files)
        if assembly is None and ext in ('.step', '.stp', '.iges', '.igs'):
            logger.info(f"Trying companion file fallback for {input_path}")
            assembly = _try_companion_fallback(input_path)

        # 5. Fallback: STL/OBJ basic import
        if assembly is None and ext in ('.stl', '.obj'):
            assembly = _trimesh_import(input_path)

        if assembly is None or (assembly.node_type == "assembly" and len(assembly.children) == 0 and assembly.mesh_data is None):
            logger.warning("All parsers failed for %s", input_path)
            error_msg = (
                f"Could not parse '{Path(input_path).name}'. "
                f"The file may be corrupted, encrypted, or contain unsupported non-geometric entities.\n\n"
                f"Attempted:\n"
                f"  1. OpenCASCADE XDE hierarchy reader\n"
                f"  2. OpenCASCADE plain reader with adaptive meshing\n"
                f"  3. OpenCASCADE shell and surface-face extractor\n"
                f"  4. Trimesh mesh & scene fallback\n"
                f"  5. Direct STEP faceted mesh poly-loop scanner\n"
                f"  6. Assembly companion geometry matcher\n\n"
                f"Troubleshooting:\n"
                f"  - Re-export with standard STEP AP203, AP214, or AP242 settings\n"
                f"  - Or export directly as STL format for maximum mesh compatibility"
            )
            raise ValueError(error_msg)

    # Build glTF
    builder = GLTFBuilder()
    parts_list = []
    _build_gltf(builder, assembly, parts_list, name_mapping)
    
    # DEBUG: Log what was extracted
    logger.info(f"[CONVERTER] Assembly parsed: {assembly.name}")
    logger.info(f"[CONVERTER] Parts extracted: {len(parts_list)} - {parts_list}")
    if len(parts_list) == 0:
        logger.warning(f"[CONVERTER] NO PARTS FOUND! Assembly structure: {assembly.to_dict()}")

    os.makedirs(output_dir, exist_ok=True)
    stem = assembly.name or "model"
    # Sanitize filename
    stem = "".join(c if c.isalnum() or c in '_-' else '_' for c in stem)
    glb_path = os.path.join(output_dir, f"{stem}.glb")
    builder.export_glb(glb_path)

    hierarchy = assembly.to_dict()
    elapsed = time.time() - start

    info_path = os.path.join(output_dir, f"{stem}_hierarchy.json")
    info = {
        "hierarchy": hierarchy, "parts": parts_list,
        "stats": {
            "num_parts": len(parts_list),
            "conversion_time": round(elapsed, 2),
            "file_size_mb": round(os.path.getsize(glb_path)/1024/1024, 2),
        }
    }
    with open(info_path, 'w') as f:
        json.dump(info, f, indent=2)

    return {
        "glb_path": glb_path, "hierarchy": hierarchy,
        "hierarchy_path": info_path, "parts": parts_list,
        "stats": info["stats"],
    }


def _build_gltf(builder, node, parts_list, name_mapping=None, parent=None):
    """Build glTF from assembly hierarchy, applying name mapping if provided.
    
    Args:
        builder: GLTFBuilder instance
        node: AssemblyNode to process
        parts_list: List to collect part names (original names)
        name_mapping: Dict mapping original names to renamed names
        parent: Parent node index in glTF
    """
    if node.node_type == "assembly":
        g = builder.add_group(node.name, parent, node.transform)
        for ch in node.children:
            _build_gltf(builder, ch, parts_list, name_mapping, g)
    elif node.mesh_data:
        # Get the name to use - either renamed or original
        mesh_name = node.name
        if name_mapping and node.name in name_mapping:
            mesh_name = name_mapping[node.name]
        
        m = builder.add_material(mesh_name, node.color)
        builder.add_mesh(mesh_name, node.mesh_data["vertices"],
                         node.mesh_data["faces"],
                         node.mesh_data.get("normals"),
                         m, parent, node.transform)
        parts_list.append(node.name)  # Always append original name to parts_list
