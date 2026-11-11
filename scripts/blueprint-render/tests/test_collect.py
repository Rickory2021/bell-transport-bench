# scripts/blueprint-render/tests/test_collect.py
"""Tests for collect rollup infrastructure.

Covers:
  - fn/collect/extract_fields.py (field extraction, transforms, key derivation)
  - fn/collect/to_comment.py (comment string production)
  - renderers/yaml.py (flat, sections, multiline, error handling)
  - runner.py additions (literal, data_with_paths, named output)
"""

import textwrap
from pathlib import Path

import pytest
import yaml

# -- extract_fields tests ------------------------------------------------------

from fn.collect.extract_fields import run as extract_fields_run


def _make_sources(entries):
    """Build a sources list from {path: data} dict."""
    return [{"_source": path, "_data": data} for path, data in entries.items()]


class TestExtractFields:

    def test_basic_extraction(self):
        sources = _make_sources({
            "bp.data.role.backend.yaml": {"title": "Backend", "tier": "core"},
        })
        result = extract_fields_run(
            data={"sources": sources},
            vars={
                "fields": [{"path": "title"}, {"path": "tier"}],
                "key_pattern": r"bp\.data\.role\.(.+)\.yaml$",
            },
        )
        assert result == {"backend": {"title": "Backend", "tier": "core"}}

    def test_dotted_path(self):
        sources = _make_sources({
            "bp.data.role.x.yaml": {
                "profile_fit": {"gaps": [{"name": "a"}, {"name": "b"}]},
            },
        })
        result = extract_fields_run(
            data={"sources": sources},
            vars={
                "fields": [{"path": "profile_fit.gaps"}],
                "key_pattern": r"bp\.data\.role\.(.+)\.yaml$",
            },
        )
        assert len(result["x"]["gaps"]) == 2

    def test_missing_field_returns_none(self):
        sources = _make_sources({
            "bp.data.role.x.yaml": {"title": "X"},
        })
        result = extract_fields_run(
            data={"sources": sources},
            vars={
                "fields": [{"path": "title"}, {"path": "nonexistent"}],
                "key_pattern": r"bp\.data\.role\.(.+)\.yaml$",
            },
        )
        assert result["x"]["nonexistent"] is None

    def test_first_sentence_transform(self):
        sources = _make_sources({
            "bp.data.role.x.yaml": {
                "summary": "First line.\nSecond line.\nThird line.\n",
            },
        })
        result = extract_fields_run(
            data={"sources": sources},
            vars={
                "fields": [{"path": "summary", "transform": "first_sentence"}],
                "key_pattern": r"bp\.data\.role\.(.+)\.yaml$",
            },
        )
        assert result["x"]["summary"] == "First line."

    def test_count_transform(self):
        sources = _make_sources({
            "bp.data.role.x.yaml": {
                "profile_fit": {"gaps": [1, 2, 3]},
            },
        })
        result = extract_fields_run(
            data={"sources": sources},
            vars={
                "fields": [
                    {"path": "profile_fit.gaps", "transform": "count", "as": "gap_count"},
                ],
                "key_pattern": r"bp\.data\.role\.(.+)\.yaml$",
            },
        )
        assert result["x"]["gap_count"] == 3

    def test_count_transform_on_none(self):
        sources = _make_sources({
            "bp.data.role.x.yaml": {"title": "X"},
        })
        result = extract_fields_run(
            data={"sources": sources},
            vars={
                "fields": [
                    {"path": "missing_list", "transform": "count", "as": "n"},
                ],
                "key_pattern": r"bp\.data\.role\.(.+)\.yaml$",
            },
        )
        assert result["x"]["n"] == 0

    def test_as_renames_output_field(self):
        sources = _make_sources({
            "bp.data.role.x.yaml": {"long_field_name": "val"},
        })
        result = extract_fields_run(
            data={"sources": sources},
            vars={
                "fields": [{"path": "long_field_name", "as": "short"}],
                "key_pattern": r"bp\.data\.role\.(.+)\.yaml$",
            },
        )
        assert "short" in result["x"]
        assert "long_field_name" not in result["x"]

    def test_alpha_sorted_by_key(self):
        sources = _make_sources({
            "bp.data.role.zebra.yaml": {"title": "Z"},
            "bp.data.role.alpha.yaml": {"title": "A"},
            "bp.data.role.mid.yaml": {"title": "M"},
        })
        result = extract_fields_run(
            data={"sources": sources},
            vars={
                "fields": [{"path": "title"}],
                "key_pattern": r"bp\.data\.role\.(.+)\.yaml$",
            },
        )
        assert list(result.keys()) == ["alpha", "mid", "zebra"]

    def test_key_pattern_extracts_from_filename(self):
        sources = _make_sources({
            "some/path/bp.data.widget.fancy-name.yaml": {"title": "W"},
        })
        result = extract_fields_run(
            data={"sources": sources},
            vars={
                "fields": [{"path": "title"}],
                "key_pattern": r"bp\.data\.widget\.(.+)\.yaml$",
            },
        )
        assert "fancy-name" in result

    def test_unknown_transform_raises(self):
        sources = _make_sources({
            "bp.data.role.x.yaml": {"title": "X"},
        })
        with pytest.raises(ValueError, match="Unknown transform"):
            extract_fields_run(
                data={"sources": sources},
                vars={
                    "fields": [{"path": "title", "transform": "bogus"}],
                    "key_pattern": r"bp\.data\.role\.(.+)\.yaml$",
                },
            )

    def test_exclude_keys_strips_nested(self):
        sources = _make_sources({
            "bp.data.role.x.yaml": {
                "compensation": {
                    "orlando": {
                        "junior": {"base": 70000},
                        "notes": "Long paragraph...",
                    },
                    "national": {
                        "junior": {"base": 90000},
                        "notes": "Another paragraph...",
                        "sub_markets": {"tampa": {}},
                    },
                },
            },
        })
        result = extract_fields_run(
            data={"sources": sources},
            vars={
                "fields": [{
                    "path": "compensation",
                    "transform": "exclude_keys",
                    "exclude": ["notes", "sub_markets"],
                }],
                "key_pattern": r"bp\.data\.role\.(.+)\.yaml$",
            },
        )
        comp = result["x"]["compensation"]
        assert "notes" not in comp["orlando"]
        assert "notes" not in comp["national"]
        assert "sub_markets" not in comp["national"]
        assert comp["orlando"]["junior"]["base"] == 70000

    def test_exclude_keys_preserves_non_excluded(self):
        sources = _make_sources({
            "bp.data.role.x.yaml": {
                "data": {"keep": 1, "drop": 2, "also_keep": 3},
            },
        })
        result = extract_fields_run(
            data={"sources": sources},
            vars={
                "fields": [{
                    "path": "data",
                    "transform": "exclude_keys",
                    "exclude": ["drop"],
                }],
                "key_pattern": r"bp\.data\.role\.(.+)\.yaml$",
            },
        )
        assert result["x"]["data"] == {"keep": 1, "also_keep": 3}


