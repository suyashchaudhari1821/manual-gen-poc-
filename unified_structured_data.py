from cad_parser import parse_step_file
from bom_parser import parse_bom_file_from_path
from manual_parser import parse_manual

from engineering_context import (
    build_engineering_knowledge
)

cad_doc = parse_step_file(
    "_tmp_cad_stp_E5312070100000.stp"
)

bom_doc = parse_bom_file_from_path(
    "_tmp_cad_bom_E53120700_BomReportEn 1.pdf"
)
manual_doc = parse_manual(
    "temp_AC Manual.pdf"
)

knowledge = build_engineering_knowledge(
    cad_doc=cad_doc,
    bom_doc=bom_doc,
    manual_doc=manual_doc
)

print(type(knowledge))

print(type(knowledge.cad))

print(type(knowledge.bom))

print(knowledge.cad.filename)

print(knowledge.cad.total_parts)

print(knowledge.bom.filename)

print(knowledge.bom.row_count)

print(knowledge.model_dump())

print(type(knowledge.manual))

print(knowledge.manual.metadata)

print(len(knowledge.manual.text_blocks))

print(len(knowledge.manual.image_blocks))

print(len(knowledge.manual.table_blocks))

