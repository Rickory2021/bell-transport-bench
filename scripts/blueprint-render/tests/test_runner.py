# scripts/blueprint-render/tests/test_runner.py
"""Tests for runner core logic.

Covers:
  - Profile: scheme resolution
  - ${} interpolation
  - Nested dict assembly from dotted keys
  - Fresh-clone guard (example profile refused)
  - enum_keys param resolution tag
"""

import pytest
from pathlib import Path

import yaml

from lib.runner import (
    resolve_profile_refs,
    interpolate_vars,
    _set_nested,
    _load_profile,
    _load_enum_keys,
    _resolve_params,
    RunError,
)


# -- profile: scheme resolution ------------------------------------------------


class TestProfileRefs:

    def test_resolves_string_ref(self):
        imports = {"personal": {"header_name": "Ricky Chen"}}
        invoke_vars = {"header_name": "profile:personal.header_name"}
        resolved = resolve_profile_refs(invoke_vars, imports)
        assert resolved["header_name"] == "Ricky Chen"

    def test_preserves_literal_strings(self):
        imports = {"personal": {"header_name": "Ricky Chen"}}
        invoke_vars = {"summary": "A backend developer."}
        resolved = resolve_profile_refs(invoke_vars, imports)
        assert resolved["summary"] == "A backend developer."

    def test_preserves_none(self):
        imports = {}
        invoke_vars = {"summary_text": None}
        resolved = resolve_profile_refs(invoke_vars, imports)
        assert resolved["summary_text"] is None

    def test_preserves_lists(self):
        imports = {}
        invoke_vars = {"items": ["a", "b", "c"]}
        resolved = resolve_profile_refs(invoke_vars, imports)
        assert resolved["items"] == ["a", "b", "c"]

    def test_resolves_inside_dict(self):
        imports = {"p": {"email": "a@b.com"}}
        invoke_vars = {"contact": {"email": "profile:p.email"}}
        resolved = resolve_profile_refs(invoke_vars, imports)
        assert resolved["contact"]["email"] == "a@b.com"

    def test_resolves_inside_list(self):
        imports = {"p": {"name": "Test"}}
        invoke_vars = {"items": ["profile:p.name", "literal"]}
        resolved = resolve_profile_refs(invoke_vars, imports)
        assert resolved["items"] == ["Test", "literal"]

    def test_unknown_import_raises(self):
        imports = {"personal": {"name": "Test"}}
        invoke_vars = {"x": "profile:unknown.field"}
        with pytest.raises(RunError, match="unknown"):
            resolve_profile_refs(invoke_vars, imports)

    def test_unknown_field_raises(self):
        imports = {"personal": {"name": "Test"}}
        invoke_vars = {"x": "profile:personal.missing_field"}
        with pytest.raises(RunError, match="missing_field"):
            resolve_profile_refs(invoke_vars, imports)

    def test_invalid_format_raises(self):
        imports = {"personal": {"name": "Test"}}
        invoke_vars = {"x": "profile:noDot"}
        with pytest.raises(RunError, match="Expected"):
            resolve_profile_refs(invoke_vars, imports)


# -- ${} interpolation ---------------------------------------------------------


class TestInterpolation:

    def test_simple_substitution(self):
        vars = {"name": "Ricky", "greeting": "Hello ${name}"}
        result = interpolate_vars(vars)
        assert result["greeting"] == "Hello Ricky"

    def test_multiple_tokens(self):
        vars = {"first": "Ricky", "last": "Chen",
                "full": "${first} ${last}"}
        result = interpolate_vars(vars)
        assert result["full"] == "Ricky Chen"

    def test_no_tokens_passthrough(self):
        vars = {"name": "Ricky", "plain": "no tokens here"}
        result = interpolate_vars(vars)
        assert result["plain"] == "no tokens here"

    def test_non_string_passthrough(self):
        vars = {"count": 5, "items": ["a", "b"]}
        result = interpolate_vars(vars)
        assert result["count"] == 5
        assert result["items"] == ["a", "b"]

    def test_unknown_var_raises(self):
        vars = {"greeting": "Hello ${unknown}"}
        with pytest.raises(RunError, match="unknown"):
            interpolate_vars(vars)

    def test_non_string_var_raises(self):
        vars = {"items": ["a", "b"], "text": "list is ${items}"}
        with pytest.raises(RunError, match="not string"):
            interpolate_vars(vars)

    def test_none_passthrough(self):
        vars = {"x": None}
        result = interpolate_vars(vars)
        assert result["x"] is None


