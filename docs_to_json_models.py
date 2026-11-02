from pydantic import BaseModel
from typing import List, Optional


class ManualImage(BaseModel):
    image_id: str
    filename: Optional[str] = None


class ManualTable(BaseModel):
    table_id: str
    rows: List[List[str]]


class ManualParagraph(BaseModel):
    text: str
    style: str


class ManualSection(BaseModel):
    section_id: str
    title: str
    style: str
    content: List[ManualParagraph]
    images: List[ManualImage]
    tables: List[ManualTable]


class ManualMetadata(BaseModel):
    title: str
    source_file: str


class ManualDocument(BaseModel):
    metadata: ManualMetadata
    sections: List[ManualSection]