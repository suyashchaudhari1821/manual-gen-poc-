"""
Streamlit Cloud Entry Point
Launches the Expleo Manual Updation Tool UI (ui.py)
"""
import sys
from pathlib import Path
import runpy

# Ensure repository root is on sys.path
REPO_DIR = Path(__file__).resolve().parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

# Execute ui.py in the main namespace
runpy.run_path(str(REPO_DIR / "ui.py"), run_name="__main__")
