try:
    from langchain_ollama import ChatOllama
except ImportError:
    ChatOllama = None
import torch
import open_clip
import numpy as np
import faiss
from PIL import Image
from manual_parser import parse_manual
from sentence_transformers import SentenceTransformer
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Literal
from langchain_core.documents import Document
from typing import List, TypedDict, Literal
from pydantic import BaseModel, Field
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langgraph.graph import StateGraph, START, END
import re
import streamlit as st
import json
try:
    from transformers import pipeline 
    from langchain_huggingface import (
        ChatHuggingFace,
        HuggingFacePipeline
    )
except ImportError:
    pipeline = None
    ChatHuggingFace = None
    HuggingFacePipeline = None
from rag_pipeline import (
    search_text_chunks,
    search_images,
    KnowledgeChunk,
    build_rag_indexes
)


from llm import llm

class State(TypedDict):

    question: str
    need_retrieval: bool

    docs: List[KnowledgeChunk]

    relevant_docs: List[KnowledgeChunk]

    context: str

    issup: Literal["fully_supported", "partially_supported", "no_support"]

    evidence: List[str]

    answer: str

    retries: int

    isuse: Literal["useful", "not_useful"]
    use_reason: str
    retrieval_query: str
    rewrite_tries: int
    chunks: list
    text_index: object
    image_index: object
    image_metadata: list

class RetrieveDecision(BaseModel):
    should_retrieve: bool = Field(
        ...,
        description=(
            "True if external documents are needed "
            "to answer reliably, else False."
        )
    )
decide_retrieval_prompt = PromptTemplate(
    template="""
You are a retrieval decision system.

Determine whether document retrieval is required.

Rules:
- Return TRUE for installation questions.
- Return TRUE for troubleshooting questions.
- Return TRUE for maintenance questions.
- Return TRUE for technical specifications.
- Return TRUE for safety information.
- Return TRUE whenever answering requires information from a manual.

Question:
{question}

Return ONLY valid JSON.

Example:

{{
    "should_retrieve": true
}}

Do not explain.
Do not return a schema.
Do not return markdown.

Only return JSON.
""",
    input_variables=["question"]
)
retrieve_chain = (
    decide_retrieval_prompt
    | llm
)

def decide_retrieval(state: State):

    response = retrieve_chain.invoke(
        {
            "question": state["question"]
        }
    )

    raw_text = response.content

    assistant_part = raw_text.split(
        "<|im_start|>assistant"
    )[-1]

    matches = re.findall(
        r"\{.*?\}",
        assistant_part,
        re.DOTALL
    )

    if not matches:
        raise ValueError(
            "No JSON found."
        )

    json_text = matches[-1]

    data = json.loads(
        json_text
    )

    decision = RetrieveDecision(
        **data
    )

    print(
        "Decision:",
        decision.should_retrieve
    )

    return {
        "need_retrieval":
        decision.should_retrieve
    }
direct_generation_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Answer the question using only your general knowledge.\n"
            "Do NOT assume access to external documents.\n"
            "If you are unsure or the answer requires specific sources, say:\n"
            "'I don't know based on my general knowledge.'"
        ),
        ("human", "{question}"),
    ]
)
def generate_direct(state: State):

    response = llm.invoke(
        direct_generation_prompt.format_messages(
            question=state["question"]
        )
    )

    return {
        "answer":
        response.content
    }
def retrieve(state: State):

    print("ENTERED RETRIEVE")

    query = state.get(
        "retrieval_query",
        state["question"]
    )

    print(
        "RETRIEVAL QUERY:",
        query
    )

    results = search_text_chunks(
        query,
        state["chunks"],
        state["text_index"],
        top_k=5
    )

    print(
        "Retrieved docs:",
        len(results)
    )

    return {
        "docs":
        results
    }
class RelevanceDecision(BaseModel):

    is_relevant: bool = Field(
        ...,
        description=
        "True if the document helps answer the question."
    )
