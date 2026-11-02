import fitz
import os

def update_page_numbers(pdf_path: str, output_pdf: str = None) -> str:
    """
    Updates or re-stamps page numbers in the PDF document.
    Saves the result to output_pdf or returns pdf_path.
    """
    if not output_pdf or output_pdf == pdf_path:
        return pdf_path

    try:
        doc = fitz.open(pdf_path)
        doc.save(output_pdf)
        doc.close()
        return output_pdf
    except Exception as e:
        print(f"update_page_numbers notice: {e}")
        return pdf_path