# -- Nested dict assembly -----------------------------------------------------


class TestSetNested:

    def test_single_key(self):
        d = {}
        _set_nested(d, "layout", {"margin": "0.5in"})
        assert d == {"layout": {"margin": "0.5in"}}

    def test_dotted_key(self):
        d = {}
        _set_nested(d, "header.name", "Ricky")
        assert d == {"header": {"name": "Ricky"}}

    def test_multiple_dotted_keys_same_parent(self):
        d = {}
        _set_nested(d, "header.name", "Ricky")
        _set_nested(d, "header.email", "a@b.com")
        assert d == {"header": {"name": "Ricky", "email": "a@b.com"}}

    def test_three_levels(self):
        d = {}
        _set_nested(d, "a.b.c", "deep")
        assert d == {"a": {"b": {"c": "deep"}}}


# -- Fresh-clone guard --------------------------------------------------------


class TestFreshCloneGuard:

    def test_example_profile_raises(self, tmp_path):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        example = profiles_dir / "personal.vars.config.example.yaml"
        example.write_text("header_name: First Last\n")

        with pytest.raises(RunError, match="personal vars config"):
            _load_profile("personal", profiles_dir)

    def test_real_profile_loads(self, tmp_path):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        real = profiles_dir / "personal.vars.config.yaml"
        real.write_text("header_name: Ricky Chen\n")

        result = _load_profile("personal", profiles_dir)
        assert result["header_name"] == "Ricky Chen"

    def test_missing_profile_raises(self, tmp_path):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()

        with pytest.raises(FileNotFoundError):
            _load_profile("personal", profiles_dir)


# -- Skip existing output tests -----------------------------------------------

import shutil
import time

from lib.runner import run_invoke

# Locate blueprint-render directory relative to this test file
_BP_DIR = Path(__file__).resolve().parent.parent
_FIXTURES = _BP_DIR / "tests" / "fixtures"


def _setup_repo(tmp_path, emit_format="yaml"):
    """Create a minimal repo structure for run_invoke tests.

    Copies widget fixtures to root and the yaml renderer to
    scripts/blueprint-render/renderers/ so the process file's
    render path resolves.

    emit_format controls the emit key in the process file. Use
    "pdf" to test skip behavior (skip only applies to PDFs).
    The yaml renderer is used regardless — format key controls
    the output extension and skip logic, not the renderer.
    """
    root = tmp_path / "repo"
    root.mkdir()

    # Renderer at the root-relative path the process file expects
    renderers_dir = root / "scripts" / "blueprint-render" / "renderers"
    renderers_dir.mkdir(parents=True)
    shutil.copy(_BP_DIR / "renderers" / "yaml.py", renderers_dir)

    # Fixtures at root level
    for name in [
        "bp.invoke.widget.yaml",
        "bp.schema.widget.yaml",
        "bp.data.widget.yaml",
    ]:
        shutil.copy(_FIXTURES / name, root)

    # Process file with configurable emit format
    process_content = (
        "vars:\n"
        "  $schema: 'https://json-schema.org/draft/2020-12/schema'\n"
        "  type: object\n"
        "  additionalProperties: false\n"
        "  required: [title]\n"
        "  properties:\n"
        "    title: {type: string}\n"
        "    color: {type: [string, 'null']}\n"
        "\n"
        "map:\n"
        "  widget.title: {var: title}\n"
        "  widget.color: {var: color}\n"
        "\n"
        f"emit:\n"
        f"  {emit_format}:\n"
        f"    render: scripts/blueprint-render/renderers/yaml.py\n"
        "\n"
        "output: adjacent\n"
    )
    (root / "bp.process.widget.yaml").write_text(process_content)

    # Enum fixture (needed by discover)
    enums_dir = root / "test-enums"
    enums_dir.mkdir()
    shutil.copy(_FIXTURES / "test-enums" / "bp.enum.colors.yaml", enums_dir)

    # Tool dir (profiles dir needed by runner)
    tool_dir = root / "scripts" / "blueprint-render"
    profiles_dir = tool_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    return root, tool_dir


