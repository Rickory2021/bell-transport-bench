# scripts/blueprint-render/renderers/yaml.py
"""YAML writer for collect/index rollups.

Template-less renderer. The fn module produces the final data
structure; this writer serializes it to YAML.

Presentation is controlled by emit options:
  sections: ordered list of map keys. The renderer iterates
      the list, looks up each key in the context, and writes
      the value based on its Python type: str is written raw
      (comments from to_comment fn), dict is yaml.dump'd.
  separator: "newline" adds blank lines between top-level
      entries (flat mode only; sections mode always separates).

When sections is absent, the context is serialized flat
(single-key unwrap, then dump).

Uses a custom dumper that renders multiline strings as literal
block scalars (|) instead of quoted strings.
"""

import re
import sys

import yaml


# -- Custom dumper for clean multiline output ----------------------------------


class _CleanDumper(yaml.Dumper):
    """Dumper that uses literal block style for multiline strings
    and flow style for leaf dicts (all-scalar values)."""
    pass


def _is_scalar(v):
    """True if v is a scalar suitable for flow style."""
    if not isinstance(v, (int, float, str, bool, type(None))):
        return False
    if isinstance(v, str) and "\n" in v:
        return False
    return True


def _is_leaf_dict(data):
    """True if dict values are all scalars or lists of scalars.

    Flow style is used for these dicts. Dicts containing nested
    dicts, multiline strings, or lists of non-scalars stay block
    style so literal block scalars (|) work.
    """
    for v in data.values():
        if isinstance(v, list):
            if not all(_is_scalar(item) for item in v):
                return False
            continue
        if not _is_scalar(v):
            return False
    return True


def _str_representer(dumper, data):
    """Represent strings: literal block (|) for multiline, plain for single-line."""
    if "\n" in data:
        cleaned = "\n".join(line.rstrip() for line in data.split("\n"))
        cleaned = cleaned.rstrip("\n")
        return dumper.represent_scalar(
            "tag:yaml.org,2002:str", cleaned, style="|"
        )
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def _dict_representer(dumper, data):
    """Represent dicts: flow style for leaf dicts, block for nested."""
    if _is_leaf_dict(data):
        return dumper.represent_mapping(
            "tag:yaml.org,2002:map", data, flow_style=True
        )
    return dumper.represent_mapping(
        "tag:yaml.org,2002:map", data, flow_style=False
    )


def _list_representer(dumper, data):
    """Represent lists: flow style for short all-scalar lists, block for rest.

    Flow style for lists where all items are scalars and the
    estimated rendered length is under 120 chars. Long lists
    of scalars and lists containing nested structures stay block.
    """
    if data and all(_is_scalar(item) for item in data):
        est_len = (sum(len(str(item)) for item in data)
                   + 2 + 2 * max(0, len(data) - 1))
        if est_len <= 120:
            return dumper.represent_sequence(
                "tag:yaml.org,2002:seq", data, flow_style=True
            )
    return dumper.represent_sequence(
        "tag:yaml.org,2002:seq", data, flow_style=False
    )


from lib.types import BlockDict


def _block_dict_representer(dumper, data):
    """Always use block style for BlockDict instances."""
    return dumper.represent_mapping(
        "tag:yaml.org,2002:map", data, flow_style=False
    )


_CleanDumper.add_representer(str, _str_representer)
_CleanDumper.add_representer(dict, _dict_representer)
_CleanDumper.add_representer(list, _list_representer)
_CleanDumper.add_representer(BlockDict, _block_dict_representer)


# -- Serialization helpers -----------------------------------------------------


def _dump(data):
    """Dump a value to YAML string using the clean dumper."""
    return yaml.dump(
        data,
        Dumper=_CleanDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=300,
    )


def _add_entry_separators(yaml_str):
    """Add blank lines between top-level entries in YAML output."""
    lines = yaml_str.split("\n")
    result = []
    for i, line in enumerate(lines):
        if i > 0 and line and not line[0].isspace() and ":" in line:
            result.append("")
        result.append(line)
    return "\n".join(result)


# -- Flow alignment -----------------------------------------------------------


def _parse_flow_pairs(flow_str):
    """Parse key-value pairs from a flow dict string.

    Handles nested brackets in values (e.g. aliases: [a, b])
    and quoted strings (e.g. pattern: 'text with, commas').
    Returns list of (key, value) tuples with whitespace stripped.

    Used by both _align_flow_rows and _align_flow_list_items.
    """
    inner = flow_str.strip()[1:-1]  # strip outer { }
    pairs = []
    i = 0
    length = len(inner)

    while i < length:
        # Skip whitespace
        while i < length and inner[i] == " ":
            i += 1
        if i >= length:
            break

        # Find key (up to colon not inside quotes)
        colon = _find_unquoted(inner, ":", i)
        if colon == -1:
            break
        key = inner[i:colon].strip()
        i = colon + 1

        # Skip whitespace after colon
        while i < length and inner[i] == " ":
            i += 1

        # Find value end: comma at depth 0 outside quotes
        start = i
        i = _scan_value(inner, i)
        value = inner[start:i].strip()
        pairs.append((key, value))

        # Skip comma
        if i < length and inner[i] == ",":
            i += 1

    return pairs


