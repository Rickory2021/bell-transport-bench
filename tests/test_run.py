# tests/test_run.py
"""CircuitRun runs a circuit file into a run folder, and a rerun of that folder repeats it exactly.

Covers docs/DESIGN.md, sections 5 and 8, as D-83 and D-75 to D-79 settle them:
the baseline's self-test (ideal F = 1, every shot kept, the pair on the ports),
the organisers' fidelities measured within three standard errors, postselection
and its Wilson interval, the stop rule for conditional channels, where a run
folder goes, the CSV headers it writes, and the rerun's refusals and
comparisons.
"""

import csv
from types import SimpleNamespace

import pytest
import yaml
from qiskit import ClassicalRegister

from bellbench import run as run_module
from bellbench.analysis import read_shots
from bellbench.circuits import save_circuit, swap_chain
from bellbench.pipeline import Simulation
from bellbench.run import (
    COUNT_COLUMNS,
    RESULT_FILE,
    SIMULATION_COLUMNS,
    CircuitRun,
    Analysis,
    _write_csv,
    rerun,
    wilson_interval,
)

# The organisers' recorded noisy fidelities under their 2% CX noise (docs/CHALLENGE.md).
ORGANISERS = {"ibm2016": 0.915, "contemporary": 0.795, "hyperbolic": 0.852}


@pytest.mark.parametrize("processor, swaps, cz", [("ibm2016", 2, 7), ("contemporary", 6, 19), ("hyperbolic", 4, 13)])
def test_baseline_passes_its_self_test(processor, swaps, cz):
    run = CircuitRun(f"baseline-{processor}", "boston-2026", shots=1000).run()
    ideal, noisy = run.analysis["ideal"], run.analysis["noisy"]
    assert ideal.accepted.value == 1.0 and ideal.acceptance == 1.0
    assert noisy.acceptance == 1.0 and noisy.accepted.value == noisy.raw.value < 1.0
    assert run.cost["pair_on_ports"] is True
    assert (run.cost["swaps"], run.cost["router_swaps"], run.cost["two_qubit_gates"]) == (swaps, 0, cz)
    assert run.duration > 0


@pytest.mark.parametrize("processor", sorted(ORGANISERS))
def test_measured_cross_check_lands_within_three_standard_errors(processor):
    noisy = CircuitRun(f"baseline-{processor}", "organiser-cx2", shots=20_000).run().analysis["noisy"]
    # The organisers recorded three decimals, so their value carries up to 0.0005 of rounding.
    assert abs(noisy.accepted.value - ORGANISERS[processor]) < 3 * noisy.accepted.standard_error + 0.0005


def test_seeds_repeat_for_the_same_labels_and_differ_otherwise():
    a = CircuitRun("baseline-ibm2016", "boston-2026")
    assert a.seeds == CircuitRun("baseline-ibm2016", "boston-2026", shots=10).seeds
    assert a.seeds != CircuitRun("baseline-ibm2016", "fez-2025").seeds
    assert a.seeds != CircuitRun("baseline-ibm2016", "boston-2026", scale=2).seeds
    assert len(set(a.seeds.values())) == 3


def test_postselection_keeps_shots_whose_checks_read_zero():
    # Keys as Qiskit writes them: the last register first, so "port check".
    raw = {"00 0": 40, "11 0": 40, "01 1": 15, "11 1": 5}
    by_basis = {b: dict(raw) for b in ("XX", "YY", "ZZ")}
    ports = read_shots({"name": "postselect"}, by_basis, [("check", 1), ("port", 2)], 100)
    analysis = Analysis(ports)
    assert analysis.accepted_shots == {"XX": 80, "YY": 80, "ZZ": 80}
    assert analysis.raw_shots == {"XX": 100, "YY": 100, "ZZ": 100}
    assert analysis.acceptance == pytest.approx(0.8)
    assert analysis.accepted.correlators["ZZ"].value == 1.0
    assert analysis.raw.correlators["ZZ"].value == pytest.approx(0.7)


def test_wilson_interval():
    low, high = wilson_interval(50, 100)
    assert (low, high) == (pytest.approx(0.4038, abs=1e-4), pytest.approx(0.5962, abs=1e-4))
    assert wilson_interval(100, 100)[1] == 1.0
    assert wilson_interval(0, 100)[0] == pytest.approx(0.0, abs=1e-12)


def _with_check(config_copy, operation):
    circuit = swap_chain("ibm2016")
    check = ClassicalRegister(1, "check")
    circuit.add_register(check)
    if operation == "reset":
        circuit.reset(1)
    else:
        circuit.measure(1, check[0])
    save_circuit("checked", "Checked", "ibm2016", circuit, "A test circuit.")


@pytest.mark.parametrize("operation, channel", [("reset", "reset_error"), ("measure", "mid_circuit_measurement_error")])
def test_a_conditional_operation_with_its_channel_unset_stops(config_copy, operation, channel):
    _with_check(config_copy, operation)
    with pytest.raises(ValueError, match=f"{operation} before the end.*{channel} is unset"):
        CircuitRun("checked", "boston-2026")


