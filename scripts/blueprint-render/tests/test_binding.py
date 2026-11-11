# scripts/blueprint-render/tests/test_binding.py
"""Tests for bp filename parsing, discovery, and uniqueness.

Pure function tests for parsing. Filesystem tests use the
fixtures/ directory as a minimal repo root.
"""

import pytest
from pathlib import Path

from lib.binding import (
    parse_bp_filename,
    discover,
    check_uniqueness,
    build_schema_data_map,
    build_process_invoke_map,
    get_process_path,
    ROLES,
)

FIXTURES = Path(__file__).parent / "fixtures"


# -- parse_bp_filename ---------------------------------------------------------


class TestParseBpFilename:
    """Parse bp.<role>.<key>[.<qualifier>].yaml filenames."""

    def test_schema_no_qualifier(self):
        result = parse_bp_filename("bp.schema.career-history.yaml")
        assert result == ("schema", "career-history", None)

    def test_data_with_qualifier(self):
        result = parse_bp_filename("bp.data.story.dupely-v2-overhaul.yaml")
        assert result == ("data", "story", "dupely-v2-overhaul")

    def test_enum_no_qualifier(self):
        result = parse_bp_filename("bp.enum.proficiency-levels.yaml")
        assert result == ("enum", "proficiency-levels", None)

    def test_process_no_qualifier(self):
        result = parse_bp_filename("bp.process.resume.yaml")
        assert result == ("process", "resume", None)

    def test_invoke_with_qualifier(self):
        result = parse_bp_filename("bp.invoke.resume.backend-developer.yaml")
        assert result == ("invoke", "resume", "backend-developer")

    def test_all_five_roles_recognized(self):
        for role in ROLES:
            result = parse_bp_filename(f"bp.{role}.test.yaml")
            assert result is not None
            assert result[0] == role

    def test_unknown_role_returns_none(self):
        assert parse_bp_filename("bp.bogus.test.yaml") is None

    def test_non_bp_prefix_returns_none(self):
        assert parse_bp_filename("SCHEMA.yaml") is None
        assert parse_bp_filename("career-history.yaml") is None

    def test_non_yaml_extension_returns_none(self):
        assert parse_bp_filename("bp.schema.test.json") is None

    def test_too_few_parts_returns_none(self):
        assert parse_bp_filename("bp.schema.yaml") is None
        assert parse_bp_filename("bp.yaml") is None

    def test_multi_segment_qualifier(self):
        result = parse_bp_filename("bp.data.thing.a.b.yaml")
        assert result == ("data", "thing", "a.b")


# -- discover ------------------------------------------------------------------


class TestDiscover:
    """Discover bp files from a directory tree."""

    def test_finds_fixtures(self):
        registry = discover(FIXTURES)
        # Fixtures have: bp.schema.widget, bp.data.widget (3 variants),
        # bp.enum.colors (in test-enums/), bp.enum.bad-list,
        # bp.enum.bad-extra-key, bp.process.widget (2 variants),
        # bp.invoke.widget (3 variants)
        assert len(registry["schema"]) >= 1
        assert len(registry["data"]) >= 1
        assert len(registry["enum"]) >= 1

    def test_extracts_correct_keys(self):
        registry = discover(FIXTURES)
        schema_keys = {key for _, key, _ in registry["schema"]}
        assert "widget" in schema_keys

    def test_finds_nested_enums(self):
        registry = discover(FIXTURES)
        enum_keys = {key for _, key, _ in registry["enum"]}
        assert "colors" in enum_keys

    def test_discovers_process_files(self):
        registry = discover(FIXTURES)
        process_keys = {key for _, key, _ in registry["process"]}
        assert "widget" in process_keys

    def test_discovers_invoke_files(self):
        registry = discover(FIXTURES)
        invoke_keys = {key for _, key, _ in registry["invoke"]}
        assert "widget" in invoke_keys

    def test_all_roles_present_in_registry(self):
        registry = discover(FIXTURES)
        for role in ROLES:
            assert role in registry


# -- check_uniqueness ----------------------------------------------------------


