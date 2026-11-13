# tests/conftest.py
"""Fixtures shared by the test files, and a backend that only draws to files.

The suite saves figures and never shows them, so it draws with Agg whatever
backend the machine defaults to. A GUI default such as TkAgg (WSLg sets DISPLAY)
makes window objects that Python's garbage collector may free on one of Aer's
worker threads, which kills the test process.
"""

import shutil

import matplotlib
import pytest

from bellbench import configs

matplotlib.use("Agg")


@pytest.fixture
def config_copy(tmp_path, monkeypatch):
    """A copy of config/ in a temporary repo root that configs.py reads instead, so a test can edit files freely.

    Returns the temporary root; the copied files are under `<root>/config/`.
    """
    shutil.copytree(configs.ROOT / "config", tmp_path / "config")
    monkeypatch.setattr(configs, "ROOT", tmp_path)
    return tmp_path
