# scripts/blueprint-render/lib/validate.py
"""Structural and contract validation for the bp file system.

Runs two of the three validation layers defined in the tech spec:

Layer 1 (structural):
  - bp.schema files pass Draft202012Validator.check_schema()
  - bp.enum files have canonical form (single 'values' key, map value)
  - bp.process files have required top-level keys (vars, map, emit,
    output) and vars is valid JSON Schema
  - bp.invoke files have valid import structure (if present)

Layer 2 (contract):
  - bp.data files validate against their bp.schema via
    Draft202012Validator with bp: enum resolution
  - bp.invoke files validate against their bp.process vars via
    Draft202012Validator (import key stripped before validation)

Layer 3 (relationship) is out of scope. Cross-file reference
checks (employer exists, evidence paths resolve, fn paths exist)
are deferred to P4+.

All checks are error tier: any failure blocks.
"""

from pathlib import Path

from jsonschema import Draft202012Validator, SchemaError

from lib.config import load_yaml
from lib.enum_registry import build_enum_registry


class ValidationResult:
    """Accumulates pass/fail/warn results with error details."""

    def __init__(self):
        self.results = []
        self.warnings = []

    def add_pass(self, rel_path, check_type):
        self.results.append((rel_path, check_type, []))

    def add_fail(self, rel_path, check_type, errors):
        self.results.append((rel_path, check_type, list(errors)))

    def add_warn(self, rel_path, check_type, warnings):
        """Warning tier: reported but never blocks."""
        self.warnings.append((rel_path, check_type, list(warnings)))

    @property
    def passed(self):
        return all(len(errs) == 0 for _, _, errs in self.results)

    @property
    def pass_count(self):
        return sum(1 for _, _, errs in self.results if not errs)

    @property
    def fail_count(self):
        return sum(1 for _, _, errs in self.results if errs)

    @property
    def warn_count(self):
        return len(self.warnings)

    def format_report(self, color=False, verbose=False):
        """Format results as a human-readable report.

        Default (quiet): only FAIL and WARN lines with details.
        Verbose: all PASS, FAIL, and WARN lines.
        When color is True, PASS is green, FAIL is red, WARN is yellow.
        """
        if color:
            green = "\033[32m"
            red = "\033[31m"
            yellow = "\033[33m"
            reset = "\033[0m"
        else:
            green = red = yellow = reset = ""

        lines = []
        for rel_path, check_type, errors in self.results:
            if not errors:
                if verbose:
                    lines.append(
                        f"{green}PASS{reset}  {rel_path}  ({check_type})"
                    )
            else:
                lines.append(
                    f"{red}FAIL{reset}  {rel_path}  ({check_type})"
                )
                for err in errors:
                    lines.append(f"      {err}")

        for rel_path, check_type, warns in self.warnings:
            lines.append(
                f"{yellow}WARN{reset}  {rel_path}  ({check_type})"
            )
            for w in warns:
                lines.append(f"      {w}")

        return "\n".join(lines)

    def format_summary(self, color=False):
        """Format the pass/fail/warn summary line."""
        if color:
            green = "\033[32m"
            red = "\033[31m"
            yellow = "\033[33m"
            reset = "\033[0m"
        else:
            green = red = yellow = reset = ""

        parts = []
        if self.pass_count:
            parts.append(f"{green}{self.pass_count} passed{reset}")
        if self.fail_count:
            parts.append(f"{red}{self.fail_count} failed{reset}")
        if self.warn_count:
            parts.append(f"{yellow}{self.warn_count} warned{reset}")
        return ", ".join(parts)


def validate_schema_self(schema_path, root):
    """Validate that a bp.schema file is valid JSON Schema.

    Uses check_schema() which raises SchemaError on invalid
    schemas. The enum registry is needed because check_schema
    does not resolve $ref, but loading the schema through
    load_yaml is sufficient for structural validation.

    Returns list of error strings (empty = pass).
    """
    errors = []
    try:
        data = load_yaml(schema_path)
        Draft202012Validator.check_schema(data)
    except SchemaError as e:
        errors.append(f"Invalid schema: {e.message}")
    except Exception as e:
        errors.append(f"Load error: {e}")
    return errors


