# scripts/blueprint-render/fn/collect/csv_rows.py
"""CSV files as rows a template can index, each value a number where it reads as one.

Input:
    data.files: [{_source, _text}] from a {text: ...} tag, each a CSV file with a header row.
    vars:
        an optional selection (under, whole, partial, names), as fn/collect/_select.py says;
        nest_by: optional list of columns; each file's rows become nested dicts keyed by
            those columns' values, in order, and two rows with the same keys raise.

Output:
    {key: rows} per file, where key is the file's folder relative to `under` (so
    "move-chain/20261116T213408Z" for results/runs/benchmark/move-chain/20261116T213408Z/comparison.csv
    under results/runs/benchmark/), and rows is a list of dicts, or the nested
    dicts nest_by asks for. An empty cell is None; "nan" stays a float NaN.
"""

import csv
import io
from pathlib import PurePosixPath

from fn.collect._select import select


def _value(text):
    if text == "":
        return None
    for kind in (int, float):
        try:
            return kind(text)
        except ValueError:
            pass
    return text


def _nest(rows, columns, where):
    nested = {}
    for row in rows:
        level = nested
        for column in columns[:-1]:
            level = level.setdefault(row[column], {})
        last = row[columns[-1]]
        if last in level:
            raise ValueError(f"{where}: two rows share {', '.join(f'{c}={row[c]!r}' for c in columns)}")
        level[last] = row
    return nested


def run(data, vars):
    vars = vars or {}
    under = vars.get("under") or ""
    columns = list(vars.get("nest_by") or ())
    result = {}
    for entry in sorted(select(data["files"], vars), key=lambda e: e["_source"]):
        rows = [{k: _value(v) for k, v in row.items()} for row in csv.DictReader(io.StringIO(entry["_text"]))]
        folder = PurePosixPath(entry["_source"]).parent.as_posix()
        key = folder[len(under):] if under and folder.startswith(under.rstrip("/")) else folder
        key = key.strip("/")
        if key in result:
            raise ValueError(f"two CSV files share the folder {folder}")
        result[key] = _nest(rows, columns, entry["_source"]) if columns else rows
    return result
