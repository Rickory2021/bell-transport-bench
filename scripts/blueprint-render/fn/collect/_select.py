# scripts/blueprint-render/fn/collect/_select.py
"""Which of a {text: ...} tag's files a collect fn keeps: shared by archive, texts and csv_rows.

Not a standalone fn module. No run() export.

A selection names folders under one root folder, as vars:
    under:   the root folder, such as "results/runs/benchmark/"; "" when unset.
    whole:   folders under it whose every file is kept.
    partial: folders under it of which only the files named in `names` are kept.
    names:   file names kept from each partial folder.
With no `whole` and no `partial`, every file is kept. A folder named but matching
no file raises, so a typo in an invoke fails the render instead of leaving a
folder out.
"""

from pathlib import PurePosixPath


def _folders(value):
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def select(files, vars):
    """The entries of `files` ([{_source, _text}]) the selection in `vars` keeps, in their order."""
    under = vars.get("under") or ""
    whole = [f"{under}{f.strip('/')}/" for f in _folders(vars.get("whole"))]
    partial = [f"{under}{f.strip('/')}/" for f in _folders(vars.get("partial"))]
    names = set(vars.get("names") or ())
    if not whole and not partial:
        return list(files)
    if partial and not names:
        raise ValueError("a partial selection needs names: the files kept from each partial folder")
    kept, used = [], set()
    for entry in files:
        path = entry["_source"]
        hit = next((f for f in whole if path.startswith(f)), None)
        if hit is None and PurePosixPath(path).name in names:
            hit = next((f for f in partial if PurePosixPath(path).parent.as_posix() + "/" == f), None)
        if hit is not None:
            kept.append(entry)
            used.add(hit)
    missing = [f for f in whole + partial if f not in used]
    if missing:
        raise ValueError(f"no file matched the selected folders: {', '.join(missing)}")
    return kept
