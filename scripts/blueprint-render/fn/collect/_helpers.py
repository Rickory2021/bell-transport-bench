# scripts/blueprint-render/fn/collect/_helpers.py
"""Shared extraction helpers for collect fn modules.

Pure functions for field access, transforms, and per-item field
extraction. Used by extract_fields (multi-file walk) and
extract_list (single-file list walk).

Not a standalone fn module. No run() export.
"""


def get_nested(data, dotted_path):
    """Access a nested value via dotted path.

    "profile_fit.gaps" -> data["profile_fit"]["gaps"]
    Returns None if any segment is missing.
    """
    current = data
    for segment in dotted_path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return None
    return current


def first_sentence(text):
    """Extract the first non-empty line from a string."""
    if not text:
        return ""
    for line in str(text).split("\n"):
        line = line.strip()
        if line:
            return line
    return ""


def exclude_keys(value, keys_to_exclude):
    """Recursively remove specified keys from a nested dict.

    Returns a new dict with the keys removed at all nesting levels.
    Non-dict values pass through unchanged.
    """
    if not isinstance(value, dict):
        return value
    return {
        k: exclude_keys(v, keys_to_exclude)
        for k, v in value.items()
        if k not in keys_to_exclude
    }


def apply_transform(value, transform, spec=None):
    """Apply a named transform to a value.

    Closed set: first_sentence, count, exclude_keys.
    """
    if transform == "first_sentence":
        return first_sentence(value)
    if transform == "count":
        if isinstance(value, (list, dict)):
            return len(value)
        return 0
    if transform == "exclude_keys":
        keys = (spec or {}).get("exclude", [])
        return exclude_keys(value, set(keys))
    raise ValueError(f"Unknown transform: {transform}")


def extract_fields(data, field_specs):
    """Extract fields from a single dict per the field specs.

    Args:
        data: dict to extract from.
        field_specs: list of field specs, each a dict:
            {path: dotted.path}
            {path: dotted.path, as: output_name}
            {path: dotted.path, transform: name}
            {path: dotted.path, transform: exclude_keys, exclude: [keys]}

    Returns:
        dict of extracted field names to values.
    """
    result = {}
    for spec in field_specs:
        path = spec["path"]
        output_name = spec.get("as", path.split(".")[-1])
        transform = spec.get("transform")

        value = get_nested(data, path)
        if transform:
            value = apply_transform(value, transform, spec)

        result[output_name] = value
    return result
