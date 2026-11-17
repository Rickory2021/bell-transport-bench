# tests/test_submission.py
"""The submission notebook: a fresh render, payloads that are the repository's files, and text the records back.

Covers docs/DESIGN.md, section 1. notebooks/bp.output.submission.ipynb is rendered
by make submission from notebooks/bp.invoke.submission.yaml. These tests check that
the committed notebook is what the template renders now; that its payloads are
src/bellbench/ one to one, the invoked snapshots and nothing else, and the schemas
with the core benchmark file; that every other config file is written out once,
exactly as the repository holds it; that its first cell installs what
pyproject.toml pins, on the Python it requires; that every link in its text lands
on a heading; that the numbers in its text are the run records'; and that every
claim the text makes still holds for the snapshots the invoke names, so changing a
snapshot cannot leave the text saying something the records no longer show.
"""

import base64
import io
import json
import math
import re
import shlex
import shutil
import subprocess
import tomllib
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
PAYLOADS = ("CODE", "RESULTS", "STUDIES", "SCHEMAS")
GRAPHS = ("ibm2016", "contemporary", "hyperbolic")
CASES = {"ibm2016": (1, 2, 3), "contemporary": (4, 5, 6), "hyperbolic": (7, 8, 9)}  # ideal, noisy baseline, protected
EARLIER = {"ibm2016": "move-chain-path-xx-ibm2016", "contemporary": "move-chain-spare-xx-contemporary",
           "hyperbolic": "move-chain-spare-xx-hyperbolic"}  # the earlier protected case on each graph


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


def _extended(processor):
    """The noisy runs of the processor's extended benchmark, the study snapshot the invoke names for it."""
    return _noisy(next(s for s in INVOKE["studies"] if s.split("/")[0].endswith(f"-extended-{processor}")))


def _F(r):
    return f"{r.fidelity:.4f} ± {r.fidelity_se:.4f}"


def _apart(a, b):
    """How many combined standard errors separate two runs' F."""
    return (a.fidelity - b.fidelity) / math.hypot(a.fidelity_se, b.fidelity_se)


def _snapshot_files(snapshot):
    """The files a snapshot payload holds: its YAML, CSV and Markdown files, in its folder and in each run's."""
    folder = BENCHMARKS / snapshot
    return {p for depth in ("*", "*/*") for p in folder.glob(depth)
            if p.is_file() and p.suffix in (".yaml", ".csv", ".md")}


def _packed_as(name, files):
    packed = _payload(name)
    assert set(packed) == {p.relative_to(ROOT).as_posix() for p in files}
    assert all(packed[n] == (ROOT / n).read_bytes() for n in packed)


# -- The render ------------------------------------------------------------------------


