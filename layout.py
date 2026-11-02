import pymupdf

pdf_path=r"C:\Users\pgavhane\OneDrive - Expleo France\Documents\PROJECT\ExpleoBot_Proposal_Updated (1).pdf"

pdf = pymupdf.open(pdf_path)

for page_no, page in enumerate(pdf):

    print(f"\nPAGE {page_no + 1}")

    print("Width :", page.rect.width)

    print("Height:", page.rect.height)

    blocks = page.get_text("blocks")

    for block in blocks[:10]:

        print(block)