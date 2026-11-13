# scripts/blueprint-render/tests/test_config.py
"""Tests for YAML loading, per-run caching, and date normalization.

Validates the two PyYAML coercion cases the loader undoes:
  - datetime.date (YYYY-MM-DD) -> isoformat string
  - datetime.datetime -> isoformat string

And passthrough of everything else, a bare year included: only a
schema can say whether 2024 is a year, so lib/validate.py turns it
into a string where the schema asks for one (test_validate.py).
Also checks that load_yaml returns the cached structure for an
unchanged file and re-reads a file that changed on disk.
"""

import datetime
import os
import pytest

from lib.config import normalize_dates, load_yaml, clear_cache


# -- normalize_dates -----------------------------------------------------------


class TestNormalizeDates:
    """Recursive date normalization."""

    def test_date_to_isoformat(self):
        d = datetime.date(2024, 10, 15)
        assert normalize_dates(d) == "2024-10-15"

    def test_datetime_to_isoformat(self):
        dt = datetime.datetime(2024, 10, 15, 14, 30, 0)
        assert normalize_dates(dt) == "2024-10-15T14:30:00"

    def test_bare_year_stays_an_int(self):
        assert normalize_dates(2024) == 2024
        assert normalize_dates(1900) == 1900
        assert normalize_dates(2100) == 2100

    def test_int_outside_range_unchanged(self):
        assert normalize_dates(42) == 42
        assert normalize_dates(1899) == 1899
        assert normalize_dates(2101) == 2101
        assert normalize_dates(100000) == 100000

    def test_string_unchanged(self):
        assert normalize_dates("2024-10") == "2024-10"
        assert normalize_dates("hello") == "hello"

    def test_none_unchanged(self):
        assert normalize_dates(None) is None

    def test_bool_unchanged(self):
        assert normalize_dates(True) is True
        assert normalize_dates(False) is False

    def test_float_unchanged(self):
        assert normalize_dates(3.14) == 3.14

    def test_dict_recursive(self):
        data = {
            "date": datetime.date(2024, 1, 1),
            "year": 2024,
            "name": "test",
            "count": 42,
        }
        result = normalize_dates(data)
        assert result == {
            "date": "2024-01-01",
            "year": 2024,
            "name": "test",
            "count": 42,
        }

    def test_list_recursive(self):
        data = [datetime.date(2024, 1, 1), 2024, "hello", 42]
        result = normalize_dates(data)
        assert result == ["2024-01-01", 2024, "hello", 42]

    def test_nested_structure(self):
        data = {
            "entries": [
                {"start": datetime.date(2021, 8, 1), "year": 2021},
                {"start": datetime.date(2024, 5, 15), "year": 2024},
            ]
        }
        result = normalize_dates(data)
        assert result["entries"][0]["start"] == "2021-08-01"
        assert result["entries"][0]["year"] == 2021
        assert result["entries"][1]["start"] == "2024-05-15"
        assert result["entries"][1]["year"] == 2024

    def test_empty_containers(self):
        assert normalize_dates({}) == {}
        assert normalize_dates([]) == []


# -- load_yaml cache -----------------------------------------------------------


class TestLoadYamlCache:
    """Per-run memoization keyed by path, size, and mtime."""

    def setup_method(self):
        clear_cache()

    def test_unchanged_file_returns_same_object(self, tmp_path):
        p = tmp_path / "bp.data.thing.yaml"
        p.write_text("name: a\nstart: 2024-01-01\n")
        first = load_yaml(p)
        second = load_yaml(p)
        assert second is first
        assert first == {"name": "a", "start": "2024-01-01"}

    def test_changed_file_is_reread(self, tmp_path):
        p = tmp_path / "bp.data.thing.yaml"
        p.write_text("name: a\n")
        first = load_yaml(p)
        # Different length and a later mtime so the key changes
        # even on filesystems with coarse timestamps.
        p.write_text("name: longer-value\n")
        st = os.stat(p)
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        second = load_yaml(p)
        assert second is not first
        assert second == {"name": "longer-value"}

    def test_empty_file_returns_empty_dict(self, tmp_path):
        p = tmp_path / "bp.invoke.thing.yaml"
        p.write_text("")
        assert load_yaml(p) == {}

    def test_clear_cache_forces_reparse(self, tmp_path):
        p = tmp_path / "bp.data.thing.yaml"
        p.write_text("name: a\n")
        first = load_yaml(p)
        clear_cache()
        assert load_yaml(p) is not first
