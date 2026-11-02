from typing import Optional

from manual_models import (
    StructuredDocument,
    DocumentSection
)


def build_document_structure(manual):
    """
    Convert parsed manual into a structured document.

    Input:
        manual.text_blocks
        manual.image_blocks
        manual.table_blocks

    Output:
        StructuredDocument
    """

    sections = []

    current_section = None

    section_counter = 1

    # ----------------------------------
    # Build sections from text blocks
    # ----------------------------------

    for block in manual.text_blocks:

        if block.block_type.lower() == "heading":

            if current_section is not None:
                sections.append(current_section)

            current_section = DocumentSection(
    section_id=f"SEC_{section_counter}",
    title=block.text.strip(),
    level=getattr(block, "level", 1),
    start_page=block.page_number,
    end_page=block.page_number,
    text_blocks=[block]
)
            section_counter += 1

            continue

        # ----------------------------------
        # Document without heading start
        # ----------------------------------

        if current_section is None:

            current_section = DocumentSection(
    section_id=f"SEC_{section_counter}",
    title="INTRODUCTION",
    level=1,
    start_page=block.page_number,
    end_page=block.page_number,
)

            section_counter += 1

        current_section.text_blocks.append(block)

        current_section.end_page = max(
         current_section.end_page,
         block.page_number
)

    # ----------------------------------
    # Add final section
    # ----------------------------------

    if current_section is not None:
        sections.append(current_section)

    # ----------------------------------
    # Attach Images
    # ----------------------------------

    for image in manual.image_blocks:

        for section in sections:

            if (
    section.start_page
    <= image.page_number
    <= section.end_page
):

                section.image_blocks.append(
                    image
                )

    # ----------------------------------
    # Attach Tables
    # ----------------------------------

    for table in manual.table_blocks:

        for section in sections:

            if (
    section.start_page
    <= table.page_number
    <= section.end_page
):

                section.table_blocks.append(
                    table
                )

    # ----------------------------------
    # Create structured document
    # ----------------------------------

    return StructuredDocument(
        metadata=manual.metadata,
        sections=sections
    )


# ==================================================
# TOC
# ==================================================

def build_toc(document: StructuredDocument):

    toc = []

    for section in document.sections:

        toc.append(
            {
    "section_id": section.section_id,
    "title": section.title,
    "level": section.level,
    "start_page": section.start_page,
    "end_page": section.end_page,
}
        )

    return toc


# ==================================================
# Section Search
# ==================================================

def find_section(
    document: StructuredDocument,
    title: str
) -> Optional[DocumentSection]:

    for section in document.sections:

        if title.lower() in section.title.lower():

            return section

    return None


# ==================================================
# Insert Section After
# ==================================================

# ==================================================
# Insert Section After
# ==================================================

def insert_section_after(
    document: StructuredDocument,
    target_title: str,
    new_section: DocumentSection
) -> StructuredDocument:

    updated_sections = []

    inserted = False

    for section in document.sections:

        updated_sections.append(section)

        if (
            target_title.lower()
            in section.title.lower()
        ):

            updated_sections.append(
                new_section
            )

            inserted = True

    # if target section not found
    if not inserted:

        updated_sections.append(
            new_section
        )

    document.sections = updated_sections

    return document


# ==================================================
# Insert Section Before
# ==================================================

def insert_section_before(
    document: StructuredDocument,
    target_title: str,
    new_section: DocumentSection
) -> StructuredDocument:

    updated_sections = []

    inserted = False

    for section in document.sections:

        if (
            target_title.lower()
            in section.title.lower()
        ):

            updated_sections.append(
                new_section
            )

            inserted = True

        updated_sections.append(section)

    # if target section not found
    if not inserted:

        updated_sections.insert(
            0,
            new_section
        )

    document.sections = updated_sections

    return document


# ==================================================
# Append Section
# ==================================================

def append_section(
    document: StructuredDocument,
    new_section: DocumentSection
) -> StructuredDocument:

    document.sections.append(
        new_section
    )

    return document


# ==================================================
# Remove Section
# ==================================================

def remove_section(
    document: StructuredDocument,
    title: str
) -> StructuredDocument:

    filtered_sections = []

    for section in document.sections:

        if (
            title.lower()
            not in section.title.lower()
        ):

            filtered_sections.append(
                section
            )

    document.sections = filtered_sections

    return document


# ==================================================
# Print Structure (Debug)
# ==================================================

def print_structure(
    document: StructuredDocument
):

    print("\nDOCUMENT STRUCTURE\n")

    for section in document.sections:

        print("=" * 80)

        print(
            f"ID: {section.section_id}"
        )

        print(
            f"TITLE: {section.title}"
        )

        print(
            f"LEVEL: {section.level}"
        )

        print(
f"START PAGE: {section.start_page}"
)
        print(
f"END PAGE: {section.end_page}"
)
        print(
            f"TEXT BLOCKS: {len(section.text_blocks)}"
        )

        print(
            f"IMAGES: {len(section.image_blocks)}"
        )

        print(
            f"TABLES: {len(section.table_blocks)}"
        )

        print("=" * 80)