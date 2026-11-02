import json
from docx import Document

from docs_to_json_models import (
    ManualDocument,
    ManualMetadata,
    ManualSection,
    ManualParagraph,
    ManualTable,
    ManualImage,
)


def extract_table(table, table_id):

    rows = []

    for row in table.rows:

        rows.append([
            cell.text.strip()
            for cell in row.cells
        ])

    return ManualTable(
        table_id=table_id,
        rows=rows
    )


def docx_to_json(docx_path):

    doc = Document(docx_path)

    metadata = ManualMetadata(
        title=(
            doc.core_properties.title
            or docx_path.split("\\")[-1]
        ),
        source_file=docx_path
    )

    sections = []

    current_section = None

    section_counter = 1

    #
    # Extract headings + paragraphs
    #
    for para in doc.paragraphs:

        text = para.text.strip()

        if not text:
            continue

        style_name = para.style.name

        is_heading = (
            style_name.lower().startswith("heading")
            or style_name.lower() == "title"
        )

        if is_heading:

            if current_section:
                sections.append(
                    current_section
                )

            current_section = ManualSection(
                section_id=f"SEC_{section_counter}",
                title=text,
                style=style_name,
                content=[],
                images=[],
                tables=[]
            )

            section_counter += 1

        else:

            if current_section is None:

                current_section = ManualSection(
                    section_id=f"SEC_{section_counter}",
                    title="INTRODUCTION",
                    style="Normal",
                    content=[],
                    images=[],
                    tables=[]
                )

                section_counter += 1

            current_section.content.append(
                ManualParagraph(
                    text=text,
                    style=style_name
                )
            )

    if current_section:
        sections.append(current_section)

    #
    # Extract tables
    #
    table_counter = 1

    for table in doc.tables:

        tbl = extract_table(
            table,
            f"TBL_{table_counter}"
        )

        table_counter += 1

        #
        # TEMP:
        # attach to nearest section
        #
        if sections:

            sections[-1].tables.append(
                tbl
            )

    #
    # Extract images
    #
    image_counter = 1

    for rel in doc.part.rels.values():

        if "image" in rel.reltype:

            image = ManualImage(
                image_id=f"IMG_{image_counter}",
                filename=str(
                    rel.target_ref
                )
            )

            image_counter += 1

            #
            # TEMP:
            # attach to nearest section
            #
            if sections:

                sections[-1].images.append(
                    image
                )

    return ManualDocument(
        metadata=metadata,
        sections=sections
    )


def save_manual_json(
    manual,
    output_file="manual_document.json"
):

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            manual.model_dump(),
            f,
            indent=4,
            ensure_ascii=False
        )

    print(
        f"Saved Manual JSON -> {output_file}"
    )


if __name__ == "__main__":

    manual = docx_to_json(
        r"ExpleoBot_Proposal_Updated.docx"
    )

    save_manual_json(
        manual,
        "manual_document.json"
    )

    print(
        f"Sections: {len(manual.sections)}"
    )