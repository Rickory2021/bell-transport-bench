# scripts/blueprint-render/lib/binding.py
"""Key discovery and filename law for the bp file system.

Parses bp.<role>.<key>[.<qualifier>].yaml filenames, builds the
key registry across all five roles, and provides schema-to-data
and process-to-invoke mapping via the binding key.

The binding law: the first descriptor segment after the role is
the binding key. bp.data.<key> binds to bp.schema.<key>.
bp.invoke.<key> binds to bp.process.<key>.

Uniqueness rules (error tier):
  - Schema and process keys unique within their role.

Data and enum files are NOT checked for basename uniqueness.
Multiple data files can share a basename (same schema, different
instances, e.g. per-opportunity evaluation files). Enum files
are resolved by full path via $ref, so basename collision is
harmless.
"""

import os
from pathlib import Path

ROLES = frozenset({"schema", "data", "enum", "process", "invoke"})

# Directories pruned from discovery. Hidden directories (any depth)
# are always pruned. _EXCLUDED_TOP applies at the repo root only:
# tool-internal files follow their own conventions. _EXCLUDED_ANYWHERE
# applies at any depth: build output, dependency trees, and
# flatten-sync exports hold no bp files and are costly to walk.
_EXCLUDED_TOP = {"scripts"}
_EXCLUDED_ANYWHERE = {
    "project-export-files", "render-out", "node_modules", "venv",
    "__pycache__",
}


def parse_bp_filename(name):
    """Parse a bp filename into (role, key, qualifier).

    Expects: bp.<role>.<key>[.<qualifier>].yaml

    Returns a (role, key, qualifier) tuple, or None if the
    filename does not match the bp grammar.
    """
    if not name.endswith(".yaml") or not name.startswith("bp."):
        return None

    stem = name.removesuffix(".yaml")
    parts = stem.split(".")

    # Minimum: bp, role, key
    if len(parts) < 3:
        return None

    role = parts[1]
    if role not in ROLES:
        return None

    key = parts[2]
    qualifier = ".".join(parts[3:]) if len(parts) > 3 else None
    return role, key, qualifier


def discover(root):
    """Walk root for bp.* files, pruning excluded dirs during the walk.

    Hidden directories and _EXCLUDED_ANYWHERE names are pruned at any
    depth; _EXCLUDED_TOP names are pruned at the root only. Pruning
    happens before descent, so a .venv or node_modules is never
    visited. Results are sorted by path.

    Returns a dict keyed by role, each value a list of
    (path, key, qualifier) tuples sorted by path.
    """
    root = Path(root)
    registry = {role: [] for role in ROLES}
    found = []

    for dirpath, dirnames, filenames in os.walk(root):
        is_top = Path(dirpath) == root
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".")
            and d not in _EXCLUDED_ANYWHERE
            and not (is_top and d in _EXCLUDED_TOP)
        )
        for name in filenames:
            if name.startswith(".") or not name.endswith(".yaml"):
                continue
            found.append(Path(dirpath) / name)

    for path in sorted(found):
        parsed = parse_bp_filename(path.name)
        if parsed is None:
            continue
        role, key, qualifier = parsed
        registry[role].append((path, key, qualifier))

    return registry


def check_uniqueness(registry):
    """Enforce filename uniqueness rules.

    Error tier:
      - Duplicate keys within schema or process roles.

    Data and enum are not checked. Multiple data files can
    share a basename when they are instances of the same schema
    (e.g. per-opportunity evaluation files). Enum files are
    resolved by full path via $ref.

    Returns a list of error strings (empty = clean).
    """
    errors = []

    # Schema and process: unique keys within role
    for role in ("schema", "process"):
        seen = {}
        for path, key, _qualifier in registry[role]:
            if key in seen:
                errors.append(
                    f"Duplicate {role} key '{key}': "
                    f"{seen[key]} and {path}"
                )
            else:
                seen[key] = path

    return errors


def build_schema_data_map(registry):
    """Map each schema key to its matching data files.

    Returns:
        mapping: dict of schema_key -> list of (data_path, qualifier)
        unbound: list of data paths with no matching schema
    """
    schema_keys = {key for _, key, _ in registry["schema"]}

    mapping = {key: [] for key in schema_keys}
    unbound = []

    for path, key, qualifier in registry["data"]:
        if key in mapping:
            mapping[key].append((path, qualifier))
        else:
            unbound.append(path)

    return mapping, unbound


def get_schema_path(registry, key):
    """Get the file path for a schema by its binding key.

    Returns None if no schema with that key exists.
    """
    for path, k, _ in registry["schema"]:
        if k == key:
            return path
    return None


def build_process_invoke_map(registry):
    """Map each process key to its matching invoke files.

    Returns:
        mapping: dict of process_key -> list of (invoke_path, qualifier)
        unbound: list of invoke paths with no matching process
    """
    process_keys = {key for _, key, _ in registry["process"]}

    mapping = {key: [] for key in process_keys}
    unbound = []

    for path, key, qualifier in registry["invoke"]:
        if key in mapping:
            mapping[key].append((path, qualifier))
        else:
            unbound.append(path)

    return mapping, unbound


def get_process_path(registry, key):
    """Get the file path for a process by its binding key.

    Returns None if no process with that key exists.
    """
    for path, k, _ in registry["process"]:
        if k == key:
            return path
    return None
