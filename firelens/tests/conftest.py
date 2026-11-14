"""Shared paths for the FireLens tests. Run from firelens/:  python -m pytest tests -q"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # firelens/
DATA = ROOT / "data"
for folder in ("app", "science"):
    sys.path.insert(0, str(ROOT / folder))
