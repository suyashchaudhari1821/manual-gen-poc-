from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer
)
from reportlab.lib.styles import (
    getSampleStyleSheet
)

import fitz
import re
from copy import deepcopy

import fitz


def update_toc_pages_in_pdf(
    pdf_path,
    toc_section,
    toc_entries,
    output_pdf
):

    doc = fitz.open(pdf_path)

    start_idx = toc_section.start_page - 1
    end_idx = toc_section.end_page - 1

    toc_lines = ["TABLE OF CONTENTS", ""]

    for entry in toc_entries:

        toc_lines.append(
            f"{entry['title']} .......... {entry['start_page']}"
        )

    toc_text = "\n".join(toc_lines)

    first_page = doc[start_idx]

    # cover first TOC page
    first_page.draw_rect(
        first_page.rect,
        color=(1, 1, 1),
        fill=(1, 1, 1)
    )

    textbox = fitz.Rect(
        50,
        50,
        first_page.rect.width - 50,
        first_page.rect.height - 50
    )

    result = first_page.insert_textbox(
        textbox,
        toc_text,
        fontsize=10,
        fontname="helv",
        color=(0, 0, 0)
    )

    print("Textbox result:", result)

    doc.save(output_pdf)
    doc.close()

    return output_pdf


# ==================================================
# Extract Original TOC From PDF
# ==================================================

def extract_original_toc(
    pdf_path,
    toc_section
):

    doc = fitz.open(pdf_path)

    toc_entries = []

    for page_no in range(
        toc_section.start_page - 1,
        toc_section.end_page
    ):

        page = doc[page_no]

        text = page.get_text()

        lines = text.split("\n")

        for line in lines:

            line = line.strip()

            match = re.match(
                r"^(.*?)\s+(\d+)$",
                line
            )

            if match:

                title = match.group(1).strip()

                page_num = int(
                    match.group(2)
                )

                toc_entries.append(
                    {
                        "title": title,
                        "start_page": page_num
                    }
                )

    doc.close()

    return toc_entries


# ==================================================
# Find TOC Section
# ==================================================

def get_toc_section(
    structured_document
):

    print("\nTOC SEARCH")

    for section in structured_document.sections:

        print(
            section.title,
            section.start_page,
            section.end_page
        )

        print(
            "TOC FOUND:",
            section.start_page,
            section.end_page
        )

    for section in structured_document.sections:

        if (
            section.title.strip().upper()
            in [
                "CONTENTS",
                "TABLE OF CONTENTS"
            ]
        ):
            return section

    return None


# ==================================================
# Update Existing TOC
# ==================================================

def update_existing_toc(
    toc_entries,
    generated_title,
    target_section,
    inserted_page,
    pages_added
):

    updated = deepcopy(toc_entries)

    target_idx = None

    for i, entry in enumerate(updated):

        if (
            target_section
            and
            target_section.lower()
            in entry["title"].lower()
        ):
            target_idx = i
            break

    # --------------------------------------
    # Append Mode
    # --------------------------------------

    if target_idx is None:

        if len(updated) > 0:

            last_entry = updated[-1]

            start_page = (
                last_entry["start_page"] + 1
            )

        else:

            start_page = 1

        updated.append(
            {
                "title": generated_title,
                "start_page": start_page
            }
        )

        return updated

    # --------------------------------------
    # Insert After Target
    # --------------------------------------

    updated.insert(
        target_idx + 1,
        {
            "title": generated_title,
            "start_page": inserted_page + 1
        }
    )

    # --------------------------------------
    # Shift Following Entries
    # --------------------------------------

    for i in range(
        target_idx + 2,
        len(updated)
    ):

        updated[i]["start_page"] += pages_added

    return updated
