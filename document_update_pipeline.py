from html_pipeline import (
    pdf_to_html,
    extract_doc_profile,
    html_to_pdf,
    update_toc,
)

from self_rag import run_self_rag
from placement_model import determine_placement

from bs4 import BeautifulSoup


def inject_generated_content(
    html: str,
    content: str,
    placement
):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    new_section = BeautifulSoup(
        f"""
        <div class="injected-page" id="generated-section">
            <h1>Generated Section</h1>
            <p>{content}</p>
        </div>
        """,
        "html.parser"
    )

    target_title = placement.target_section

    for page in soup.find_all(
        class_="pdf-page"
    ):

        text = page.get_text(
            " ",
            strip=True
        ).lower()

        if (
            target_title.lower()
            in text
        ):

            page.insert_after(
                new_section
            )

            return str(soup)

    body = soup.find("body")

    body.append(
        new_section
    )

    return str(soup)


def update_manual(
    pdf_path,
    requirement,
    structured_document,
    output_pdf
):

    html = pdf_to_html(
        pdf_path
    )

    profile = extract_doc_profile(
        html
    )

    rag_result = run_self_rag(
        question=requirement
    )

    generated_content = (
        rag_result["answer"]
    )

    placement = determine_placement(
        requirement=requirement,
        structured_document=structured_document
    )

    updated_html = inject_generated_content(
        html,
        generated_content,
        placement
    )

    updated_html = update_toc(
        updated_html,
        "Generated Section",
        999
    )

    success, engine = html_to_pdf(
        updated_html,
        output_pdf
    )

    return {
        "success": success,
        "engine": engine,
        "placement": placement,
        "generated_content": generated_content
    }