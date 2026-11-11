# scripts/blueprint-render/tests/conftest.py
"""Add the blueprint-render directory to sys.path so tests can
import lib modules regardless of where the directory lives."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
