# tests/test_submission.py
"""The submission notebook: a fresh render, payloads that are the repository's files, and text the records back.

Covers docs/DESIGN.md, section 1. notebooks/bp.output.submission.ipynb is rendered
by make submission from notebooks/bp.invoke.submission.yaml. These tests check that
the committed notebook is what the template renders now; that its code payload is
src/bellbench/ one to one and its results payload the invoked snapshots and nothing
else; that each config file is written out once, exactly as the repository holds
it; that the numbers in its text are the run records'; and that every claim the
text makes still holds for the snapshots the invoke names, so changing a snapshot
cannot leave the text saying something the records no longer show.
"""

import base64
import io
import json
import math
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

from bellbench.run import read_table

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = ROOT / "scripts" / "blueprint-render"
NOTEBOOK = ROOT / "notebooks" / "bp.output.submission.ipynb"
INVOKE = yaml.safe_load((ROOT / "notebooks" / "bp.invoke.submission.yaml").read_text(encoding="utf-8"))
BENCHMARKS = ROOT / "results" / "runs" / "benchmark"
STUDY_FILES = ("comparison.csv", "report.md", "bp.data.runs.yaml")


def _cells(path=NOTEBOOK):
    return [(c["cell_type"], "".join(c["source"])) for c in json.loads(path.read_text(encoding="utf-8"))["cells"]]


def _payload(name, path=NOTEBOOK):
    """The files a payload cell, `NAME = "..."`, unpacks to: {path: bytes}."""
    source = next(s for kind, s in _cells(path) if kind == "code" and s.startswith(f'{name} = "'))
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(source[len(name) + 4:-1]))) as archive:
        return {n: archive.read(n) for n in archive.namelist()}


def _markdown():
    return "\n".join(s for kind, s in _cells() if kind == "markdown")


def _noisy(snapshot):
    """A snapshot's noisy simulations, one row per run, from its comparison table."""
    table = read_table(BENCHMARKS / snapshot / "comparison.csv")
    return {r.run: r for r in table[table.simulation == "noisy"].itertuples(index=False)}


def _cases(snapshot):
    table = read_table(BENCHMARKS / snapshot / "comparison.csv")
    return {int(r.case): r for r in table.dropna(subset=["case"]).itertuples(index=False)}


def _study(name):
    return next(s for s in INVOKE["studies"] if s.split("/")[0] == name)


def _F(r):
    return f"{r.fidelity:.4f} ± {r.fidelity_se:.4f}"


def _apart(a, b):
    """How many combined standard errors separate two runs' F."""
    return (a.fidelity - b.fidelity) / math.hypot(a.fidelity_se, b.fidelity_se)


# -- The render ------------------------------------------------------------------------


@pytest.mark.slow
def test_the_committed_notebook_is_a_fresh_render(tmp_path):
    """Every cell as the template renders it now; the two payloads compared by what they unpack to, since deflate's
    bytes can differ between zlib builds."""
    if shutil.which("uv") is None:
        pytest.skip("uv runs blueprint-render in its own environment")
    for name in ("src", "config", "results", "scripts"):
        (tmp_path / name).symlink_to(ROOT / name, target_is_directory=True)
    for path in ("notebooks/bp.process.submission.yaml", "notebooks/bp.invoke.submission.yaml",
                 "notebooks/templates/submission.py.j2"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / path, tmp_path / path)
    subprocess.run(
        ["uv", "run", "blueprint_render.py", "--root", str(tmp_path), "run", "--force", "--output", "adjacent",
         "--file", "notebooks/bp.invoke.submission.yaml"],
        cwd=BLUEPRINT, check=True, capture_output=True,
    )
    fresh = tmp_path / "notebooks" / "bp.output.submission.ipynb"
    payloads = ("CODE", "RESULTS")
    strip = lambda cells: [c for c in cells if not any(c[1].startswith(f'{p} = "') for p in payloads)]  # noqa: E731
    assert strip(_cells(fresh)) == strip(_cells()), "run make submission and commit the rendered notebook"
    for name in payloads:
        assert _payload(name, fresh) == _payload(name), f"the {name} payload differs: run make submission"
    text = NOTEBOOK.read_text(encoding="utf-8")
    assert '"outputs": []' in text and '"execution_count": null' in text and "image/png" not in text  # no outputs


# -- The payloads ----------------------------------------------------------------------


def test_the_code_payload_is_src_one_to_one():
    expected = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in (ROOT / "src" / "bellbench").rglob("*.py")}
    assert _payload("CODE") == expected


def test_the_results_payload_is_the_invoked_snapshots_and_nothing_else():
    reported = BENCHMARKS / INVOKE["reported"]
    expected = {p for p in reported.rglob("*") if p.is_file() and p.suffix != ".png"}
    expected |= {BENCHMARKS / s / name for s in INVOKE["studies"] for name in STUDY_FILES}
    packed = _payload("RESULTS")
    assert set(packed) == {p.relative_to(ROOT).as_posix() for p in expected}
    assert all(packed[name] == (ROOT / name).read_bytes() for name in packed)


def test_every_config_file_is_written_once_exactly_as_the_repository_holds_it():
    written = {}
    for kind, source in _cells():
        if kind == "code" and source.startswith("%%repo_file "):
            line, _, body = source.partition("\n")
            path = line[len("%%repo_file "):]
            assert path not in written, f"{path} is written twice"
            written[path] = body + "\n"  # a cell drops its file's final newline
    expected = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8") for p in (ROOT / "config").rglob("*.yaml")}
    assert written == expected


