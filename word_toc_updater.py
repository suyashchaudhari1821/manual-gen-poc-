from dataclasses import dataclass
from docx import Document


# ==========================================================
# MODELS
# ==========================================================

@dataclass
class TocEntry:
    title: str
    level: int
    page_number: int | None = None


@dataclass
class TocInfo:
    exists: bool
    toc_type: str  # text | table | none
    start_index: int | None = None
    end_index: int | None = None


# ==========================================================
# TOC DETECTOR
# ==========================================================

TOC_KEYWORDS = {
    "content",
    "contents",
    "table of contents"
}


def detect_toc(docx_path):

    doc = Document(docx_path)

    # ----------------------------------------
    # TEXT TOC
    # ----------------------------------------

    for idx, para in enumerate(doc.paragraphs):

        text = para.text.strip().lower()

        if text in TOC_KEYWORDS:

            return TocInfo(
                exists=True,
                toc_type="text",
                start_index=idx,
                end_index=None
            )

    # ----------------------------------------
    # TABLE TOC
    # ----------------------------------------

    for table_idx, table in enumerate(doc.tables):

        table_text = " ".join(
            cell.text.lower()
            for row in table.rows
            for cell in row.cells
        )

        if (
            "contents" in table_text
            or "table of contents" in table_text
            or "page" in table_text
        ):

            return TocInfo(
                exists=True,
                toc_type="table",
                start_index=table_idx,
                end_index=None
            )

    return TocInfo(
        exists=False,
        toc_type="none"
    )


# ==========================================================
# BUILD TOC ENTRIES
# ==========================================================

def build_toc_entries(docx_path):

    doc = Document(docx_path)

    entries = []

    for para in doc.paragraphs:

        if not para.text.strip():
            continue

        style_name = para.style.name.lower()

        # Accept only Heading styles
        if style_name.startswith("heading"):

            try:
                level = int(
                    style_name.split()[-1]
                )

            except Exception:
                level = 1

            entries.append(
                TocEntry(
                    title=para.text.strip(),
                    level=level
                )
            )

    return entries


# ==========================================================
# TOC RENDERER
# ==========================================================

def render_text_toc(entries):

    toc_lines = []

    counters = {}

    for entry in entries:

        level = entry.level

        counters[level] = (
            counters.get(level, 0) + 1
        )

        for key in list(counters.keys()):

            if key > level:
                counters[key] = 0

        numbering = ".".join(
            str(counters[k])
            for k in sorted(counters)
            if k <= level and counters[k] > 0
        )

        indent = "    " * (level - 1)

        toc_lines.append(
            f"{indent}{numbering} {entry.title}"
        )

    return toc_lines


# ==========================================================
# TEXT TOC UPDATER
# ==========================================================

def update_text_toc(docx_path, output_path):

    doc = Document(docx_path)

    toc_info = detect_toc(docx_path)

    entries = build_toc_entries(docx_path)

    toc_lines = render_text_toc(entries)

    # ------------------------------------------------------
    # No TOC Found
    # ------------------------------------------------------

    if toc_info.toc_type != "text":

        if len(doc.paragraphs) == 0:
            doc.add_paragraph("TABLE OF CONTENTS")

        else:
            doc.paragraphs[0].insert_paragraph_before(
                "TABLE OF CONTENTS"
            )

            anchor = doc.paragraphs[0]

            for line in reversed(toc_lines):
                anchor.insert_paragraph_before(line)

        doc.save(output_path)

        return output_path

    # ------------------------------------------------------
    # Existing Text TOC
    # ------------------------------------------------------

    start = toc_info.start_index

    current = start + 1

    while current < len(doc.paragraphs):

        text = doc.paragraphs[current].text.strip()

        if not text:
            break

        elem = doc.paragraphs[current]._element
        elem.getparent().remove(elem)

    anchor_index = min(
        start + 1,
        len(doc.paragraphs) - 1
    )

    anchor = doc.paragraphs[anchor_index]

    for line in reversed(toc_lines):

        anchor.insert_paragraph_before(
            line
        )

    doc.save(output_path)

    return output_path


# ==========================================================
# TABLE TOC UPDATER
# ==========================================================

def update_table_toc(
    docx_path,
    output_path
):

    doc = Document(docx_path)

    entries = build_toc_entries(
        docx_path
    )

    target_table = None

    for table in doc.tables:

        table_text = " ".join(
            cell.text.lower()
            for row in table.rows
            for cell in row.cells
        )

        if (
            "contents" in table_text
            or "table of contents" in table_text
            or "page" in table_text
        ):
            target_table = table
            break

    if target_table is None:

        doc.save(output_path)

        return output_path

    # Keep Header Row

    while len(target_table.rows) > 1:

        target_table._tbl.remove(
            target_table.rows[-1]._tr
        )

    for entry in entries:

        row = target_table.add_row()

        row.cells[0].text = (
            ("    " * (entry.level - 1))
            + entry.title
        )

        row.cells[1].text = ""

    doc.save(output_path)

    return output_path


# ==========================================================
# MASTER API
# ==========================================================

def update_toc(
    docx_path,
    output_path=None
):

    if output_path is None:
        output_path = docx_path

    toc = detect_toc(docx_path)

    print("TOC FOUND:", toc)

    if toc.toc_type == "table":

        print("Updating TABLE TOC")

        return update_table_toc(
            docx_path,
            output_path
        )

    print("Updating TEXT TOC")

    return update_text_toc(
        docx_path,
        output_path
    )