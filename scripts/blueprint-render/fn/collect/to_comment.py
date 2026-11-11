# scripts/blueprint-render/fn/collect/to_comment.py
"""Produce a YAML comment string.

Input:
    vars.text: the comment text (without # prefix).

Output:
    string: "# {text}"
"""


def run(data, vars):
    return f"# {vars['text']}"