def validate_enum_form(enum_path):
    """Validate bp.enum canonical form.

    Canonical form (from tech spec):
      - Exactly one top-level key named 'values'
      - 'values' holds a map (dict), never a list
      - Keys are the legal values; bodies are documentation

    Returns list of error strings (empty = pass).
    """
    errors = []
    try:
        data = load_yaml(enum_path)
    except Exception as e:
        errors.append(f"Load error: {e}")
        return errors

    if not isinstance(data, dict):
        errors.append(
            f"Top level must be a map, got {type(data).__name__}"
        )
        return errors

    keys = list(data.keys())
    if keys != ["values"]:
        errors.append(
            f"Must have exactly one top-level key 'values', "
            f"got: {keys}"
        )
        return errors

    if not isinstance(data["values"], dict):
        errors.append(
            f"'values' must be a map, "
            f"got {type(data['values']).__name__}"
        )

    return errors


def validate_data_contract(data_path, schema_path, enum_registry):
    """Validate bp.data against its bp.schema using jsonschema.

    Resolves bp: $ref via the provided enum registry.

    Returns list of error strings (empty = pass).
    """
    errors = []
    try:
        data = load_yaml(data_path)
        schema = load_yaml(schema_path)
    except Exception as e:
        errors.append(f"Load error: {e}")
        return errors

    try:
        validator = Draft202012Validator(schema, registry=enum_registry)
        for error in sorted(
            validator.iter_errors(data), key=lambda e: e.json_path
        ):
            errors.append(f"{error.json_path}: {error.message}")
    except Exception as e:
        errors.append(f"Validation setup error: {e}")

    return errors


def validate_process_structure(path, root):
    """Validate bp.process outer shape.

    Structural checks (error tier):
      - Required top-level keys: vars, map, emit, output
      - vars section is valid JSON Schema (check_schema)

    Returns list of error strings (empty = pass).
    """
    errors = []
    try:
        data = load_yaml(path)
    except Exception as e:
        errors.append(f"Load error: {e}")
        return errors

    if not isinstance(data, dict):
        errors.append(
            f"Top level must be a map, got {type(data).__name__}"
        )
        return errors

    required_keys = {"vars", "map", "emit", "output"}
    missing = required_keys - set(data.keys())
    if missing:
        errors.append(
            f"Missing required top-level keys: {sorted(missing)}"
        )
        return errors

    # vars section must be valid JSON Schema
    try:
        Draft202012Validator.check_schema(data["vars"])
    except SchemaError as e:
        errors.append(f"vars: invalid JSON Schema: {e.message}")

    return errors


def validate_invoke_structure(path):
    """Validate bp.invoke import structure.

    If the 'import' key is present, it must be a list of dicts
    each containing a 'profile' key. All other keys are var
    assignments validated separately by the contract check.

    Returns list of error strings (empty = pass).
    """
    errors = []
    try:
        data = load_yaml(path)
    except Exception as e:
        errors.append(f"Load error: {e}")
        return errors

    if not isinstance(data, dict):
        errors.append(
            f"Top level must be a map, got {type(data).__name__}"
        )
        return errors

    if "import" in data:
        imports = data["import"]
        if not isinstance(imports, list):
            errors.append(
                f"'import' must be a list, "
                f"got {type(imports).__name__}"
            )
            return errors
        for i, entry in enumerate(imports):
            if not isinstance(entry, dict):
                errors.append(
                    f"import[{i}]: must be a map, "
                    f"got {type(entry).__name__}"
                )
            elif "profile" not in entry:
                errors.append(
                    f"import[{i}]: missing required key 'profile'"
                )

    return errors


def validate_invoke_contract(invoke_path, process_path, enum_registry):
    """Validate bp.invoke against its bp.process vars schema.

    Strips the 'import' reserved engine key before validation.
    All remaining keys must satisfy the process's vars section
    (a JSON Schema document).

    Returns list of error strings (empty = pass).
    """
    errors = []
    try:
        invoke_data = load_yaml(invoke_path)
        process_data = load_yaml(process_path)
    except Exception as e:
        errors.append(f"Load error: {e}")
        return errors

    vars_schema = process_data.get("vars")
    if not vars_schema:
        errors.append("Process file has no vars section")
        return errors

    # Strip reserved engine key before contract check
    invoke_vars = {
        k: v for k, v in invoke_data.items() if k != "import"
    }

    try:
        validator = Draft202012Validator(
            vars_schema, registry=enum_registry
        )
        for error in sorted(
            validator.iter_errors(invoke_vars),
            key=lambda e: e.json_path,
        ):
            errors.append(f"{error.json_path}: {error.message}")
    except Exception as e:
        errors.append(f"Validation setup error: {e}")

    return errors


