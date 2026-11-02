"""
cad_bom_manual.py  –  Manual Generation from STP + BOM + Reference Points
==========================================================================
Generates a complete professional manual grounded in REAL structured
engineering data instead of a free-text outline:

    • .stp / .step   – CAD assembly file (ISO-10303-21 / STEP AP21x)
                        → part names, descriptions, assembly (parent/child)
                          structure, reference designators
    • BOM            – .xlsx / .xls / .csv / .pdf Bill of Materials
                        → item no, part number, description, qty, material
    • Reference pts  – .csv / .xlsx / .json list of callout / balloon
                        points that tie a BOM item number to a location
                        (2D or 3D) on the drawing/model

WHY THIS EXISTS
  scratch.py's `generate_new_manual()` needs a text outline and the LLM
  fills in the rest — fine for narrative manuals, but for assembly /
  service manuals you actually want the AI to write ONLY around real
  part numbers, real quantities and real reference designators instead
  of inventing them. This module extracts that ground truth first, then
  reuses scratch.py's section-writing + formatting.py's PDF engine so
  the rest of the pipeline (AI content, diagrams, TOC, layout) is
  unchanged.

HOW IT WORKS
  1. parse_stp_file()          – lightweight regex parser, no CAD kernel
                                  required (works on ASCII STEP files)
  2. parse_bom_file()          – fuzzy header-matching BOM reader
  3. parse_reference_points()  – reads callout/balloon coordinates
  4. merge_sources()           – cross references all three by item
                                  number / part number / name
  5. build_manual_meta()       – builds section outline grounded in the
                                  merged parts list (reuses scratch.py's
                                  writer so tone/quality stays identical)
  6. generate_manual_from_cad_bom() – orchestrates everything and calls
                                  formatting.create_professional_manual_pdf()

USAGE (standalone)
    python cad_bom_manual.py --stp assy.stp --bom bom.xlsx --refs refs.csv

USAGE (from app.py)
    from cad_bom_manual import generate_manual_from_cad_bom
    result = generate_manual_from_cad_bom(
        stp_path="assy.stp", bom_path="bom.xlsx", ref_points_path="refs.csv",
        pages=15, product_name="Split AC Indoor Unit",
    )
"""

from __future__ import annotations

import os
import re
import io
import csv
import json
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# ── Reuse the existing AI writer + PDF engine ────────────────────────────────
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

try:
    from scratch import (
        generate_section, generate_appendix, _clean_content, _word_count,
        _build_system_prompt, GROQ_API_KEY, GROQ_MODEL, WORDS_PER_PAGE,
        OUTPUT_DIR,
    )
    SCRATCH_AVAILABLE = True
except ImportError:
    SCRATCH_AVAILABLE = False

try:
    from formatting import create_professional_manual_pdf, create_manual_docx
    FORMATTING_AVAILABLE = True
except ImportError:
    FORMATTING_AVAILABLE = False

# Optional (recommended) — used for .xlsx/.xls BOM & reference-point files
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# Optional — used for .pdf BOM files (table extraction)
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════
#  1. STP / STEP parser  (regex based — no CAD kernel dependency)
# ══════════════════════════════════════════════════════════════════════════

_RE_PRODUCT            = re.compile(
    r"#(\d+)\s*=\s*PRODUCT\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'", re.I)
_RE_PRODUCT_DEF        = re.compile(
    r"#(\d+)\s*=\s*PRODUCT_DEFINITION\(\s*'[^']*'\s*,\s*'[^']*'\s*,\s*#(\d+)", re.I)
_RE_PRODUCT_DEF_FORM   = re.compile(
    r"#(\d+)\s*=\s*PRODUCT_DEFINITION_FORMATION\(\s*'[^']*'\s*,\s*'[^']*'\s*,\s*#(\d+)\)", re.I)
_RE_NAUO               = re.compile(
    r"#(\d+)\s*=\s*NEXT_ASSEMBLY_USAGE_OCCURRENCE\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,"
    r"\s*'([^']*)'\s*,\s*#(\d+)\s*,\s*#(\d+)\s*,\s*(?:'([^']*)'|\$)", re.I)