class TestSkipExisting:

    def test_yaml_always_rerenders(self, tmp_path):
        """YAML outputs always re-render (deterministic format)."""
        root, tool_dir = _setup_repo(tmp_path, emit_format="yaml")
        invoke_path = root / "bp.invoke.widget.yaml"

        # First render
        rendered, _, _ = run_invoke(invoke_path, root, tool_dir, force=False)
        output_path = rendered[0]
        output_path.write_text("sentinel")

        # Second render should overwrite (YAML doesn't skip)
        rendered2, skipped2, _ = run_invoke(
            invoke_path, root, tool_dir, force=False
        )

        assert len(rendered2) == 1
        assert len(skipped2) == 0
        assert output_path.read_text() != "sentinel"

    def test_pdf_skips_when_output_exists(self, tmp_path):
        """PDF outputs skip when they exist (non-deterministic metadata)."""
        root, tool_dir = _setup_repo(tmp_path, emit_format="pdf")
        invoke_path = root / "bp.invoke.widget.yaml"

        # First render
        rendered, _, _ = run_invoke(invoke_path, root, tool_dir, force=False)
        output_path = rendered[0]
        assert output_path.suffix == ".pdf"
        output_path.write_text("sentinel")

        # Second render should skip
        rendered2, skipped2, _ = run_invoke(
            invoke_path, root, tool_dir, force=False
        )

        assert len(rendered2) == 0
        assert len(skipped2) == 1
        assert output_path.read_text() == "sentinel"

    def test_pdf_renders_when_force_true(self, tmp_path):
        """PDF outputs re-render with --force."""
        root, tool_dir = _setup_repo(tmp_path, emit_format="pdf")
        invoke_path = root / "bp.invoke.widget.yaml"

        run_invoke(invoke_path, root, tool_dir, force=False)
        output_path = root / "bp.output.widget.pdf"
        output_path.write_text("sentinel")

        rendered, skipped, _ = run_invoke(
            invoke_path, root, tool_dir, force=True
        )

        assert len(rendered) == 1
        assert len(skipped) == 0
        assert output_path.read_text() != "sentinel"

    def test_skipped_path_matches_output(self, tmp_path):
        root, tool_dir = _setup_repo(tmp_path, emit_format="pdf")
        invoke_path = root / "bp.invoke.widget.yaml"

        rendered, _, _ = run_invoke(invoke_path, root, tool_dir, force=False)
        output_path = rendered[0]

        _, skipped, _ = run_invoke(invoke_path, root, tool_dir, force=False)

        assert skipped[0] == output_path

    def test_renders_when_output_does_not_exist(self, tmp_path):
        """Both YAML and PDF render normally when no output exists."""
        root, tool_dir = _setup_repo(tmp_path, emit_format="pdf")
        invoke_path = root / "bp.invoke.widget.yaml"

        rendered, skipped, warnings = run_invoke(
            invoke_path, root, tool_dir, force=False
        )

        assert len(rendered) == 1
        assert len(skipped) == 0
        assert rendered[0].exists()


# -- enum_keys resolution -----------------------------------------------------


def _write_enum(tmp_path, filename, values_keys):
    """Write a minimal bp.enum file with the given keys."""
    content = {"values": {k: f"Description for {k}" for k in values_keys}}
    path = tmp_path / filename
    with open(path, "w") as f:
        yaml.dump(content, f, sort_keys=False)
    return path


class TestLoadEnumKeys:

    def test_returns_keys_in_order(self, tmp_path):
        _write_enum(tmp_path, "bp.enum.stages.yaml",
                    ["discovered", "evaluating", "applied", "stale"])
        result = _load_enum_keys("bp.enum.stages.yaml", tmp_path)
        assert result == ["discovered", "evaluating", "applied", "stale"]

    def test_preserves_insertion_order(self, tmp_path):
        _write_enum(tmp_path, "bp.enum.stages.yaml",
                    ["z_last", "a_first", "m_middle"])
        result = _load_enum_keys("bp.enum.stages.yaml", tmp_path)
        assert result == ["z_last", "a_first", "m_middle"]

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RunError, match="enum file not found"):
            _load_enum_keys("nonexistent.yaml", tmp_path)

    def test_no_values_key_raises(self, tmp_path):
        path = tmp_path / "bp.enum.bad.yaml"
        path.write_text("not_values:\n  a: description\n")
        with pytest.raises(RunError, match="missing 'values' map"):
            _load_enum_keys("bp.enum.bad.yaml", tmp_path)

    def test_empty_values_returns_empty_list(self, tmp_path):
        path = tmp_path / "bp.enum.empty.yaml"
        path.write_text("values: {}\n")
        result = _load_enum_keys("bp.enum.empty.yaml", tmp_path)
        assert result == []


