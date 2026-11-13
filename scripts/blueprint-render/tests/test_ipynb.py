# scripts/blueprint-render/tests/test_ipynb.py
"""Tests for the ipynb renderer: percent-format templates become clean, deterministic notebooks."""

import json
from pathlib import Path

import jinja2
import pytest

from renderers import ipynb

FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATE = "tests/fixtures/notebook/demo.py.j2"
ROOT = Path(__file__).parent.parent


def _render(tmp_path, context):
    out = tmp_path / "demo.ipynb"
    ipynb.render(context, TEMPLATE, out, ROOT)
    return out


def test_cells_follow_the_markers(tmp_path):
    nb = json.loads(_render(tmp_path, {"title": "Demo", "value": 7}).read_text(encoding="utf-8"))
    assert [c["cell_type"] for c in nb["cells"]] == ["markdown", "code", "code"]
    assert nb["cells"][0]["source"] == ["# Demo\n", "\n", "Some *text*.\n", "\n", "no space after the hash"]
    assert nb["cells"][1]["source"] == ["x = 7\n", "\n", "print(x)"]
    assert nb["cells"][2]["source"] == ["y = 2"]
    assert nb["cells"][1]["outputs"] == [] and nb["cells"][1]["execution_count"] is None
    assert [c["id"] for c in nb["cells"]] == ["cell-00", "cell-01", "cell-02"]
    assert (nb["nbformat"], nb["nbformat_minor"]) == (4, 5)


def test_rendering_twice_gives_the_same_bytes(tmp_path):
    first = _render(tmp_path, {"title": "Demo", "value": 7}).read_bytes()
    assert _render(tmp_path, {"title": "Demo", "value": 7}).read_bytes() == first


def test_a_missing_value_fails_the_render(tmp_path):
    with pytest.raises(jinja2.UndefinedError):
        _render(tmp_path, {"title": "Demo"})


def test_a_process_without_a_template_raises(tmp_path):
    with pytest.raises(ValueError, match="needs a template"):
        ipynb.render({}, None, tmp_path / "x.ipynb", ROOT)
