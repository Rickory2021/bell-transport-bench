# tests/test_workbench.py
"""The tutorial and the workbench notebook run as committed, and each is what its template renders.

Covers docs/DESIGN.md, section 1. The workbench notebook's code cells, run in
order at low shots in a temporary copy of the repo's config and its committed
move-chain benchmark, build a trial, show it with every debug view, run it,
compare it with committed runs and keep its run in workspace/; every view a
cell displays is built. The tutorial's cells run the same way, lessons first,
then Part 2's two trials. A fresh render from each template, process and
invoke gives the committed notebook byte for byte, and make workbench renders
every one of them.

The plain notebook the Workbench first shipped with, kept in tests/fixtures/,
still runs cell for cell against the package, as a teammate's copy of it does;
with its commented promote line on, the trial moves into config/circuit/. The
usage example in workbench.py's docstring is that notebook's, and runs as
written.
"""

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from bellbench import configs
from bellbench import workbench as workbench_module
from bellbench.views import base as views_base
from bellbench.views import lessons

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = ("workbench", "tutorial")  # each rendered from notebooks/bp.invoke.<name>.yaml into notebooks/bp.output.<name>.ipynb
PLAIN = ROOT / "tests" / "fixtures" / "plain-workbench.ipynb"
BLUEPRINT = ROOT / "scripts" / "blueprint-render"
BENCHMARKS = Path("results") / "runs" / "benchmark"
MOVE_CHAIN = BENCHMARKS / "move-chain"
PROMOTE = "# wb.promote("
TRIAL = "try-move-xx"
TUTORIAL_PARTS = {"html": 14, "latex": 10, "markdown": 16, "png": 4, "stepper": 2}  # how many parts of each kind the tutorial's cells display


def _code_cells(notebook=PLAIN):
    cells = json.loads(Path(notebook).read_text(encoding="utf-8"))["cells"]
    return ["".join(c["source"]) for c in cells if c["cell_type"] == "code"]


def _run_cell(source, namespace):
    """Run one cell as a notebook does, and return the value of its last line when that line is an expression."""
    tree = ast.parse(source)
    last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
    exec(compile(tree, "a notebook cell", "exec"), namespace)
    return eval(compile(ast.Expression(last.value), "a notebook cell", "eval"), namespace) if last else None


def test_the_workbench_notebooks_cells_run_and_every_view_they_display_is_built(config_copy, monkeypatch):
    shutil.copytree(ROOT / MOVE_CHAIN, config_copy / MOVE_CHAIN)
    shown = []
    monkeypatch.setattr(workbench_module, "emit", shown.append)
    monkeypatch.setattr(views_base, "emit", shown.append)  # a View shows itself through its own module's emit
    cells = _code_cells(ROOT / "notebooks" / "bp.output.workbench.ipynb")
    assert sum(c.count(PROMOTE) for c in cells) == 1 and sum("from bellbench" in c for c in cells) == 1
    assert "from bellbench.workbench import Workbench\n" in cells[0]  # the one bellbench import
    namespace, displayed = {}, 0
    for source in cells:
        value = _run_cell(source.replace("SHOTS = 500 ", "SHOTS = 50 "), namespace)
        if hasattr(value, "_ipython_display_"):
            value._ipython_display_()
            displayed += 1
    wb, my_run = namespace["wb"], namespace["my_run"]
    assert wb.shots == 50 and my_run.record["shots"] == 50 and my_run.self_test is None
    assert displayed == len(shown) == 4  # show, the run's result, compare and the benchmark line
    kinds = [[part.kind for part in parts] for parts in shown]
    assert kinds[0] == ["markdown", "png", "markdown", "html", "html", "html", "html"]  # show, with its three folds
    assert kinds[2] == ["html", "png", "markdown", "png", "markdown", "png", "markdown", "png"]  # compare, with circuits
    assert shown[3][0].content.startswith("```yaml\n  - {run: my-move-chain, circuit: my-move-chain, noise: boston-2026}")
    assert namespace["folder"].relative_to(configs.ROOT).parts[:4] == ("workspace", "runs", "workbench", "my-move-chain")
    assert configs.trial_names() == ["my-move-chain"]  # promote stays commented out


def test_the_tutorial_notebooks_cells_run_and_every_view_they_display_is_built(config_copy, monkeypatch):
    for benchmark in ("move-chain", "biased-noise"):
        shutil.copytree(ROOT / BENCHMARKS / benchmark, config_copy / BENCHMARKS / benchmark)
    shown = []
    for module in (workbench_module, views_base, lessons):  # each shows through the emit it imported
        monkeypatch.setattr(module, "emit", shown.append)
    cells = _code_cells(ROOT / "notebooks" / "bp.output.tutorial.ipynb")
    assert len(cells) == 24 and [i for i, c in enumerate(cells) if "from bellbench" in c] == [0]  # one import cell
    assert "from bellbench.views.lessons import algebra, bloch_steps, journey, ket, matrix_of, state_steps, tex, whole" in cells[0]
    namespace = {}
    for source in cells:
        value = _run_cell(source.replace("shots=500,", "shots=50,"), namespace)
        if hasattr(value, "_ipython_display_"):
            value._ipython_display_()
    assert namespace["wb"].shots == 50 and namespace["my_run"].self_test is None
    kinds = [part.kind for parts in shown for part in parts]
    assert {kind: kinds.count(kind) for kind in sorted(set(kinds))} == TUTORIAL_PARTS
    assert configs.trial_names() == ["my-case-6", "my-xx-check"]  # Part 2 builds two trials and promotes neither


