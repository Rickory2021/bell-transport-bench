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
import shutil
import subprocess
from types import SimpleNamespace

import pytest
import yaml
from qiskit import ClassicalRegister

from bellbench import configs
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


def _save_checked(build) -> str:
    """The 2016 baseline, whose path is 0-3-4, with a one-bit check register and whatever `build` adds."""
    circuit = swap_chain("ibm2016")
    check = ClassicalRegister(1, "check")
    circuit.add_register(check)
    build(circuit, check)
    save_circuit("checked", "Checked", "ibm2016", circuit, "A test circuit.")
    return "checked"


def test_a_final_check_measurement_runs_with_the_channels_unset(config_copy):
    """Qubit 3 is vacated when the SWAPs come back, so a vacancy read at the end finds 0 and keeps every shot."""
    name = _save_checked(lambda qc, check: qc.measure(3, check[0]))
    run = CircuitRun(name, "boston-2026", shots=500).run()
    assert run.analysis["ideal"].accepted.value == 1.0 and run.analysis["ideal"].acceptance == 1.0
    assert run.registers == ["check", "port"]


@pytest.mark.parametrize(
    "build, message",
    [
        (lambda qc, check: qc.reset(1), r"resets qubit\(s\) \[1\] in its XX circuit, but .* reset_error is unset"),
        (
            lambda qc, check: (qc.measure(1, check[0]), qc.x(1)),
            r"measures qubit\(s\) \[1\] and then acts on them again .* mid_circuit_measurement_error is unset",
        ),
        (
            lambda qc, check: (qc.measure(1, check[0]), qc.measure(1, check[0])),
            r"measures qubit\(s\) \[1\] and then acts on them again",
        ),
    ],
)
def test_a_reset_or_a_reused_measured_qubit_stops_while_its_channel_is_unset(config_copy, build, message):
    name = _save_checked(build)
    with pytest.raises(ValueError, match=message):
        CircuitRun(name, "boston-2026", shots=100).run()


@pytest.mark.parametrize("p, low, high", [(0.0, 0.9, 1.0), (1.0, 0.0, 0.1)])
def test_a_reset_runs_once_its_channel_is_set(config_copy, p, low, high):
    """Qubit 1 is reset and then read: the ideal run keeps every shot, and the noisy one keeps a shot only when
    the reset left it in |0>, so about 1 - p of them, readout errors aside."""
    def build(qc, check):
        qc.reset(1)
        qc.measure(1, check[0])

    name = _save_checked(build)
    run = CircuitRun(name, "boston-2026", shots=2000, conditional={"reset_error": p}).run()
    assert run.analysis["ideal"].acceptance == 1.0
    assert low <= run.analysis["noisy"].acceptance <= high


def _vacancy_then_zz(reset: bool):
    """Read qubit 3 once the pair has left it (a vacancy check), optionally reset it, then reuse it as the ancilla
    of a ZZ parity check on the ports 0 and 4, read last. With no error both checks read 0."""
    def build(qc, check):
        zz = ClassicalRegister(1, "check_zz")
        qc.add_register(zz)
        qc.measure(3, check[0])
        if reset:
            qc.reset(3)
        qc.cx(0, 3)
        qc.cx(4, 3)
        qc.measure(3, zz[0])

    return build


def test_a_protected_circuit_runs_end_to_end_once_both_channels_are_set(config_copy):
    name = _save_checked(_vacancy_then_zz(reset=True))
    conditional = {"reset_error": 0.01, "mid_circuit_measurement_error": 0.01}
    run = CircuitRun(name, "boston-2026", shots=2000, conditional=conditional).run()
    ideal, noisy = run.analysis["ideal"], run.analysis["noisy"]
    assert ideal.accepted.value == 1.0 and ideal.acceptance == 1.0
    assert 0.5 < noisy.acceptance < 1.0 and noisy.accepted.value > noisy.raw.value
    assert run.registers == ["check", "check_zz", "port"]


@pytest.mark.parametrize("p, low, high", [(0.0, 0.8, 1.0), (1.0, 0.0, 0.1)])
def test_a_reused_qubit_carries_the_mid_circuit_error_into_its_next_check(config_copy, p, low, high):
    """With no reset between, a flip after the vacancy read starts the ZZ ancilla in |1>, so its check fires."""
    name = _save_checked(_vacancy_then_zz(reset=False))
    run = CircuitRun(name, "boston-2026", shots=2000, conditional={"mid_circuit_measurement_error": p}).run()
    assert run.analysis["ideal"].acceptance == 1.0
    assert low <= run.analysis["noisy"].acceptance <= high