def test_the_payloads_say_where_they_come_from():
    text = _markdown()
    assert f"[`{INVOKE['repo']}`](https://github.com/{INVOKE['repo']}/tree/{INVOKE['tag']}) at tag `{INVOKE['tag']}`" in text
    assert f"({len(_payload('CODE'))} files)" in text and f"({len(_payload('RESULTS'))} files)" in text


# -- The numbers in the text ------------------------------------------------------------


def test_the_case_table_in_the_text_is_the_records():
    cases, text = _cases(INVOKE["reported"]), _markdown()
    for graph, (base, protected) in {"2016-inspired": (2, 3), "Contemporary": (5, 6), "Hyperbolic-inspired": (8, 9)}.items():
        row = f"| {graph} | 1 (case {base - 1}) | {_F(cases[base])} (case {base}) | " \
              f"{_F(cases[protected])}, {cases[protected].acceptance:.3f} (case {protected}) |"
        assert row in text


def test_the_abstract_quotes_the_records():
    cases, moves = _cases(INVOKE["reported"]), _noisy(INVOKE["reported"])
    abstract = _markdown().split("**Abstract.**")[1].split("**To run it:**")[0]
    for base, processor in ((2, "ibm2016"), (5, "contemporary"), (8, "hyperbolic")):
        assert f"from {cases[base].fidelity:.4f} to {moves[f'move-{processor}'].fidelity:.4f}" in abstract \
            or f"{cases[base].fidelity:.4f} to {moves[f'move-{processor}'].fidelity:.4f}" in abstract
    for protected in (3, 6, 9):
        assert f"{_F(cases[protected])} keeping {100 * cases[protected].acceptance:.1f}%" in abstract


def test_draft_marks_follow_the_invoke():
    assert ("[check]" in _markdown()) == bool(INVOKE.get("draft"))


# -- The claims the text makes ------------------------------------------------------------


def test_the_claims_about_the_nine_cases_hold():
    cases, runs = _cases(INVOKE["reported"]), _noisy(INVOKE["reported"])
    move = {p: runs[f"move-{p}"] for p in ("ibm2016", "contemporary", "hyperbolic")}
    # The move chain beats the baseline on every graph.
    assert all(move[p].fidelity > cases[b].fidelity for p, b in (("ibm2016", 2), ("contemporary", 5), ("hyperbolic", 8)))
    # The check does not pay on ibm2016, and pays by more than two combined standard errors on the other two.
    assert cases[3].fidelity < move["ibm2016"].fidelity
    assert _apart(cases[6], move["contemporary"]) > 2 and _apart(cases[9], move["hyperbolic"]) > 2
    # Unprotected, F ranks the graphs by hops; protected, the hyperbolic graph leads and the other two are within one SE.
    for rows in ((cases[2], cases[8], cases[5]), (move["ibm2016"], move["hyperbolic"], move["contemporary"])):
        assert rows[0].fidelity > rows[1].fidelity > rows[2].fidelity
    assert cases[9].fidelity > max(cases[3].fidelity, cases[6].fidelity)
    assert abs(_apart(cases[6], cases[3])) < 1
    # Every ideal case gives F = 1 with every shot kept.
    assert all(cases[i].fidelity == 1 and cases[i].acceptance == 1 for i in (1, 4, 7))


def test_the_claims_about_the_studies_hold():
    moves = _noisy(INVOKE["reported"])
    sweep = _noisy(_study("mid-circuit-sweep"))
    at = {float(re.search(r"mcm-([0-9e-]+)$", run).group(1)): r for run, r in sweep.items() if "-mcm-" in run}
    assert at[0.0].fidelity < moves["move-ibm2016"].fidelity  # below the move chain with no mid-circuit error
    assert all(_apart(r, moves["move-ibm2016"]) < 1 for r in at.values())  # never above it by a standard error
    errors = sorted(at)
    assert all(at[a].acceptance > at[b].acceptance for a, b in zip(errors, errors[1:]))  # more errors, fewer shots kept
    assert _apart(at[errors[-1]], at[0.0]) > -1  # without lowering F

    excitation = _noisy(_study("starting-excitation"))
    assert excitation["move-contemporary-exc-5e-3"].fidelity < excitation["baseline-contemporary-exc-5e-3"].fidelity
    assert excitation["move-contemporary-exc-2e-2"].fidelity < excitation["baseline-contemporary-exc-2e-2"].fidelity
    loss = {run[: -len("-exc-0")]: r.fidelity - excitation[run.replace("-exc-0", "-exc-2e-2")].fidelity
            for run, r in excitation.items() if run.endswith("-exc-0")}
    assert min(loss, key=loss.get) == "path-xx-ibm2016"  # case 3's check loses least

    middle = _noisy(_study("middle-out"))
    assert abs(_apart(middle["middle-out-xx-contemporary"], middle["spare-xx-contemporary"])) < 1
    assert abs(_apart(middle["middle-out-xx-hyperbolic"], middle["spare-xx-hyperbolic"])) < 1
    zz, xx = middle["middle-out-zz-xx-hyperbolic"], middle["middle-out-xx-hyperbolic"]
    assert zz.acceptance < xx.acceptance and zz.fidelity <= xx.fidelity

    vacancy = _noisy(_study("vacancy-read"))
    ghz, case3 = vacancy["ghz-vacancy-ibm2016"], vacancy["path-xx-ibm2016"]
    assert ghz.fidelity > case3.fidelity and ghz.acceptance > case3.acceptance
    assert ghz.two_qubit_gates < case3.two_qubit_gates and ghz.scheduled_duration < case3.scheduled_duration
