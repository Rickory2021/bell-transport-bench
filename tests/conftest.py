# tests/conftest.py
"""Fixtures shared by the test files."""

import shutil

import pytest

from bellbench import configs


@pytest.fixture
def config_copy(tmp_path, monkeypatch):
    """A copy of config/ in a temporary repo root that configs.py reads instead, so a test can edit files freely.

    Returns the temporary root; the copied files are under `<root>/config/`.
    """
    shutil.copytree(configs.ROOT / "config", tmp_path / "config")
    monkeypatch.setattr(configs, "ROOT", tmp_path)
    return tmp_path