def test_a_router_swap_through_a_measured_qubit_makes_its_measurement_mid_circuit(config_copy):
    """Written last on qubit 3, the read is followed in the compiled circuit by the SWAP the router adds to bring
    ports 0 and 4 together through qubit 3, the 2016 graph's only route between them. The barrier keeps the read
    before the CX; without it the router reads the qubit after its SWAP, and the measurement stays final."""
    def build(qc, check):
        qc.measure(3, check[0])
        qc.barrier()
        qc.cx(0, 4)

    name = _save_checked(build)
    with pytest.raises(ValueError, match=r"measures qubit\(s\) \[3\] and then acts on them again"):
        CircuitRun(name, "boston-2026", shots=100).run()


def test_a_written_delay_lasts_exactly_its_length(config_copy):
    """A 1 us wait on the first port before the pair is made adds exactly 1 us to the scheduled circuit."""
    circuit = swap_chain("ibm2016")
    circuit.data.insert(0, circuit.copy_empty_like().delay(1, 0, unit="us")[0])
    save_circuit("waits", "Waits", "ibm2016", circuit, "A test circuit.")
    base = CircuitRun("baseline-ibm2016", "boston-2026", shots=100).run()
    waits = CircuitRun("waits", "boston-2026", shots=100).run()
    assert waits.duration - base.duration == pytest.approx(1e-6, abs=1e-12)


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