def _find_unquoted(s, char, start):
    """Find next occurrence of char outside quotes and brackets."""
    i = start
    length = len(s)
    while i < length:
        c = s[i]
        if c in "'\"":
            i = _skip_quoted(s, i)
            continue
        if c == char:
            return i
        i += 1
    return -1


def _scan_value(s, start):
    """Scan past a flow value, respecting brackets and quotes.

    Returns the index of the comma or end of string.
    """
    i = start
    length = len(s)
    depth = 0
    while i < length:
        c = s[i]
        if c in "'\"":
            i = _skip_quoted(s, i)
            continue
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == "," and depth == 0:
            return i
        i += 1
    return i


def _skip_quoted(s, start):
    """Skip past a quoted string. Returns index after closing quote."""
    quote = s[start]
    i = start + 1
    while i < len(s):
        if s[i] == quote:
            return i + 1
        i += 1
    return i


def _can_align(parsed):
    """Check if parsed flow dict rows are eligible for alignment.

    Requires all rows to have the same keys in the same order.
    If any row at the same indent has different keys, the entire
    group fails — same indent implies same shape, a mismatch
    means alignment would be misleading.

    Used by both _align_flow_rows and _align_flow_list_items.
    """
    if not parsed:
        return False

    reference_keys = tuple(k for k, _ in parsed[0])
    for pairs in parsed[1:]:
        if tuple(k for k, _ in pairs) != reference_keys:
            return False

    return True


def _align_flow_rows(yaml_str):
    """Right-align values in consecutive flow-style dict rows.

    Groups consecutive lines at the same indent that contain flow
    dicts ({...}), then pads keys and right-aligns values. Only
    aligns groups where all rows share the same keys in the same
    order. Non-matching groups pass through unchanged.

    Before:
      junior: {base_low: 85000, base_high: 110000}
      mid: {base_low: 110000, base_high: 145000}
      senior: {base_low: 145000, base_high: 185000}

    After:
      junior: {base_low:  85000, base_high: 110000}
      mid:    {base_low: 110000, base_high: 145000}
      senior: {base_low: 145000, base_high: 185000}
    """
    flow_re = re.compile(r"^(\s+)(\S+):\s*(\{.*\})\s*$")
    lines = yaml_str.split("\n")
    result = []
    i = 0

    while i < len(lines):
        m = flow_re.match(lines[i])
        if not m:
            result.append(lines[i])
            i += 1
            continue

        # Collect consecutive flow-style lines at same indent
        indent = m.group(1)
        group = []
        while i < len(lines):
            m = flow_re.match(lines[i])
            if m and m.group(1) == indent:
                group.append((m.group(1), m.group(2), m.group(3)))
                i += 1
            else:
                break

        if len(group) < 2:
            # Single flow line, pass through
            ind, key, flow = group[0]
            result.append(f"{ind}{key}: {flow}")
            continue

        # Parse all rows to check alignment eligibility
        parsed = [_parse_flow_pairs(flow_str)
                  for _, _, flow_str in group]

        if _can_align(parsed):
            result.extend(_align_row_group(group, parsed))
        else:
            # Pass through unaligned
            for ind, key, flow in group:
                result.append(f"{ind}{key}: {flow}")

    return "\n".join(result)


def _align_row_group(group, parsed):
    """Align a group of (indent, key, flow_dict_str) tuples.

    Pads keys to uniform width and right-aligns numeric values
    within each column position.
    """
    indent = group[0][0]
    max_key_len = max(len(key) for _, key, _ in group)

    # Compute max value width per column position
    num_cols = len(parsed[0]) if parsed else 0
    col_widths = [0] * num_cols
    for pairs in parsed:
        for j, (_, val) in enumerate(pairs):
            col_widths[j] = max(col_widths[j], len(val))

    # Rebuild lines with alignment
    aligned = []
    for (_, key, _), pairs in zip(group, parsed):
        inner_parts = []
        for j, (k, v) in enumerate(pairs):
            width = col_widths[j] if j < len(col_widths) else len(v)
            inner_parts.append(f"{k}: {v:>{width}}")
        flow = "{" + ", ".join(inner_parts) + "}"
        # Pad after colon: "mid:    {" not "mid   : {"
        padding = " " * (max_key_len - len(key) + 1)
        aligned.append(f"{indent}{key}:{padding}{flow}")

    return aligned