# -- to_comment tests ----------------------------------------------------------

from fn.collect.to_comment import run as to_comment_run


class TestToComment:

    def test_plain_text(self):
        result = to_comment_run({}, {"text": "hello"})
        assert result == "# hello"

    def test_decorated_text(self):
        result = to_comment_run({}, {"text": "--- core ---"})
        assert result == "# --- core ---"

    def test_empty_text(self):
        result = to_comment_run({}, {"text": ""})
        assert result == "# "


# -- yaml renderer tests -------------------------------------------------------

from renderers.yaml import render as yaml_render
from renderers.yaml import _serialize_sections, _add_entry_separators, _dump


class TestYamlRendererFlat:

    def test_single_key_unwrap(self, tmp_path):
        context = {"index": {"a": {"title": "A"}, "b": {"title": "B"}}}
        out = tmp_path / "out.yaml"
        yaml_render(context, None, out, tmp_path)
        data = yaml.safe_load(out.read_text())
        assert "a" in data
        assert "index" not in data

    def test_multi_key_no_unwrap(self, tmp_path):
        context = {"x": {"title": "X"}, "y": {"title": "Y"}}
        out = tmp_path / "out.yaml"
        yaml_render(context, None, out, tmp_path)
        data = yaml.safe_load(out.read_text())
        assert "x" in data
        assert "y" in data

    def test_separator_newline(self, tmp_path):
        context = {"index": {"a": {"t": 1}, "b": {"t": 2}}}
        out = tmp_path / "out.yaml"
        yaml_render(context, None, out, tmp_path,
                     emit_entry={"separator": "newline"})
        lines = out.read_text().split("\n")
        # Find the two entry lines and check blank line between
        entry_indices = [i for i, l in enumerate(lines)
                        if l and not l[0].isspace() and ":" in l
                        and not l.startswith("#")]
        assert len(entry_indices) == 2
        # Blank line should exist between them
        between = lines[entry_indices[0]+1:entry_indices[1]]
        assert "" in between

    def test_directory_comment_header(self, tmp_path):
        context = {"index": {"a": {"t": 1}}}
        out = tmp_path / "sub" / "out.yaml"
        out.parent.mkdir()
        yaml_render(context, None, out, tmp_path)
        first_line = out.read_text().split("\n")[0]
        assert first_line == "# sub/out.yaml"

    def test_auto_generated_notice(self, tmp_path):
        context = {"index": {"a": {"t": 1}}}
        out = tmp_path / "out.yaml"
        yaml_render(context, None, out, tmp_path)
        text = out.read_text()
        assert "Auto-generated. Do not edit." in text


