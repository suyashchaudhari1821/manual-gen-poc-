"""
bom_parser.py
=============
Parses Bill of Materials files (CSV, XLSX, XLS, JSON, TXT/TSV) and
correlates BOM rows with CAD parts by fuzzy name/part-number matching.

Original source: cad-assistant/backend/bom_parser.py
All original parsing logic is PRESERVED EXACTLY.

Changes from original:
  1. parse_bom_file(filename, content) signature is preserved as-is.
     An additional parse_bom_file_from_path(file_path) convenience wrapper
     is provided for callers that have the file on disk (used by app_patch.py).

  2. correlate_bom_with_cad() is EXTENDED with Jaccard token similarity so
     partial name matches that the original substring check would miss are
     now caught (e.g. "SUNROOF_FRAME_ASSY" vs "Sunroof Frame").
     The original exact-match and substring-match paths are preserved first
     in priority; Jaccard is only the third-priority fallback.

  3. COLUMN_ALIASES extended: torque / drawing_ref / revision columns added
     (needed by spec_resolver.py to extract torque values from BOM).

  4. correlate_bom_with_cad() return dict gains "match_threshold" key for
     transparency; "enriched_parts" items gain "bom_match_score" for the
     confidence report.
"""

import io
import re
import json
import csv
from pathlib import Path
import logging
import time

logger = logging.getLogger(__name__)
from bom_tracing import traceable
from bom_models import BOMDocument, BOMItem

# ---------------------------------------------------------------------------
# Column name aliases — original set extended with torque, drawing_ref, revision
# ---------------------------------------------------------------------------

COLUMN_ALIASES = {
    "part_number": [
        "part number", "part no", "part#", "partno", "pn",
        "part_number", "partnumber",
        "component no", "component number", "drawing number",
    ],
    "item_no": [
        # The BOM "ITEM" column (a short ordinal like "2", "10", "200/201")
        # is a DIFFERENT field from the part number ("NAS577B6A") — they used
        # to share the "part_number" canonical bucket, which meant whichever
        # column got parsed last silently overwrote the other in the row
        # dict. Real Airbus-style BOMs have both columns side by side.
        "item", "item no", "item number", "item#", "fin", "ipc item",
    ],
    "name": [
        "name", "description", "part name", "component", "component name",
        "title", "part description", "desc", "item description",
    ],
    "quantity": [
        "qty", "quantity", "count", "amount", "no of parts",
        "num", "pieces", "pcs", "units",
    ],
    "material": [
        "material", "mat", "material type", "alloy", "grade", "substance",
        "material spec", "raw material",
    ],
    "supplier": [
        "supplier", "vendor", "manufacturer", "make", "brand", "source",
        "oem", "mfr",
    ],
    "weight": [
        "weight", "mass", "wt", "kg", "gram", "lbs",
        "unit weight", "weight kg",
    ],
    "torque": [
        "torque", "torque value", "torque spec", "torque nm",
        "tightening torque", "fastening torque", "bolt torque",
        "torque ft-lb", "torque specification",
    ],
    "cost": [
        "cost", "price", "unit price", "unit cost", "value", "list price",
    ],
    "drawing_ref": [
        "drawing", "drawing no", "drg", "dwg", "drawing number",
        "drawing ref", "drg no", "dwg no",
    ],
    "revision": [
        "rev", "revision", "version", "ver", "revision level",
    ],
    "notes": [
        "notes", "remarks", "comment", "comments", "note",
        "additional info",
    ],
}


def _normalize_col(col_name: str) -> str:
    """Map a raw column header to a canonical field name."""
    c = col_name.strip().lower().replace("_", " ").replace("-", " ")
    for canonical, aliases in COLUMN_ALIASES.items():
        if c in aliases or c == canonical:
            return canonical
    return c  # keep as-is if no match


def _safe_str(v) -> str:
    """Safely convert any cell value to a stripped string."""
    if v is None:
        return ""
    if isinstance(v, list):
        v = " ".join(str(x) for x in v if x is not None)
    return str(v).strip()


# ---------------------------------------------------------------------------
# Format parsers — copied verbatim from original bom_parser.py
# ---------------------------------------------------------------------------

def _parse_csv(content: bytes) -> list:
    # Try utf-8-sig first, fall back to latin-1
    text = ""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content.decode(encoding, errors="replace")
            break
        except Exception:
            continue

    reader = csv.DictReader(io.StringIO(text))
    rows = []
    fieldnames = [h for h in (reader.fieldnames or []) if h is not None and str(h).strip()]
    col_map = {h: _normalize_col(h) for h in fieldnames}
    for row in reader:
        mapped = {}
        for k, v in row.items():
            if k is None or not str(k).strip():
                continue
            if k not in col_map:
                continue
            clean = _safe_str(v)
            if clean:
                mapped[col_map[k]] = clean
        if mapped:
            rows.append(mapped)
    return rows


