import pymupdf
import fitz
import os
from docx import Document
from manual_models import (
    ManualDocument,
    ManualMetadata,
    TextBlock,
    ImageBlock,
    TableBlock,
)
def parse_manual(file_path):

    if file_path.lower().endswith(".pdf"):
        return parse_pdf_manual(file_path)

    elif file_path.lower().endswith(".docx"):
        return parse_docx_manual(file_path)

    else:
        raise ValueError(
            f"Unsupported file type: {file_path}"
        )
import re
from docx import Document


def is_heading_text(text: str, style_name: str = "") -> bool:
    """
    Generic heading detection for DOCX files.
    """

    text = text.strip()

    if not text:
        return False

    score = 0

    style = style_name.lower()

    # Strong signal: Word heading styles
    if style.startswith("heading"):
        score += 10

    if style == "title":
        score += 10

    # Numbered headings
    # Examples:
    # 7. Header Settings
    # 7.1 Reel Height Adjustment
    if (
    re.match(r"^\d+(\.\d+)*\.?\s+[A-Za-z]", text)
    and len(text.split()) <= 8
):
        score += 4

    # ALL CAPS headings
    # Examples:
    # PREFACE
    # WARRANTY
    if text.isupper():
        score += 4

    word_count = len(text.split())

    # Headings are usually short
    if word_count <= 8:
        score += 2

    # Headings rarely end with punctuation
    if not text.endswith((".", ";", "!", "?")):
        score += 1

    # Reasonable heading length
    if len(text) <= 80:
        score += 1

    # Penalize obvious paragraphs
    if word_count > 15:
        score -= 10

    return score >= 4


def parse_docx_manual(docx_path):

    doc = Document(docx_path)

    text_blocks = []

    counter = 1
    page_no = 1

    for para in doc.paragraphs:

        text = para.text.strip()

        if not text:
            continue

        style_name = (
            para.style.name
            if para.style
            else ""
        )

        heading = is_heading_text(
            text=text,
            style_name=style_name
        )

        print(
            f"TEXT={text[:80]}"
            f" | STYLE={style_name}"
            f" | HEADING={heading}"
        )

        text_blocks.append(
            TextBlock(
                block_id=f"TXT_{counter}",
                page_number=page_no,

                block_type=(
                    "heading"
                    if heading
                    else "paragraph"
                ),

                level=(
                    1
                    if heading
                    else 0
                ),

                text=text
            )
        )

        counter += 1

    return ManualDocument(
        metadata=ManualMetadata(
            title=docx_path.split("\\")[-1],
            source_file=docx_path,
            total_pages=1
        ),

        text_blocks=text_blocks,
        image_blocks=[],
        table_blocks=[]
    )

def block_type_and_level(font_size):

    if font_size >= 16:
        return "heading", 1

    elif font_size >= 14:
        return "heading", 2

    return "paragraph", 0


def extract_images(doc, page, page_number):

    images = []

    image_list = page.get_images(full=True)

    image_dir = "extracted_images"

    os.makedirs(image_dir, exist_ok=True)

    for idx, image in enumerate(image_list):

        xref = image[0]

        image_info = doc.extract_image(xref)

        image_bytes = image_info["image"]

        image_ext = image_info["ext"]

        filename = (
            f"P{page_number}_IMG{idx + 1}.{image_ext}"
        )

        image_path = os.path.join(
            image_dir,
            filename
        )

        with open(image_path, "wb") as img_file:
            img_file.write(image_bytes)

        images.append(
            ImageBlock(
                block_id=f"P{page_number}_IMG{idx + 1}",
                page_number=page_number,
                caption=None,
                image_path=image_path,
            )
        )

    return images


def looks_like_table(text):

    text_upper = text.upper()

    table_keywords = [
        "SPECIFICATION",
        "POSSIBLE CAUSE",
        "POSSIBLE REMEDY",
        "PART NUMBER",
        "MODEL",
        "TROUBLE",
        "DIMENSION",
        "WEIGHT",
        "TECHNOLOGY",
        "PURPOSE",
        "COMPONENT",
        "FRAMEWORK",
        "MATERIAL",
    ]

    return any(
        keyword in text_upper
        for keyword in table_keywords
    )


def parse_pdf_manual(pdf_path):

    doc = pymupdf.open(pdf_path)

    text_blocks = []
    image_blocks = []
    table_blocks = []

    text_counter = 1
    table_counter = 1

    for page_no, page in enumerate(doc, start=1):

        # -----------------------------
        # Images
        # -----------------------------
        image_blocks.extend(
            extract_images(doc,page, page_no)
        )

        # -----------------------------
        # Text Blocks
        # -----------------------------
        text_dict = page.get_text("dict")

        for block in text_dict["blocks"]:

            if "lines" not in block:
                continue

            block_lines = []

            first_font_size = None

            for line in block["lines"]:

                line_parts = []

                for span in line["spans"]:

                    text = span["text"].strip()

                    if not text:
                        continue

                    # Ignore standalone bullets
                    if text in ["•", "-", "*"]:
                        continue

                    if first_font_size is None:
                        first_font_size = span.get(
                            "size",
                            0,
                        )

                    line_parts.append(text)

                if line_parts:

                    block_lines.append(
                        " ".join(line_parts)
                    )

            if not block_lines:
                continue

            combined_text = "\n".join(
                block_lines
            ).strip()

            if not combined_text:
                continue

            block_type, level = (
                block_type_and_level(
                    first_font_size or 0
                )
            )

            text_blocks.append(
                TextBlock(
                    block_id=f"TXT_{text_counter}",
                    page_number=page_no,
                    block_type=block_type,
                    level=level,
                text=combined_text,
                )
            )

            text_counter += 1

            # -----------------------------
            # Table Detection
            # -----------------------------
            if looks_like_table(combined_text):

                table_blocks.append(
                    TableBlock(
                        block_id=f"TBL_{table_counter}",
                        page_number=page_no,
                        table_text=combined_text,
                    )
                )

                table_counter += 1

    return ManualDocument(
        metadata=ManualMetadata(
            title=pdf_path.split("\\")[-1],
            source_file=pdf_path,
            total_pages=len(doc),
        ),
        text_blocks=text_blocks,
        image_blocks=image_blocks,
        table_blocks=table_blocks,
    )