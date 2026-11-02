from langchain.tools import tool

from cad_parser import parse_step_file


@tool
def analyze_cad(filepath: str):
    """
    Parse and analyze CAD data.
    """

    return parse_step_file(filepath)