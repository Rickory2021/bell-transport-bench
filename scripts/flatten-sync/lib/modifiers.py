# scripts/flatten-sync/lib/modifiers.py
"""Modifier library loading and path matching."""

import re
from pathlib import Path

import yaml

from .prune import parse_path


def load_modifiers(path: Path) -> dict:
    """Load and parse modifiers.yaml.

    Args:
        path: Path to modifiers.yaml file.

    Returns:
        dict of modifier_name -> modifier definition dict.

    Raises:
        FileNotFoundError: if path does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Modifiers file not found: {path}")
    with open(path) as f:
        data = yaml.safe_load(f)
    modifiers = data.get("modifiers", {})
    validate_modifiers(modifiers)
    return modifiers


# -- Condition modifiers --------------------------------------------------------
#
# A condition modifier prunes files by reading a value from a probe file
# instead of matching names. It has a `condition` block and no dirs, files,
# or patterns: mixing the two would apply name matching everywhere and the
# prune on top, which no reader would expect. lib/prune.py runs it.

_NAME_MATCH_FIELDS = ("dirs", "files", "patterns")
_CONDITION_KEYS = {"group", "probe", "path", "when"}
_WHEN_ENTRY_KEYS = {"keep"}


def validate_modifiers(modifiers: dict) -> None:
    """Validate modifier definitions at load time.

    A bad config fails every run loudly here, so the walk never meets a
    malformed condition block. Name-matching modifiers are not checked
    (their fields have always been free-form).

    Raises:
        ValueError: naming the modifier and the problem.
    """
    for name, mod_def in modifiers.items():
        if not isinstance(mod_def, dict) or "condition" not in mod_def:
            continue
        mixed = [f for f in _NAME_MATCH_FIELDS if mod_def.get(f)]
        if mixed:
            raise ValueError(
                f"Modifier '{name}': a condition modifier cannot also set "
                f"{', '.join(mixed)}"
            )
        _validate_condition(name, mod_def["condition"])


def _validate_condition(name: str, condition) -> None:
    if not isinstance(condition, dict):
        raise ValueError(f"Modifier '{name}': condition must be a mapping")

    missing = sorted(_CONDITION_KEYS - condition.keys())
    if missing:
        raise ValueError(f"Modifier '{name}': condition is missing {', '.join(missing)}")
    unknown = sorted(condition.keys() - _CONDITION_KEYS)
    if unknown:
        raise ValueError(f"Modifier '{name}': condition has unknown keys {', '.join(unknown)}")

    for key in ("group", "probe", "path"):
        value = condition[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Modifier '{name}': condition.{key} must be a non-empty string")

    try:
        parse_path(condition["path"])
    except ValueError as exc:
        raise ValueError(f"Modifier '{name}': condition.path {exc}") from None

    group = condition["group"]
    segments = group.split("/")
    if group.startswith("/") or group.endswith("/") or "" in segments or "**" in segments:
        raise ValueError(
            f"Modifier '{name}': condition.group '{group}' must be root-relative "
            "segments with no leading or trailing slash, empty segment, or '**'"
        )

    when = condition["when"]
    if not isinstance(when, dict) or not when:
        raise ValueError(f"Modifier '{name}': condition.when must be a non-empty mapping")
    for value, entry in when.items():
        if not isinstance(entry, dict):
            raise ValueError(f"Modifier '{name}': when.{value} must be a mapping")
        unknown = sorted(entry.keys() - _WHEN_ENTRY_KEYS)
        if unknown or "keep" not in entry:
            raise ValueError(
                f"Modifier '{name}': when.{value} must have exactly a 'keep' list"
            )
        keep = entry["keep"]
        if not isinstance(keep, list) or not all(isinstance(k, str) and k for k in keep):
            raise ValueError(f"Modifier '{name}': when.{value}.keep must be a list of paths")
        for k in keep:
            if k.startswith("/") or "**" in k.split("/"):
                raise ValueError(
                    f"Modifier '{name}': keep entry '{k}' must be group-relative "
                    "with no leading slash or '**'"
                )


def matches_modifier(relative_path: str, modifier: dict) -> bool:
    """Check if a relative path matches a modifier's dirs/files/patterns.

    Matching rules:
    - dirs: directory name matches an exact path component (not filename)
    - files: filename matches the basename of the path
    - patterns: regex matches against the full relative path

    Any single match returns True.
    """
    parts = Path(relative_path).parts
    basename = parts[-1] if parts else ""
    # Directory components (everything except the filename)
    dir_parts = parts[:-1] if len(parts) > 1 else ()

    # Check dirs -- exact component match in parent directories
    for dir_name in modifier.get("dirs", []):
        if dir_name in dir_parts:
            return True

    # Check files -- exact basename match at any depth
    for file_name in modifier.get("files", []):
        if basename == file_name:
            return True

    # Check patterns -- regex against full relative path
    for pattern in modifier.get("patterns", []):
        if re.search(pattern, relative_path):
            return True

    return False
