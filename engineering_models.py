from pydantic import BaseModel
from typing import Optional

from cad_models import CADAssembly
from bom_models import BOMDocument
from manual_models import ManualDocument

class ReferencePoint(BaseModel):
    point_id: str

    label: Optional[str] = None

    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None

    item_no: Optional[str] = None
class ReferencePointDocument(BaseModel):
    points: list[ReferencePoint]
class BOMCADMatch(BaseModel):

    cad_part_name: str

    bom_part_number: Optional[str] = None

    bom_name: Optional[str] = None

    match_score: float = 0.0

    match_method: Optional[str] = None
class CorrelationResult(BaseModel):

    matches: list[BOMCADMatch]

    matched_parts: int

    unmatched_parts: int

    match_threshold: float = 0.25

    correlation_duration: float = 0.0
class EngineeringKnowledge(BaseModel):

    cad: Optional[CADAssembly] = None

    bom: Optional[BOMDocument] = None

    manual: Optional[ManualDocument] = None