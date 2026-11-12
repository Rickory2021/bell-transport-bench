# tests/test_workbench.py
"""The workbench notebook runs as committed, and the committed notebook is what its template renders.

Covers docs/DESIGN.md, section 1, as D-84 and D-87 settle them: the notebook's
code cells, run in order at low shots, make and write one run, including the
commented example that builds and saves a circuit with the analysis its settings
name; and a fresh render from the
template, process and invoke gives the committed notebook byte for byte.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from bellbench import configs

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "bp.output.workbench.ipynb"
BLUEPRINT = ROOT / "scripts" / "blueprint-render"
EXAMPLE = ("# circuit = ", "# notes = ", "# save_circuit(", "# CIRCUIT = ")
# With the example on, ANALYSIS is set to a parity analysis, which save_circuit would never pick by default, so the
# saved file shows whether the setting reached it. A parity with no groups suits a circuit that measures no check.
DEFAULT_ANALYSIS = 'ANALYSIS = {"name": "postselect"}'
PARITY = {"name": "parity", "settings": {"checks": []}}


def _code_cells():
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    return ["".join(c["source"]) for c in cells if c["cell_type"] == "code"]


@pytest.mark.parametrize("with_example", [False, True])
def test_the_code_cells_run_in_order(config_copy, with_example):
    namespace = {"display": lambda *a, **k: None}
    cells = _code_cells()
    if with_example:
        assert sum(c.count(DEFAULT_ANALYSIS) for c in cells) == 1
    for source in cells:
        if with_example:
            source = "\n".join(line[2:] if line.startswith(EXAMPLE) else line for line in source.splitlines())
            source = source.replace(DEFAULT_ANALYSIS, f"ANALYSIS = {PARITY!r}")
        exec(compile(source, str(NOTEBOOK), "exec"), namespace)
        if "SHOTS" in namespace and namespace["SHOTS"] != 50:
            namespace["SHOTS"] = 50  # the settings cell sets the core benchmark's shots; a test needs few
    circuit = "chain-04567" if with_example else "baseline-contemporary"
    folder = namespace["folder"]
    assert folder.relative_to(configs.ROOT).parts[:5] == ("workspace", "runs", "workbench", circuit, "boston-2026")
    assert namespace["run"].base_seed == namespace["core"]["base_seed"]
    if with_example:
        from bellbench.circuits import load_circuit

        assert load_circuit(circuit).analysis == PARITY


def test_the_committed_notebook_is_a_fresh_render(tmp_path):
    if shutil.which("uv") is None:
        pytest.skip("uv runs blueprint-render in its own environment")
    for path in ("notebooks/bp.process.workbench.yaml", "notebooks/bp.invoke.workbench.yaml",
                 "notebooks/templates/workbench.py.j2", "scripts/blueprint-render/renderers/ipynb.py"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / path, tmp_path / path)
    subprocess.run(
        ["uv", "run", "blueprint_render.py", "--root", str(tmp_path), "run", "--force", "--output", "adjacent",
         "--file", "notebooks/bp.invoke.workbench.yaml"],
        cwd=BLUEPRINT, check=True, capture_output=True,
    )
    fresh = tmp_path / "notebooks" / "bp.output.workbench.ipynb"
    assert fresh.read_bytes() == NOTEBOOK.read_bytes(), "run make workbench and commit the rendered notebook"
