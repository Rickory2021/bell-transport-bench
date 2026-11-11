# scripts/blueprint-render/tests/test_enum_registry.py
"""Tests for the bp: scheme $ref retrieve callback.

Uses fixtures/ as a mock repo root with a test-enums/ directory
containing bp.enum.colors.yaml.
"""

import pytest
from pathlib import Path
from jsonschema import Draft202012Validator

from lib.enum_registry import build_enum_registry

FIXTURES = Path(__file__).parent / "fixtures"


class TestBuildEnumRegistry:
    """Build and use a referencing.Registry with bp: resolution."""

    def test_valid_enum_resolves(self):
        registry = build_enum_registry(FIXTURES)
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "color": {"$ref": "bp:test-enums/bp.enum.colors.yaml"}
            },
        }
        validator = Draft202012Validator(schema, registry=registry)
        errors = list(validator.iter_errors({"color": "red"}))
        assert errors == []

    def test_invalid_value_caught(self):
        registry = build_enum_registry(FIXTURES)
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "color": {"$ref": "bp:test-enums/bp.enum.colors.yaml"}
            },
        }
        validator = Draft202012Validator(schema, registry=registry)
        errors = list(validator.iter_errors({"color": "purple"}))
        assert len(errors) == 1
        assert "purple" in errors[0].message

    def test_nullable_enum_accepts_null(self):
        registry = build_enum_registry(FIXTURES)
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "color": {
                    "anyOf": [
                        {"$ref": "bp:test-enums/bp.enum.colors.yaml"},
                        {"type": "null"},
                    ]
                }
            },
        }
        validator = Draft202012Validator(schema, registry=registry)
        # null should pass
        assert list(validator.iter_errors({"color": None})) == []
        # valid enum should pass
        assert list(validator.iter_errors({"color": "blue"})) == []
        # invalid enum should fail
        errors = list(validator.iter_errors({"color": "purple"}))
        assert len(errors) == 1

    def test_missing_file_raises(self):
        """Missing bp.enum file raises during validation.

        The referencing library wraps our FileNotFoundError in
        its own Unresolvable exception, which jsonschema wraps
        again. The important thing is it doesn't pass silently.
        """
        registry = build_enum_registry(FIXTURES)
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "color": {"$ref": "bp:nonexistent/bp.enum.nope.yaml"}
            },
        }
        validator = Draft202012Validator(schema, registry=registry)
        with pytest.raises(Exception, match="[Uu]nresolvable"):
            list(validator.iter_errors({"color": "red"}))

    def test_non_bp_scheme_raises(self):
        registry = build_enum_registry(FIXTURES)
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "color": {"$ref": "http://example.com/colors"}
            },
        }
        validator = Draft202012Validator(schema, registry=registry)
        # The retrieve callback should raise for non-bp schemes
        with pytest.raises(Exception):
            list(validator.iter_errors({"color": "red"}))
