from pydantic import BaseModel,Field
from typing import List, Optional


class ManualMetadata(BaseModel):
    title: str
    source_file: str
    total_pages: int


class TextBlock(BaseModel):
    block_id: str
    page_number: int
    block_type: str      # heading / paragraph
    level: int
    text: str


class ImageBlock(BaseModel):
    block_id: str
    page_number: int
    caption: Optional[str] = None
    image_path: Optional[str] = None


class TableBlock(BaseModel):
    block_id: str
    page_number: int
    table_text: str


class ManualDocument(BaseModel):
    metadata: ManualMetadata

    text_blocks: List[TextBlock] = []

    image_blocks: List[ImageBlock] = []

    table_blocks: List[TableBlock] = []

class DocumentSection(BaseModel):
    section_id: str
    title: str
    level: int
    start_page: int
    end_page: int

    text_blocks: List[TextBlock] = Field(
        default_factory=list
    )

    image_blocks: List[ImageBlock] = Field(
        default_factory=list
    )

    table_blocks: List[TableBlock] = Field(
        default_factory=list
    )
class StructuredDocument(BaseModel):
      metadata: ManualMetadata
      sections: List[DocumentSection] = Field(
default_factory=list
)
class GeneratedSection(DocumentSection):

    source: str = "LLM"

    generated_from_query: str = ""