class TestYamlRendererSections:

    def test_sections_ordering(self):
        context = {
            "c1": "# --- alpha ---",
            "alpha": {"a1": {"title": "A1"}},
            "c2": "# --- beta ---",
            "beta": {"b1": {"title": "B1"}},
        }
        result = _serialize_sections(context, ["c1", "alpha", "c2", "beta"])
        lines = result.split("\n")
        alpha_pos = next(i for i, l in enumerate(lines) if "alpha" in l and "---" in l)
        beta_pos = next(i for i, l in enumerate(lines) if "beta" in l and "---" in l)
        assert alpha_pos < beta_pos

    def test_comment_written_raw(self):
        context = {"c": "# my comment"}
        result = _serialize_sections(context, ["c"])
        assert "# my comment" in result

    def test_data_serialized_as_yaml(self):
        context = {"d": {"key1": {"field": "value"}}}
        result = _serialize_sections(context, ["d"])
        assert "key1:" in result
        assert "field: value" in result

    def test_missing_key_warns(self, capsys):
        context = {"a": "# comment"}
        _serialize_sections(context, ["a", "missing"])
        captured = capsys.readouterr()
        assert "missing" in captured.err

    def test_unknown_type_raises(self):
        context = {"bad": 42}
        with pytest.raises(ValueError, match="expected str or dict"):
            _serialize_sections(context, ["bad"])

    def test_entry_separators_within_data(self):
        context = {
            "d": {"a": {"t": 1}, "b": {"t": 2}, "c": {"t": 3}},
        }
        result = _serialize_sections(context, ["d"])
        # Each top-level entry should have a blank line before it
        lines = result.split("\n")
        entry_lines = [i for i, l in enumerate(lines)
                      if l and not l[0].isspace() and ":" in l]
        # Between first and second entry there should be a blank
        if len(entry_lines) >= 2:
            between = lines[entry_lines[0]+1:entry_lines[1]]
            assert "" in between


class TestYamlRendererMultiline:

    def test_multiline_uses_block_scalar(self, tmp_path):
        context = {"index": {"a": {"summary": "Line 1.\nLine 2.\n"}}}
        out = tmp_path / "out.yaml"
        yaml_render(context, None, out, tmp_path)
        text = out.read_text()
        assert "|-" in text
        assert "''" not in text  # no escaped quotes

    def test_apostrophe_unescaped(self, tmp_path):
        context = {"index": {"a": {"summary": "It's a test.\nLine 2.\n"}}}
        out = tmp_path / "out.yaml"
        yaml_render(context, None, out, tmp_path)
        text = out.read_text()
        assert "It's a test." in text
        assert "It''s" not in text


# -- runner additions tests ----------------------------------------------------

from lib.runner import _resolve_params, _load_data_with_paths, RunError


class TestLiteralParam:

    def test_literal_resolves_to_var_params(self):
        params = {"fields": {"literal": [{"path": "title"}]}}
        data_p, var_p = _resolve_params(params, {}, Path("/tmp"))
        assert "fields" in var_p
        assert var_p["fields"] == [{"path": "title"}]
        assert "fields" not in data_p

    def test_literal_string(self):
        params = {"pattern": {"literal": r"bp\.data\.(.+)\.yaml$"}}
        _, var_p = _resolve_params(params, {}, Path("/tmp"))
        assert var_p["pattern"] == r"bp\.data\.(.+)\.yaml$"

    def test_literal_mixed_with_var(self):
        params = {
            "text": {"var": "my_var"},
            "fields": {"literal": ["a", "b"]},
        }
        resolved_vars = {"my_var": "hello"}
        data_p, var_p = _resolve_params(params, resolved_vars, Path("/tmp"))
        assert var_p["text"] == "hello"
        assert var_p["fields"] == ["a", "b"]