def _edit_csv(path, column, value):
    """Set `column` in the first data row of the CSV at `path` to `value`."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows[0][column] = value
    _write_csv(path, rows, tuple(rows[0]))


@pytest.mark.parametrize(
    "name, column, value, line",
    [
        ("counts.csv", "count", "1", "DIFFERS: counts"),
        ("simulations.csv", "fidelity", "0.5", "DIFFERS: simulations"),
    ],
)
def test_a_rerun_reports_changed_counts_or_numbers(folder, name, column, value, line):
    _edit_csv(folder / name, column, value)
    code, lines = rerun(folder)
    assert code == 1 and line in lines


@pytest.mark.parametrize(
    "path",
    [
        "config/circuit/bp.data.circuit.baseline-ibm2016.yaml",
        "config/noise/bp.data.noise.boston-2026.yaml",
        "config/processor/bp.data.processor.ibm2016.yaml",
    ],
)
def test_a_rerun_refuses_a_changed_file(config_copy, path):
    folder = CircuitRun("baseline-ibm2016", "boston-2026", shots=200).run().write(config_copy / "results")
    edited = config_copy / path
    edited.write_text(edited.read_text(encoding="utf-8").replace("label: ", "label: Edited ", 1), encoding="utf-8")
    code, lines = rerun(folder)
    assert code == 2 and f"{path} changed since it was recorded" in lines[0]


@pytest.mark.parametrize("name", ["missing", f"missing/{RESULT_FILE}"])
def test_a_rerun_refuses_a_path_with_no_run_record(tmp_path, name):
    code, lines = rerun(tmp_path / name)
    assert code == 2 and lines == [f"refused: {tmp_path / 'missing' / RESULT_FILE} does not exist; "
                                   f"give a run folder or its {RESULT_FILE}"]
    assert run_module.main(["rerun", str(tmp_path / name)]) == 2


def _edit_record(folder, change):
    path = folder / RESULT_FILE
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(record)
    path.write_text(yaml.safe_dump(record), encoding="utf-8")


@pytest.mark.parametrize(
    "change, line",
    [
        (lambda r: r.update(scheduled_duration=r["scheduled_duration"] * 2), "DIFFERS: scheduled duration"),
        (lambda r: r["simulations"]["noisy"]["seeds"].update(XX=1), "DIFFERS: simulator seeds and methods"),
        (lambda r: r["simulations"]["ideal"]["methods"].update(XX="density_matrix"),
         "DIFFERS: simulator seeds and methods"),
    ],
)
def test_a_rerun_reports_a_changed_duration_or_simulator_record(folder, change, line):
    _edit_record(folder, change)
    code, lines = rerun(folder)
    assert code == 1 and line in lines


def test_a_rerun_runs_with_the_recorded_seeds(folder, monkeypatch):
    """A changed derivation, such as a new label, leaves an earlier run rerunnable: the record's seeds are used,
    and the change is reported without counting as a difference."""
    derive = run_module.derive_seed
    monkeypatch.setattr(run_module, "derive_seed", lambda *args: derive(*args) + 1)
    code, lines = rerun(folder)
    assert code == 0, lines
    assert "DIFFERS: seeds the labels derive now" in lines


def test_a_rerun_with_edited_recorded_seeds_differs_in_its_counts(folder):
    _edit_record(folder, lambda r: r["seeds"].update(noisy=r["seeds"]["noisy"] + 1))
    code, lines = rerun(folder)
    assert code == 1 and "DIFFERS: counts" in lines and "DIFFERS: seeds the labels derive now" in lines


@pytest.mark.parametrize(
    "path, broken",
    [
        ("config/noise/bp.data.noise.boston-2026.yaml", "\nbogus_field: 1\n"),
        ("config/circuit/bp.data.circuit.baseline-ibm2016.yaml", "\nprocessor: no-such-graph\n"),
        ("config/processor/bp.data.processor.ibm2016.yaml", "\n: not yaml: [\n"),
    ],
)
def test_a_changed_file_that_no_longer_loads_is_refused_for_the_change(config_copy, path, broken):
    folder = CircuitRun("baseline-ibm2016", "boston-2026", shots=100).run().write(config_copy / "results")
    edited = config_copy / path
    edited.write_text(edited.read_text(encoding="utf-8") + broken, encoding="utf-8")
    code, lines = rerun(folder)
    assert code == 2 and f"{path} changed since it was recorded" in lines[0], lines


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


def test_the_git_state_is_read_when_the_run_starts(config_copy, monkeypatch):
    """Simulated with an uncommitted edit, written after a commit: the run still lands in workspace/ as uncommitted."""
    monkeypatch.setattr(run_module, "_git_state", lambda: ("abc123", True))
    run = CircuitRun("baseline-ibm2016", "boston-2026", shots=100).run()
    monkeypatch.setattr(run_module, "_git_state", lambda: ("def456", False))
    folder = run.write()
    record = yaml.safe_load((folder / RESULT_FILE).read_text(encoding="utf-8"))
    assert folder.relative_to(config_copy).parts[0] == "workspace"
    assert record["provenance"]["commit"] == "abc123" and record["provenance"]["uncommitted"] is True


def _git(root, *args):
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args]
    subprocess.run(command, cwd=root, check=True, capture_output=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_the_git_state_flags_uncommitted_changes_in_src_and_config_only(tmp_path, monkeypatch):
    """The real check behind where a run lands: an edit in src/ or config/ counts, one elsewhere does not."""
    monkeypatch.setattr(configs, "ROOT", tmp_path)
    assert run_module._git_state() == (None, True), "outside git, a run counts as uncommitted"
    for name in ("src/a.py", "config/b.yaml", "docs/c.md"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "start")
    commit, uncommitted = run_module._git_state()
    assert len(commit) == 40 and uncommitted is False
    (tmp_path / "docs" / "c.md").write_text("edited\n", encoding="utf-8")
    assert run_module._git_state()[1] is False
    for name in ("src/a.py", "config/b.yaml"):
        (tmp_path / name).write_text("edited\n", encoding="utf-8")
        assert run_module._git_state() == (commit, True), name
        _git(tmp_path, "checkout", "-q", "--", name)
    (tmp_path / "src" / "new.py").write_text("x\n", encoding="utf-8")
    assert run_module._git_state()[1] is True, "an untracked file in src/ counts too"


@pytest.mark.parametrize(
    "scale, conditional, suffix",
    [
        (1.0, None, ""),
        (2.0, None, "-x2"),
        (1.0, {"reset_error": 0.01}, "-{h}"),
        (2.0, {"reset_error": 0.01}, "-x2-{h}"),
    ],
)
def test_a_workbench_folder_names_its_scale_and_settings(tmp_path, monkeypatch, scale, conditional, suffix):
    monkeypatch.setattr(run_module, "_stamp", lambda: "20261116T120000Z")
    run = CircuitRun("baseline-ibm2016", "boston-2026", shots=50, scale=scale, conditional=conditional)
    folder = run.run().write(tmp_path)
    assert folder.name == "20261116T120000Z" + suffix.format(h=run.settings_hash)
    assert run.settings_hash is None or len(run.settings_hash) == 8
