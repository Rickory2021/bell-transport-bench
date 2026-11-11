"""Tests for scripts/fetch_refs.py: planning only, no network."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("fetch_refs", ROOT / "scripts" / "fetch_refs.py")
fetch_refs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_refs)


def test_shared_download_is_fetched_once():
    refs = [
        {"id": "deck", "download": "https://example.org/assets/Hackathon.zip"},
        {"id": "starter", "download": "https://example.org/assets/Hackathon.zip"},
        {"id": "site", "download": None},
    ]
    assert fetch_refs.plan(refs) == [
        ("https://example.org/assets/Hackathon.zip", "deck.zip", ["deck", "starter"]),
    ]


def test_arxiv_pdf_gets_pdf_extension():
    assert fetch_refs.file_name("paper", "https://arxiv.org/pdf/2508.00437v3") == "paper.pdf"


def test_duplicate_ids_are_rejected(tmp_path):
    path = tmp_path / "refs.yaml"
    path.write_text("references:\n  - id: a\n  - id: a\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate reference id"):
        fetch_refs.load_references(path)


def test_repo_references_load_and_plan():
    jobs = fetch_refs.plan(fetch_refs.load_references())
    names = [name for _, name, _ in jobs]
    assert len(names) == len(set(names))
