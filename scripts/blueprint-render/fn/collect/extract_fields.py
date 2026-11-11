# scripts/blueprint-render/fn/collect/extract_fields.py
"""Extract fields from multiple data files.

Walks loaded YAML files (one per source path), extracts specified
fields per file, and returns a keyed dict. Key derivation uses
a regex against each source filename. No grouping, no sorting
beyond alphabetical by key. Composition happens in the process
map, not here.

Counterpart: extract_list walks items within a single file's list.
Both share helpers from _helpers.

Input:
    data.sources: list of {_source: rel_path, _data: dict}
        from the runner's data_with_paths resolution tag.
    vars.fields: list of field specs (see _helpers.extract_fields).
    vars.key_pattern: regex applied to the source filename.
        First capture group becomes the output key.

Output:
    dict keyed by extracted key (alpha-sorted), each value a
    dict of extracted fields.
"""

import re
from pathlib import Path

from fn.collect._helpers import extract_fields


def _extract_key(source_path, key_pattern):
    """Extract the output key from a source file path.

    Applies the regex to the filename only (not the full path).
    Falls back to the file stem if no match.
    """
    filename = Path(source_path).name
    match = re.search(key_pattern, filename)
    if match and match.groups():
        return match.group(1)
    return Path(source_path).stem


def run(data, vars):
    """Extract fields from loaded data files.

    Args:
        data: {"sources": list of {_source, _data} dicts}
        vars: {"fields": list of field specs,
               "key_pattern": regex for key extraction}

    Returns:
        dict keyed by extracted key (alpha-sorted).
    """
    sources = data["sources"]
    field_specs = vars["fields"]
    key_pattern = vars["key_pattern"]

    entries = []
    for entry in sources:
        key = _extract_key(entry["_source"], key_pattern)
        result = extract_fields(entry["_data"], field_specs)
        entries.append((key, result))

    entries.sort(key=lambda e: e[0])
    return dict(entries)