def parse_stp_file(path_or_text: str, is_text: bool = False) -> Dict:
    """
    Extract a best-effort part list + assembly (parent/child) structure
    from an ASCII STEP (ISO-10303-21) file. This is intentionally
    lightweight (regex, not a full EXPRESS/CAD-kernel parser) so it has
    no heavy dependency — it works well on STEP AP203/AP214 files as
    exported by SolidWorks, Inventor, CATIA, Fusion 360, etc.

    Returns
    -------
    {
      "parts": [{"id": "#10", "name": "...", "description": "..."}],
      "assembly_tree": [{"parent": "...", "child": "...", "ref_designator": "..."}],
      "part_count": N,
      "root_name": "...",
    }
    """
    if is_text:
        text = path_or_text
    else:
        with open(path_or_text, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

    products: Dict[str, Dict] = {}          # entity_id -> {id, name, description}
    def_to_product: Dict[str, str] = {}     # PRODUCT_DEFINITION id -> PRODUCT entity id
    form_to_product: Dict[str, str] = {}    # PRODUCT_DEFINITION_FORMATION id -> PRODUCT entity id

    for m in _RE_PRODUCT.finditer(text):
        eid, code, name, desc = m.groups()
        products[eid] = {
            "id": code.strip() or eid,
            "name": (name or code or f"Part {eid}").strip(),
            "description": desc.strip(),
        }

    for m in _RE_PRODUCT_DEF_FORM.finditer(text):
        form_id, prod_id = m.groups()
        form_to_product[form_id] = prod_id

    for m in _RE_PRODUCT_DEF.finditer(text):
        def_id, form_id = m.groups()
        if form_id in form_to_product:
            def_to_product[def_id] = form_to_product[form_id]

    assembly_tree: List[Dict] = []
    for m in _RE_NAUO.finditer(text):
        _eid, _nauo_id, _name, _desc, parent_def, child_def, ref_des = m.groups()
        parent_prod = def_to_product.get(parent_def)
        child_prod = def_to_product.get(child_def)
        if parent_prod in products and child_prod in products:
            assembly_tree.append({
                "parent": products[parent_prod]["name"],
                "child": products[child_prod]["name"],
                "ref_designator": (ref_des or "").strip(),
            })

    parts_list = list(products.values())

    # Determine likely root: a product that is only ever a parent (never a child)
    child_names = {rel["child"] for rel in assembly_tree}
    root_candidates = [p["name"] for p in parts_list if p["name"] not in child_names]
    root_name = root_candidates[0] if root_candidates else (
        parts_list[0]["name"] if parts_list else "Assembly"
    )

    return {
        "parts": parts_list,
        "assembly_tree": assembly_tree,
        "part_count": len(parts_list),
        "root_name": root_name,
    }


# ══════════════════════════════════════════════════════════════════════════
#  2. BOM parser  (.xlsx / .xls / .csv / .pdf)  — fuzzy header matching
# ══════════════════════════════════════════════════════════════════════════

_BOM_HEADER_ALIASES = {
    "item_no":     ["item no", "item", "item number", "#", "no", "ref", "find no", "find number", "balloon"],
    "part_number": ["part number", "part no", "p/n", "pn", "part#", "drawing no", "component"],
    "description": ["description", "desc", "part name", "name", "title"],
    "qty":         ["qty", "quantity", "qty.", "count", "no. required", "qty required"],
    "material":    ["material", "matl", "spec", "material spec"],
    "ref_designator": ["ref designator", "reference designator", "ref des", "designator", "tag"],
}


def _normalise_header(h: str) -> str:
    return re.sub(r"[^a-z0-9/#. ]", "", str(h).strip().lower())


def _map_headers(headers: List[str]) -> Dict[str, str]:
    """Return {canonical_field: actual_header_name}."""
    mapping = {}
    norm_headers = {h: _normalise_header(h) for h in headers}
    for field, aliases in _BOM_HEADER_ALIASES.items():
        for h, nh in norm_headers.items():
            if nh in aliases or any(a == nh for a in aliases):
                mapping[field] = h
                break
        else:
            # partial match fallback
            for h, nh in norm_headers.items():
                if any(a in nh for a in aliases):
                    mapping[field] = h
                    break
    return mapping


def parse_bom_file(path: str) -> List[Dict]:
    """
    Read a BOM (.xlsx/.xls/.csv/.pdf) into a normalised list of dicts:
      {item_no, part_number, description, qty, material, ref_designator}
    Unrecognised extra columns are preserved under "extra".
    """
    ext = os.path.splitext(path)[1].lower()
    rows: List[Dict] = []

    if ext in (".xlsx", ".xls") and PANDAS_AVAILABLE:
        df = pd.read_excel(path, dtype=str).fillna("")
        headers = list(df.columns)
        hmap = _map_headers(headers)
        for _, row in df.iterrows():
            rows.append(_bom_row_from_mapping(row.to_dict(), hmap, headers))

    elif ext == ".csv":
        if PANDAS_AVAILABLE:
            df = pd.read_csv(path, dtype=str).fillna("")
            headers = list(df.columns)
            hmap = _map_headers(headers)
            for _, row in df.iterrows():
                rows.append(_bom_row_from_mapping(row.to_dict(), hmap, headers))
        else:
            with open(path, newline="", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                hmap = _map_headers(headers)
                for row in reader:
                    rows.append(_bom_row_from_mapping(row, hmap, headers))

    elif ext == ".pdf":
        rows = parse_bom_pdf(path)

    else:
        raise ValueError(f"Unsupported BOM file type: {ext} (use .xlsx, .xls, .csv or .pdf)")

    return rows


def parse_bom_pdf(path: str) -> List[Dict]:
    """
    Extract a BOM from a PDF. Two strategies, tried in order:
      1. pdfplumber's table detector (works when the BOM has real
         table/grid lines or clearly gridded whitespace — the common
         case for BOM tables exported from CAD/PLM tools or Excel->PDF).
      2. A whitespace-column text fallback for PDFs with no detectable
         table lines (BOM printed as plain aligned text).
    Returns the same normalised row dicts as the xlsx/csv path.
    """
    if not PDFPLUMBER_AVAILABLE:
        raise ValueError("pdfplumber not installed — required to read BOM PDFs. "
                          "Run: pip install pdfplumber")

    header_row: Optional[List[str]] = None
    hmap: Dict[str, str] = {}
    rows: List[Dict] = []

    with pdfplumber.open(path) as pdf:
        any_table_found = False
        for page in pdf.pages:
            tables = page.extract_tables({
                "vertical_strategy": "lines_strict",
                "horizontal_strategy": "lines_strict",
            }) or page.extract_tables()
            for table in tables:
                table = [r for r in table if r and any((c or "").strip() for c in r)]
                if not table:
                    continue
                any_table_found = True
                start_idx = 0
                if header_row is None:
                    header_row = [str(c or "").strip() for c in table[0]]
                    hmap = _map_headers(header_row)
                    start_idx = 1
                elif [str(c or "").strip() for c in table[0]] == header_row:
                    # repeated header row on a later page — skip it
                    start_idx = 1
                for raw_row in table[start_idx:]:
                    cells = [str(c or "").strip() for c in raw_row]
                    row_dict = {h: cells[i] if i < len(cells) else ""
                                for i, h in enumerate(header_row or [])}
                    rows.append(_bom_row_from_mapping(row_dict, hmap, header_row or []))

        if any_table_found and rows:
            return rows

    # ── Fallback: no gridded table detected — parse aligned text columns ──
    return _parse_bom_pdf_text_fallback(path)


def _split_by_whitespace_columns(lines: List[str]) -> List[List[str]]:
    """
    Classic 'ASCII table' column splitter: finds character columns that
    are blank across every line (not just the current line) and uses
    those as field separators. More robust than splitting each line
    independently, since a header word can be shorter than the data
    below it and still land in the same visual column.
    """
    if not lines:
        return []
    width = max(len(l) for l in lines)
    padded = [l.ljust(width) for l in lines]
    blank_cols = [all(l[c] == " " for l in padded) for c in range(width)]

    # Collapse consecutive blank columns into ranges, keep ranges >=2 wide
    ranges, start = [], None
    for c, is_blank in enumerate(blank_cols + [True]):
        if is_blank and start is None:
            start = c
        elif not is_blank and start is not None:
            if c - start >= 2:
                ranges.append((start, c))
            start = None

    # Build cut points from the midpoints of each blank range (skipping
    # any at the very start/end of the line)
    cuts = [0]
    for s, e in ranges:
        if s > 0 and e < width:
            cuts.append((s + e) // 2)
    cuts.append(width)
    cuts = sorted(set(cuts))

    rows = []
    for l in padded:
        cells = [l[cuts[i]:cuts[i+1]].strip() for i in range(len(cuts)-1)]
        rows.append(cells)
    return rows


def _parse_bom_pdf_text_fallback(path: str) -> List[Dict]:
    """
    Heuristic reader for BOM PDFs with no real table lines: detects
    shared whitespace columns across the whole text block (works even
    when the header text doesn't character-align perfectly with the
    data rows below it), finds the header line by keyword match, and
    parses subsequent lines using the same column boundaries.
    """
    with pdfplumber.open(path) as pdf:
        raw_lines: List[str] = []
        for page in pdf.pages:
            # layout=True preserves original character spacing/positions,
            # which is what lets us split on column gaps below. Without
            # it, pdfplumber collapses runs of whitespace and the column
            # structure of a gridline-less BOM is lost.
            text = page.extract_text(layout=True) or page.extract_text() or ""
            raw_lines.extend(l for l in text.split("\n") if l.strip())

    if not raw_lines:
        return []

    split_rows = _split_by_whitespace_columns(raw_lines)

    header_idx, header_cells = None, None
    for i, cells in enumerate(split_rows):
        norm = [_normalise_header(c) for c in cells]
        hits = sum(1 for aliases in _BOM_HEADER_ALIASES.values()
                   if any(n in aliases for n in norm))
        if hits >= 2:
            header_idx, header_cells = i, [c.strip() for c in cells]
            break

    if header_idx is None:
        return []  # couldn't confidently locate a header row

    hmap = _map_headers(header_cells)
    ncols = len(header_cells)
    rows: List[Dict] = []
    for cells in split_rows[header_idx + 1:]:
        if len(cells) < 2 or not any(c.strip() for c in cells):
            continue
        cells = (list(cells) + [""] * ncols)[:ncols]
        row_dict = {h: cells[i] for i, h in enumerate(header_cells)}
        rows.append(_bom_row_from_mapping(row_dict, hmap, header_cells))

    return rows


def _bom_row_from_mapping(row: Dict, hmap: Dict[str, str], headers: List[str]) -> Dict:
    def get(field, default=""):
        h = hmap.get(field)
        return str(row.get(h, default)).strip() if h else default

    used_headers = set(hmap.values())
    extra = {h: row.get(h, "") for h in headers if h not in used_headers}

    return {
        "item_no":        get("item_no"),
        "part_number":    get("part_number"),
        "description":    get("description"),
        "qty":            get("qty", "1"),
        "material":       get("material"),
        "ref_designator": get("ref_designator"),
        "extra":          extra,
    }


# ══════════════════════════════════════════════════════════════════════════
#  3. Reference / callout point parser  (.csv / .xlsx / .json)
# ══════════════════════════════════════════════════════════════════════════

_REF_HEADER_ALIASES = {
    "point_id": ["point id", "ref no", "reference no", "id", "item no", "callout", "balloon", "item"],
    "label":    ["label", "description", "name", "part", "callout label"],
    "x":        ["x"],
    "y":        ["y"],
    "z":        ["z"],
    "item_no":  ["item no", "bom item", "linked item", "item"],
}


def parse_reference_points(path: str) -> List[Dict]:
    """
    Read reference/callout points that annotate a drawing or 3D view.
    Expected (flexible) columns: Point ID / Ref No, Label, X, Y, (Z optional),
    and optionally an Item No that links back to a BOM row.

    Returns list of dicts: {point_id, label, x, y, z, item_no}
    """
    ext = os.path.splitext(path)[1].lower()

    if ext == ".json":
        with open(path, encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
        rows = data if isinstance(data, list) else data.get("points", [])
        out = []
        for r in rows:
            out.append({
                "point_id": str(r.get("point_id", r.get("id", r.get("ref_no", "")))),
                "label":    str(r.get("label", r.get("description", ""))),
                "x":        _to_float(r.get("x")),
                "y":        _to_float(r.get("y")),
                "z":        _to_float(r.get("z")),
                "item_no":  str(r.get("item_no", r.get("bom_item", ""))),
            })
        return out

    if ext in (".xlsx", ".xls", ".csv"):
        if PANDAS_AVAILABLE:
            df = (pd.read_excel(path, dtype=str) if ext != ".csv"
                  else pd.read_csv(path, dtype=str)).fillna("")
            headers = list(df.columns)
            hmap = _map_ref_headers(headers)
            out = []
            for _, row in df.iterrows():
                out.append(_ref_row_from_mapping(row.to_dict(), hmap))
            return out
        else:
            with open(path, newline="", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                hmap = _map_ref_headers(headers)
                return [_ref_row_from_mapping(row, hmap) for row in reader]

    raise ValueError(f"Unsupported reference-points file type: {ext}")


def _map_ref_headers(headers: List[str]) -> Dict[str, str]:
    mapping = {}
    norm = {h: _normalise_header(h) for h in headers}
    for field, aliases in _REF_HEADER_ALIASES.items():
        for h, nh in norm.items():
            if nh in aliases:
                mapping[field] = h
                break
    return mapping


def _ref_row_from_mapping(row: Dict, hmap: Dict[str, str]) -> Dict:
    def get(field, default=""):
        h = hmap.get(field)
        return row.get(h, default) if h else default

    return {
        "point_id": str(get("point_id")).strip(),
        "label":    str(get("label")).strip(),
        "x":        _to_float(get("x")),
        "y":        _to_float(get("y")),
        "z":        _to_float(get("z")),
        "item_no":  str(get("item_no")).strip(),
    }


def _to_float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════════
#  4. Merge STP + BOM + Reference Points into one grounded parts master
# ══════════════════════════════════════════════════════════════════════════

def merge_sources(stp_data: Optional[Dict],
                   bom_rows: Optional[List[Dict]],
                   ref_points: Optional[List[Dict]]) -> Dict:
    """
    Cross-reference the three sources by item number / part number / name.
    Priority for the master key: BOM item_no > reference point_id > STP part name.

    Returns:
      {
        "parts_master": [ {item_no, part_number, name, description, qty,
                            material, ref_designator, x, y, z, sources: [...]} ],
        "assembly_tree": [...],   # from STP, unchanged
        "unmatched_refs": [...],  # reference points that could not be tied to a BOM row
        "stats": {...}
      }
    """
    bom_rows   = bom_rows or []
    ref_points = ref_points or []
    stp_data   = stp_data or {"parts": [], "assembly_tree": [], "part_count": 0}

    parts_master: Dict[str, Dict] = {}

    # Seed from BOM (authoritative for item_no / qty / material)
    for row in bom_rows:
        key = row.get("item_no") or row.get("part_number") or row.get("description")
        if not key:
            continue
        parts_master[key] = {
            "item_no":        row.get("item_no", ""),
            "part_number":    row.get("part_number", ""),
            "name":           row.get("description", "") or row.get("part_number", ""),
            "description":    row.get("description", ""),
            "qty":            row.get("qty", "1"),
            "material":       row.get("material", ""),
            "ref_designator": row.get("ref_designator", ""),
            "x": None, "y": None, "z": None,
            "sources": ["BOM"],
        }

    # Attach reference points by item_no match, else by point_id match, else keep unmatched
    unmatched_refs = []
    for rp in ref_points:
        target_key = None
        if rp.get("item_no") and rp["item_no"] in parts_master:
            target_key = rp["item_no"]
        elif rp.get("point_id") and rp["point_id"] in parts_master:
            target_key = rp["point_id"]
        else:
            # try matching by label text against BOM description/part number
            label = (rp.get("label") or "").strip().lower()
            if label:
                for k, v in parts_master.items():
                    if label and (label in v["description"].lower()
                                  or label in v["part_number"].lower()):
                        target_key = k
                        break

        if target_key:
            entry = parts_master[target_key]
            entry["x"], entry["y"], entry["z"] = rp.get("x"), rp.get("y"), rp.get("z")
            entry["point_id"] = rp.get("point_id", "")
            if "Reference Points" not in entry["sources"]:
                entry["sources"].append("Reference Points")
        else:
            unmatched_refs.append(rp)
            # still create a standalone entry so the point isn't lost
            key = rp.get("point_id") or f"REF-{len(parts_master)+1}"
            parts_master.setdefault(key, {
                "item_no": rp.get("item_no", ""), "part_number": "",
                "name": rp.get("label") or key, "description": rp.get("label", ""),
                "qty": "1", "material": "", "ref_designator": "",
                "x": rp.get("x"), "y": rp.get("y"), "z": rp.get("z"),
                "point_id": rp.get("point_id", ""),
                "sources": ["Reference Points"],
            })

    # Cross reference against STP part names (fuzzy substring match)
    stp_names = [p["name"] for p in stp_data.get("parts", [])]
    for k, v in parts_master.items():
        needle = (v["description"] or v["part_number"] or v["name"]).strip().lower()
        if not needle:
            continue
        for sname in stp_names:
            if needle in sname.lower() or sname.lower() in needle:
                if "STP" not in v["sources"]:
                    v["sources"].append("STP")
                break

    # Any STP parts with no BOM/ref match at all get added too, so the
    # manual still documents every modelled component
    matched_stp_names = {v["name"].lower() for v in parts_master.values()}
    for p in stp_data.get("parts", []):
        if p["name"].lower() not in matched_stp_names:
            key = p.get("id") or p["name"]
            parts_master[key] = {
                "item_no": "", "part_number": p.get("id", ""),
                "name": p["name"], "description": p.get("description", ""),
                "qty": "1", "material": "", "ref_designator": "",
                "x": None, "y": None, "z": None,
                "sources": ["STP"],
            }

    parts_list = list(parts_master.values())
    # Stable order: numeric item_no first, then alphabetical by name
    def _sort_key(p):
        try:
            return (0, int(re.sub(r"\D", "", p["item_no"]) or 9999))
        except Exception:
            return (1, p["name"])
    parts_list.sort(key=_sort_key)

    return {
        "parts_master":  parts_list,
        "assembly_tree": stp_data.get("assembly_tree", []),
        "unmatched_refs": unmatched_refs,
        "stats": {
            "bom_rows":       len(bom_rows),
            "ref_points":     len(ref_points),
            "stp_parts":      stp_data.get("part_count", 0),
            "merged_parts":   len(parts_list),
            "matched_all_three": sum(1 for p in parts_list if len(p["sources"]) >= 2),
        },
    }


# ══════════════════════════════════════════════════════════════════════════
#  5. Build manual outline grounded in the merged parts data
# ══════════════════════════════════════════════════════════════════════════

def build_manual_meta(merged: Dict, product_name: str = "",
                       domain_hint: str = "", extra_instructions: str = "") -> Dict:
    parts = merged["parts_master"]
    part_names  = [p["name"] for p in parts if p["name"]][:25]
    major_parts = [p["name"] for p in parts if p.get("qty", "1") not in ("", "0")][:12]

    product = product_name or (parts[0]["name"] if parts else "Assembly")
    domain  = domain_hint or "mechanical/electromechanical assembly"

    sections = [
        {"number": "1", "title": "Introduction",
         "subsections": ["Purpose of this Manual", "How to Use This Document"],
         "key_topics": [f"overview of {product}", "intended audience", "document conventions"]},

        {"number": "2", "title": "Product & Assembly Overview",
         "subsections": ["Assembly Structure", "Major Components"],
         "key_topics": part_names[:10] or ["major components"]},

        {"number": "3", "title": "Bill of Materials",
         "subsections": ["Parts List", "Ordering Information"],
         "key_topics": ["how to read the BOM table", "part numbering scheme",
                         "ordering replacement parts"]},

        {"number": "4", "title": "Reference Point / Callout Diagram",
         "subsections": ["Callout Numbering", "Locating Components"],
         "key_topics": ["how callout numbers map to BOM items",
                         "using the reference diagram during assembly/service"]},

        {"number": "5", "title": "Safety Instructions",
         "subsections": ["General Safety", "Handling & Lifting", "Electrical Safety"],
         "key_topics": ["PPE requirements", "lockout/tagout", "handling precautions for "
                         + (major_parts[0] if major_parts else "major components")]},

        {"number": "6", "title": "Assembly & Installation Instructions",
         "subsections": major_parts[:6] or ["Sub-assembly Installation"],
         "key_topics": [f"installing {p}" for p in major_parts[:6]] or ["installation sequence"]},

        {"number": "7", "title": "Operating Instructions",
         "subsections": ["Startup Procedure", "Normal Operation", "Shutdown Procedure"],
         "key_topics": ["operating the assembled unit", "control interfaces", "operating limits"]},

        {"number": "8", "title": "Maintenance & Spare Parts",
         "subsections": ["Preventive Maintenance Schedule", "Spare Parts Replacement"],
         "key_topics": [f"maintaining {p}" for p in major_parts[:5]] or ["periodic maintenance"]},

        {"number": "9", "title": "Troubleshooting",
         "subsections": ["Common Issues", "Diagnostic Steps"],
         "key_topics": ["fault diagnosis", "component-level troubleshooting"]},

        {"number": "10", "title": "Technical Specifications",
         "subsections": ["Dimensions & Weights", "Materials"],
         "key_topics": ["specification table", "materials of construction"]},

        {"number": "11", "title": "Warranty & Support",
         "subsections": ["Warranty Terms", "Contacting Support"],
         "key_topics": ["warranty coverage", "support channels"]},
    ]

    return {
        "domain": domain,
        "product_name": product,
        "title": f"{product} — Assembly & Service Manual",
        "subtitle": "Generated from CAD (STP), Bill of Materials & Reference Points",
        "revision": "1.0",
        "company": "",
        "sections": sections,
        "key_technical_terms": part_names[:12],
        "safety_relevant": True,
        "extra": extra_instructions,
    }


# ══════════════════════════════════════════════════════════════════════════
#  6. Markdown helpers: BOM table + assembly tree rendered as manual content
# ══════════════════════════════════════════════════════════════════════════

def _bom_markdown_table(parts: List[Dict]) -> str:
    """Render the FULL bom as a markdown pipe-table (rendered as a real
    reportlab Table by formatting.py's parser — see the pipe-table
    support added to parse_to_story())."""
    header = "| Item No | Part Number | Description | Qty | Material |"
    sep    = "|---|---|---|---|---|"
    lines  = [header, sep]
    for p in parts:
        lines.append(
            f"| {p.get('item_no','') or '-'} | {p.get('part_number','') or '-'} | "
            f"{p.get('description') or p.get('name','') } | {p.get('qty','1')} | "
            f"{p.get('material','') or '-'} |"
        )
    return "\n".join(lines)


def _assembly_tree_text(assembly_tree: List[Dict]) -> str:
    if not assembly_tree:
        return ""
    lines = []
    for rel in assembly_tree[:40]:
        tag = f" (Ref: {rel['ref_designator']})" if rel.get("ref_designator") else ""
        lines.append(f"- **{rel['parent']}** → {rel['child']}{tag}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
#  7. Diagram specs built directly from data (no AI needed / no hallucination)
# ══════════════════════════════════════════════════════════════════════════

def build_diagram_specs(merged: Dict) -> Dict:
    """Pre-built diagram_specs dict consumed by formatting.create_professional_manual_pdf.
    Reuses the existing 'table' and 'system_flow' renderers, plus the new
    'reference_map' renderer added to formatting.py."""
    parts = merged["parts_master"]
    tree  = merged["assembly_tree"]
    specs = {}

    # Section 2 — Product & Assembly Overview → system_flow of assembly tree
    if tree:
        nodes, node_ids, edges = [], {}, []
        for rel in tree[:6]:
            for name in (rel["parent"], rel["child"]):
                if name not in node_ids:
                    node_ids[name] = f"N{len(node_ids)}"
                    nodes.append({"id": node_ids[name], "label": name[:22]})
            edges.append([node_ids[rel["parent"]], node_ids[rel["child"]]])
        specs["2"] = {
            "type": "system_flow",
            "title": "Figure 1: Assembly Structure",
            "data": {"nodes": nodes[:6], "edges": edges[:8]},
        }

    # Section 3 — Bill of Materials → small table diagram (summary, full
    # table is also embedded as real text/Table via _bom_markdown_table)
    if parts:
        specs["3"] = {
            "type": "table",
            "title": "Figure 2: Bill of Materials (Summary)",
            "data": {
                "headers": ["Item", "Part Number", "Description", "Qty"],
                "rows": [[p.get("item_no") or "-", p.get("part_number") or "-",
                          (p.get("description") or p.get("name", ""))[:28],
                          p.get("qty", "1")] for p in parts[:7]],
            },
        }

    # Section 4 — Reference Point / Callout Diagram → new reference_map type
    ref_parts = [p for p in parts if p.get("x") is not None and p.get("y") is not None]
    if ref_parts:
        specs["4"] = {
            "type": "reference_map",
            "title": "Figure 3: Reference Point / Callout Map",
            "data": {
                "points": [
                    {"num": p.get("item_no") or p.get("point_id") or str(i+1),
                     "label": (p.get("description") or p.get("name", ""))[:24],
                     "x": p["x"], "y": p["y"]}
                    for i, p in enumerate(ref_parts[:20])
                ],
            },
        }

    return specs


# ══════════════════════════════════════════════════════════════════════════
#  8. Main entry point
# ══════════════════════════════════════════════════════════════════════════

def generate_manual_from_cad_bom(
    stp_path:            Optional[str] = None,
    bom_path:            Optional[str] = None,
    ref_points_path:     Optional[str] = None,
    stp_text:            Optional[str] = None,
    pages:               int = 12,
    include_diagrams:    bool = True,
    product_name:        str = "",
    domain_hint:         str = "",
    extra_instructions:  str = "",
    api_key:             Optional[str] = None,
) -> Dict:
    """
    Generate a complete professional manual grounded in a CAD (STP)
    assembly, a Bill of Materials, and reference/callout points.

    At least one of `stp_path`/`stp_text` or `bom_path` must be provided.
    `ref_points_path` is optional but strongly recommended — it is what
    lets the generated manual show a labelled callout diagram tying
    BOM item numbers to physical locations.

    Returns a dict compatible with scratch.generate_new_manual()'s
    output, plus `parts_master`, `assembly_tree` and `merge_stats`.
    """
    if not SCRATCH_AVAILABLE:
        return {"error": "scratch.py not importable — required for AI section writing."}
    if not GROQ_AVAILABLE:
        return {"error": "groq not installed. Run: pip install groq"}

    key = api_key or GROQ_API_KEY
    if not key:
        return {"error": "GROQ_API_KEY not set."}

    if not (stp_path or stp_text or bom_path):
        return {"error": "Provide at least an STP file/text or a BOM file."}

    try:
        # ── Phase 1: parse all provided sources ──────────────────────────
        stp_data = None
        if stp_text:
            stp_data = parse_stp_file(stp_text, is_text=True)
        elif stp_path:
            stp_data = parse_stp_file(stp_path)

        bom_rows = parse_bom_file(bom_path) if bom_path else []
        ref_points = parse_reference_points(ref_points_path) if ref_points_path else []

        merged = merge_sources(stp_data, bom_rows, ref_points)
        if not merged["parts_master"]:
            return {"error": "No parts could be extracted from the provided files. "
                              "Check that the STP/BOM/reference-point files are valid."}

        # ── Phase 2: build grounded meta + section outline ───────────────
        meta = build_manual_meta(merged, product_name=product_name,
                                  domain_hint=domain_hint,
                                  extra_instructions=extra_instructions)
        sections = meta["sections"]
        title, subtitle = meta["title"], meta["subtitle"]

        client = Groq(api_key=key)

        # ── Phase 3: word budget (same formula as scratch.py) ────────────
        target_total = int(pages * WORDS_PER_PAGE * 1.30)
        per_section  = max(450, target_total // max(len(sections), 1))

        # ── Phase 4: write each section via scratch.py's AI writer ───────
        parts_text: List[str] = [f"# {title}\n\n"]
        section_list: List[str] = []

        for sec in sections:
            content = generate_section(sec, meta, per_section, client)

            # Ground sections 3 & 4 with the REAL bom table / assembly list
            # instead of (or in addition to) free-text AI content.
            if sec["number"] == "3":
                content += "\n\n" + _bom_markdown_table(merged["parts_master"]) + "\n\n"
            if sec["number"] == "2" and merged["assembly_tree"]:
                content += "\n\n**Assembly Relationships:**\n\n" + \
                           _assembly_tree_text(merged["assembly_tree"]) + "\n\n"

            parts_text.append(content)
            section_list.append(f"{sec['number']}. {sec['title']}")

        full_manual = "".join(parts_text)

        # ── Phase 5: top-up if short ──────────────────────────────────────
        current_wc = _word_count(full_manual)
        minimum_wc = int(pages * WORDS_PER_PAGE * 0.85)
        if current_wc < minimum_wc:
            full_manual += generate_appendix(meta, minimum_wc - current_wc, client)

        full_manual = _clean_content(full_manual)
        final_wc  = _word_count(full_manual)
        est_pages = final_wc / WORDS_PER_PAGE

        # ── Phase 6: render PDF with data-driven diagrams ─────────────────
        pdf_path = None
        docx_path = None
        if FORMATTING_AVAILABLE:
            diagram_specs = build_diagram_specs(merged) if include_diagrams else {}
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            pdf_path = os.path.join(OUTPUT_DIR, f"Manual_{ts}.pdf")
            create_professional_manual_pdf(
                content=full_manual,
                output_path=pdf_path,
                doc_title=title,
                doc_subtitle=subtitle,
                include_diagrams=include_diagrams,
                diagram_specs=diagram_specs,   # pre-built — no extra AI calls, no hallucination
                groq_client=client,
                groq_model=GROQ_MODEL,
                revision=meta["revision"],
                company=meta["company"],
                parts_master=merged["parts_master"],
            )
            # Also generate DOCX
            docx_path = os.path.join(OUTPUT_DIR, f"Manual_{ts}.docx")
            create_manual_docx(
                content=full_manual,
                output_path=docx_path,
                doc_title=title,
                doc_subtitle=subtitle,
                revision=meta["revision"],
                company=meta["company"],
                parts_master=merged["parts_master"],
            )

        return {
            "title": title, "subtitle": subtitle, "domain": meta["domain"],
            "revision": meta["revision"], "company": meta["company"],
            "sections": section_list, "full_manual": full_manual,
            "word_count": final_wc, "estimated_pages": est_pages,
            "pdf_path": pdf_path,
            "docx_path": docx_path,
            "parts_master": merged["parts_master"],
            "assembly_tree": merged["assembly_tree"],
            "merge_stats": merged["stats"],
            "summary": (
                f"{merged['stats']['merged_parts']} parts merged "
                f"(BOM: {merged['stats']['bom_rows']}, "
                f"STP: {merged['stats']['stp_parts']}, "
                f"Ref Points: {merged['stats']['ref_points']}) | "
                f"{final_wc:,} words (~{est_pages:.1f} pages)"
            ),
        }

    except Exception as e:
        msg = str(e)
        if "rate_limit" in msg.lower() or "429" in msg:
            return {"error": "Rate limit hit. Wait 60 s and retry."}
        import traceback; traceback.print_exc()
        return {"error": f"Generation error: {msg}"}


# ══════════════════════════════════════════════════════════════════════════
#  9. Streamlit UI helpers (mirrors scratch.py's render_new_manual_* style)
# ══════════════════════════════════════════════════════════════════════════

def render_cad_bom_sidebar(Config, DocumentProcessor) -> None:
    import streamlit as st

    st.markdown("""
        <div style="background:linear-gradient(135deg,#5B2D8E,#7B3FAC);
                    padding:1.2rem;border-radius:12px;margin-bottom:1rem;
                    box-shadow:0 4px 14px rgba(91,45,142,.45);">
            <h2 style="color:white;margin:0;font-size:1.25rem;">
                🧩 CAD + BOM + Reference Point Manual
            </h2>
            <p style="color:rgba(255,255,255,.85);margin:.4rem 0 0;font-size:.82rem;">
                Grounded in your STP assembly, BOM & callout points
            </p>
        </div>""", unsafe_allow_html=True)

    stp_file = st.file_uploader("📐 STP / STEP CAD File", type=["stp", "step"],
                                 key="cad_stp_uploader",
                                 help="Assembly CAD file — used for part names & structure")
    bom_file = st.file_uploader("📋 Bill of Materials", type=["xlsx", "xls", "csv", "pdf"],
                                 key="cad_bom_uploader",
                                 help="Item No / Part Number / Description / Qty / Material "
                                      "— .xlsx, .xls, .csv, or a PDF with a BOM table")
    ref_file = st.file_uploader("📍 Reference / Callout Points", type=["csv", "xlsx", "json"],
                                 key="cad_ref_uploader",
                                 help="Point ID/Item No, Label, X, Y (Z optional)")

    st.text_input("Product name (optional)", key="cad_product_name",
                  placeholder="e.g. Split AC Indoor Unit Assembly")
    st.number_input("📄 Minimum Pages", min_value=1, max_value=150,
                    value=st.session_state.get("cad_pages", 12), step=1, key="cad_pages")
    st.checkbox("📊 Include Diagrams (assembly tree, BOM, callout map)",
                value=st.session_state.get("cad_include_diagrams", True),
                key="cad_include_diagrams")
    st.text_area("✍️ Extra instructions (optional)", key="cad_instructions",
                 placeholder="e.g. emphasise torque specs, add regulatory references…",
                 height=80)

    for label, key_name, uploaded in (
        ("stp", "cad_stp_path", stp_file),
        ("bom", "cad_bom_path", bom_file),
        ("ref", "cad_ref_path", ref_file),
    ):
        if uploaded is not None:
            tmp = f"_tmp_cad_{label}_{uploaded.name}"
            with open(tmp, "wb") as f:
                f.write(uploaded.getbuffer())
            st.session_state[key_name] = tmp
            st.success(f"✅ Loaded {label.upper()}: {uploaded.name}")

    if st.button("🚀 Generate Manual from CAD/BOM/Ref Points",
                 key="gen_cad_btn", use_container_width=True):
        st.session_state.cad_generate_clicked = True


def render_cad_bom_main(Config, DocumentProcessor) -> None:
    import streamlit as st

    st.markdown("### 🧩 CAD + BOM + Reference Point Manual Generator")
    st.info(
        "**What this generates:**\n"
        "- ✅ Part names & assembly structure extracted from your STP file\n"
        "- ✅ Full Bill of Materials rendered as a real table in the manual\n"
        "- ✅ Reference-point / callout diagram linking BOM items to locations\n"
        "- ✅ AI-written sections grounded in your real part numbers (no invented parts)\n"
        "- ✅ Same professional PDF layout as the standard generator"
    )

    if not st.session_state.get("cad_generate_clicked"):
        return
    st.session_state.cad_generate_clicked = False

    stp_path = st.session_state.get("cad_stp_path")
    bom_path = st.session_state.get("cad_bom_path")
    ref_path = st.session_state.get("cad_ref_path")

    if not (stp_path or bom_path):
        st.error("❌ Please upload at least an STP file or a BOM file in the sidebar.")
        return

    progress = st.progress(0); status = st.empty()
    try:
        status.text("🔍 Parsing STP / BOM / reference points…")
        progress.progress(15)

        result = generate_manual_from_cad_bom(
            stp_path=stp_path, bom_path=bom_path, ref_points_path=ref_path,
            pages=int(st.session_state.get("cad_pages", 12)),
            include_diagrams=st.session_state.get("cad_include_diagrams", True),
            product_name=st.session_state.get("cad_product_name", ""),
            extra_instructions=st.session_state.get("cad_instructions", ""),
        )

        if "error" in result:
            st.error(f"❌ {result['error']}"); progress.empty(); status.empty(); return

        progress.progress(85); status.text("✅ Done!")

        st.success(result["summary"])
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Words", f"{result['word_count']:,}")
        c2.metric("Pages", f"{result['estimated_pages']:.1f}")
        c3.metric("Parts merged", str(result["merge_stats"]["merged_parts"]))
        c4.metric("Sections", str(len(result["sections"])))

        with st.expander("📦 Merged Parts Master List"):
            for p in result["parts_master"][:50]:
                st.write(f"**{p.get('item_no') or '-'}** — {p.get('name')} "
                         f"(qty {p.get('qty','1')}) · sources: {', '.join(p['sources'])}")

        pdf_path = result.get("pdf_path")
        docx_path = result.get("docx_path")
        
        if (pdf_path and os.path.exists(pdf_path)) or (docx_path and os.path.exists(docx_path)):
            st.markdown("#### 📥 Download Manual")
            c_pdf, c_docx = st.columns(2)
            if pdf_path and os.path.exists(pdf_path):
                size_kb = os.path.getsize(pdf_path) / 1024
                with open(pdf_path, "rb") as fh:
                    c_pdf.download_button(
                        label=f"📕 Download PDF ({size_kb:.0f} KB)",
                        data=fh.read(), file_name=os.path.basename(pdf_path),
                        mime="application/pdf", use_container_width=True,
                    )
            if docx_path and os.path.exists(docx_path):
                size_kb = os.path.getsize(docx_path) / 1024
                with open(docx_path, "rb") as fh:
                    c_docx.download_button(
                        label=f"📘 Download Word DOCX ({size_kb:.0f} KB)",
                        data=fh.read(), file_name=os.path.basename(docx_path),
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True,
                    )
        else:
            st.error("Generated files not found.")

        progress.empty(); status.empty()

    except Exception as e:
        import traceback
        st.error(f"❌ Unexpected error: {e}")
        st.code(traceback.format_exc())
        progress.empty(); status.empty()


# ══════════════════════════════════════════════════════════════════════════
#  10. Standalone CLI
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a manual from STP + BOM + Reference Points")
    parser.add_argument("--stp", help="Path to .stp/.step CAD file")
    parser.add_argument("--bom", help="Path to BOM .xlsx/.xls/.csv/.pdf")
    parser.add_argument("--refs", help="Path to reference-points .csv/.xlsx/.json")
    parser.add_argument("--pages", type=int, default=12)
    parser.add_argument("--product-name", default="")
    parser.add_argument("--no-diagrams", action="store_true")
    args = parser.parse_args()

    print("=" * 62)
    print("  CAD + BOM + Reference Point Manual Generator")
    print("=" * 62)

    result = generate_manual_from_cad_bom(
        stp_path=args.stp, bom_path=args.bom, ref_points_path=args.refs,
        pages=args.pages, include_diagrams=not args.no_diagrams,
        product_name=args.product_name,
    )

    if "error" in result:
        print(f"\n[ERROR] {result['error']}")
        sys.exit(1)

    print(f"\nTitle    : {result['title']}")
    print(f"Words    : {result['word_count']:,}")
    print(f"Pages    : {result['estimated_pages']:.1f}")
    print(f"Parts    : {result['merge_stats']['merged_parts']}")
    if result.get("pdf_path"):
        print(f"PDF      : {result['pdf_path']}")
    print("✅ Done!")