def _parse_excel(content: bytes) -> list:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows_iter = list(ws.iter_rows(values_only=True))
        if not rows_iter:
            return []
        # Find header row (first non-empty row)
        header_row_idx = 0
        for i, row in enumerate(rows_iter):
            if any(cell is not None and str(cell).strip() for cell in row):
                header_row_idx = i
                break
        headers = [str(c).strip() if c is not None else f"col_{i}"
                   for i, c in enumerate(rows_iter[header_row_idx])]
        col_map = {h: _normalize_col(h) for h in headers}
        rows = []
        for row in rows_iter[header_row_idx + 1:]:
            mapped = {}
            for h, cell in zip(headers, row):
                if cell is not None and str(cell).strip():
                    mapped[col_map[h]] = str(cell).strip()
            if mapped:
                rows.append(mapped)
        return rows
    except ImportError:
        raise ValueError("openpyxl is required for Excel files. Run: pip install openpyxl")


def _parse_json(content: bytes) -> list:
    data = json.loads(content.decode("utf-8"))
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        # Look for a key that holds an array
        rows = None
        for v in data.values():
            if isinstance(v, list):
                rows = v
                break
        if rows is None:
            rows = [data]
    else:
        rows = [data]
    result = []
    for item in rows:
        if isinstance(item, dict):
            mapped = {_normalize_col(k): _safe_str(v) for k, v in item.items() if v}
            result.append(mapped)
    return result


def _parse_txt(content: bytes) -> list:
    """Try tab-separated or pipe-separated text."""
    text = content.decode("utf-8-sig", errors="replace")
    # Detect delimiter
    first_line = text.split("\n")[0]
    if "\t" in first_line:
        delim = "\t"
    elif "|" in first_line:
        delim = "|"
    else:
        delim = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    rows = []
    fieldnames = [h for h in (reader.fieldnames or []) if h is not None and str(h).strip()]
    col_map = {h: _normalize_col(h) for h in fieldnames}
    for row in reader:
        mapped = {}
        for k, v in row.items():
            if k is None or not str(k).strip():
                continue
            if k not in col_map:
                continue
            clean = _safe_str(v)
            if clean:
                mapped[col_map[k]] = clean
        if mapped:
            rows.append(mapped)
    return rows


def _find_header_row(table: list) -> tuple:
    """
    Find which row in a pdfplumber-extracted table is the REAL column-header
    row, instead of blindly assuming it's row 0.

    Real-world exports (this Airbus BOM report is a good example) often have
    a section title row (e.g. "GENERAL INFORMATION") immediately before the
    actual header row ("ALT | QTY | ITEM | PART NUMBER | DESCRIPTION | ..."),
    or pdfplumber's grid detection can pick up an unrelated metadata block
    as its own separate "table" ahead of the real one. Blindly trusting
    table[0] silently turns the real header into a garbled DATA row and
    every column gets a meaningless "col_N" name — which then means
    spec_resolver.py can't find part_number/item/etc. in ANY row, even
    though rows were "successfully" extracted.

    Scores every row by how many cells normalise to a KNOWN canonical BOM
    column name, and returns the row with the most hits (ties broken by
    earliest row). Returns (header_row_index, score).
    """
    best_idx, best_score = 0, -1
    for i, row in enumerate(table):
        cells = [str(c).strip() if c is not None else "" for c in row]
        score = sum(1 for c in cells if c and _normalize_col(c) in COLUMN_ALIASES)
        if score > best_score:
            best_score, best_idx = score, i
    return best_idx, best_score


