from pydantic import BaseModel

from llm import llm

from langchain_core.prompts import ChatPromptTemplate


class Placement(BaseModel):

    action: str

    target_section: str | None

    generated_title: str


placement_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a document placement assistant.

The user has requested generation of a new document section.

Your job is to determine the BEST insertion location
based on the available document sections.

Return ONLY JSON.

Format:

{{
    "action": "insert_after",
    "target_section": "Section Name",
    "generated_title": "Generated Title"
}}
"""
        ),
        (
            "human",
            """
Generated Title:
{generated_title}

Available Sections:
{sections}
"""
        )
    ]
)
import json


def determine_placement(
    intent,
    structured_document
):

    print("\nINTENT RECEIVED")
    print(intent)

    # ----------------------------------
    # Explicit placement from user
    # ----------------------------------

    if intent.target_section:

        if intent.placement_type == "after":

            return Placement(
                action="insert_after",
                target_section=intent.target_section,
                generated_title=intent.generated_title
            )

        if intent.placement_type == "before":

            return Placement(
                action="insert_before",
                target_section=intent.target_section,
                generated_title=intent.generated_title
            )

        if intent.placement_type == "append":

            return Placement(
                action="append",
                target_section=None,
                generated_title=intent.generated_title
            )

    # ----------------------------------
    # No location provided
    # Let LLM determine best section
    # ----------------------------------

    sections_text = "\n".join(
        [
            section.title
            for section in structured_document.sections
        ]
    )

    response = llm.invoke(
        placement_prompt.format_messages(
            generated_title=intent.generated_title,
            sections=sections_text
        )
    )

    raw = response.content.strip()

    raw = raw.replace(
        "```json",
        ""
    )

    raw = raw.replace(
        "```",
        ""
    )

    data = json.loads(raw)

    return Placement(
        **data
    )
