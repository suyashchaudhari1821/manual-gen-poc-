from pydantic import BaseModel
from typing import Optional


class BoundingBox(BaseModel):
    width: float
    height: float
    depth: float


class CenterOfMass(BaseModel):
    x: float
    y: float
    z: float


class CADPart(BaseModel):
    part_id: str
    name: str

    description: Optional[str] = None

    face_count: int = 0
    edge_count: int = 0
    vertex_count: int = 0

    volume: float = 0.0
    surface_area: float = 0.0

    bounding_box: BoundingBox
    center_of_mass: CenterOfMass


class CADAssembly(BaseModel):
    filename: str

    parts: list

    parsing_mode: str

    parsing_confidence: float

    parse_duration: float

    total_parts: int

    total_faces: int

    total_edges: int

    total_surface_area: float

    total_volume: float

    bounding_box: dict

    face_type_summary: dict