@traceable(name="parse_pdf_bom")
def _parse_pdf(content: bytes) -> list:
    """
    Extract BOM rows from a PDF.

    Priority 1: structured tables via pdfplumber's table-grid detection —
    handles most PDFs exported straight from Excel/ERP systems.
    Priority 2: whitespace-aligned text columns, for PDFs with no table
    grid lines. Only used if the first line of a page actually contains a
    recognised BOM column name (part number / name / qty / etc.) — this
    avoids silently turning random paragraphs into garbage BOM rows.
    """
    try:
        import pdfplumber
    except ImportError:
        raise ValueError("pdfplumber is required for PDF BOM files. Run: pip install pdfplumber")

    rows = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        # Priority 1: structured tables
        for page in pdf.pages:
            for table in (page.extract_tables() or []):
                if not table or len(table) < 2:
                    continue

                # Find the REAL header row instead of assuming table[0].
                # Require at least 2 recognised canonical columns before
                # trusting this table at all — otherwise it's very likely
                # a title/metadata block, not actual BOM data, and every
                # row would just get meaningless "col_N" keys.
                header_idx, header_score = _find_header_row(table)
                if header_score < 2:
                    continue

                headers = [str(h).strip() if h else f"col_{i}"
                           for i, h in enumerate(table[header_idx])]
                col_map = {h: _normalize_col(h) for h in headers}
                for raw_row in table[header_idx + 1:]:
                    mapped = {}
                    for h, cell in zip(headers, raw_row):
                        clean = _safe_str(cell)
                        if clean:
                            mapped[col_map[h]] = clean
                    if mapped:
                        rows.append(mapped)

        # Priority 2: whitespace/tab-aligned text columns (no table grid found)
        if not rows:
            for page in pdf.pages:
                text = page.extract_text() or ""
                lines = [l for l in text.splitlines() if l.strip()]
                if len(lines) < 2:
                    continue
                header_cells = re.split(
    r"\s{2,}|\t",
    lines[0].strip()
)
                col_map = {h: _normalize_col(h) for h in header_cells}
                if not any(v in COLUMN_ALIASES for v in col_map.values()):
                    continue  # first line doesn't look like a BOM header — skip this page
                for line in lines[1:]:
                    cells = re.split(
    r"\s{2,}|\t",
    line.strip()
)
                    mapped = {}
                    for h, cell in zip(header_cells, cells):
                        clean = _safe_str(cell)
                        if clean:
                            mapped[col_map[h]] = clean
                    if mapped:
                        rows.append(mapped)

    return rows


# ---------------------------------------------------------------------------
# Public parse entry points
# ---------------------------------------------------------------------------
@traceable(name="parse_bom_file")
def parse_bom_file(filename: str, content: bytes) -> BOMDocument:
    """
    Parse a BOM file and return structured data.

    Original signature from cad-assistant project — preserved exactly.

    Parameters
    ----------
    filename : original filename string (used for extension detection only)
    content  : raw file bytes

    Returns
    -------
    {
      "filename": str,
      "row_count": int,
      "fields_found": [str, ...],
      "total_quantity": int,
      "unique_materials": [str, ...],
      "unique_suppliers": [str, ...],
      "rows": [{canonical_field: value, ...}, ...]
    }
    """
    print("NEW PARSE_BOM_FILE EXECUTING")
    start_time = time.perf_counter()
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".csv":
            rows = _parse_csv(content)
        elif ext in (".xlsx", ".xls"):
            rows = _parse_excel(content)
        elif ext == ".json":
            rows = _parse_json(content)
        elif ext in (".txt", ".tsv"):
            rows = _parse_txt(content)
        elif ext == ".pdf":
            rows = _parse_pdf(content)
        else:
            raise ValueError(f"Unsupported BOM format: {ext}. Supported: CSV, XLSX, JSON, TXT, PDF")
    except Exception as e:
        raise ValueError(f"Failed to parse BOM file: {str(e)}")

    if not rows:
        if ext == ".pdf":
            raise ValueError(
                "Could not find a recognisable BOM table in this PDF. "
                "It may be a scanned/image-only PDF (needs OCR) or use column "
                "headers this parser doesn't recognise yet."
            )
        raise ValueError("BOM file appears to be empty or has no readable rows")

    # Extract all unique field names found
    all_fields: set = set()
    for r in rows:
        all_fields.update(r.keys())

    # Build summary stats
    total_qty = 0
    materials: set = set()
    suppliers: set = set()
    for row in rows:
        try:
            q = row.get("quantity", "1")
            total_qty += int(float(q)) if q else 1
        except Exception:
            total_qty += 1
        if row.get("material"):
            materials.add(row["material"])
        if row.get("supplier"):
            suppliers.add(row["supplier"])
    logger.info(
    "Parsing BOM file. filename=%s format=%s",
    filename,
    ext,
) 
    logger.info(
        "BOM parsed successfully. rows=%s",
        len(rows),
    )

    items = []

    for row in rows:

        quantity = None

        try:
            if row.get("quantity"):
                quantity = float(row["quantity"])
        except Exception:
            quantity = None

        items.append(
            BOMItem(
                item_no=row.get("item_no"),
                part_number=row.get("part_number"),
                name=row.get("name"),
                quantity=quantity,
                material=row.get("material"),
                supplier=row.get("supplier"),
                weight=row.get("weight"),
                torque=row.get("torque"),
                drawing_ref=row.get("drawing_ref"),
                revision=row.get("revision"),
                notes=row.get("notes"),
            )
        )

    duration = time.perf_counter() - start_time

    return BOMDocument(
        filename=filename,
        row_count=len(items),
        items=items,
        parsing_mode=ext.replace(".", ""),
        parsing_confidence=1.0,
        parse_duration=round(duration, 3),
    )
    print("RETURN TYPE:", type(result))
    return result

