# tests/test_workbench.py
"""The workbench notebook runs as committed, and the committed notebook is what its template renders.

Covers docs/DESIGN.md, section 1: the notebook's code cells, run in order at low
shots in a temporary copy of the repo's config and its committed move-chain
benchmark, fetch the committed baseline, build and run a trial, compare the two
and keep the trial's run in workspace/; with its commented promote line on, the
trial moves into config/circuit/. A fresh render from the template, process and
invoke gives the committed notebook byte for byte.
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
MOVE_CHAIN = Path("results") / "runs" / "benchmark" / "move-chain"
PROMOTE = "# wb.promote("
TRIAL = "try-move-xx"


def _code_cells():
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    return ["".join(c["source"]) for c in cells if c["cell_type"] == "code"]


@pytest.mark.parametrize("with_promote", [False, True])
def test_the_code_cells_run_in_order(config_copy, with_promote):
    shutil.copytree(ROOT / MOVE_CHAIN, config_copy / MOVE_CHAIN)
    namespace = {}
    cells = _code_cells()
    assert sum(c.count(PROMOTE) for c in cells) == 1
    for source in cells:
        if with_promote:
            source = source.replace(PROMOTE, "wb.promote(")
        exec(compile(source, str(NOTEBOOK), "exec"), namespace)
        if "wb" in namespace:
            namespace["wb"].shots = 50  # the settings cell takes the core benchmark's shots; a test needs few
    base, trial, folder = namespace["base"], namespace["trial"], namespace["folder"]
    assert base.label == f"{namespace['BASELINE']} under boston-2026" and base.self_test is None
    assert trial.self_test is None and trial.record["shots"] == 50
    assert folder.relative_to(configs.ROOT).parts[:5] == ("workspace", "runs", "workbench", TRIAL, "boston-2026")
    assert "Comparison, noisy simulations" in repr(namespace["wb"].compare(base, trial))
    promoted = (configs.ROOT / "config" / "circuit" / configs.file_name("circuit", TRIAL)).is_file()
    assert promoted == with_promote and (TRIAL in configs.trial_names()) != with_promote


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
