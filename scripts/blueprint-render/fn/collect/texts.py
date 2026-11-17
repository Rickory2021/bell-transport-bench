# scripts/blueprint-render/fn/collect/texts.py
"""Text files as a mapping from each file's root-relative path to its text, unchanged.

A template can then place a file's exact text wherever it explains it.

Input:
    data.files: [{_source, _text}] from a {text: ...} tag.
    vars: an optional selection (under, whole, partial, names), as fn/collect/_select.py says.

Output:
    {rel_path: text}, in path order.
"""

from fn.collect._select import select


def run(data, vars):
    return {e["_source"]: e["_text"] for e in sorted(select(data["files"], vars or {}), key=lambda e: e["_source"])}
