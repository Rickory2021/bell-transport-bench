# scripts/blueprint-render/tests/test_collect_text.py
"""Tests for the {text: ...} resolution tag and the collect fns that read raw text.

Covers:
  - runner.py: {text: glob} and {text: [globs]}, raw and sorted, refusing non-UTF-8 files
  - fn/collect/_select.py: whole and partial folders, and a folder that matches nothing
  - fn/collect/archive.py: the payload unpacks to the files, its manifest, and the same bytes twice
  - fn/collect/texts.py: path to text, unchanged
  - fn/collect/csv_rows.py: numbers, empty cells, folder keys and nest_by
"""

import base64
import hashlib
import io
import math
import zipfile

import pytest

from fn.collect.archive import run as archive_run
from fn.collect.csv_rows import run as csv_rows_run
from fn.collect.texts import run as texts_run
from lib.runner import RunError, _resolve_params


def _files(entries):
    return [{"_source": path, "_text": text} for path, text in entries.items()]


def _unpack(payload):
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(payload))) as z:
        return {name: z.read(name).decode("utf-8") for name in z.namelist()}


# -- the {text: ...} tag --------------------------------------------------------------


class TestTextTag:

    def test_raw_text_with_comments_and_paths_sorted(self, tmp_path):
        (tmp_path / "b").mkdir()
        (tmp_path / "b" / "two.yaml").write_text("# a comment\nkey: 2\n", encoding="utf-8")
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        data, _ = _resolve_params({"files": {"text": ["b/*.yaml", "*.py"]}}, {}, tmp_path)
        assert data["files"] == [{"_source": "a.py", "_text": "x = 1\n"},
                                 {"_source": "b/two.yaml", "_text": "# a comment\nkey: 2\n"}]

    def test_a_file_two_globs_match_is_loaded_once(self, tmp_path):
        (tmp_path / "a.csv").write_text("x\n1\n", encoding="utf-8")
        data, _ = _resolve_params({"files": {"text": ["*.csv", "a.*"]}}, {}, tmp_path)
        assert [e["_source"] for e in data["files"]] == ["a.csv"]

    def test_a_binary_file_is_refused_by_name(self, tmp_path):
        (tmp_path / "picture.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
        with pytest.raises(RunError, match="picture.png, which is not UTF-8 text"):
            _resolve_params({"files": {"text": "*.png"}}, {}, tmp_path)

    def test_a_tag_that_is_not_a_glob_is_refused(self, tmp_path):
        with pytest.raises(RunError, match="takes a glob or a list of globs"):
            _resolve_params({"files": {"text": 3}}, {}, tmp_path)


# -- selection -------------------------------------------------------------------------

RESULTS = _files({
    "r/bench/a/1/x.yaml": "x", "r/bench/a/1/table.csv": "t", "r/bench/a/0/x.yaml": "old",
    "r/bench/b/1/table.csv": "t", "r/bench/b/1/run/record.yaml": "rec", "r/bench/b/1/report.md": "rep",
})


class TestSelection:

    def test_no_selection_keeps_every_file(self):
        assert texts_run({"files": RESULTS}, {}) == {e["_source"]: e["_text"] for e in RESULTS}

    def test_whole_and_partial_folders(self):
        kept = texts_run({"files": RESULTS}, {"under": "r/bench/", "whole": "a/1", "partial": ["b/1"],
                                              "names": ["table.csv", "report.md"]})
        assert list(kept) == ["r/bench/a/1/table.csv", "r/bench/a/1/x.yaml", "r/bench/b/1/report.md",
                              "r/bench/b/1/table.csv"]

    def test_a_folder_that_matches_nothing_raises(self):
        with pytest.raises(ValueError, match="no file matched the selected folders: r/bench/a/2/"):
            texts_run({"files": RESULTS}, {"under": "r/bench/", "whole": ["a/1", "a/2"]})

    def test_a_partial_selection_needs_names(self):
        with pytest.raises(ValueError, match="needs names"):
            texts_run({"files": RESULTS}, {"under": "r/bench/", "partial": ["b/1"]})


# -- archive ---------------------------------------------------------------------------


class TestArchive:

    def test_the_payload_unpacks_to_the_files_and_the_manifest_hashes_them(self):
        files = _files({"src/b.py": "b = 'é'\n", "src/a.py": "a = 1\n"})
        result = archive_run({"files": files}, {})
        assert _unpack(result["payload"]) == {"src/a.py": "a = 1\n", "src/b.py": "b = 'é'\n"}
        assert result["files"] == [
            {"path": "src/a.py", "sha256": hashlib.sha256(b"a = 1\n").hexdigest()},
            {"path": "src/b.py", "sha256": hashlib.sha256("b = 'é'\n".encode()).hexdigest()},
        ]
        assert result["count"] == 2

    def test_the_same_files_give_the_same_payload(self):
        files = _files({"src/a.py": "a = 1\n", "src/b.py": "b = 2\n"})
        assert archive_run({"files": files}, {}) == archive_run({"files": list(reversed(files))}, {})

    def test_a_selection_packs_only_its_files(self):
        result = archive_run({"files": RESULTS}, {"under": "r/bench/", "whole": "b/1"})
        assert sorted(_unpack(result["payload"])) == ["r/bench/b/1/report.md", "r/bench/b/1/run/record.yaml",
                                                      "r/bench/b/1/table.csv"]

    def test_nothing_to_pack_raises(self):
        with pytest.raises(ValueError, match="no file to pack"):
            archive_run({"files": []}, {})


# -- csv_rows --------------------------------------------------------------------------

TABLE = "case,run,simulation,fidelity,label\n3,a,noisy,0.98,x\n,a,ideal,1.0,\n,b,noisy,nan,y\n"


class TestCsvRows:

    def test_numbers_and_empty_cells(self):
        rows = csv_rows_run({"files": _files({"r/bench/m/1/comparison.csv": TABLE})}, {"under": "r/bench/"})
        assert list(rows) == ["m/1"]
        first, second, third = rows["m/1"]
        assert first == {"case": 3, "run": "a", "simulation": "noisy", "fidelity": 0.98, "label": "x"}
        assert second["case"] is None and second["label"] is None and second["fidelity"] == 1.0
        assert math.isnan(third["fidelity"])

    def test_nest_by_keys_rows_by_their_columns(self):
        rows = csv_rows_run({"files": _files({"r/bench/m/1/comparison.csv": TABLE})},
                            {"under": "r/bench/", "nest_by": ["run", "simulation"]})
        assert rows["m/1"]["a"]["noisy"]["fidelity"] == 0.98 and rows["m/1"]["a"]["ideal"]["fidelity"] == 1.0

    def test_two_rows_with_the_same_keys_raise(self):
        with pytest.raises(ValueError, match="two rows share run='a'"):
            csv_rows_run({"files": _files({"m/comparison.csv": TABLE})}, {"nest_by": ["run"]})