class TestDataWithPaths:

    def test_returns_source_and_data(self, tmp_path):
        # Create test YAML files
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "bp.data.role.alpha.yaml").write_text(
            "title: Alpha\n"
        )
        (tmp_path / "sub" / "bp.data.role.beta.yaml").write_text(
            "title: Beta\n"
        )
        result = _load_data_with_paths("sub/bp.data.role.*.yaml", tmp_path)
        assert len(result) == 2
        assert all("_source" in r and "_data" in r for r in result)

    def test_source_is_root_relative(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "test.yaml").write_text("x: 1\n")
        result = _load_data_with_paths("a/test.yaml", tmp_path)
        # Glob matches, _source should not start with /
        assert not result[0]["_source"].startswith("/")
        assert result[0]["_source"] == "a/test.yaml"

    def test_data_loaded_correctly(self, tmp_path):
        (tmp_path / "test.yaml").write_text("title: Hello\ntier: core\n")
        result = _load_data_with_paths("test.yaml", tmp_path)
        assert result[0]["_data"]["title"] == "Hello"

    def test_param_tag_resolves(self, tmp_path):
        (tmp_path / "f.yaml").write_text("x: 1\n")
        params = {"sources": {"data_with_paths": "f.yaml"}}
        data_p, _ = _resolve_params(params, {}, tmp_path)
        assert "sources" in data_p
        assert len(data_p["sources"]) == 1
        assert data_p["sources"][0]["_data"]["x"] == 1


class TestUnknownParamTag:

    def test_raises_on_unknown_tag(self):
        params = {"bad": {"unknown_tag": "value"}}
        with pytest.raises(RunError, match="unknown resolution tag"):
            _resolve_params(params, {}, Path("/tmp"))


# -- entry separator helper test -----------------------------------------------

class TestAddEntrySeparators:

    def test_adds_blanks_between_entries(self):
        yaml_str = "a:\n  x: 1\nb:\n  x: 2\nc:\n  x: 3\n"
        result = _add_entry_separators(yaml_str)
        lines = result.split("\n")
        # Before b: and c: there should be blank lines
        b_idx = lines.index("b:")
        c_idx = lines.index("c:")
        assert lines[b_idx - 1] == ""
        assert lines[c_idx - 1] == ""

    def test_no_blank_before_first(self):
        yaml_str = "a:\n  x: 1\n"
        result = _add_entry_separators(yaml_str)
        assert not result.startswith("\n")


# -- _helpers tests ------------------------------------------------------------

from fn.collect._helpers import (
    get_nested, first_sentence, exclude_keys, apply_transform, extract_fields,
)


class TestGetNested:

    def test_single_level(self):
        assert get_nested({"a": 1}, "a") == 1

    def test_dotted_path(self):
        data = {"a": {"b": {"c": 42}}}
        assert get_nested(data, "a.b.c") == 42

    def test_missing_returns_none(self):
        assert get_nested({"a": 1}, "b") is None

    def test_missing_intermediate_returns_none(self):
        assert get_nested({"a": {"b": 1}}, "a.x.y") is None

    def test_non_dict_intermediate_returns_none(self):
        assert get_nested({"a": "string"}, "a.b") is None


class TestFirstSentence:

    def test_multiline(self):
        assert first_sentence("First.\nSecond.\n") == "First."

    def test_leading_blank_lines(self):
        assert first_sentence("\n\n  Content here\n") == "Content here"

    def test_empty_string(self):
        assert first_sentence("") == ""

    def test_none(self):
        assert first_sentence(None) == ""

    def test_non_string_coerced(self):
        assert first_sentence(42) == "42"


class TestExcludeKeys:

    def test_shallow(self):
        result = exclude_keys({"a": 1, "b": 2, "c": 3}, {"b"})
        assert result == {"a": 1, "c": 3}

    def test_nested(self):
        data = {"x": {"drop": 1, "keep": 2}, "y": {"drop": 3, "keep": 4}}
        result = exclude_keys(data, {"drop"})
        assert result == {"x": {"keep": 2}, "y": {"keep": 4}}

    def test_non_dict_passthrough(self):
        assert exclude_keys("hello", {"a"}) == "hello"
        assert exclude_keys(42, {"a"}) == 42
        assert exclude_keys(None, {"a"}) is None


