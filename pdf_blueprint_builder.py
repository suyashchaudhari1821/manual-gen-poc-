import json
from collections import Counter
import pymupdf


def build_pdf_blueprint(pdf_path):

    doc = pymupdf.open(pdf_path)

    blueprint = {
        "document": {},
        "pages": [],
        "styles": {},
        "sections": []
    }

    font_counter = Counter()
    size_counter = Counter()

    heading_candidates = []

    for page_number, page in enumerate(doc, start=1):

        page_width = round(page.rect.width, 2)
        page_height = round(page.rect.height, 2)

        text_dict = page.get_text("dict")

        page_info = {
            "page_number": page_number,
            "width": page_width,
            "height": page_height,
            "margins": {},
            "header_blocks": [],
            "footer_blocks": [],
            "images": [],
            "text_blocks": []
        }

        min_x = page_width
        max_x = 0

        for block in text_dict["blocks"]:

            # IMAGE BLOCK
            if block.get("type") == 1:

                page_info["images"].append({
                    "bbox": block.get("bbox")
                })

                continue

            if "lines" not in block:
                continue

            block_text = []

            block_fonts = Counter()

            bx0 = None
            by0 = None
            bx1 = None
            by1 = None

            for line in block["lines"]:

                for span in line["spans"]:

                    text = span["text"].strip()

                    if not text:
                        continue

                    font = span["font"]
                    size = round(span["size"], 1)

                    font_counter[font] += 1
                    size_counter[size] += 1

                    block_fonts[f"{font}_{size}"] += 1

                    x0, y0, x1, y1 = span["bbox"]

                    min_x = min(min_x, x0)
                    max_x = max(max_x, x1)

                    if bx0 is None:
                        bx0, by0, bx1, by1 = x0, y0, x1, y1
                    else:
                        bx0 = min(bx0, x0)
                        by0 = min(by0, y0)
                        bx1 = max(bx1, x1)
                        by1 = max(by1, y1)

                    block_text.append(text)

                    heading_candidates.append({
                        "page": page_number,
                        "text": text,
                        "font": font,
                        "size": size,
                        "bbox": span["bbox"]
                    })

            if not block_text:
                continue

            block_entry = {
                "text": " ".join(block_text),
                "bbox": [
                    round(bx0, 2),
                    round(by0, 2),
                    round(bx1, 2),
                    round(by1, 2)
                ],
                "fonts": dict(block_fonts)
            }

            page_info["text_blocks"].append(block_entry)

            # Header area
            if by0 < page_height * 0.10:
                page_info["header_blocks"].append(block_entry)

            # Footer area
            if by1 > page_height * 0.90:
                page_info["footer_blocks"].append(block_entry)

        page_info["margins"] = {
            "left": round(min_x, 2),
            "right": round(page_width - max_x, 2)
        }

        blueprint["pages"].append(page_info)

    body_size = size_counter.most_common(1)[0][0]

    headings = []

    for element in heading_candidates:

        if element["size"] > body_size:

            headings.append({
                "page": element["page"],
                "title": element["text"],
                "font": element["font"],
                "size": element["size"]
            })

    blueprint["document"] = {
        "page_count": len(doc),
        "page_width": blueprint["pages"][0]["width"],
        "page_height": blueprint["pages"][0]["height"]
    }

    blueprint["styles"] = {
        "primary_font": font_counter.most_common(1)[0][0],
        "primary_size": body_size,
        "fonts_found": dict(font_counter),
        "sizes_found": dict(size_counter)
    }

    blueprint["sections"] = headings

    return blueprint


def save_blueprint(blueprint, filename):

    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            blueprint,
            f,
            indent=4
        )

    print(f"\nBlueprint saved: {filename}")


if __name__ == "__main__":

    pdf_file = (
        r"C:\Users\pgavhane\OneDrive - Expleo France"
        r"\Documents\PROJECT\ExpleoBot_Proposal_Updated (1).pdf"
    )

    blueprint = build_pdf_blueprint(pdf_file)

    save_blueprint(
        blueprint,
        "pdf_blueprint.json"
    )

    print("\nSUMMARY")
    print("=" * 80)

    print(
        "Pages:",
        blueprint["document"]["page_count"]
    )

    print(
        "Primary Font:",
        blueprint["styles"]["primary_font"]
    )

    print(
        "Primary Size:",
        blueprint["styles"]["primary_size"]
    )

    print(
        "Sections Found:",
        len(blueprint["sections"])
    )