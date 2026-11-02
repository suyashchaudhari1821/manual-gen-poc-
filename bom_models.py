from typing import Optional, Any
from pydantic import BaseModel


class BOMItem(BaseModel):
    item_no: Optional[str] = None
    part_number: Optional[str] = None
    name: Optional[str] = None

    quantity: Optional[float] = None

    material: Optional[str] = None
    supplier: Optional[str] = None

    weight: Optional[str] = None
    torque: Optional[str] = None

    drawing_ref: Optional[str] = None
    revision: Optional[str] = None

    notes: Optional[str] = None


class BOMDocument(BaseModel):
    filename: str

    row_count: int

    items: list[BOMItem]

    parsing_mode: str

    parsing_confidence: float

    parse_duration: float


class BOMPartMatch(BaseModel):
    part_name: str

    bom_match_score: float = 0.0

    bom_match_method: Optional[str] = None

    matched: bool = False


class BOMCorrelationResult(BaseModel):
    matched_parts: int

    unmatched_parts: int

    match_threshold: float

    correlation_duration: float

    enriched_parts: list[dict[str, Any]]