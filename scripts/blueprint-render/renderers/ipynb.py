# scripts/blueprint-render/renderers/ipynb.py
"""Jupyter notebook renderer: a Jinja2 template in the percent format, written as notebook JSON.

The template is a Python file in the percent format that editors and Jupytext
read: a line starting `# %% [markdown]` opens a Markdown cell, and any other
line starting `# %%` opens a code cell. In a Markdown cell, each line's leading
`# ` (or a bare `#`) is removed. Text before the first marker is dropped, so a
template can open with a comment naming its path. Blank lines at either end of
a cell are trimmed.

A marker line may set the cell's metadata the way Jupytext's percent format
does, as `key=value` words whose value is JSON with no spaces, such as
`# %% cellView="form" jupyter={"source_hidden":true}`, which opens the cell
folded in Colab. Any other word on the marker line is a title and is dropped. A
value that is not JSON fails the render, so a misspelt setting is never
silently ignored.

The context from the map stage fills the template's Jinja tags; undefined
variables raise, so a missing value fails the render instead of leaving a
blank. The output carries no outputs, execution counts or volatile metadata,
and cell ids are their positions, so rendering the same template and values
twice gives the same bytes and a committed notebook diffs cleanly.
"""

import json
import re

import jinja2

MARKER = re.compile(r"^# %%(?P<rest>.*)$")
OPTION = re.compile(r"^(?P<key>[A-Za-z_][\w.-]*)=(?P<value>\S+)$")
KERNEL = {
    "kernelspec": {"display_name": "Python 3 (ipykernel)", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}


def render(context, template_path, output_path, root, **kwargs):
    """Render `template_path` (root-relative) with `context` and write the notebook to `output_path`."""
    if not template_path:
        raise ValueError("the ipynb renderer needs a template: set emit.ipynb.template in the process")
    template = root / template_path
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template.parent)),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )
    text = env.get_template(template.name).render(**context)
    notebook = {"cells": cells(text), "metadata": KERNEL, "nbformat": 4, "nbformat_minor": 5}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def cells(text: str) -> list[dict]:
    """The notebook cells a percent-format text holds, in order."""
    found, kind, metadata, lines = [], None, {}, []
    for line in text.splitlines():
        match = MARKER.match(line)
        if match:
            if kind is not None:
                found.append(_cell(kind, lines, len(found), metadata))
            kind = "markdown" if match["rest"].strip().startswith("[markdown]") else "code"
            metadata = _metadata(line, match["rest"])
            lines = []
        elif kind is not None:
            lines.append(line)
    if kind is not None:
        found.append(_cell(kind, lines, len(found), metadata))
    return found


def _metadata(line: str, rest: str) -> dict:
    """The `key=value` words on a marker line, each value read as JSON."""
    metadata = {}
    for word in rest.split():
        option = OPTION.match(word)
        if option:
            try:
                metadata[option["key"]] = json.loads(option["value"])
            except json.JSONDecodeError as error:
                raise ValueError(f"cell metadata on {line!r}: {option['key']}'s value is not JSON") from error
    return metadata


def _cell(kind: str, lines: list[str], index: int, metadata: dict) -> dict:
    if kind == "markdown":
        lines = [re.sub(r"^# ?", "", line) if line.startswith("#") else line for line in lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    source = [line + "\n" for line in lines[:-1]] + lines[-1:]
    cell = {"cell_type": kind, "id": f"cell-{index:02d}", "metadata": metadata, "source": source}
    if kind == "code":
        cell |= {"execution_count": None, "outputs": []}
    return cell