@pytest.mark.parametrize("with_promote", [False, True])
def test_the_code_cells_run_in_order(config_copy, with_promote):
    shutil.copytree(ROOT / MOVE_CHAIN, config_copy / MOVE_CHAIN)
    namespace = {}
    cells = _code_cells()
    assert sum(c.count(PROMOTE) for c in cells) == 1
    for source in cells:
        if with_promote:
            source = source.replace(PROMOTE, "wb.promote(")
        exec(compile(source, str(PLAIN), "exec"), namespace)
        if "wb" in namespace:
            namespace["wb"].shots = 50  # the settings cell takes the core benchmark's shots; a test needs few
    base, trial, folder = namespace["base"], namespace["trial"], namespace["folder"]
    assert base.label == f"{namespace['BASELINE']} under boston-2026" and base.self_test is None
    assert trial.self_test is None and trial.record["shots"] == 50
    assert folder.relative_to(configs.ROOT).parts[:5] == ("workspace", "runs", "workbench", TRIAL, "boston-2026")
    assert "Comparison, noisy simulations" in repr(namespace["wb"].compare(base, trial))
    promoted = (configs.ROOT / "config" / "circuit" / configs.file_name("circuit", TRIAL)).is_file()
    assert promoted == with_promote and (TRIAL in configs.trial_names()) != with_promote


def test_the_example_in_the_workbench_docstring_runs_as_written(config_copy):
    shutil.copytree(ROOT / MOVE_CHAIN, config_copy / MOVE_CHAIN)
    example = [line[4:] for line in workbench_module.__doc__.splitlines() if line.startswith("    ")]
    assert example[0] == "from bellbench.workbench import Workbench, builders" and len(example) == 9
    notebook = "\n".join(_code_cells()).replace(PROMOTE, "wb.promote(")
    baseline = re.search(r'^BASELINE = ("[a-z0-9-]+")', notebook, re.MULTILINE).group(1)
    notebook = notebook.replace('"move-chain", BASELINE)', f'"move-chain", {baseline})')  # the notebook names it once
    namespace = {}
    for line in example:
        call = line.split("  #")[0]
        assert call in notebook or call == "wb = Workbench()", f"the notebook has no cell line {call!r}"
        exec(compile(line, "the docstring of workbench.py", "exec"), namespace)
        if "wb" in namespace:
            namespace["wb"].shots = 50
    assert namespace["trial"].self_test is None and namespace["base"].self_test is None
    assert TRIAL not in configs.trial_names()  # the example's last line promoted it


def test_make_workbench_renders_every_committed_notebook():
    names = next(line for line in (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
                 if line.startswith("WORKBENCH_NOTEBOOKS ="))
    assert tuple(names.split("=")[1].split()) == NOTEBOOKS
    # make submission renders the submission notebook, and make submission-executed writes its run beside it
    # (tests/test_submission.py)
    others = ["bp.output.submission.ipynb", "bp.output.submission.executed.ipynb"]
    assert sorted(p.name for p in (ROOT / "notebooks").glob("bp.output.*.ipynb")) == sorted(
        [f"bp.output.{name}.ipynb" for name in NOTEBOOKS] + others)


@pytest.mark.parametrize("name", NOTEBOOKS)
def test_the_committed_notebook_is_a_fresh_render(tmp_path, name):
    if shutil.which("uv") is None:
        pytest.skip("uv runs blueprint-render in its own environment")
    for path in (f"notebooks/bp.process.{name}.yaml", f"notebooks/bp.invoke.{name}.yaml",
                 f"notebooks/templates/{name}.py.j2", "scripts/blueprint-render/renderers/ipynb.py"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / path, tmp_path / path)
    subprocess.run(
        ["uv", "run", "blueprint_render.py", "--root", str(tmp_path), "run", "--force", "--output", "adjacent",
         "--file", f"notebooks/bp.invoke.{name}.yaml"],
        cwd=BLUEPRINT, check=True, capture_output=True,
    )
    fresh = tmp_path / "notebooks" / f"bp.output.{name}.ipynb"
    committed = ROOT / "notebooks" / f"bp.output.{name}.ipynb"
    assert fresh.read_bytes() == committed.read_bytes(), "run make workbench and commit the rendered notebook"
    text = committed.read_text(encoding="utf-8")
    assert '"outputs": []' in text and '"execution_count": null' in text and "image/png" not in text  # no outputs