is_relevant_prompt = PromptTemplate(
    template="""
You are a document relevance grader.

Question:
{question}

Document:
{document}

A document is RELEVANT if:
- it contains the answer
- it contains part of the answer
- it contains instructions related to the question
- it contains keywords closely related to the question

A document is NOT RELEVANT if:
- it discusses an unrelated topic
- it contains no information useful for answering the question

Return ONLY valid JSON.

Example:

{{
    "is_relevant": true
}}

Only return JSON.
"""
)
relevance_chain = (
    is_relevant_prompt
    | llm
)
def is_relevant(state: State):
    print("ENTERED IS_RELEVANT")
    
    relevant_docs = []

    for doc in state["docs"]:

        response = relevance_chain.invoke(
    {
        "question": state["question"],
        "document": doc.content
    }
)
        print("\nMODEL RESPONSE:")
        print(response.content)

        raw_text = response.content

        assistant_part = raw_text.split(
            "<|im_start|>assistant"
        )[-1]

        matches = re.findall(
            r"\{.*?\}",
            assistant_part,
            re.DOTALL
        )

        if not matches:
            continue

        json_text = matches[-1]

        data = json.loads(json_text)

        decision = RelevanceDecision(
            **data
        )

        if decision.is_relevant:
            relevant_docs.append(doc)

    print(
        f"Relevant docs: {len(relevant_docs)}"
    )

    return {
        "relevant_docs":
        relevant_docs
    }
rag_generation_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a RAG assistant..\n"
            "Use ONLY the provided context.\n"
            "If the requested content does not exist exactly.\n"
            "but related information exists in the context.\n"
            "generate the requested content from that information."
           " Only return 'No relevant document found."
           "when the context is unrelated to the question."
        ),
        (
            "human",
            "Question:\n{question}\n\n"
            "Context:\n{context}"
        ),
    ]
)
MAX_CONTEXT_CHARS = 12000
def generate_from_context(state: State):

    print("ENTERED GENERATE_FROM_CONTEXT")

    context = "\n\n---\n\n".join(    
        [
            doc.content
            for doc in state.get(
                "relevant_docs",
                []
            )[:3]
        ]
    ).strip()

    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS]

    print("\nCONTEXT PASSED TO GENERATION:")
    print(context)
    

    if not context:
        return {
            "answer": "No relevant document found."
        }

    response = llm.invoke(
        rag_generation_prompt.format_messages(
            question=state["question"],
            context=context
        )
    )

    print("\nGENERATED ANSWER:")
    print(response.content)

    return {
        "answer": response.content,
        "context": context
    }
class IsSUPDecision(BaseModel):

    issup: Literal[
        "fully_supported",
        "partially_supported",
        "no_support"
    ]

    evidence: List[str] = Field(
        default_factory=list
    )
issup_prompt = PromptTemplate(
    template="""
You are verifying whether the answer is supported by the provided context.

Question:
{question}

Answer:
{answer}

Context:
{context}

Return ONLY valid JSON.

Example:

{{
    "issup": "fully_supported",
    "evidence": [
        "quote 1",
        "quote 2"
    ]
}}

Rules:

- fully_supported:
  All claims are supported by context.

- partially_supported:
  Core claims are supported but some statements
  are inferred or not explicitly present.

- no_support:
  Claims are unsupported by context.

Evidence should contain up to 3 short supporting quotes.

Only return JSON.
"""
)
issup_chain = (
    issup_prompt
    | llm
)
def is_sup(state: State):

    print("ENTERED IS_SUP")
    print("\nCONTEXT SENT TO ISSUP:")
    print(state.get("context", "EMPTY"))
    print("\nANSWER:")
    print(state.get("answer", "EMPTY"))

    response = issup_chain.invoke(
        {
            "question":
            state["question"],

            "answer":
            state.get(
                "answer",
                ""
            ),

            "context":
            state.get(
                "context",
                ""
            ),
        }
    )
    print("\nRAW ISSUP RESPONSE:")
    print(response.content)

    print("\nMODEL RESPONSE:")
    print(response.content)

    raw_text = response.content

    assistant_part = raw_text.split(
        "<|im_start|>assistant"
    )[-1]

    matches = re.findall(
        r"\{.*?\}",
        assistant_part,
        re.DOTALL
    )

    if not matches:
        raise ValueError(
            "No JSON returned by IsSUP."
        )

    json_text = matches[-1]

    data = json.loads(
        json_text
    )

    decision = IsSUPDecision(
        **data
    )

    return {
        "issup":
        decision.issup,

        "evidence":
        decision.evidence
    }
revise_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are an answer reviser.

Use ONLY the supplied context.

Rules:
- Keep the answer useful.
- Remove unsupported claims.
- Keep supported information.
- Improve accuracy.
- Do not reduce the answer into quotes only.
- Preserve procedural steps and checklists when present.
"""
        ),
        (
            "human",
            """
Question:
{question}

Current Answer:
{answer}

