from langchain.tools import tool

from bom_parser import parse_bom_file_from_path


@tool
def analyze_bom(file_path: str):
    """
    Parse a BOM file and return structured information.
    """
    return parse_bom_file_from_path(file_path)


@tool
def validate_bom(file_path: str):
    """
    Validate a BOM and report common quality issues.
    """
    bom = parse_bom_file_from_path(file_path)

    rows = bom.get("rows", [])

    missing_part_numbers = []
    missing_quantities = []

    seen_items = set()
    duplicate_items = []

    for idx, row in enumerate(rows, start=1):

        item_no = row.get("item_no")
        part_number = row.get("part_number")
        quantity = row.get("quantity")

        if not part_number:
            missing_part_numbers.append(idx)

        if not quantity:
            missing_quantities.append(idx)

        if item_no:
            if item_no in seen_items:
                duplicate_items.append(item_no)
            else:
                seen_items.add(item_no)

    return {
        "row_count": len(rows),

        "missing_part_numbers": missing_part_numbers,

        "missing_quantities": missing_quantities,

        "duplicate_item_numbers": duplicate_items,

        "validation_passed": (
            len(missing_part_numbers) == 0
            and len(missing_quantities) == 0
            and len(duplicate_items) == 0
        ),
    }