class TestCheckUniqueness:
    """Enforce filename uniqueness rules."""

    def test_clean_registry_no_errors(self):
        registry = {
            "schema": [
                (Path("a/bp.schema.foo.yaml"), "foo", None),
                (Path("b/bp.schema.bar.yaml"), "bar", None),
            ],
            "data": [
                (Path("a/bp.data.foo.yaml"), "foo", None),
                (Path("b/bp.data.bar.baz.yaml"), "bar", "baz"),
            ],
            "enum": [],
            "process": [],
            "invoke": [],
        }
        assert check_uniqueness(registry) == []

    def test_duplicate_schema_key_errors(self):
        registry = {
            "schema": [
                (Path("a/bp.schema.foo.yaml"), "foo", None),
                (Path("b/bp.schema.foo.yaml"), "foo", None),
            ],
            "data": [],
            "enum": [],
            "process": [],
            "invoke": [],
        }
        errors = check_uniqueness(registry)
        assert len(errors) == 1
        assert "Duplicate schema key 'foo'" in errors[0]

    def test_duplicate_data_basename_allowed(self):
        """Same-basename data files are valid (instance directories)."""
        registry = {
            "schema": [],
            "data": [
                (Path("a/bp.data.foo.yaml"), "foo", None),
                (Path("b/bp.data.foo.yaml"), "foo", None),
            ],
            "enum": [],
            "process": [],
            "invoke": [],
        }
        assert check_uniqueness(registry) == []

    def test_duplicate_process_key_errors(self):
        registry = {
            "schema": [],
            "data": [],
            "enum": [],
            "process": [
                (Path("a/bp.process.foo.yaml"), "foo", None),
                (Path("b/bp.process.foo.yaml"), "foo", None),
            ],
            "invoke": [],
        }
        errors = check_uniqueness(registry)
        assert len(errors) == 1
        assert "Duplicate process key 'foo'" in errors[0]

    def test_same_key_across_roles_ok(self):
        """Cross-role key reuse is legal per the tech spec."""
        registry = {
            "schema": [(Path("a/bp.schema.foo.yaml"), "foo", None)],
            "data": [(Path("a/bp.data.foo.yaml"), "foo", None)],
            "enum": [(Path("a/bp.enum.foo.yaml"), "foo", None)],
            "process": [(Path("a/bp.process.foo.yaml"), "foo", None)],
            "invoke": [(Path("a/bp.invoke.foo.yaml"), "foo", None)],
        }
        assert check_uniqueness(registry) == []


# -- build_schema_data_map -----------------------------------------------------


class TestBuildSchemaDataMap:
    """Map schema keys to their data files."""

    def test_binds_by_key(self):
        registry = {
            "schema": [
                (Path("bp.schema.foo.yaml"), "foo", None),
            ],
            "data": [
                (Path("a/bp.data.foo.yaml"), "foo", None),
                (Path("a/bp.data.foo.bar.yaml"), "foo", "bar"),
            ],
            "enum": [],
            "process": [],
            "invoke": [],
        }
        mapping, unbound = build_schema_data_map(registry)
        assert len(mapping["foo"]) == 2
        assert unbound == []

    def test_unbound_data_reported(self):
        registry = {
            "schema": [],
            "data": [
                (Path("bp.data.orphan.yaml"), "orphan", None),
            ],
            "enum": [],
            "process": [],
            "invoke": [],
        }
        mapping, unbound = build_schema_data_map(registry)
        assert len(unbound) == 1


# -- build_process_invoke_map --------------------------------------------------


class TestBuildProcessInvokeMap:
    """Map process keys to their invoke files."""

    def test_binds_by_key(self):
        registry = {
            "schema": [],
            "data": [],
            "enum": [],
            "process": [
                (Path("bp.process.resume.yaml"), "resume", None),
            ],
            "invoke": [
                (Path("a/bp.invoke.resume.yaml"), "resume", None),
                (Path("b/bp.invoke.resume.backend.yaml"), "resume", "backend"),
            ],
        }
        mapping, unbound = build_process_invoke_map(registry)
        assert len(mapping["resume"]) == 2
        assert unbound == []

    def test_unbound_invoke_reported(self):
        registry = {
            "schema": [],
            "data": [],
            "enum": [],
            "process": [],
            "invoke": [
                (Path("bp.invoke.orphan.yaml"), "orphan", None),
            ],
        }
        mapping, unbound = build_process_invoke_map(registry)
        assert len(unbound) == 1

    def test_get_process_path_found(self):
        registry = {
            "schema": [],
            "data": [],
            "enum": [],
            "process": [
                (Path("a/bp.process.resume.yaml"), "resume", None),
            ],
            "invoke": [],
        }
        assert get_process_path(registry, "resume") == Path("a/bp.process.resume.yaml")

    def test_get_process_path_not_found(self):
        registry = {
            "schema": [],
            "data": [],
            "enum": [],
            "process": [],
            "invoke": [],
        }
        assert get_process_path(registry, "resume") is None