@pytest.mark.slow
def test_the_committed_notebook_is_a_fresh_render(tmp_path):
    """Every cell as the template renders it now; the payloads compared by what they unpack to, since deflate's
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
    strip = lambda cells: [c for c in cells if not any(c[1].startswith(f'{p} = "') for p in PAYLOADS)]  # noqa: E731
    assert strip(_cells(fresh)) == strip(_cells()), "run make submission and commit the rendered notebook"
    for name in PAYLOADS:
        assert _payload(name, fresh) == _payload(name), f"the {name} payload differs: run make submission"
    code = [c for c in json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"] if c["cell_type"] == "code"]
    assert all(c["outputs"] == [] and c["execution_count"] is None for c in code)  # committed without outputs


# -- The setup ---------------------------------------------------------------------------


def test_the_first_cell_installs_what_pyproject_pins_on_the_python_it_requires():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    first = next(s for kind, s in _cells() if kind == "code")
    install = next(line for line in first.splitlines() if line.startswith("%pip install"))
    assert shlex.split(install)[3:] == project["dependencies"]  # after "%pip install -q", in pyproject's order
    guard = re.search(r"sys\.version_info < \((\d+), (\d+)\)", first)
    assert project["requires-python"] == f">={guard[1]}.{guard[2]}"


def test_every_link_lands_on_a_heading():
    """A link to a section targets its heading the way Jupyter and VS Code name it: spaces become hyphens."""
    text = _markdown()
    headings = {h.strip().replace(" ", "-") for h in re.findall(r"^#{1,6} (.+)$", text, re.M)}
    links = re.findall(r"\]\(#([^)]+)\)", text)
    assert links and not [link for link in links if link not in headings]
    assert "<a id=" not in text


# -- The payloads ----------------------------------------------------------------------


def test_the_code_payload_is_src_one_to_one():
    expected = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in (ROOT / "src" / "bellbench").rglob("*.py")}
    assert _payload("CODE") == expected


def test_the_results_payloads_are_the_invoked_snapshots_and_nothing_else():
    _packed_as("RESULTS", _snapshot_files(INVOKE["reported"]))
    _packed_as("STUDIES", set().union(*(_snapshot_files(s) for s in INVOKE["studies"])))


def test_the_schemas_payload_is_the_schemas_and_the_core_benchmark_file():
    _packed_as("SCHEMAS", {*(ROOT / "config").glob("bp.schema.*.yaml"), ROOT / "config/benchmark/bp.data.benchmark.core.yaml"})


def test_every_other_config_file_is_written_once_exactly_as_the_repository_holds_it():
    written = {}
    for kind, source in _cells():
        if kind == "code" and source.startswith("%%repo_file "):
            line, _, body = source.partition("\n")
            path = line[len("%%repo_file "):]
            assert path not in written, f"{path} is written twice"
            written[path] = body + "\n"  # a cell drops its file's final newline
    packed = set(_payload("SCHEMAS"))
    expected = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8") for p in (ROOT / "config").rglob("*.yaml")}
    assert not packed & set(written)
    assert written == {path: text for path, text in expected.items() if path not in packed}


def test_the_payloads_say_where_they_come_from():
    text = _markdown()
    assert f"[`{INVOKE['repo']}`](https://github.com/{INVOKE['repo']}/tree/{INVOKE['tag']}) at tag `{INVOKE['tag']}`" in text
    for name in PAYLOADS:
        assert f"({len(_payload(name))} files)" in text


# -- The numbers in the text ------------------------------------------------------------


def test_the_case_table_in_the_text_is_the_records():
    cases, text = _cases(INVOKE["reported"]), _markdown()
    for graph, (ideal, base, protected) in zip(("2016-inspired", "Contemporary", "Hyperbolic-inspired"), CASES.values()):
        row = f"| {graph} | 1 (case {ideal}) | {_F(cases[base])} (case {base}) | " \
              f"{_F(cases[protected])}, {cases[protected].acceptance:.3f} (case {protected}) |"
        assert row in text


def test_the_abstract_quotes_the_records():
    cases = _cases(INVOKE["reported"])
    abstract = _markdown().split("**Abstract.**")[1].split("**To run it:**")[0]
    for processor, (_, base, protected) in CASES.items():
        assert f"from {_F(cases[base])} to {_F(cases[protected])} keeping {100 * cases[protected].acceptance:.1f}%" \
            in abstract
    gates = lambda case_of: ", ".join(str(cases[c].two_qubit_gates) for c in case_of[:-1]) + \
        f" and {cases[case_of[-1]].two_qubit_gates}"  # noqa: E731
    assert f"with {gates((3, 6, 9))} two-qubit gates against the baseline's {gates((2, 5, 8))}" in abstract
    read = [_extended(p)[f"ghz-uncompute-vacancy-{p}"].fidelity - _extended(p)[f"ghz-uncompute-{p}"].fidelity for p in GRAPHS]
    assert "The read alone added " + ", ".join(f"{d:+.4f}" for d in read[:-1]) + f" and {read[-1]:+.4f}" in abstract
    assert f"{_shots():,} shots per basis" in abstract


def _shots():
    return yaml.safe_load((ROOT / "config" / "benchmark" / f"bp.data.benchmark.{INVOKE['reported'].split('/')[0]}.yaml")
                          .read_text(encoding="utf-8"))["shots"]


def test_draft_marks_follow_the_invoke():
    assert ("[check]" in _markdown()) == bool(INVOKE.get("draft"))


# -- The claims the text makes ------------------------------------------------------------


def test_the_claims_about_the_nine_cases_hold():
    cases = _cases(INVOKE["reported"])
    # Every ideal case gives F = 1 with every shot kept.
    assert all(cases[ideal].fidelity == 1 and cases[ideal].acceptance == 1 for ideal, _, _ in CASES.values())
    for processor, (_, base, protected) in CASES.items():
        # The protected case beats the noisy baseline with fewer two-qubit gates, no SWAP and no extra qubit.
        assert _apart(cases[protected], cases[base]) > 2
        assert cases[protected].two_qubit_gates < cases[base].two_qubit_gates and cases[protected].swaps == 0
        assert cases[protected].qubits_used <= cases[base].qubits_used
    # F ranks the graphs by hops, 2, then 3, then 4: baseline, transport alone and protected case alike.
    alone = {p: _extended(p)[f"ghz-uncompute-{p}"] for p in GRAPHS}
    for rows in ((cases[2], cases[8], cases[5]), (alone["ibm2016"], alone["hyperbolic"], alone["contemporary"]),
                 (cases[3], cases[9], cases[6])):
        assert rows[0].fidelity > rows[1].fidelity > rows[2].fidelity


def test_the_nine_cases_avoid_the_contemporary_graph_s_five_edge_qubit():
    graph = yaml.safe_load((ROOT / "config/processor/bp.data.processor.contemporary.yaml").read_text(encoding="utf-8"))
    degree = {q["id"]: sum(q["id"] in e for e in graph["edges"]) for q in graph["qubits"]}
    busiest = max(degree, key=degree.get)
    for run in ("baseline-contemporary", "ghz-uncompute-vacancy-contemporary"):
        record = yaml.safe_load((BENCHMARKS / INVOKE["reported"] / run / "bp.data.result.yaml").read_text(encoding="utf-8"))
        assert busiest not in record["cost"]["qubits_used"]


def test_the_claims_about_the_extended_benchmarks_hold():
    loss = {}
    for processor in GRAPHS:
        runs = _extended(processor)
        read, alone = runs[f"ghz-uncompute-vacancy-{processor}"], runs[f"ghz-uncompute-{processor}"]
        # The read raises F above the same transport by more than two combined standard errors, at no gate's cost,
        # and gains more after GHZ disentangling than after the move chain.
        assert _apart(read, alone) > 2 and read.two_qubit_gates == alone.two_qubit_gates
        move_gain = runs[f"move-chain-vacancy-{processor}"].fidelity - runs[f"move-chain-{processor}"].fidelity
        assert read.fidelity - alone.fidelity > move_gain
        assert read.fidelity > runs[f"move-chain-vacancy-{processor}"].fidelity
        # Among the runs that keep at least as many shots as the earlier protected case, the read gives the highest F.
        floor = runs[EARLIER[processor]].acceptance
        assert max((r for r in runs.values() if r.acceptance >= floor), key=lambda r: r.fidelity) is read
        # The textbook GHZ transport loses to GHZ disentangling, and wins with no readout error on the qubits it reads.
        measure = runs[f"ghz-measure-{processor}"]
        assert measure.fidelity < alone.fidelity < runs[f"ghz-measure-{processor}-readout-0"].fidelity
        loss[processor] = alone.fidelity - measure.fidelity
    # Its loss grows with the qubits it reads: one, two, then three.
    assert loss["ibm2016"] < loss["hyperbolic"] < loss["contemporary"]


def test_the_claims_about_a_spare_path_hold():
    for processor in ("hyperbolic", "contemporary"):
        runs = _extended(processor)
        read, alone = runs[f"ghz-uncompute-vacancy-{processor}"], runs[f"ghz-uncompute-{processor}"]
        spare = runs[f"ghz-uncompute-vacancy-spare-xx-{processor}"]
        # An XX check on a spare path raises F a little further only by discarding more shots, with more gates and
        # qubits, and it gains less F per extra discarded shot than the read gains per discarded shot.
        assert spare.fidelity > read.fidelity and spare.acceptance < read.acceptance
        assert spare.two_qubit_gates > read.two_qubit_gates and spare.qubits_used > read.qubits_used
        per_check = (spare.fidelity - read.fidelity) / (read.acceptance - spare.acceptance)
        assert per_check < (read.fidelity - alone.fidelity) / (1 - read.acceptance)
    assert "ghz-uncompute-vacancy-spare-xx-ibm2016" not in _extended("ibm2016")  # the 2016-inspired graph has no spare path
