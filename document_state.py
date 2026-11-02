# document_state.py

from pydantic import BaseModel
from typing import Optional
from pydantic import Field
from datetime import datetime


class GeneratedSection(BaseModel):
    title: str
    content: str

    placement_action: str
    target_section: Optional[str] = None

    image_path: Optional[str] = None
    image_caption: Optional[str] = None


class DocumentState(BaseModel):

    document_thread_id: str

    document_name: str

    current_file: str

    version: int = 0

    last_updated: datetime | None = None

    generated_sections: list[GeneratedSection] = Field(
        default_factory=list
    )