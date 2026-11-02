import json

from pydantic import BaseModel
from langchain_core.prompts import ChatPromptTemplate

from llm import llm


class QueryIntent(BaseModel):

    intent: str

    generated_title: str | None = None

    placement_type: str | None = None

    target_section: str | None = None

    retrieval_query: str | None = None


intent_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a Document Intent Extraction Assistant.

Analyze the user's request and extract structured intent.

Your job is ONLY to understand the user's request.

DO NOT generate content.
DO NOT answer the request.
DO NOT decide final placement.

Extract:

1. intent
2. generated_title
3. placement_type
4. target_section
5. retrieval_query

Supported intents:

1. qa
   User is asking a question.

2. generate_section
   User is asking for generation of new content.

3. insert_section
   User is asking for generation of new content
   and explicitly specifies an insertion location.

placement_type can be:

- after
- before
- append
- null

target_section:

- Section explicitly mentioned by user
- If no section is mentioned, return null

generated_title:

- Short title describing requested content
- Only applicable for generate/insert requests

retrieval_query:

- A concise search query representing the topic
- This will be used by the retrieval pipeline
- Works for BOTH qa and generation requests

Return ONLY JSON.

Examples:

User:
Generate a summary of the recent findings and insert it after Background.

Output:
{{
  "intent":"insert_section",
  "generated_title":"Summary of Recent Findings",
  "placement_type":"after",
  "target_section":"Background",
  "retrieval_query":"recent findings summary"
}}

User:
Create a comparison checklist.

Output:
{{
  "intent":"generate_section",
  "generated_title":"Comparison Checklist",
  "placement_type":null,
  "target_section":null,
  "retrieval_query":"comparison checklist"
}}

User:
What are the key advantages of this approach?

Output:
{{
  "intent":"qa",
  "generated_title":null,
  "placement_type":null,
  "target_section":null,
  "retrieval_query":"key advantages"
}}

User:
Explain the main challenges involved.

Output:
{{
  "intent":"qa",
  "generated_title":null,
  "placement_type":null,
  "target_section":null,
  "retrieval_query":"main challenges"
}}

User:
Generate recommendations and place them before Conclusion.

Output:
{{
  "intent":"insert_section",
  "generated_title":"Recommendations",
  "placement_type":"before",
  "target_section":"Conclusion",
  "retrieval_query":"recommendations"
}}
"""
        ),
        (
            "human",
            "{query}"
        ),
    ]
)


def extract_query_intent(
    query: str
) -> QueryIntent:

    response = llm.invoke(
        intent_prompt.format_messages(
            query=query
        )
    )

    try:

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

        return QueryIntent(
            **data
        )

    except Exception as e:
        print("\nERROR:")
        raise
