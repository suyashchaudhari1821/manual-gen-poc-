from engineering_models import EngineeringKnowledge

def build_engineering_knowledge(
    cad_doc=None,
    bom_doc=None,
    manual_doc=None,
):


    return EngineeringKnowledge(
    cad=cad_doc,
    bom=bom_doc,
    manual=manual_doc,
)