class TestResolveParamsEnumKeys:

    def test_enum_keys_goes_to_var_params(self, tmp_path):
        _write_enum(tmp_path, "bp.enum.stages.yaml",
                    ["discovered", "applied"])
        params = {
            "stage_order": {"enum_keys": "bp.enum.stages.yaml"},
        }
        data_params, var_params = _resolve_params(params, {}, tmp_path)
        assert "stage_order" not in data_params
        assert var_params["stage_order"] == ["discovered", "applied"]

    def test_enum_keys_alongside_literal(self, tmp_path):
        _write_enum(tmp_path, "bp.enum.stages.yaml",
                    ["discovered", "applied"])
        params = {
            "stage_order": {"enum_keys": "bp.enum.stages.yaml"},
            "priority_order": {"literal": ["high", "low"]},
        }
        _, var_params = _resolve_params(params, {}, tmp_path)
        assert var_params["stage_order"] == ["discovered", "applied"]
        assert var_params["priority_order"] == ["high", "low"]

    def test_enum_keys_missing_file_raises(self, tmp_path):
        params = {
            "stage_order": {"enum_keys": "nonexistent.yaml"},
        }
        with pytest.raises(RunError, match="enum file not found"):
            _resolve_params(params, {}, tmp_path)


# -- Named output + renderout early exit --------------------------------------


def _setup_named_output_repo(tmp_path):
    """Create a repo with a named-output process file (index rollup pattern)."""
    root, tool_dir = _setup_repo(tmp_path, emit_format="yaml")

    # Overwrite process file with named output
    process_content = (
        "vars:\n"
        "  $schema: 'https://json-schema.org/draft/2020-12/schema'\n"
        "  type: object\n"
        "  additionalProperties: false\n"
        "  required: [title]\n"
        "  properties:\n"
        "    title: {type: string}\n"
        "    color: {type: [string, 'null']}\n"
        "\n"
        "map:\n"
        "  widget.title: {var: title}\n"
        "  widget.color: {var: color}\n"
        "\n"
        "emit:\n"
        "  yaml:\n"
        "    render: scripts/blueprint-render/renderers/yaml.py\n"
        "\n"
        'output:\n'
        '  name: "_INDEX.yaml"\n'
    )
    (root / "bp.process.widget.yaml").write_text(process_content)
    return root, tool_dir


class TestNamedOutputRenderout:

    def test_renderout_skips_named_output(self, tmp_path):
        """Named-output invokes produce nothing in renderout mode."""
        root, tool_dir = _setup_named_output_repo(tmp_path)
        invoke_path = root / "bp.invoke.widget.yaml"

        rendered, skipped, warnings = run_invoke(
            invoke_path, root, tool_dir,
            output_scope="renderout",
        )

        assert rendered == []
        assert skipped == []
        assert warnings == []

    def test_adjacent_renders_named_output(self, tmp_path):
        """Named-output invokes render normally in adjacent mode."""
        root, tool_dir = _setup_named_output_repo(tmp_path)
        invoke_path = root / "bp.invoke.widget.yaml"

        rendered, skipped, warnings = run_invoke(
            invoke_path, root, tool_dir,
            output_scope="adjacent",
        )

        assert len(rendered) == 1
        assert rendered[0].name == "_INDEX.yaml"

    def test_all_renders_named_output(self, tmp_path):
        """Named-output invokes render normally in default (all) mode."""
        root, tool_dir = _setup_named_output_repo(tmp_path)
        invoke_path = root / "bp.invoke.widget.yaml"

        rendered, skipped, warnings = run_invoke(
            invoke_path, root, tool_dir,
            output_scope="all",
        )

        assert len(rendered) == 1
        assert rendered[0].name == "_INDEX.yaml"