def _align_flow_list_items(yaml_str):
    """Left-align values in consecutive flow-style list items.

    Groups consecutive lines that are flow-style list items
    (- {...}), then pads each column to uniform width so values
    align vertically. Last column is not padded. Comma goes
    immediately after the value; padding fills between comma
    and the next key.

    Before:
      - {name: C, proficiency: working_knowledge, aliases: []}
      - {name: Docker, proficiency: proficient, aliases: []}
      - {name: AWS, proficiency: working_knowledge, aliases: [AWS S3]}

    After:
      - {name: C,      proficiency: working_knowledge, aliases: []}
      - {name: Docker,  proficiency: proficient,        aliases: []}
      - {name: AWS,     proficiency: working_knowledge, aliases: [AWS S3]}
    """
    flow_list_re = re.compile(r"^(\s*-\s*)(\{.*\})\s*$")
    lines = yaml_str.split("\n")
    result = []
    i = 0

    while i < len(lines):
        m = flow_list_re.match(lines[i])
        if not m:
            result.append(lines[i])
            i += 1
            continue

        # Collect consecutive flow-style list items
        prefix = m.group(1)
        group = []
        while i < len(lines):
            m = flow_list_re.match(lines[i])
            if m and m.group(1) == prefix:
                group.append(m.group(2))
                i += 1
            else:
                break

        if len(group) < 2:
            result.append(f"{prefix}{group[0]}")
            continue

        # Parse and check eligibility (shared helpers)
        parsed = [_parse_flow_pairs(flow) for flow in group]

        if not _can_align(parsed):
            for flow in group:
                result.append(f"{prefix}{flow}")
            continue

        result.extend(
            _align_list_group(prefix, parsed)
        )

    return "\n".join(result)


def _align_list_group(prefix, parsed):
    """Align a group of parsed flow dict pairs for list items.

    Left-aligns values. Comma goes right after value, padding
    fills between comma and the next key. Last column unpadded.
    """
    num_cols = len(parsed[0])

    # Compute max segment width per column (key: value)
    seg_widths = [0] * num_cols
    for pairs in parsed:
        for j, (k, v) in enumerate(pairs):
            seg_widths[j] = max(seg_widths[j], len(f"{k}: {v}"))

    # Rebuild aligned lines
    aligned = []
    for pairs in parsed:
        inner = ""
        for j, (k, v) in enumerate(pairs):
            if j > 0:
                inner += " "
            inner += f"{k}: {v}"
            if j < num_cols - 1:
                pad = seg_widths[j] - len(f"{k}: {v}")
                inner += "," + " " * pad
        aligned.append(f"{prefix}{{{inner}}}")

    return aligned


# -- Renderer ------------------------------------------------------------------


def render(context, template_path, output_path, root, **kwargs):
    """Write context as YAML.

    Args:
        context: dict from the map stage.
        template_path: ignored (no template for YAML output).
        output_path: absolute path for the output file.
        root: repo root (Path).
        **kwargs: emit_entry passed by runner for format-specific options.
    """
    emit_entry = kwargs.get("emit_entry", {}) or {}
    sections = emit_entry.get("sections")
    separator = emit_entry.get("separator", "")

    # Derive root-relative path for directory comment
    try:
        rel_path = output_path.relative_to(root)
    except ValueError:
        rel_path = output_path.name

    if sections:
        yaml_str = _serialize_sections(context, sections)
    else:
        # Flat mode: unwrap single-key context, dump
        data = context
        if isinstance(context, dict) and len(context) == 1:
            data = list(context.values())[0]
        yaml_str = _dump(data)
        yaml_str = _align_flow_rows(yaml_str)
        yaml_str = _align_flow_list_items(yaml_str)
        if separator == "newline":
            yaml_str = _add_entry_separators(yaml_str)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(f"# {rel_path}\n")
        f.write("#\n# Auto-generated. Do not edit.\n")
        f.write(yaml_str)


def _serialize_sections(context, sections):
    """Serialize context using an ordered list of map keys.

    Each key is looked up in context. The value type determines
    how it is written:
      str  — written raw (comment produced by to_comment fn)
      dict — serialized as YAML entries with separators
    """
    parts = []
    for key in sections:
        if key not in context:
            print(f"Warning: sections key '{key}' not in context",
                  file=sys.stderr)
            continue

        value = context[key]

        if isinstance(value, str):
            parts.append(f"\n{value}\n")
        elif isinstance(value, dict):
            yaml_str = _dump(value)
            yaml_str = _align_flow_rows(yaml_str)
            yaml_str = _add_entry_separators(yaml_str)
            parts.append(yaml_str)
        else:
            raise ValueError(
                f"Section '{key}': expected str or dict, "
                f"got {type(value).__name__}"
            )

    return "\n".join(parts)
