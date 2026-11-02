import torch
import open_clip
import numpy as np
import faiss
from PIL import Image
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
from langchain_core.prompts import ChatPromptTemplate

from langgraph.graph import StateGraph, START, END
class KnowledgeChunk(BaseModel):



    chunk_id: str



    title: str



    source_type: str



    page_number: int



    content: str



    text_block_ids: List[str] = Field(default_factory=list)



    image_block_ids: List[str] = Field(default_factory=list)



    image_paths: List[str] = Field(default_factory=list)



    table_block_ids: List[str] = Field(default_factory=list)



    metadata: Dict[str, Any] = Field(default_factory=dict)




def build_chunks(document) -> List[KnowledgeChunk]:
    """
    Generic chunk builder.



    Expected document structure:



        document.text_blocks
        document.image_blocks
        document.table_blocks



    Each text block should contain:



        block_id
        page_number
        block_type
        text
    """



    chunks: List[KnowledgeChunk] = []



    current_chunk = None



    chunk_counter = 1



    source_type = document.__class__.__name__



    for block in document.text_blocks:



        #
        # Start of new section
        #
        if block.block_type.lower() == "heading":



            if current_chunk is not None:
                chunks.append(current_chunk)



            current_chunk = KnowledgeChunk(
                chunk_id=f"CHUNK_{chunk_counter}",
                title=block.text.strip(),
                source_type=source_type,
                page_number=block.page_number,
                content=block.text.strip(),
                text_block_ids=[block.block_id],
            )



            chunk_counter += 1



            continue



        #
        # Handle documents that begin without heading
        #
        if current_chunk is None:



            current_chunk = KnowledgeChunk(
                chunk_id=f"CHUNK_{chunk_counter}",
                title="INTRODUCTION",
                source_type=source_type,
                page_number=block.page_number,
                content="",
            )



            chunk_counter += 1



        current_chunk.content += "\n\n" + block.text.strip()



        current_chunk.text_block_ids.append(
            block.block_id
        )



    if current_chunk is not None:
        chunks.append(current_chunk)



    #
    # Attach images by page
    #
    for image_block in document.image_blocks:



        for chunk in chunks:



            if chunk.page_number == image_block.page_number:



                chunk.image_block_ids.append(
                  image_block.block_id
            )



                if image_block.image_path:



                    chunk.image_paths.append(
                      image_block.image_path
                )



    #
    # Attach tables by page
    #
    for table_block in document.table_blocks:



        for chunk in chunks:



            if chunk.page_number == table_block.page_number:



                chunk.table_block_ids.append(
                    table_block.block_id
                )



    return chunks



def chunks_to_documents(
    chunks: List[KnowledgeChunk]
) -> List[Document]:



    documents = []



    for chunk in chunks:



        doc = Document(



            page_content=chunk.content,



            metadata={



                "chunk_id":
                    chunk.chunk_id,



                "title":
                    chunk.title,



                "source_type":
                    chunk.source_type,



                "page_number":
                    chunk.page_number,



                "image_block_ids":
                    chunk.image_block_ids,
                "image_paths":
                    chunk.image_paths,



                "table_block_ids":
                    chunk.table_block_ids,
            }
        )



        documents.append(doc)



    return documents



from langchain_text_splitters import (
    RecursiveCharacterTextSplitter
)
splitter = RecursiveCharacterTextSplitter(



    chunk_size=1200,



    chunk_overlap=200,
)
def split_documents(documents):



    return splitter.split_documents(
        documents
    ) 

# -------------------------
# OpenCLIP
# -------------------------

MODEL_NAME = "ViT-B-32"
PRETRAINED = "laion2b_s34b_b79k"

device = "cuda" if torch.cuda.is_available() else "cpu"

clip_model, _, preprocess = open_clip.create_model_and_transforms(
    MODEL_NAME,
    pretrained=PRETRAINED
)

clip_model = clip_model.to(device)

clip_tokenizer = open_clip.get_tokenizer(
    MODEL_NAME
)

# -------------------------
# MiniLM
# -------------------------

