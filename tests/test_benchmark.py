# tests/test_benchmark.py
"""A benchmark makes the runs its file lists, refuses a case that fails the self-test, and writes its folder.

Covers docs/DESIGN.md, section 6, as D-78, D-81 and D-86 settle them: the core
benchmark file maps cases 1, 2, 4, 5, 7 and 8; a benchmark writes a new stamped
folder with its runs inside, and a remake keeps the earlier one; a run folder's
views are drawn; and the make targets reach the command line.
"""

import csv

import pytest
import yaml
from qiskit import QuantumCircuit

from bellbench import run as run_module
from bellbench.circuits import save_circuit
from bellbench.run import RESULT_FILE, RUN_LIST, CircuitRun, load_benchmark, main, run_benchmark, write_views


def test_core_benchmark_file_maps_the_baseline_cases():
    data, record = load_benchmark("core")
    assert record["path"] == "config/benchmark/bp.data.benchmark.core.yaml"
    assert {r["noise"] for r in data["runs"]} == {"boston-2026"}
    assert sorted(c["case"] for c in data["cases"]) == [1, 2, 4, 5, 7, 8]
    assert data["shots"] == 20_000


def test_benchmark_end_to_end(tmp_path, monkeypatch):
    stamps = iter(["20261116T120000Z", "20261116T130000Z"])
    monkeypatch.setattr(run_module, "_stamp", lambda: next(stamps))
    folder = run_benchmark("core", tmp_path, shots=200)
    assert folder == tmp_path / "runs" / "benchmark" / "core" / "20261116T120000Z"
    run_list = yaml.safe_load((folder / RUN_LIST).read_text(encoding="utf-8"))
    assert run_list["runs"] == ["ibm2016", "contemporary", "hyperbolic"]
    assert all((folder / run_id / RESULT_FILE).exists() for run_id in run_list["runs"])
    report = (folder / "ibm2016" / "report.md").read_text(encoding="utf-8")
    assert report.startswith("# Run baseline-ibm2016 under boston-2026\n"), "a run's report names it by its record"
    with open(folder / "comparison.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 6
    assert {r["case"] for r in rows} == {"1", "2", "4", "5", "7", "8"}
    assert all(float(r["two_qubit_gates_per_accepted_pair"]) == float(r["two_qubit_gates"]) for r in rows)
    assert "| 5 | contemporary | noisy |" in (folder / "report.md").read_text(encoding="utf-8")

    again = run_benchmark("core", tmp_path, shots=200)
    assert again == folder.parent / "20261116T130000Z"
    assert len(list(folder.rglob(RESULT_FILE))) == 3, "a remake keeps the earlier benchmark whole"
    assert len(list((tmp_path / "runs").rglob(RESULT_FILE))) == 6


def _write_benchmark(root, name, runs, cases):
    data = {"name": name, "label": "Test", "notes": "A test benchmark.", "shots": 100, "base_seed": 7,
            "runs": runs, "cases": cases}
    (root / "config" / "benchmark" / f"bp.data.benchmark.{name}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def test_a_case_whose_pair_ends_off_its_ports_is_refused(config_copy):
    off = QuantumCircuit(5)  # CX between the ports with no SWAPs, so the router moves the pair
    off.h(0)
    off.cx(0, 4)
    save_circuit("off-ports", "Off the ports", "ibm2016", off, "A test circuit the router must move.")
    _write_benchmark(config_copy, "off", [{"id": "a", "circuit": "off-ports", "noise": "boston-2026"}],
                     [{"case": 1, "run": "a", "simulation": "ideal"}])
    with pytest.raises(ValueError, match="left the pair off its ports"):
        run_benchmark("off", config_copy / "results")
    assert not (config_copy / "results").exists(), "a refused benchmark writes nothing"


@pytest.mark.parametrize(
    "runs, cases, message",
    [
        ([{"id": "a", "circuit": "baseline-ibm2016", "noise": "boston-2026"}] * 2, [], "run ids must be unique"),
        ([{"id": "a", "circuit": "baseline-ibm2016", "noise": "boston-2026"}],
         [{"case": 1, "run": "b", "simulation": "ideal"}], "names run 'b'"),
    ],
)
def test_a_malformed_benchmark_file_raises_naming_the_field(config_copy, runs, cases, message):
    _write_benchmark(config_copy, "bad", runs, cases)
    with pytest.raises(ValueError, match=message):
        load_benchmark("bad")


@pytest.mark.parametrize("diagrams, files", [
    ("lean", {"graph.png", "circuit-zz.png", "report.md"}),
    ("full", {"graph.png", "circuit-zz.png", "written.png", "circuit-xx.png", "circuit-yy.png", "timeline.png", "report.md"}),
])
def test_views_are_drawn(tmp_path, diagrams, files):
    folder = CircuitRun("baseline-ibm2016", "boston-2026", shots=100, diagrams=diagrams).run().write(tmp_path)
    assert files <= {p.name for p in folder.iterdir()}
    assert {p.name for p in write_views(folder)} == files


def test_command_line(tmp_path, capsys):
    folder = CircuitRun("baseline-ibm2016", "boston-2026", shots=100).run().write(tmp_path)
    assert main(["rerun", str(folder)]) == 0
    assert main(["report", str(folder / RESULT_FILE)]) == 0
    assert main(["nonsense"]) == 2
    assert "usage" in capsys.readouterr().err