class TestApplyTransform:

    def test_first_sentence(self):
        assert apply_transform("Line 1\nLine 2", "first_sentence") == "Line 1"

    def test_count_list(self):
        assert apply_transform([1, 2, 3], "count") == 3

    def test_count_dict(self):
        assert apply_transform({"a": 1, "b": 2}, "count") == 2

    def test_count_none(self):
        assert apply_transform(None, "count") == 0

    def test_exclude_keys(self):
        data = {"keep": 1, "drop": 2}
        result = apply_transform(data, "exclude_keys", {"exclude": ["drop"]})
        assert result == {"keep": 1}

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown transform"):
            apply_transform("x", "bogus")


class TestExtractFieldsHelper:

    def test_basic(self):
        data = {"name": "Python", "level": "advanced"}
        specs = [{"path": "name"}, {"path": "level"}]
        assert extract_fields(data, specs) == {"name": "Python", "level": "advanced"}

    def test_rename(self):
        data = {"long_name": "val"}
        specs = [{"path": "long_name", "as": "short"}]
        result = extract_fields(data, specs)
        assert "short" in result
        assert "long_name" not in result

    def test_dotted_path(self):
        data = {"a": {"b": 42}}
        specs = [{"path": "a.b", "as": "value"}]
        assert extract_fields(data, specs) == {"value": 42}

    def test_transform(self):
        data = {"items": [1, 2, 3]}
        specs = [{"path": "items", "transform": "count", "as": "n"}]
        assert extract_fields(data, specs) == {"n": 3}

    def test_missing_field(self):
        data = {"a": 1}
        specs = [{"path": "b"}]
        assert extract_fields(data, specs) == {"b": None}


# -- extract_list tests --------------------------------------------------------

from fn.collect.extract_list import run as extract_list_run


class TestExtractList:

    def test_basic_extraction(self):
        data = {"source": {
            "skills": [
                {"name": "Python", "proficiency": "advanced", "extra": "x"},
                {"name": "Go", "proficiency": "beginner", "extra": "y"},
            ],
        }}
        result = extract_list_run(
            data=data,
            vars={
                "list_key": "skills",
                "fields": [{"path": "name"}, {"path": "proficiency"}],
            },
        )
        assert len(result) == 2
        assert result[0] == {"name": "Python", "proficiency": "advanced"}
        assert result[1] == {"name": "Go", "proficiency": "beginner"}

    def test_preserves_source_order(self):
        data = {"source": {
            "items": [
                {"name": "Zebra"},
                {"name": "Alpha"},
                {"name": "Mid"},
            ],
        }}
        result = extract_list_run(
            data=data,
            vars={
                "list_key": "items",
                "fields": [{"path": "name"}],
            },
        )
        names = [r["name"] for r in result]
        assert names == ["Zebra", "Alpha", "Mid"]

    def test_dotted_list_key(self):
        data = {"source": {
            "outer": {"inner": [{"name": "A"}, {"name": "B"}]},
        }}
        result = extract_list_run(
            data=data,
            vars={
                "list_key": "outer.inner",
                "fields": [{"path": "name"}],
            },
        )
        assert len(result) == 2
        assert result[0] == {"name": "A"}

    def test_missing_list_key_returns_empty(self):
        data = {"source": {"other": []}}
        result = extract_list_run(
            data=data,
            vars={
                "list_key": "nonexistent",
                "fields": [{"path": "name"}],
            },
        )
        assert result == []

    def test_non_list_raises(self):
        data = {"source": {"skills": {"not": "a list"}}}
        with pytest.raises(ValueError, match="expected list"):
            extract_list_run(
                data=data,
                vars={
                    "list_key": "skills",
                    "fields": [{"path": "name"}],
                },
            )

    def test_transform_applied(self):
        data = {"source": {
            "items": [
                {"summary": "First line.\nSecond line.\n"},
            ],
        }}
        result = extract_list_run(
            data=data,
            vars={
                "list_key": "items",
                "fields": [{"path": "summary", "transform": "first_sentence"}],
            },
        )
        assert result[0]["summary"] == "First line."

    def test_rename_via_as(self):
        data = {"source": {
            "items": [{"long_field": "val"}],
        }}
        result = extract_list_run(
            data=data,
            vars={
                "list_key": "items",
                "fields": [{"path": "long_field", "as": "short"}],
            },
        )
        assert "short" in result[0]
        assert "long_field" not in result[0]

    def test_nested_field_extraction(self):
        data = {"source": {
            "items": [
                {"meta": {"score": 95}, "name": "A"},
                {"meta": {"score": 80}, "name": "B"},
            ],
        }}
        result = extract_list_run(
            data=data,
            vars={
                "list_key": "items",
                "fields": [
                    {"path": "name"},
                    {"path": "meta.score", "as": "score"},
                ],
            },
        )
        assert result[0] == {"name": "A", "score": 95}
        assert result[1] == {"name": "B", "score": 80}

    def test_empty_list(self):
        data = {"source": {"items": []}}
        result = extract_list_run(
            data=data,
            vars={
                "list_key": "items",
                "fields": [{"path": "name"}],
            },
        )
        assert result == []

    def test_missing_fields_in_items(self):
        data = {"source": {
            "items": [
                {"name": "A"},
                {"name": "B", "extra": "val"},
            ],
        }}
        result = extract_list_run(
            data=data,
            vars={
                "list_key": "items",
                "fields": [{"path": "name"}, {"path": "extra"}],
            },
        )
        assert result[0]["extra"] is None
        assert result[1]["extra"] == "val"

    def test_count_transform(self):
        data = {"source": {
            "items": [
                {"name": "A", "tags": ["x", "y", "z"]},
                {"name": "B", "tags": []},
            ],
        }}
        result = extract_list_run(
            data=data,
            vars={
                "list_key": "items",
                "fields": [
                    {"path": "name"},
                    {"path": "tags", "transform": "count", "as": "tag_count"},
                ],
            },
        )
        assert result[0]["tag_count"] == 3
        assert result[1]["tag_count"] == 0


