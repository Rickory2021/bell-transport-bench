# scripts/blueprint-render/tests/test_validate.py
"""Tests for structural and contract validation.

Uses fixtures/ as a mock repo root. Tests cover:
  - Schema self-validation (check_schema)
  - Enum canonical form
  - Data contract validation (valid passes, seeded errors fail)
  - Date normalization integration (bare year in data)
  - Process structural validation (outer shape + vars schema)
  - Invoke structural validation (import format)
  - Invoke contract validation (against process vars)
  - Error format
"""

import pytest
from pathlib import Path

from lib.binding import discover
from lib.enum_registry import build_enum_registry
from lib.validate import (
    validate_schema_self,
    validate_enum_form,
    validate_data_contract,
    validate_process_structure,
    validate_invoke_structure,
    validate_invoke_contract,
    run_all,
    run_file,
    ValidationResult,
)

FIXTURES = Path(__file__).parent / "fixtures"


# -- validate_schema_self ------------------------------------------------------


class TestValidateSchemaSelf:
    """check_schema on bp.schema files."""

    def test_valid_schema_passes(self):
        path = FIXTURES / "bp.schema.widget.yaml"
        errors = validate_schema_self(path, FIXTURES)
        assert errors == []

    def test_nonexistent_file_errors(self):
        path = FIXTURES / "bp.schema.nope.yaml"
        errors = validate_schema_self(path, FIXTURES)
        assert len(errors) == 1
        assert "Load error" in errors[0]


# -- validate_enum_form --------------------------------------------------------


class TestValidateEnumForm:
    """Canonical form checks on bp.enum files."""

    def test_valid_enum_passes(self):
        path = FIXTURES / "test-enums" / "bp.enum.colors.yaml"
        errors = validate_enum_form(path)
        assert errors == []

    def test_list_values_fails(self):
        path = FIXTURES / "bp.enum.bad-list.yaml"
        errors = validate_enum_form(path)
        assert len(errors) == 1
        assert "must be a map" in errors[0]

    def test_extra_key_fails(self):
        path = FIXTURES / "bp.enum.bad-extra-key.yaml"
        errors = validate_enum_form(path)
        assert len(errors) == 1
        assert "exactly one top-level key" in errors[0]


# -- validate_data_contract ----------------------------------------------------


class TestValidateDataContract:
    """Data-vs-schema contract validation."""

    def test_valid_data_passes(self):
        enum_reg = build_enum_registry(FIXTURES)
        errors = validate_data_contract(
            FIXTURES / "bp.data.widget.yaml",
            FIXTURES / "bp.schema.widget.yaml",
            enum_reg,
        )
        assert errors == []

    def test_invalid_data_fails(self):
        enum_reg = build_enum_registry(FIXTURES)
        errors = validate_data_contract(
            FIXTURES / "bp.data.widget.bad.yaml",
            FIXTURES / "bp.schema.widget.yaml",
            enum_reg,
        )
        # Should catch: invalid enum value + missing required field
        assert len(errors) >= 2
        error_text = " ".join(errors)
        assert "purple" in error_text
        assert "year" in error_text

    def test_date_normalization_makes_bare_year_pass(self):
        """Bare 2024 in YAML loads as int. Normalization converts
        to '2024' so the string type + pattern check passes."""
        enum_reg = build_enum_registry(FIXTURES)
        errors = validate_data_contract(
            FIXTURES / "bp.data.widget.dates.yaml",
            FIXTURES / "bp.schema.widget.yaml",
            enum_reg,
        )
        assert errors == []


# -- validate_process_structure ------------------------------------------------


class TestValidateProcessStructure:
    """Outer shape checks on bp.process files."""

    def test_valid_process_passes(self):
        errors = validate_process_structure(
            FIXTURES / "bp.process.widget.yaml", FIXTURES
        )
        assert errors == []

    def test_missing_keys_fails(self):
        errors = validate_process_structure(
            FIXTURES / "bp.process.widget.bad.yaml", FIXTURES
        )
        assert len(errors) == 1
        assert "Missing required top-level keys" in errors[0]
        assert "emit" in errors[0]
        assert "output" in errors[0]

    def test_nonexistent_file_errors(self):
        errors = validate_process_structure(
            FIXTURES / "bp.process.nope.yaml", FIXTURES
        )
        assert len(errors) == 1
        assert "Load error" in errors[0]