Context:
{context}
"""
        ),
    ]
)
def no_relevant_docs(state: State):

    print("NO RELEVANT DOCS")

    return {
        "answer": "No relevant document found."
    }
def revise_answer(state: State):

    print("ENTERED REVISE_ANSWER")

    response = llm.invoke(
        revise_prompt.format_messages(
            question=state["question"],
            answer=state.get(
                "answer",
                ""
            ),
            context=state.get(
                "context",
                ""
            ),
        )
    )

    print("\nREVISED ANSWER:")
    print(response.content)

    return {
        "answer":
        response.content,

        "retries":
        state.get(
            "retries",
            0
        ) + 1
    }
def accept_answer(state: State):

    print("ANSWER ACCEPTED")

    return {}

MAX_RETRIES = 2
def route_after_issup(state):

    if state["issup"] in [
        "fully_supported",
        "partially_supported"
    ]:
        return "accept_answer"

    if state.get("retries", 0) >= MAX_RETRIES:
        return "accept_answer"

    return "revise_answer"
class IsUSEDecision(BaseModel):

    isuse: Literal[
        "useful",
        "not_useful"
    ]

    reason: str
isuse_prompt = PromptTemplate(
    template="""
You are an answer usefulness evaluator.

Your task is NOT to check factual grounding.
Grounding has already been verified.

Your task is ONLY to determine whether the answer is useful for the user's question.

Question:
{question}

Answer:
{answer}

Return ONLY valid JSON.

Example:

{{
    "isuse": "useful",
    "reason": "The answer directly explains the requested procedure."
}}

Decision Rules:

Choose "useful" if:
- The answer directly addresses the user's question.
- The answer provides the requested information.
- The answer includes enough detail to be actionable.
- A reasonable user would feel their question was answered.

Choose "not_useful" if:
- The answer is vague.
- The answer is generic.
- The answer only repeats unrelated information.
- The answer provides background but not the requested answer.
- The answer is incomplete.
- The answer avoids the question.
- The answer says information exists but does not provide it.

Examples:

Question:
How do I install the exhaust hose?

Answer:
The manual contains an exhaust hose installation section.

Output:

{{
    "isuse": "not_useful",
    "reason": "Mentions the topic but does not provide the procedure."
}}

Question:
How do I install the exhaust hose?

Answer:
1. Attach the hose inlet.
2. Secure the hose outlet.
3. Install the hose into the window slider kit.

Output:

{{
    "isuse": "useful",
    "reason": "Provides the installation steps requested."
}}

Question:
What are the maintenance steps?

Answer:
The product has many features and components.

Output:

{{
    "isuse": "not_useful",
    "reason": "Does not answer the maintenance question."
}}

Question:
How often should the filter be cleaned?

Answer:
Clean the filter every two weeks during normal operation.

Output:

{{
    "isuse": "useful",
    "reason": "Provides the requested maintenance frequency."
}}

Keep the reason under 15 words.

Return ONLY valid JSON.

Required format:

{{
    "isuse": "useful",
    "reason": "short reason"
}}
"""
)
isuse_chain = (
    isuse_prompt
    | llm
)
def is_use(state: State):

    print("ENTERED IS_USE")

    response = isuse_chain.invoke(
        {
            "question":
            state["question"],

            "answer":
            state.get(
                "answer",
                ""
            )
        }
    )

    print("\nMODEL RESPONSE:")
    print(response.content)

    raw_text = response.content

    matches = re.findall(
        r"\{.*?\}",
        raw_text,
        re.DOTALL
    )

    if not matches:
        raise ValueError(
            "No JSON returned."
        )

    json_text = matches[-1]

    data = json.loads(
        json_text
    )

    decision = IsUSEDecision(
        **data
    )

    return {
        "isuse":
        decision.isuse,

        "use_reason":
        decision.reason
    }
class RewriteDecision(BaseModel):

    retrieval_query: str
rewrite_prompt = PromptTemplate(
    template="""
Rewrite the user's question into a better query for vector retrieval.

Question:
{question}

Previous Retrieval Query:
{retrieval_query}

Current Answer:
{answer}

Return ONLY JSON.

Example:

{{
    "retrieval_query":
    "exhaust hose installation procedure hose inlet hose outlet"
}}

Rules:

- Keep query short.
- Preserve important keywords.
- Add retrieval-friendly terms.
- Do not answer the question.
- Return ONLY JSON.
"""
)
rewrite_chain = (
    rewrite_prompt
    | llm
)

def rewrite_question(state: State):

    print("ENTERED REWRITE_QUESTION")

    response = rewrite_chain.invoke(
        {
            "question":
                state["question"],

            "retrieval_query":
                state.get(
                    "retrieval_query",
                    ""
                ),

            "answer":
                state.get(
                    "answer",
                    ""
                )
        }
    )

    print("\nMODEL RESPONSE:")
    print(response.content)

    raw_text = response.content

    matches = re.findall(
        r"\{.*?\}",
        raw_text,
        re.DOTALL
    )

    if not matches:
        raise ValueError(
            "No JSON returned by Rewrite."
        )

    json_text = matches[-1]

    data = json.loads(
        json_text
    )

    decision = RewriteDecision(
        **data
    )

    return {

        "retrieval_query":
            decision.retrieval_query,

        "rewrite_tries":
            state.get(
                "rewrite_tries",
                0
            ) + 1,

        "docs": [],
        "relevant_docs": [],
        "context": ""
    }
def route_after_decide(state: State) -> Literal["generate_direct", "retrieve"]:
    if state["need_retrieval"]:
        return "retrieve"
    return "generate_direct"
def route_after_relevance(state):

    if len(state.get("relevant_docs", [])) > 0:
        return "generate_from_context"

    # No relevant docs found
    if state.get("rewrite_tries", 0) >= MAX_REWRITE_TRIES:
        return "no_relevant_docs"

    return "rewrite_question"
MAX_REWRITE_TRIES = 2

def route_after_isuse(state: State):

    if (
        state.get("isuse")
        ==
        "useful"
    ):
        return "END"

    if (
        state.get(
            "rewrite_tries",
            0
        )
        >=
        MAX_REWRITE_TRIES
    ):
        return  "no_relevant_docs"

    return "rewrite_question"


g = StateGraph(State)

# --------------------
# Nodes
# --------------------
g.add_node("decide_retrieval", decide_retrieval)
g.add_node("generate_direct", generate_direct)
g.add_node("retrieve", retrieve)
g.add_node("is_relevant",is_relevant)
g.add_node("generate_from_context",generate_from_context)
g.add_node("no_relevant_docs", no_relevant_docs)
g.add_node("is_sup",is_sup)
g.add_node( "accept_answer",accept_answer)
g.add_node("revise_answer",revise_answer)
g.add_node("is_use", is_use)
g.add_node("rewrite_question", rewrite_question)

# --------------------
# Edges
# --------------------
g.add_edge(START, "decide_retrieval")
g.add_conditional_edges( "decide_retrieval", route_after_decide,
    {
        "generate_direct": "generate_direct",
        "retrieve": "retrieve",
    },
)
g.add_edge("generate_direct", END)
g.add_edge( "retrieve", "is_relevant")
g.add_conditional_edges(
    "is_relevant",
    route_after_relevance,
    {
        "generate_from_context":
            "generate_from_context",

        "rewrite_question":
            "rewrite_question",

        "no_relevant_docs":
            "no_relevant_docs",
    }
)
g.add_conditional_edges(
    "is_sup",
    route_after_issup,
    {
        "accept_answer":
            "accept_answer",

        "revise_answer":
            "revise_answer",
    }
)
g.add_edge(
    "revise_answer",
    "is_sup"
)
g.add_edge(
    "accept_answer",
    "is_use"
)
g.add_edge("generate_from_context","is_sup")
g.add_edge("no_relevant_docs", END)
g.add_edge("rewrite_question","retrieve")
g.add_conditional_edges(
    "is_use",
    route_after_isuse,
    {
        "END":
            END,

        "rewrite_question":
            "rewrite_question",

        "no_relevant_docs":
            "no_relevant_docs",
    }
)
app = g.compile()


def run_self_rag(
    question: str,
    chunks,
    text_index,
    image_index=None,
    image_metadata=None
):

    print(
        "TOTAL CHUNKS:",
        len(chunks)
    )

    final_state = app.invoke(
        {
            "question": question,

            "retrieval_query": question,

            "rewrite_tries": 0,

            "retries": 0,

            "chunks": chunks,

            "text_index": text_index,

            "image_index": image_index,

            "image_metadata": image_metadata,
        }
    )
    result = {
        "chunks": chunks,
        "retrieved_docs": final_state.get("docs", []),
        "relevant_docs": final_state.get("relevant_docs", []),
        "context": final_state.get("context", ""),
        "answer": final_state.get("answer", ""),
        "issup": final_state.get("issup", ""),
        "evidence": final_state.get("evidence", []),
        "isuse": final_state.get("isuse", ""),
        "use_reason": final_state.get("use_reason", "")
}
    

    return result




if __name__ == "__main__":

    try:

        png = (
            app.get_graph()
            .draw_mermaid_png()
        )

        with open(
            "step1_graph.png",
            "wb"
        ) as f:

            f.write(png)

        print(
            "Graph image saved."
        )

    except Exception as e:

        print(
            "Graph image error:",
            e
        )

    result = run_self_rag(
        "What is the exhaust hose installation procedure?"
    )

    print(
        result["answer"]
    )