def test_an_analysis_the_registry_lacks_is_refused(config_copy):
    with pytest.raises(ValueError, match=r"\$\.analysis: no analysis named 'correct'; known: postselect, parity"):
        circuit = swap_chain("ibm2016")
        save_circuit("corrected", "Corrected", "ibm2016", circuit, "A test.", analysis={"name": "correct"})


# -- Run folders and reruns ------------------------------------------------------------


@pytest.fixture
def folder(tmp_path):
    return CircuitRun("baseline-ibm2016", "boston-2026", shots=500).run().write(tmp_path)


def test_run_folder_holds_its_record_and_numbers(folder, tmp_path):
    assert folder.relative_to(tmp_path).parts[:4] == ("runs", "workbench", "baseline-ibm2016", "boston-2026")
    record = yaml.safe_load((folder / RESULT_FILE).read_text(encoding="utf-8"))
    assert record["circuit"]["path"] == "config/circuit/bp.data.circuit.baseline-ibm2016.yaml"
    assert record["registers"] == ["port"] and record["cost"]["pair_on_ports"] is True
    with open(folder / "counts.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert sum(int(r["count"]) for r in rows if r["simulation"] == "noisy" and r["basis"] == "ZZ") == 500


@pytest.mark.parametrize("name, columns", [("simulations.csv", SIMULATION_COLUMNS), ("counts.csv", COUNT_COLUMNS)])
def test_run_folder_csv_headers_are_the_declared_columns(folder, name, columns):
    raw = (folder / name).read_bytes()
    assert b"\r" not in raw, f"{name} ends its lines with LF only"
    assert tuple(raw.decode("utf-8").split("\n", 1)[0].split(",")) == columns


def test_counts_hold_the_full_outcome_key():
    # Keys as Qiskit writes them: the last register first, so "port frame_z check_zz".
    raw = {b: {"01 0 1": 3, "10 1 0": 2} for b in ("XX", "YY", "ZZ")}
    sims = {name: Simulation({}, {}, {}, 5, raw) for name in ("ideal", "noisy")}
    rows = CircuitRun.count_rows(SimpleNamespace(simulations=sims))
    assert len(rows) == 12
    assert all(tuple(r) == COUNT_COLUMNS for r in rows)
    assert {(r["outcome"], r["count"]) for r in rows} == {("01 0 1", 3), ("10 1 0", 2)}


def test_a_row_that_does_not_fit_the_declared_columns_raises(tmp_path):
    row = {c: 0 for c in COUNT_COLUMNS}
    with pytest.raises(ValueError, match="extra \\['stray'\\]"):
        _write_csv(tmp_path / "counts.csv", [{**row, "stray": 1}], COUNT_COLUMNS)
    with pytest.raises(ValueError, match="missing \\['count'\\]"):
        _write_csv(tmp_path / "counts.csv", [{k: v for k, v in row.items() if k != "count"}], COUNT_COLUMNS)


def test_a_rerun_matches(folder):
    code, lines = rerun(folder / RESULT_FILE)
    assert code == 0, lines
    assert all(line.startswith("same") for line in lines)


def test_a_rerun_reports_a_changed_circuit(folder):
    path = folder / RESULT_FILE
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    record["compiled"]["ZZ"] += "barrier q[0];\n"
    path.write_text(yaml.safe_dump(record), encoding="utf-8")
    code, lines = rerun(folder)
    assert code == 1 and "DIFFERS: compiled ZZ circuit" in lines


def test_a_rerun_refuses_a_changed_file(config_copy):
    folder = CircuitRun("baseline-ibm2016", "boston-2026", shots=200).run().write(config_copy / "results")
    path = config_copy / "config" / "circuit" / "bp.data.circuit.baseline-ibm2016.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("label: Baseline", "label: Edited"), encoding="utf-8")
    code, lines = rerun(folder)
    assert code == 2 and "changed since it was recorded" in lines[0]


def test_a_run_of_an_earlier_result_format_is_refused(folder):
    """A run recorded in OpenQASM 2 (format 1) is history: a rerun or a redraw names the commit that can rebuild it."""
    path = folder / RESULT_FILE
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    record["result_format"] = 1
    path.write_text(yaml.safe_dump(record), encoding="utf-8")
    code, lines = rerun(folder)
    assert code == 2 and "recorded in result format 1" in lines[0]
    with pytest.raises(ValueError, match="rebuild it from the commit that made it"):
        run_module.write_views(folder)


def test_the_record_holds_the_circuits_in_openqasm_3(folder):
    record = yaml.safe_load((folder / RESULT_FILE).read_text(encoding="utf-8"))
    assert record["written"].startswith("OPENQASM 3.0;\n")
    assert all(text.startswith("OPENQASM 3.0;\n") for text in record["compiled"].values())
    assert "qiskit-qasm3-import" in record["provenance"]["packages"]


@pytest.mark.parametrize("uncommitted, root", [(True, "workspace"), (False, "results")])
def test_uncommitted_runs_go_to_workspace(config_copy, monkeypatch, uncommitted, root):
    monkeypatch.setattr(run_module, "_git_state", lambda: ("abc123", uncommitted))
    folder = CircuitRun("baseline-ibm2016", "boston-2026", shots=100).run().write()
    assert folder.relative_to(config_copy).parts[0] == root