# -- validate_invoke_structure -------------------------------------------------


class TestValidateInvokeStructure:
    """Import format checks on bp.invoke files."""

    def test_valid_invoke_no_import_passes(self):
        errors = validate_invoke_structure(
            FIXTURES / "bp.invoke.widget.yaml"
        )
        assert errors == []

    def test_valid_invoke_with_import_passes(self):
        errors = validate_invoke_structure(
            FIXTURES / "bp.invoke.widget.with-import.yaml"
        )
        assert errors == []

    def test_nonexistent_file_errors(self):
        errors = validate_invoke_structure(
            FIXTURES / "bp.invoke.nope.yaml"
        )
        assert len(errors) == 1
        assert "Load error" in errors[0]

    def test_import_not_list_fails(self, tmp_path):
        invoke = tmp_path / "bp.invoke.widget.yaml"
        invoke.write_text("import: {profile: personal}\ntitle: x\n")
        errors = validate_invoke_structure(invoke)
        assert len(errors) == 1
        assert "must be a list" in errors[0]

    def test_import_entry_missing_profile_fails(self, tmp_path):
        invoke = tmp_path / "bp.invoke.widget.yaml"
        invoke.write_text(
            "import:\n  - {as: ctx}\ntitle: x\n"
        )
        errors = validate_invoke_structure(invoke)
        assert len(errors) == 1
        assert "missing required key 'profile'" in errors[0]

    def test_import_entry_not_map_fails(self, tmp_path):
        invoke = tmp_path / "bp.invoke.widget.yaml"
        invoke.write_text(
            "import:\n  - personal\ntitle: x\n"
        )
        errors = validate_invoke_structure(invoke)
        assert len(errors) == 1
        assert "must be a map" in errors[0]


# -- validate_invoke_contract --------------------------------------------------


class TestValidateInvokeContract:
    """Invoke-vs-process vars contract validation."""

    def test_valid_invoke_passes(self):
        enum_reg = build_enum_registry(FIXTURES)
        errors = validate_invoke_contract(
            FIXTURES / "bp.invoke.widget.yaml",
            FIXTURES / "bp.process.widget.yaml",
            enum_reg,
        )
        assert errors == []

    def test_invalid_invoke_fails(self):
        enum_reg = build_enum_registry(FIXTURES)
        errors = validate_invoke_contract(
            FIXTURES / "bp.invoke.widget.bad.yaml",
            FIXTURES / "bp.process.widget.yaml",
            enum_reg,
        )
        # Should catch: title is wrong type + unknown_field
        assert len(errors) >= 2
        error_text = " ".join(errors)
        assert "42" in error_text or "integer" in error_text
        assert "unknown_field" in error_text

    def test_import_stripped_before_validation(self):
        """Import key is reserved, not a var. Should not cause
        additionalProperties failure."""
        enum_reg = build_enum_registry(FIXTURES)
        errors = validate_invoke_contract(
            FIXTURES / "bp.invoke.widget.with-import.yaml",
            FIXTURES / "bp.process.widget.yaml",
            enum_reg,
        )
        assert errors == []


# -- run_all -------------------------------------------------------------------


class TestRunAll:
    """Full validation run against the fixtures directory."""

    def test_fixtures_produce_results(self):
        registry = discover(FIXTURES)
        result = run_all(registry, FIXTURES)
        # Should have results for schemas, enums, data, processes,
        # and invokes
        assert len(result.results) > 0

    def test_pass_and_fail_counts(self):
        registry = discover(FIXTURES)
        result = run_all(registry, FIXTURES)
        # We have both valid and invalid fixtures
        assert result.pass_count > 0
        assert result.fail_count > 0

    def test_report_format(self):
        registry = discover(FIXTURES)
        result = run_all(registry, FIXTURES)
        report = result.format_report(verbose=True)
        assert "PASS" in report
        assert "FAIL" in report

    def test_process_checked_in_run_all(self):
        registry = discover(FIXTURES)
        result = run_all(registry, FIXTURES)
        report = result.format_report(verbose=True)
        assert "process_structure" in report

    def test_invoke_checked_in_run_all(self):
        registry = discover(FIXTURES)
        result = run_all(registry, FIXTURES)
        report = result.format_report(verbose=True)
        assert "invoke_structure" in report
        assert "bp.process.widget" in report