def run_all(registry, root):
    """Run all validation checks against discovered bp files.

    Checks run in order:
      1. Schema self-validation (check_schema)
      2. Enum canonical form
      3. Data-vs-schema contract (with enum resolution)
      4. Process structural validation (outer shape + vars schema)
      5. Invoke structural + contract validation

    Unbound data files (no matching schema) and unbound invoke
    files (no matching process) are reported as binding errors.

    Args:
        registry: output of binding.discover()
        root: repo root path (Path or str)

    Returns a ValidationResult.
    """
    from lib.binding import (
        build_schema_data_map, get_schema_path,
        build_process_invoke_map, get_process_path,
    )

    root = Path(root)
    result = ValidationResult()
    enum_reg = build_enum_registry(root)

    def _rel(path):
        """Convert absolute path to root-relative string."""
        try:
            return str(Path(path).relative_to(root))
        except ValueError:
            return str(path)

    # 1. Schema self-validation
    for path, _key, _qualifier in registry["schema"]:
        errors = validate_schema_self(path, root)
        rel = _rel(path)
        if errors:
            result.add_fail(rel, "check_schema", errors)
        else:
            result.add_pass(rel, "check_schema")

    # 2. Enum canonical form
    for path, _key, _qualifier in registry["enum"]:
        errors = validate_enum_form(path)
        rel = _rel(path)
        if errors:
            result.add_fail(rel, "canonical_form", errors)
        else:
            result.add_pass(rel, "canonical_form")

    # 3. Data contract validation
    mapping, unbound = build_schema_data_map(registry)

    for schema_key, data_files in sorted(mapping.items()):
        schema_path = get_schema_path(registry, schema_key)
        for data_path, _qualifier in data_files:
            errors = validate_data_contract(
                data_path, schema_path, enum_reg
            )
            rel = _rel(data_path)
            check_label = f"contract: bp.schema.{schema_key}"
            if errors:
                result.add_fail(rel, check_label, errors)
            else:
                result.add_pass(rel, check_label)

    # Report unbound data files
    for path in unbound:
        rel = _rel(path)
        result.add_fail(
            rel, "binding", ["No matching bp.schema found"]
        )

    # 4. Process structural validation
    for path, _key, _qualifier in registry["process"]:
        errors = validate_process_structure(path, root)
        rel = _rel(path)
        if errors:
            result.add_fail(rel, "process_structure", errors)
        else:
            result.add_pass(rel, "process_structure")

    # 5. Invoke structural + contract validation
    proc_mapping, proc_unbound = build_process_invoke_map(registry)

    for process_key, invoke_files in sorted(proc_mapping.items()):
        process_path = get_process_path(registry, process_key)
        for invoke_path, _qualifier in invoke_files:
            rel = _rel(invoke_path)

            # Structural check
            struct_errors = validate_invoke_structure(invoke_path)
            if struct_errors:
                result.add_fail(
                    rel, "invoke_structure", struct_errors
                )
            else:
                result.add_pass(rel, "invoke_structure")

            # Contract check
            contract_errors = validate_invoke_contract(
                invoke_path, process_path, enum_reg
            )
            check_label = f"contract: bp.process.{process_key}"
            if contract_errors:
                result.add_fail(rel, check_label, contract_errors)
            else:
                result.add_pass(rel, check_label)

    # Report unbound invoke files
    for path in proc_unbound:
        rel = _rel(path)
        result.add_fail(
            rel, "binding", ["No matching bp.process found"]
        )

    return result