text_model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)
def embed_text(text: str):

    embedding = text_model.encode(
        text,
        normalize_embeddings=True
    )

    return embedding
def embed_image(image_path: str):

    image = preprocess(
        Image.open(image_path)
    ).unsqueeze(0).to(device)

    with torch.no_grad():

        image_features = clip_model.encode_image(
            image
        )

        image_features /= image_features.norm(
            dim=-1,
            keepdim=True
        )

    return image_features.cpu().numpy()[0]
def embed_clip_query(query: str):

    tokens = clip_tokenizer(
        [query]
    ).to(device)

    with torch.no_grad():

        text_features = clip_model.encode_text(
            tokens
        )

        text_features /= text_features.norm(
            dim=-1,
            keepdim=True
        )

    return text_features.cpu().numpy()[0]
def build_text_index(chunks):

    text_embeddings = []

    for chunk in chunks:

        vector = embed_text(
            chunk.content
        )

        text_embeddings.append(
            vector
        )

    embedding_matrix = np.array(
        text_embeddings
    ).astype("float32")

    dimension = embedding_matrix.shape[1]

    text_index = faiss.IndexFlatIP(
        dimension
    )

    text_index.add(
        embedding_matrix
    )

    return text_index
def search_text_chunks(
    query,
    chunks,
    text_index,
    top_k=5
):

    query_vector = embed_text(
        query
    )

    query_vector = np.array(
        [query_vector]
    ).astype("float32")

    scores, indices = text_index.search(
        query_vector,
        top_k
    )

    results = []

    for idx in indices[0]:

        results.append(
            chunks[idx]
        )

    return results
def build_image_index(chunks):

    image_embeddings = []

    image_metadata = []

    for chunk in chunks:

        for image_path in chunk.image_paths:

            try:

                vector = embed_image(
                    image_path
                )

                image_embeddings.append(
                    vector
                )

                image_metadata.append(
                    {
                        "chunk_id": chunk.chunk_id,
                        "title": chunk.title,
                        "image_path": image_path,
                        "page_number": chunk.page_number
                    }
                )

            except Exception as e:

                print(
                    f"Failed image {image_path}: {e}"
                )

    if len(image_embeddings) == 0:

        return None, []

    embedding_matrix = np.array(
        image_embeddings
    ).astype("float32")

    dimension = embedding_matrix.shape[1]

    image_index = faiss.IndexFlatIP(
        dimension
    )

    image_index.add(
        embedding_matrix
    )

    return image_index, image_metadata
def search_images(
    query,
    image_index,
    image_metadata,
    top_k=5
):

    query_vector = embed_clip_query(
        query
    )

    query_vector = np.array(
        [query_vector]
    ).astype("float32")

    scores, indices = image_index.search(
        query_vector,
        top_k
    )

    results = []

    for idx in indices[0]:

        results.append(
            image_metadata[idx]
        )

    return results
"""
from manual_parser import parse_manual
pdf_path = r"temp_AC Manual.pdf"

document = parse_manual(
    pdf_path
)

chunks = build_chunks(
    document
)

print(
    f"Total Chunks: {len(chunks)}"
)
text_index = build_text_index(
    chunks
)

image_index, image_metadata = (
    build_image_index(
        chunks
    )
)
query = "How do I install the window slider kit?"

text_results = search_text_chunks(
    query,
    chunks,
    text_index,
    top_k=5
)

image_results = search_images(
    query,
    image_index,
    image_metadata,
    top_k=5
)
print("\nTEXT RESULTS\n")

for chunk in text_results:

    print("=" * 80)

    print(chunk.title)

    print(chunk.content[:500])

    print(chunk.image_paths)
print("\nIMAGE RESULTS\n")

for image in image_results:

    print("=" * 80)

    print(image["title"])

    print(image["image_path"]) """

def build_rag_indexes(manual_doc):

    chunks = build_chunks(
        manual_doc
    )

    text_index = build_text_index(
        chunks
    )

    image_index, image_metadata = (
        build_image_index(
            chunks
        )
    )

    return (
        chunks,
        text_index,
        image_index,
        image_metadata
    )
