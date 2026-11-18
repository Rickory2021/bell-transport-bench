# scripts/execute_notebook.py
"""Run a notebook top to bottom in a fresh kernel and write the run as a normalized copy.

make submission-executed uses it to write notebooks/bp.output.submission.executed.ipynb,
the submission notebook with its outputs, so a reader sees every result without running
anything. A cell that raises stops the run, and nothing is written.

Normalizing removes what differs from one run to the next, so the committed copy changes
only when the notebook or its results do:
- the kernel records no per-cell timestamps;
- the kernel runs with a fixed string hash seed, so a printed set lists its items in the
  same order every run;
- the folder the notebook works in, a new temporary folder on every run, is written as
  WORK_FOLDER wherever an output names it;
- each circuit step-through's random element id, stepper- and eight hex digits, is
  numbered in order of appearance instead, each still unique in the notebook.

Usage:
    uv run --group dev python scripts/execute_notebook.py IN OUT
"""

import argparse
import os
import re
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient

TIMEOUT_S = 1800  # per cell; the longest makes a benchmark, a few minutes on a laptop
WORK_FOLDER = "WORK_FOLDER"
# The notebook's work folder, tempfile.mkdtemp(prefix="bellbench-"), as an output prints it: the folder's
# own name, after the temporary directory's path in POSIX or Windows form.
WORK_PATH = re.compile(r"(?:[A-Za-z]:)?[\w./\\~-]*?[/\\]bellbench-\w{8}")
STEPPER_ID = re.compile(r"stepper-[0-9a-f]{8}")  # bellbench.views' id for one step-through's element


def normalize_outputs(notebook) -> None:
    """Normalize every text an output holds, in place: streams, and every data type but images."""
    numbers = {}  # each step-through id met so far, by its number

    def normalize(text: str) -> str:
        text = WORK_PATH.sub(WORK_FOLDER, text)
        return STEPPER_ID.sub(lambda m: f"stepper-{numbers.setdefault(m.group(), len(numbers) + 1):08d}", text)

    for cell in notebook.cells:
        for output in cell.get("outputs", []):
            if "text" in output:
                output["text"] = normalize(output["text"])
            for mime, value in output.get("data", {}).items():
                if isinstance(value, str) and not mime.startswith("image/"):  # images are base64, never a path
                    output["data"][mime] = normalize(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source", type=Path, help="the notebook to run")
    parser.add_argument("target", type=Path, help="where to write the run, normalized")
    args = parser.parse_args()
    notebook = nbformat.read(args.source, as_version=4)
    os.environ["PYTHONHASHSEED"] = "0"  # the kernel inherits it
    start = time.monotonic()
    NotebookClient(notebook, timeout=TIMEOUT_S, kernel_name="python3", record_timing=False,
                   resources={"metadata": {"path": str(args.source.parent)}}).execute()
    normalize_outputs(notebook)
    nbformat.write(notebook, args.target)
    print(f"wrote {args.target} in {time.monotonic() - start:.0f} s")


if __name__ == "__main__":
    main()