def run_file(path, registry, root):
    """Validate a single file based on its bp role.

    Args:
        path: path to the file to validate
        registry: output of binding.discover()
        root: repo root path

    Returns a ValidationResult.
    """
    from lib.binding import (
        parse_bp_filename, get_schema_path, get_process_path,
    )

    root = Path(root)
    path = Path(path)
    result = ValidationResult()

    def _rel(p):
        try:
            return str(Path(p).relative_to(root))
        except ValueError:
            return str(p)

    parsed = parse_bp_filename(path.name)
    if parsed is None:
        result.add_fail(
            _rel(path), "grammar", ["Not a valid bp filename"]
        )
        return result

    role, key, _qualifier = parsed

    if role == "schema":
        errors = validate_schema_self(path, root)
        check = "check_schema"
        if errors:
            result.add_fail(_rel(path), check, errors)
        else:
            result.add_pass(_rel(path), check)

    elif role == "enum":
        errors = validate_enum_form(path)
        check = "canonical_form"
        if errors:
            result.add_fail(_rel(path), check, errors)
        else:
            result.add_pass(_rel(path), check)

    elif role == "data":
        schema_path = get_schema_path(registry, key)
        if schema_path is None:
            result.add_fail(
                _rel(path), "binding",
                [f"No bp.schema.{key} found"]
            )
        else:
            enum_reg = build_enum_registry(root)
            errors = validate_data_contract(path, schema_path, enum_reg)
            check = f"contract: bp.schema.{key}"
            if errors:
                result.add_fail(_rel(path), check, errors)
            else:
                result.add_pass(_rel(path), check)

    elif role == "process":
        errors = validate_process_structure(path, root)
        check = "process_structure"
        if errors:
            result.add_fail(_rel(path), check, errors)
        else:
            result.add_pass(_rel(path), check)

    elif role == "invoke":
        # Structural check
        struct_errors = validate_invoke_structure(path)
        if struct_errors:
            result.add_fail(
                _rel(path), "invoke_structure", struct_errors
            )
        else:
            result.add_pass(_rel(path), "invoke_structure")

        # Contract check against process vars
        process_path = get_process_path(registry, key)
        if process_path is None:
            result.add_fail(
                _rel(path), "binding",
                [f"No bp.process.{key} found"]
            )
        else:
            enum_reg = build_enum_registry(root)
            errors = validate_invoke_contract(
                path, process_path, enum_reg
            )
            check = f"contract: bp.process.{key}"
            if errors:
                result.add_fail(_rel(path), check, errors)
            else:
                result.add_pass(_rel(path), check)

    return result


def run_key(key, registry, root):
    """Validate all files with a given binding key.

    Checks both schema+data and process+invoke namespaces for
    the key. The namespaces are independent; a key may exist in
    one or both.

    Returns a ValidationResult.
    """
    from lib.binding import (
        get_schema_path, get_process_path,
    )

    root = Path(root)
    result = ValidationResult()
    enum_reg = build_enum_registry(root)
    found_anything = False

    def _rel(p):
        try:
            return str(Path(p).relative_to(root))
        except ValueError:
            return str(p)

    # Schema + data namespace
    schema_path = get_schema_path(registry, key)
    if schema_path is not None:
        found_anything = True

        errors = validate_schema_self(schema_path, root)
        if errors:
            result.add_fail(
                _rel(schema_path), "check_schema", errors
            )
        else:
            result.add_pass(_rel(schema_path), "check_schema")

        for path, data_key, _qualifier in registry["data"]:
            if data_key != key:
                continue
            errors = validate_data_contract(
                path, schema_path, enum_reg
            )
            rel = _rel(path)
            check = f"contract: bp.schema.{key}"
            if errors:
                result.add_fail(rel, check, errors)
            else:
                result.add_pass(rel, check)

    # Process + invoke namespace
    process_path = get_process_path(registry, key)
    if process_path is not None:
        found_anything = True

        errors = validate_process_structure(process_path, root)
        if errors:
            result.add_fail(
                _rel(process_path), "process_structure", errors
            )
        else:
            result.add_pass(
                _rel(process_path), "process_structure"
            )

        for path, invoke_key, _qualifier in registry["invoke"]:
            if invoke_key != key:
                continue
            rel = _rel(path)

            struct_errors = validate_invoke_structure(path)
            if struct_errors:
                result.add_fail(
                    rel, "invoke_structure", struct_errors
                )
            else:
                result.add_pass(rel, "invoke_structure")

            contract_errors = validate_invoke_contract(
                path, process_path, enum_reg
            )
            check = f"contract: bp.process.{key}"
            if contract_errors:
                result.add_fail(rel, check, contract_errors)
            else:
                result.add_pass(rel, check)

    if not found_anything:
        result.add_fail(
            f"bp.*.{key}", "binding",
            [f"No bp.schema.{key} or bp.process.{key} found"]
        )

    return result
