# scripts/blueprint-render/lib/enum_registry.py
"""bp: scheme $ref retrieve callback for referencing.Registry.

Schemas reference bp.enum files with $ref: "bp:<path>". The
jsonschema library resolves these via a referencing.Registry
retrieve callback that loads the enum file, extracts the keys
from its values map, and returns {"enum": [keys]}.

Example schema property:
    proficiency:
      $ref: "bp:skills/bp.enum.proficiency-levels.yaml"

The callback loads skills/bp.enum.proficiency-levels.yaml,
reads its values map, and returns:
    {"enum": ["awareness", "working_knowledge", "proficient", "expert"]}
"""

from pathlib import Path

from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from lib.config import load_yaml


def _bp_retrieve(uri, root):
    """Retrieve callback for bp: scheme URIs.

    Loads the bp.enum file at the root-relative path after "bp:",
    extracts keys from the values map, and returns an enum schema
    as a referencing Resource.
    """
    if not uri.startswith("bp:"):
        raise ValueError(f"Unknown URI scheme: {uri}")

    rel_path = uri[3:]  # strip "bp:"
    abs_path = Path(root) / rel_path

    if not abs_path.exists():
        raise FileNotFoundError(
            f"bp.enum file not found: {rel_path} "
            f"(resolved to {abs_path})"
        )

    # load_yaml is the per-run cache, so repeated $ref hits on the
    # same enum cost a dict lookup, not a parse.
    doc = load_yaml(abs_path)

    if not isinstance(doc, dict) or "values" not in doc:
        raise ValueError(
            f"Not a valid bp.enum file (missing 'values' map): "
            f"{rel_path}"
        )

    keys = list(doc["values"].keys())
    schema = {"enum": keys}
    return Resource.from_contents(schema, default_specification=DRAFT202012)


def build_enum_registry(root):
    """Build a referencing.Registry with bp: scheme resolution.

    The registry is reusable across all validation calls within
    the same run. The referencing library caches resolved URIs
    internally.
    """
    root = Path(root).resolve()
    return Registry(retrieve=lambda uri: _bp_retrieve(uri, root))
