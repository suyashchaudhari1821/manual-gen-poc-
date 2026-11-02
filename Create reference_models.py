class ReferencePoint(BaseModel):
    point_id: str
    label: str | None = None

    x: float | None = None
    y: float | None = None
    z: float | None = None

    item_no: str | None = None
class ReferencePointDocument(BaseModel):
    points: list[ReferencePoint]