# -- run_file ------------------------------------------------------------------


class TestRunFile:
    """Single-file validation dispatch."""

    def test_process_file(self):
        registry = discover(FIXTURES)
        result = run_file(
            FIXTURES / "bp.process.widget.yaml",
            registry, FIXTURES,
        )
        assert result.passed is True
        checks = [c for _, c, _ in result.results]
        assert "process_structure" in checks

    def test_bad_process_file(self):
        registry = discover(FIXTURES)
        result = run_file(
            FIXTURES / "bp.process.widget.bad.yaml",
            registry, FIXTURES,
        )
        assert result.passed is False

    def test_invoke_file(self):
        registry = discover(FIXTURES)
        result = run_file(
            FIXTURES / "bp.invoke.widget.yaml",
            registry, FIXTURES,
        )
        assert result.passed is True
        checks = [c for _, c, _ in result.results]
        assert "invoke_structure" in checks
        assert any("bp.process.widget" in c for c in checks)

    def test_bad_invoke_file(self):
        registry = discover(FIXTURES)
        result = run_file(
            FIXTURES / "bp.invoke.widget.bad.yaml",
            registry, FIXTURES,
        )
        assert result.passed is False


# -- ValidationResult ----------------------------------------------------------


class TestValidationResult:
    """Result accumulator formatting."""

    def test_empty_result_passes(self):
        r = ValidationResult()
        assert r.passed is True
        assert r.pass_count == 0
        assert r.fail_count == 0

    def test_pass_only(self):
        r = ValidationResult()
        r.add_pass("file.yaml", "check")
        assert r.passed is True
        assert r.pass_count == 1

    def test_fail_makes_passed_false(self):
        r = ValidationResult()
        r.add_pass("good.yaml", "check")
        r.add_fail("bad.yaml", "check", ["error"])
        assert r.passed is False
        assert r.pass_count == 1
        assert r.fail_count == 1

    def test_format_report_pass_line(self):
        r = ValidationResult()
        r.add_pass("a/b.yaml", "check_schema")
        report = r.format_report(verbose=True)
        assert "PASS  a/b.yaml  (check_schema)" in report

    def test_format_report_fail_with_details(self):
        r = ValidationResult()
        r.add_fail("a/b.yaml", "contract", ["$.x: bad value"])
        report = r.format_report()
        assert "FAIL  a/b.yaml  (contract)" in report
        assert "$.x: bad value" in report

    def test_format_report_quiet_hides_pass(self):
        r = ValidationResult()
        r.add_pass("good.yaml", "check")
        r.add_fail("bad.yaml", "check", ["error"])
        report = r.format_report(verbose=False)
        assert "PASS" not in report
        assert "FAIL" in report

    def test_format_report_verbose_shows_pass(self):
        r = ValidationResult()
        r.add_pass("good.yaml", "check")
        r.add_fail("bad.yaml", "check", ["error"])
        report = r.format_report(verbose=True)
        assert "PASS" in report
        assert "FAIL" in report

    def test_format_report_color_pass(self):
        r = ValidationResult()
        r.add_pass("a/b.yaml", "check_schema")
        report = r.format_report(color=True, verbose=True)
        assert "\033[32mPASS\033[0m" in report

    def test_format_report_color_fail(self):
        r = ValidationResult()
        r.add_fail("a/b.yaml", "contract", ["error"])
        report = r.format_report(color=True)
        assert "\033[31mFAIL\033[0m" in report

    def test_format_report_no_color_is_plain(self):
        r = ValidationResult()
        r.add_pass("a/b.yaml", "check")
        report = r.format_report(color=False, verbose=True)
        assert "\033[" not in report

    def test_format_summary_color(self):
        r = ValidationResult()
        r.add_pass("a.yaml", "check")
        r.add_fail("b.yaml", "check", ["err"])
        summary = r.format_summary(color=True)
        assert "\033[32m1 passed\033[0m" in summary
        assert "\033[31m1 failed\033[0m" in summary
