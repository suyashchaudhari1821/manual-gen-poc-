from langchain_groq import ChatGroq
llm = ChatGroq(
    model="qwen/qwen3.8-27b",
    api_key="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",
    temperature=0,
    max_tokens=400
)
#openai/gpt-oss-20b qwen/qwen3-8b-27b