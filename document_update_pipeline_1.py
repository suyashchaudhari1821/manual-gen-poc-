import fitz
from collections import Counter
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
   
)

from reportlab.lib.styles import (
ParagraphStyle,
)
from pdf_blueprint_builder import (
build_pdf_blueprint
)




def find_insertion_page(
    structured_document,
    target_section
):

    if target_section is None:
        return None

    for section in structured_document.sections:

        print(
            f"Comparing '{section.title}' "
            f"with '{target_section}'"
        )

        if (
            section.title.strip().lower()
            ==
            target_section.strip().lower()
        ):
            return section.end_page

    return None


def create_generated_section_pdf(
    title,
    image_path,
    content,
    blueprint,
    output_pdf="generated_section.pdf"
):
    """
    Creates a PDF section using the
    formatting extracted from the
    original PDF blueprint.
    """
    
    blueprint 
    pdf_styles = blueprint["styles"]

    first_page = blueprint["pages"][0]

    page_width = first_page["width"]
    page_height = first_page["height"]

    left_margin = first_page["margins"]["left"]
    right_margin = first_page["margins"]["right"]

    body_size = pdf_styles["primary_size"]
    heading_sizes = [
        sec["size"]
        for sec in blueprint["sections"]
]

    if heading_sizes:
        heading_size = Counter(
            heading_sizes
        ).most_common(1)[0][0]
    else:
         heading_size = body_size + 2
    print("\nSTYLE INFO")
    print("Body Size:", body_size)
    print("Heading Size:", heading_size)
    print("Page Width:", page_width)
    print("Page Height:", page_height)
    print("Left Margin:", left_margin)
    print("Right Margin:", right_margin)
    body_style = ParagraphStyle(
        name="Body",
        fontName="Times-Roman",
        fontSize=body_size,
        leading=body_size + 2,
    )

    heading_style = ParagraphStyle(
        name="Heading",
        fontName="Times-Bold",
        fontSize=heading_size,
        leading=heading_size + 4,
    )

    doc = SimpleDocTemplate(
        output_pdf,
        pagesize=(
            page_width,
            page_height,
        ),
        leftMargin=left_margin,
        rightMargin=right_margin,
        topMargin=72,
        bottomMargin=72,
    )

    story = []

    story.append(
        Paragraph(
            title,
            heading_style,
        )
    )

    story.append(
        Spacer(1, 12)
    )

    paragraphs = content.split("\n")

    for para in paragraphs:

        para = para.strip()

        if not para:
            continue

        story.append(
            Paragraph(
                para.replace(
                    "\n",
                    "<br/>"
                ),
                body_style,
            )
        )

        story.append(
            Spacer(1, 6)
        )

    doc.build(story)

    print(
        f"Generated section PDF created: {output_pdf}"
    )

    return output_pdf
def insert_generated_pdf(
    original_pdf,
    generated_pdf,
    insert_after_page,
    output_pdf
):
    """
    Insert generated PDF pages after a specific page.
    If insert_after_page is None, append to end.
    """

    original = fitz.open(original_pdf)
    generated = fitz.open(generated_pdf)

    result = fitz.open()

    # -----------------------------
    # APPEND TO END
    # -----------------------------
    if insert_after_page is None:

        print(
            "APPEND MODE: Adding generated section to end of document"
        )

        result.insert_pdf(original)
        result.insert_pdf(generated)

    # -----------------------------
    # INSERT AFTER PAGE
    # -----------------------------
    else:

        print(
            f"INSERT MODE: After page {insert_after_page}"
        )

        for page_no in range(insert_after_page):

            result.insert_pdf(
                original,
                from_page=page_no,
                to_page=page_no
            )

        result.insert_pdf(
            generated
        )

        for page_no in range(
            insert_after_page,
            len(original)
        ):

            result.insert_pdf(
                original,
                from_page=page_no,
                to_page=page_no
            )

    result.save(output_pdf)

    result.close()
    original.close()
    generated.close()

    return output_pdf