def parse_bom_file_from_path(file_path: str) -> dict:
    """
    Convenience wrapper for callers that have the BOM file on disk.
    Reads the file bytes and delegates to parse_bom_file().

    Used by app_patch.py (PATCH POINT C sidebar) where Streamlit saves
    the uploaded file to a temp path before parsing.

    Parameters
    ----------
    file_path : absolute path to the BOM file on disk

    Returns same dict as parse_bom_file().
    """
    path = Path(file_path)
    if not path.exists():
        raise ValueError(f"BOM file not found: {file_path}")
    content = path.read_bytes()
    if not content:
        raise ValueError("BOM file is empty")
    return parse_bom_file(path.name, content)


# ---------------------------------------------------------------------------
# BOM <-> CAD correlation
# Extended from original: adds Jaccard token similarity as third-priority
# fallback while preserving the original exact-match and substring paths.
# ---------------------------------------------------------------------------

def _normalize_str(s: str) -> str:
    """Collapse to lowercase alphanumeric tokens for matching."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _tokenize(s: str) -> set:
    """Split into lowercase word tokens of length >= 2."""
    return {t for t in re.findall(r"[a-z0-9]{2,}", s.lower())}


def _jaccard(a: str, b: str) -> float:
    """Jaccard similarity between token sets of two strings."""
    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@traceable(name="correlate_bom_with_cad")
def correlate_bom_with_cad(
    bom_data: dict,
    cad_data: dict,
    jaccard_threshold: float = 0.25,
) -> dict:
    """
    Match BOM rows to CAD parts using a three-priority strategy:
      1. Exact normalised match on name or part_number (score = 1.0)
      2. Substring containment — either direction (score = 0.85)
      3. Jaccard token similarity >= jaccard_threshold (score = similarity)

    Original exact-match and substring paths from cad-assistant are preserved
    as priorities 1 and 2. Jaccard is the new priority-3 fallback.

    Parameters
    ----------
    bom_data          : output of parse_bom_file()
    cad_data          : output of cad_parser.parse_step_file()
    jaccard_threshold : minimum Jaccard score for priority-3 match (default 0.25)

    Returns
    -------
    {
      "matched_parts":   int,
      "unmatched_parts": int,
      "match_threshold": float,
      "enriched_parts":  [
          {...original cad part fields...,
           "bom": {matched BOM row} | None,
           "bom_match_score": float},
          ...
      ]
    }
    """
    start_time = time.perf_counter()
   
    bom_rows  = bom_data.get("rows", [])
    cad_parts = cad_data.get("parts", [])

    # Build normalised lookup from BOM for fast exact/substring checks
    # (same approach as original)
    bom_lookup: dict = {}
    for row in bom_rows:
        for field in ("name", "part_number", "description"):
            val = row.get(field, "")
            if val:
                key = _normalize_str(val)
                if key:
                    bom_lookup[key] = row

    matched   = 0
    enriched  = []

    for part in cad_parts:
        match_method = None
        part_copy = dict(part)
        part_name_norm = _normalize_str(part.get("name", ""))

        bom_match = None
        match_score = 0.0

        # Priority 1: exact normalised match (original logic)
        bom_match = bom_lookup.get(part_name_norm)
        if bom_match:
            match_score = 1.0
            match_method = "exact"
        # Priority 2: substring containment (original logic)
        if not bom_match:
            for bom_key, bom_row in bom_lookup.items():
                if (len(part_name_norm) > 3 and part_name_norm in bom_key) or \
                   (len(bom_key) > 3 and bom_key in part_name_norm):
                    bom_match  = bom_row
                    match_score = 0.85
                    match_method = "substring"
                    break

        # Priority 3: Jaccard token similarity (new addition)
        if not bom_match:
            best_score = 0.0
            best_row   = None
            part_name  = part.get("name", "")
            for row in bom_rows:
                for field in ("name", "part_number", "description"):
                    val = row.get(field, "")
                    if not val:
                        continue
                    score = _jaccard(part_name, val)
                    if score > best_score:
                        best_score = score
                        best_row   = row
            if best_score >= jaccard_threshold:
                bom_match   = best_row
                match_score = best_score
                match_method = "jaccard"

        part_copy["bom"]             = bom_match
        part_copy["bom_match_score"] = round(match_score, 3)
        part_copy["bom_match_method"] = match_method

        if bom_match is not None:
            matched += 1

        enriched.append(part_copy)
    duration = time.perf_counter() - start_time

    return {
    "matched_parts": matched,
    "unmatched_parts": len(cad_parts) - matched,
    "match_threshold": jaccard_threshold,
    "correlation_duration": round(duration, 3),
    "enriched_parts": enriched,
}