class TestExtractListGroupBy:

    def _data(self, items):
        return {"source": {"items": items}}

    def _vars(self, fields, group_by=None):
        v = {"list_key": "items", "fields": fields}
        if group_by:
            v["group_by"] = group_by
        return v

    def test_groups_by_field(self):
        data = self._data([
            {"name": "A", "cat": "x"},
            {"name": "B", "cat": "x"},
            {"name": "C", "cat": "y"},
        ])
        result = extract_list_run(
            data=data,
            vars=self._vars(
                [{"path": "name"}, {"path": "cat"}],
                group_by="cat",
            ),
        )
        assert isinstance(result, dict)
        assert list(result.keys()) == ["x", "y"]
        assert len(result["x"]) == 2
        assert len(result["y"]) == 1

    def test_removes_group_field_from_rows(self):
        data = self._data([
            {"name": "A", "cat": "x", "val": 1},
        ])
        result = extract_list_run(
            data=data,
            vars=self._vars(
                [{"path": "name"}, {"path": "cat"}, {"path": "val"}],
                group_by="cat",
            ),
        )
        row = result["x"][0]
        assert "name" in row
        assert "val" in row
        assert "cat" not in row

    def test_preserves_source_order_within_groups(self):
        data = self._data([
            {"name": "Z", "cat": "a"},
            {"name": "A", "cat": "a"},
            {"name": "M", "cat": "a"},
        ])
        result = extract_list_run(
            data=data,
            vars=self._vars(
                [{"path": "name"}, {"path": "cat"}],
                group_by="cat",
            ),
        )
        names = [r["name"] for r in result["a"]]
        assert names == ["Z", "A", "M"]

    def test_preserves_group_order(self):
        data = self._data([
            {"name": "A", "cat": "beta"},
            {"name": "B", "cat": "alpha"},
            {"name": "C", "cat": "beta"},
        ])
        result = extract_list_run(
            data=data,
            vars=self._vars(
                [{"path": "name"}, {"path": "cat"}],
                group_by="cat",
            ),
        )
        assert list(result.keys()) == ["beta", "alpha"]

    def test_skips_items_missing_group_field(self):
        data = self._data([
            {"name": "A", "cat": "x"},
            {"name": "B"},
        ])
        result = extract_list_run(
            data=data,
            vars=self._vars(
                [{"path": "name"}, {"path": "cat"}],
                group_by="cat",
            ),
        )
        assert len(result) == 1
        assert "x" in result

    def test_empty_list_returns_empty_dict(self):
        data = self._data([])
        result = extract_list_run(
            data=data,
            vars=self._vars(
                [{"path": "name"}, {"path": "cat"}],
                group_by="cat",
            ),
        )
        assert result == {}

    def test_missing_list_returns_empty_dict(self):
        data = {"source": {"other": []}}
        result = extract_list_run(
            data=data,
            vars=self._vars(
                [{"path": "name"}, {"path": "cat"}],
                group_by="cat",
            ),
        )
        assert result == {}

    def test_no_group_by_returns_list(self):
        data = self._data([{"name": "A", "cat": "x"}])
        result = extract_list_run(
            data=data,
            vars=self._vars([{"path": "name"}, {"path": "cat"}]),
        )
        assert isinstance(result, list)
