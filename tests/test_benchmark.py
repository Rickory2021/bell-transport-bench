# tests/test_benchmark.py
"""A benchmark makes the runs its file lists, refuses a run that fails the self-test, and writes its folder.

Covers docs/DESIGN.md, section 6, as D-78, D-81 and D-86 settle them: the core
benchmark file maps cases 1, 2, 4, 5, 7 and 8; a benchmark writes a new stamped
folder with its runs inside, a remake keeps the earlier one, and the latest is
the current one; two makes in one second refuse; the run list fits its schema;
comparison.csv's header is the declared columns; a run folder's views are drawn;
and the make targets reach the command line. The biased-noise study's circuit
files equal what the builders make, its file runs each under each pauli
profile, and it runs end to end. The mid-circuit sweep runs the XX check on
ibm2016's path at six mid-circuit measurement errors beside two fixed references.
The starting-excitation study runs the move-chain benchmark's nine runs at four
starting excitations.
"""

import csv
import subprocess
import sys
import math
import re
from types import SimpleNamespace

import pytest
import yaml
from qiskit import ClassicalRegister, QuantumCircuit

from bellbench import builders, configs
from bellbench import run as run_module
from bellbench.circuits import load_circuit, save_circuit, swap_chain
from bellbench.pipeline import basis_circuits, mid_circuit_measurements
from bellbench.run import (
    COMPARISON_COLUMNS,
    OLD_VIEWS,
    RESULT_FILE,
    RUN_LIST,
    CircuitRun,
    comparison_rows,
    current_benchmark,
    read_table,
    load_benchmark,
    main,
    run_benchmark,
    write_views,
)


SEED = 2026  # the base seed every test run uses; CircuitRun has no default


def test_core_benchmark_file_maps_the_baseline_cases():
    data, record = load_benchmark("core")
    assert record["path"] == "config/benchmark/bp.data.benchmark.core.yaml"
    assert {r["noise"] for r in data["runs"]} == {"boston-2026"}
    assert sorted(c["case"] for c in data["cases"]) == [1, 2, 4, 5, 7, 8]
    assert data["shots"] == 20_000


def test_each_core_case_names_its_model_and_simulation():
    data, _ = load_benchmark("core")
    circuit_of = {r["run"]: r["circuit"] for r in data["runs"]}
    named = {c["case"]: (circuit_of[c["run"]], c["simulation"]) for c in data["cases"]}
    assert named == {
        1: ("baseline-ibm2016", "ideal"), 2: ("baseline-ibm2016", "noisy"),
        4: ("baseline-contemporary", "ideal"), 5: ("baseline-contemporary", "noisy"),
        7: ("baseline-hyperbolic", "ideal"), 8: ("baseline-hyperbolic", "noisy"),
    }


@pytest.mark.slow
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
    assert tuple(rows[0]) == COMPARISON_COLUMNS
    assert b"\r" not in (folder / "comparison.csv").read_bytes()
    assert {r["case"] for r in rows} == {"1", "2", "4", "5", "7", "8"}
    assert all(float(r["two_qubit_gates_per_accepted_pair"]) == float(r["two_qubit_gates"]) for r in rows)
    assert all(r["infidelity_removed_per_rejection"] == r["infidelity_removed_per_rejection_se"] == "nan" for r in rows)
    assert "| 5 | contemporary | noisy |" in (folder / "report.md").read_text(encoding="utf-8")

    again = run_benchmark("core", tmp_path, shots=200)
    assert again == folder.parent / "20261116T130000Z"
    assert len(list(folder.rglob(RESULT_FILE))) == 3, "a remake keeps the earlier benchmark whole"
    assert len(list((tmp_path / "runs").rglob(RESULT_FILE))) == 6


# -- The biased-noise study -----------------------------------------------------------

# Each study circuit file, as the builders make it: move_chain on the graph's default path, then the checks.
STUDY = {
    "move-chain-ibm2016": ("ibm2016", ()),
    "move-chain-contemporary": ("contemporary", ()),
    "move-chain-hyperbolic": ("hyperbolic", ()),
    "move-chain-path-xx-ibm2016": ("ibm2016", ({},)),
    "move-chain-spare-xx-contemporary": ("contemporary", ({"on": "spare"},)),
    "move-chain-spare-xx-hyperbolic": ("hyperbolic", ({"on": "spare"},)),
}
STUDY_PROFILES = ("pauli-cx-biased", "pauli-cz-biased", "pauli-cx-unbiased")


@pytest.mark.parametrize("name", sorted(STUDY))
def test_each_study_circuit_equals_what_its_builders_build(name):
    processor, checks = STUDY[name]
    state = builders.move_chain(builders.start(processor))
    for kwargs in checks:
        state = builders.bus_xx(state, **kwargs)
    loaded = load_circuit(name)
    assert loaded.processor == processor
    assert loaded.circuit == state.circuit
    assert loaded.analysis == state.analysis()
    assert loaded.notes == state.notes()


def test_the_study_runs_each_circuit_and_baseline_under_each_profile():
    data, _ = load_benchmark("biased-noise")
    runs = {(r["circuit"], r["noise"]) for r in data["runs"]}
    circuits = set(STUDY) | {f"baseline-{p}" for p in ("ibm2016", "contemporary", "hyperbolic")}
    assert runs == {(c, n) for c in circuits for n in STUDY_PROFILES} and len(data["runs"]) == len(runs)
    assert "cases" not in data, "the study fills none of the challenge's nine cases"
    assert (data["shots"], data["base_seed"]) == (20_000, 20261116)


@pytest.mark.parametrize("benchmark", ["biased-noise", "move-chain", "mid-circuit-sweep", "starting-excitation"])
def test_the_mid_circuit_channel_is_set_only_where_a_circuit_reads_a_qubit_then_reuses_it(benchmark):
    """The spare-path checks read only at the end and need no channel; the check on ibm2016's path does."""
    data, _ = load_benchmark(benchmark)
    for r in data["runs"]:
        loaded = load_circuit(r["circuit"])
        ports = tuple(configs.load_processor(loaded.processor)["ports"])
        reads_then_reuses = any(mid_circuit_measurements(c) for c in basis_circuits(loaded.circuit, ports).values())
        channel = r.get("conditional", {}).get("mid_circuit_measurement_error")
        assert (channel is not None) == reads_then_reuses, r["run"]
        assert "reset_error" not in r.get("conditional", {}), "no circuit here resets"


@pytest.mark.slow
def test_the_study_runs_end_to_end(tmp_path):
    """Every run compiles under its profile's gates, and every ideal simulation gives F = 1 with every shot kept."""
    folder = run_benchmark("biased-noise", tmp_path, shots=100)
    with open(folder / "comparison.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2 * len(load_benchmark("biased-noise")[0]["runs"])
    for row in (r for r in rows if r["simulation"] == "ideal"):
        assert float(row["fidelity"]) == 1.0 and float(row["acceptance"]) == 1.0, row["run"]


# -- The move-chain benchmark -----------------------------------------------------------


def test_the_move_chain_benchmark_fills_the_nine_cases_with_the_baseline_and_the_xx_check():
    """Each row's ideal and noisy cases are the organisers' baseline, its protected case the move chain with its XX
    check, and the move chain alone runs beside them filling no case, all under the core's noise profile."""
    data, _ = load_benchmark("move-chain")
    runs = {r["run"]: r for r in data["runs"]}
    expected = {}
    for row, processor in enumerate(configs.CORE_PROCESSORS):
        xx = "move-chain-path-xx-ibm2016" if processor == "ibm2016" else f"move-chain-spare-xx-{processor}"
        expected |= {3 * row + 1: f"baseline-{processor}", 3 * row + 2: f"baseline-{processor}", 3 * row + 3: xx}
    assert {c["case"]: runs[c["run"]]["circuit"] for c in data["cases"]} == expected
    uncased = {runs[i]["circuit"] for i in runs} - {runs[c["run"]]["circuit"] for c in data["cases"]}
    assert uncased == {f"move-chain-{p}" for p in configs.CORE_PROCESSORS}
    assert {r["noise"] for r in data["runs"]} == {load_benchmark("core")[0]["runs"][0]["noise"]}
    assert (data["shots"], data["base_seed"]) == (20_000, 20261116)


@pytest.mark.slow
def test_the_move_chain_benchmark_runs_end_to_end(tmp_path):
    """Every case passes the self-test: the pair ends on the ports, and every ideal simulation gives F = 1 with
    every shot kept."""
    folder = run_benchmark("move-chain", tmp_path, shots=100)
    table = read_table(folder / "comparison.csv")
    assert sorted(table["case"].dropna()) == list(range(1, 10))
    ideal = table[table["simulation"] == "ideal"]
    assert (ideal["fidelity"] == 1.0).all() and (ideal["acceptance"] == 1.0).all()
    runs = [path for path in folder.iterdir() if path.is_dir()]
    assert len(runs) == 9 and all(PICTURES <= set(_files(run)) for run in runs)  # the pictures a workbench run holds


# -- The mid-circuit sweep ----------------------------------------------------------------


def test_the_mid_circuit_sweep_runs_the_path_check_at_six_errors_beside_two_fixed_references():
    """The protected circuit on ibm2016 at each swept error, the baseline and the move chain alone once each without
    the channel, all under the core's noise profile, with the core's shots and base seed and no case filled."""
    data, _ = load_benchmark("mid-circuit-sweep")
    runs = {r["run"]: (r["circuit"], r.get("conditional")) for r in data["runs"]}
    errors = {"0": 0.0, "1e-3": 0.001, "3e-3": 0.003, "1e-2": 0.01, "2e-2": 0.02, "5e-2": 0.05}
    swept = {
        f"path-xx-ibm2016-mcm-{name}": ("move-chain-path-xx-ibm2016", {"mid_circuit_measurement_error": value})
        for name, value in errors.items()
    }
    references = {"baseline-ibm2016": ("baseline-ibm2016", None), "move-ibm2016": ("move-chain-ibm2016", None)}
    assert runs == references | swept and len(data["runs"]) == len(runs)
    core = load_benchmark("core")[0]
    assert {r["noise"] for r in data["runs"]} == {core["runs"][0]["noise"]}
    assert (data["shots"], data["base_seed"]) == (core["shots"], core["base_seed"])
    assert "cases" not in data, "the sweep fills none of the challenge's nine cases"


def test_the_sweep_point_at_case_3s_error_has_case_3s_settings():
    """So the sweep's run at 0.01 gives the move-chain benchmark's case 3, and its references give that benchmark's."""
    sweep = {r["run"]: r for r in load_benchmark("mid-circuit-sweep")[0]["runs"]}
    move_chain = {r["run"]: r for r in load_benchmark("move-chain")[0]["runs"]}
    pairs = {"path-xx-ibm2016-mcm-1e-2": "path-xx-ibm2016", "baseline-ibm2016": "baseline-ibm2016",
             "move-ibm2016": "move-ibm2016"}
    for ours, theirs in pairs.items():
        settings = [{k: v for k, v in r.items() if k != "run"} for r in (sweep[ours], move_chain[theirs])]
        assert settings[0] == settings[1], ours


@pytest.mark.slow
def test_the_mid_circuit_sweep_runs_end_to_end(tmp_path):
    """Every point compiles and simulates, the error of 0 included, and every ideal simulation gives F = 1 with
    every shot kept."""
    table = read_table(run_benchmark("mid-circuit-sweep", tmp_path, shots=100) / "comparison.csv")
    assert len(table) == 2 * len(load_benchmark("mid-circuit-sweep")[0]["runs"])
    ideal = table[table["simulation"] == "ideal"]
    assert (ideal["fidelity"] == 1.0).all() and (ideal["acceptance"] == 1.0).all()


# -- The starting-excitation study -------------------------------------------------------


def test_the_starting_excitation_study_runs_the_move_chain_benchmarks_runs_at_four_values():
    """Each of the move-chain benchmark's runs, with its own settings, at each starting excitation, named by run and
    value, with the core's shots and base seed and no case filled."""
    data, _ = load_benchmark("starting-excitation")
    move_chain = load_benchmark("move-chain")[0]["runs"]
    values = {"0": 0.0, "5e-3": 0.005, "1e-2": 0.01, "2e-2": 0.02}
    expected = {
        f"{r['run']}-exc-{name}": {
            "circuit": r["circuit"], "noise": r["noise"],
            "conditional": {**r.get("conditional", {}), "starting_excitation": value},
        }
        for r in move_chain
        for name, value in values.items()
    }
    assert {r["run"]: {k: v for k, v in r.items() if k != "run"} for r in data["runs"]} == expected
    assert len(data["runs"]) == len(expected) == 36
    core = load_benchmark("core")[0]
    assert (data["shots"], data["base_seed"]) == (core["shots"], core["base_seed"])
    assert "cases" not in data, "the study fills none of the challenge's nine cases"


@pytest.mark.slow
@pytest.mark.parametrize(
    "states, root",
    [
        ([("abc", False)], "results"),
        ([("abc", True)], "workspace"),
        ([("abc", False), ("abc", True)], "workspace"),
        ([("abc", False), ("def", False)], "workspace"),
    ],
)
def test_a_benchmark_lands_in_results_only_when_every_reading_is_clean(config_copy, monkeypatch, states, root):
    """The state is read as the benchmark starts and as each run starts; an edit or a commit during the make
    sends the whole benchmark to workspace/."""
    readings = iter(states + [states[-1]] * 3)
    monkeypatch.setattr(run_module, "_git_state", lambda: next(readings))
    folder = run_benchmark("core", shots=50)
    assert folder.relative_to(config_copy).parts[0] == root


def test_the_current_benchmark_is_the_latest_finished_stamp(tmp_path):
    """A folder is finished once it holds report.md; a later one a failed make left partway is passed over."""
    with pytest.raises(FileNotFoundError, match="make benchmark NAME=core"):
        current_benchmark("core", tmp_path)
    parent = tmp_path / "runs" / "benchmark" / "core"
    for name in ("20261115T090000Z", "20261116T120000Z", "20261114T230000Z", "notes"):
        (parent / name).mkdir(parents=True)
        (parent / name / "report.md").write_text("# A benchmark\n", encoding="utf-8")
    (parent / "20261117T080000Z" / "ibm2016").mkdir(parents=True)
    assert current_benchmark("core", tmp_path) == parent / "20261116T120000Z"


def test_the_derived_metrics_follow_the_cost_columns_in_order():
    assert COMPARISON_COLUMNS[-3:] == (
        "two_qubit_gates_per_accepted_pair", "infidelity_removed_per_rejection", "infidelity_removed_per_rejection_se"
    )


def test_a_simulation_that_kept_no_shot_has_no_gates_per_accepted_pair():
    scores = {
        name: SimpleNamespace(
            acceptance=acceptance, removed_per_rejection=removed, row=lambda n: {"simulation": n},
            raw_shots={"XX": 10, "YY": 10, "ZZ": 10},
        )
        for name, acceptance, removed in (("ideal", 1.0, (math.nan, math.nan)), ("noisy", 0.0, (0.39, 0.016)))
    }
    run = SimpleNamespace(
        scores=scores, circuit=SimpleNamespace(name="c", processor="ibm2016"),
        nc=SimpleNamespace(noise_name="boston-2026", scale=1.0, overrides=[]),
        cost={"swaps": 2, "router_swaps": 0, "two_qubit_gates": 7, "depth": 8, "qubits_used": [0, 3, 4]},
        duration=None,
    )
    ideal, noisy = comparison_rows({"a": run}, {"runs": []})
    assert ideal["two_qubit_gates_per_accepted_pair"] == 7.0
    assert math.isnan(noisy["two_qubit_gates_per_accepted_pair"])
    assert all(math.isnan(ideal[c]) for c in COMPARISON_COLUMNS[-2:])
    assert (noisy["infidelity_removed_per_rejection"], noisy["infidelity_removed_per_rejection_se"]) == (0.39, 0.016)


def test_the_report_gives_the_infidelity_removed_per_rejection_with_its_error_or_n_a():
    row = {
        "processor": "ibm2016", "simulation": "noisy", "fidelity": 0.98, "fidelity_se": 0.0007, "acceptance": 0.97,
        "two_qubit_gates": 5, "swaps": 0, "se_method": "binomial",
    }
    rows = [
        {**row, "case": case, "infidelity_removed_per_rejection": value, "infidelity_removed_per_rejection_se": error}
        for case, value, error in ((2, math.nan, math.nan), (3, 0.39381, 0.01585))
    ]
    report = run_module._benchmark_report({"label": "Trial", "notes": "Notes.", "cases": [{}]}, rows)
    assert "| 2 | ibm2016 | noisy | 0.9800 | 0.0007 | 0.9700 | 5 | 0 | n/a |" in report
    assert "| 3 | ibm2016 | noisy | 0.9800 | 0.0007 | 0.9700 | 5 | 0 | 0.394 ± 0.016 |" in report
    assert "(F - F raw) / (1 - p) within the run" in report


@pytest.mark.slow
def test_two_makes_in_one_second_refuse_and_keep_the_first(tmp_path, monkeypatch):
    monkeypatch.setattr(run_module, "_stamp", lambda: "20261116T120000Z")
    folder = run_benchmark("core", tmp_path, shots=50)
    with pytest.raises(FileExistsError, match="made this second already"):
        run_benchmark("core", tmp_path, shots=50)
    assert len(list(folder.rglob(RESULT_FILE))) == 3


@pytest.mark.parametrize("runs, ok", [
    (["ibm2016", "contemporary"], True),
    (["ibm2016", "ibm2016"], False),
    (["../elsewhere"], False),
    ([], False),
])
def test_the_run_list_schema(runs, ok):
    record = {"path": "config/benchmark/bp.data.benchmark.core.yaml", "hash": "sha256:" + "0" * 64}
    run_list = {"benchmark": record, "runs": runs, "cases": [{"case": 1, "run": "ibm2016", "simulation": "ideal"}]}
    if ok:
        configs.check_config("runs", run_list, "the run list")
    else:
        with pytest.raises(ValueError, match=r"the run list: \$\.runs"):
            configs.check_config("runs", run_list, "the run list")


def _write_benchmark(root, name, runs, cases):
    data = {"name": name, "label": "Test", "notes": "A test benchmark.", "shots": 100, "base_seed": 7,
            "runs": runs, "cases": cases}
    (root / "config" / "benchmark" / f"bp.data.benchmark.{name}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def test_read_table_gives_cases_as_integers_and_no_case_as_na(config_copy):
    _write_benchmark(config_copy, "mixed", [
        {"run": "a", "circuit": "baseline-ibm2016", "noise": "boston-2026"},
        {"run": "b", "circuit": "baseline-contemporary", "noise": "boston-2026"},
    ], [{"case": 1, "run": "a", "simulation": "ideal"}])
    table = read_table(run_benchmark("mixed", config_copy / "results", shots=50) / "comparison.csv")
    assert str(table["case"].dtype) == "Int64"
    assert table["case"].iloc[0] == 1 and table["case"].iloc[1:].isna().all()
    assert tuple(table.columns) == COMPARISON_COLUMNS


def test_a_case_whose_pair_ends_off_its_ports_is_refused(config_copy):
    off = QuantumCircuit(5)  # CX between the ports with no SWAPs, so the router moves the pair
    off.h(0)
    off.cx(0, 4)
    save_circuit("off-ports", "Off the ports", "ibm2016", off, "A test circuit the router must move.")
    _write_benchmark(config_copy, "off", [{"run": "a", "circuit": "off-ports", "noise": "boston-2026"}],
                     [{"case": 1, "run": "a", "simulation": "ideal"}])
    with pytest.raises(ValueError, match="left the pair off its ports"):
        run_benchmark("off", config_copy / "results")
    assert not (config_copy / "results").exists(), "a refused benchmark writes nothing"


def test_a_case_whose_check_fires_with_no_noise_is_refused(config_copy):
    """A check on a qubit put in superposition keeps half the ideal shots; the kept ones still give F = 1."""
    circuit = swap_chain("ibm2016")
    check = ClassicalRegister(1, "check")
    circuit.add_register(check)
    circuit.h(1)
    circuit.measure(1, check[0])
    save_circuit("lossy", "Lossy", "ibm2016", circuit, "A test circuit whose check fires without noise.")
    _write_benchmark(config_copy, "lossy", [{"run": "a", "circuit": "lossy", "noise": "boston-2026"}],
                     [{"case": 1, "run": "a", "simulation": "ideal"}])
    with pytest.raises(ValueError, match=r"case 1: run 'a' kept 0\.\d+ of its ideal shots, not every one"):
        run_benchmark("lossy", config_copy / "results")
    assert not (config_copy / "results").exists(), "a refused benchmark writes nothing"


def test_a_case_whose_ideal_f_is_not_1_is_refused(config_copy):
    unpaired = QuantumCircuit(5)  # a superposition on one port and no entangling gate, so ideal F is about 1/4
    unpaired.h(0)
    save_circuit("unpaired", "Unpaired", "ibm2016", unpaired, "A test circuit that makes no pair.")
    _write_benchmark(config_copy, "unpaired", [{"run": "a", "circuit": "unpaired", "noise": "boston-2026"}],
                     [{"case": 1, "run": "a", "simulation": "ideal"}])
    with pytest.raises(ValueError, match=r"case 1: run 'a' has ideal F .*, not 1"):
        run_benchmark("unpaired", config_copy / "results")
    assert not (config_copy / "results").exists(), "a refused benchmark writes nothing"


@pytest.mark.parametrize(
    "runs, cases, message",
    [
        ([{"run": "a", "circuit": "baseline-ibm2016", "noise": "boston-2026"}] * 2, [], "run ids must be unique"),
        # A file written before runs were named by run, as cases name them, is refused naming the missing key.
        ([{"id": "a", "circuit": "baseline-ibm2016", "noise": "boston-2026"}], [],
         r"\$\.runs\[0\]: 'run' is a required property"),
        ([{"run": "a", "circuit": "baseline-ibm2016", "noise": "boston-2026"}],
         [{"case": 1, "run": "b", "simulation": "ideal"}], "names run 'b'"),
        ([{"run": "a", "circuit": "baseline-ibm2016", "noise": "boston-2026"}],
         [{"case": 1, "run": "a", "simulation": "ideal"}, {"case": 1, "run": "a", "simulation": "noisy"}],
         "each case is filled once"),
        ([{"run": "a", "circuit": "baseline-ibm2016", "noise": "boston-2026"}],
         [{"case": 2, "run": "a", "simulation": "noisy"}, {"case": 3, "run": "a", "simulation": "noisy"}],
         "cases 2 and 3 both name run 'a', noisy"),
        ([{"run": "a", "circuit": "baseline-ibm2016", "noise": "boston-2026"}],
         [{"case": 4, "run": "a", "simulation": "ideal"}],
         "case 4 is the contemporary model's ideal simulation; run 'a' is on ibm2016"),
        ([{"run": "a", "circuit": "baseline-ibm2016", "noise": "boston-2026"}],
         [{"case": 1, "run": "a", "simulation": "noisy"}],
         "case 1 is the ibm2016 model's ideal simulation; .* names its noisy simulation"),
        ([{"run": "a", "circuit": "baseline-hyperbolic", "noise": "boston-2026"}],
         [{"case": 9, "run": "a", "simulation": "ideal"}],
         "case 9 is the hyperbolic model's noisy simulation"),
        # A second run id on a baseline cannot fill a protected case: its circuit measures no check.
        ([{"run": "a", "circuit": "baseline-ibm2016", "noise": "boston-2026"},
          {"run": "b", "circuit": "baseline-ibm2016", "noise": "boston-2026"}],
         [{"case": 2, "run": "a", "simulation": "noisy"}, {"case": 3, "run": "b", "simulation": "noisy"}],
         "case 3 is a protected case; run 'b''s circuit 'baseline-ibm2016' measures no check register"),
    ],
)
def test_a_malformed_benchmark_file_raises_naming_the_field(config_copy, runs, cases, message):
    _write_benchmark(config_copy, "bad", runs, cases)
    with pytest.raises(ValueError, match=message):
        load_benchmark("bad")


@pytest.mark.parametrize("register", ["check", "check_zz", "flag"])
def test_a_protected_case_needs_a_circuit_that_measures_a_check(config_copy, register):
    circuit = swap_chain("hyperbolic")
    reg = ClassicalRegister(1, register)
    circuit.add_register(reg)
    circuit.measure(5, reg[0])  # a qubit off the pair's path, so the read changes nothing
    save_circuit("read-one", "Read one", "hyperbolic", circuit, "A test circuit that reads one spare qubit.")
    _write_benchmark(config_copy, "protected", [{"run": "a", "circuit": "read-one", "noise": "boston-2026"}],
                     [{"case": 9, "run": "a", "simulation": "noisy"}])
    if register == "flag":
        with pytest.raises(ValueError, match="case 9 is a protected case; .* measures no check register"):
            load_benchmark("protected")
    else:
        assert load_benchmark("protected")[0]["cases"][0]["case"] == 9


def _report_row(folder) -> str:
    """The report's cost row, which ends with the pair's arrival."""
    return [line for line in (folder / "report.md").read_text(encoding="utf-8").splitlines() if " µs | " in line][0]


def test_the_report_says_the_pair_arrived_only_when_the_ideal_f_is_1(config_copy):
    """A pair never made on the ports, in a circuit the router leaves alone, keeps the layout on the ports; the
    report pairs that with the ideal F and says NO."""
    unmade = QuantumCircuit(5)
    unmade.h(0)
    unmade.cx(0, 3)  # a pair on 0 and 3, a neighbour, never moved to the second port, 4
    save_circuit("unmade", "Unmade", "ibm2016", unmade, "A test circuit whose pair never reaches the second port.")
    folder = CircuitRun("unmade", "boston-2026", shots=500, base_seed=SEED).run().write(config_copy / "results")
    record = yaml.safe_load((folder / "bp.data.result.yaml").read_text(encoding="utf-8"))
    assert record["cost"]["pair_on_ports"] is True, "the layout alone says the pair is on the ports"
    assert re.search(r"\| NO \(ideal F 0\.\d{4}\) \|$", _report_row(folder))
    baseline = CircuitRun("baseline-ibm2016", "boston-2026", shots=500, base_seed=SEED).run()
    baseline = baseline.write(config_copy / "results")
    assert _report_row(baseline).endswith("| yes |")


PICTURES = {"graph.png"} | {f"{group}/{basis}.png" for group in ("written", "compiled", "timeline")
                             for basis in ("zz", "xx", "yy")}


def _files(folder):
    """Every file in a run folder, by its path from the folder."""
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


@pytest.mark.parametrize("diagrams", ["lean", "full"])
def test_every_run_folder_holds_the_same_pictures_whatever_diagrams_says(tmp_path, diagrams):
    run = CircuitRun("baseline-ibm2016", "boston-2026", shots=100, base_seed=SEED, diagrams=diagrams)
    folder = run.run().write(tmp_path)
    assert set(_files(folder)) == PICTURES | {"report.md", "bp.data.result.yaml", "counts.csv", "simulations.csv"}
    assert yaml.safe_load((folder / "bp.data.result.yaml").read_text(encoding="utf-8"))["diagrams"] == diagrams
    assert {p.relative_to(folder).as_posix() for p in write_views(folder)} == PICTURES | {"report.md"}
    assert len({_files(folder)[f"written/{basis}.png"] for basis in ("zz", "xx", "yy")}) == 3  # one per reading


def test_a_timeline_picture_has_a_wider_margin_than_the_other_pictures(tmp_path, monkeypatch):
    folder = CircuitRun("baseline-ibm2016", "boston-2026", shots=50, base_seed=SEED).run().write(tmp_path)
    wide = _files(folder)
    monkeypatch.setattr(run_module, "TIMELINE_MARGIN", 0.1)  # matplotlib's default, which the other pictures keep
    write_views(folder)
    narrow = _files(folder)
    for basis in ("zz", "xx", "yy"):
        name = f"timeline/{basis}.png"
        added = int.from_bytes(wide[name][16:20], "big") - int.from_bytes(narrow[name][16:20], "big")  # PNG widths
        assert added == pytest.approx(2 * (0.4 - 0.1) * 150, abs=2)  # both sides, at 150 dots per inch
    assert all(wide[name] == narrow[name] for name in wide if not name.startswith("timeline/"))


def test_a_redraw_replaces_the_earlier_picture_names_and_a_profile_without_durations_has_no_timeline(tmp_path):
    folder = CircuitRun("baseline-ibm2016", "organiser-cx2", shots=50, base_seed=SEED).run().write(tmp_path)
    assert not (folder / "timeline").exists() and (folder / "compiled" / "yy.png").is_file()
    for name in OLD_VIEWS:
        (folder / name).write_bytes(b"a picture from the earlier layout")
    write_views(folder)
    assert not any((folder / name).exists() for name in OLD_VIEWS)
    assert set(_files(folder)) & PICTURES == PICTURES - {f"timeline/{basis}.png" for basis in ("zz", "xx", "yy")}


def test_views_refuse_a_changed_file_before_drawing(config_copy):
    run = CircuitRun("baseline-ibm2016", "boston-2026", shots=100, base_seed=SEED)
    folder = run.run().write(config_copy / "results")
    before = _files(folder)
    path = config_copy / "config" / "processor" / "bp.data.processor.ibm2016.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("label: ", "label: Edited ", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="bp.data.processor.ibm2016.yaml changed since it was recorded"):
        write_views(folder)
    assert main(["report", str(folder)]) == 2
    assert _files(folder) == before, "a refused redraw changes no file"


@pytest.mark.slow
def test_views_draw_without_pyplot_or_a_backend_switch(tmp_path, monkeypatch):
    """Every view is drawn on its own Figure: pyplot makes no figure, so a GUI backend gets no window object
    for Aer's worker threads to free, and nothing switches or resolves the backend."""
    import matplotlib
    import matplotlib.pyplot as plt

    def refuse(*args, **kwargs):
        raise AssertionError("a view went through pyplot or switched the backend")

    monkeypatch.setattr(plt, "new_figure_manager", refuse)  # every pyplot figure is made through it
    monkeypatch.setattr(plt, "switch_backend", refuse)
    monkeypatch.setattr(matplotlib, "use", refuse)
    folder = CircuitRun("baseline-contemporary", "boston-2026", shots=50, base_seed=SEED).run().write(tmp_path)
    assert PICTURES <= set(_files(folder))
    # qiskit draws a global phase through pyplot; the exporter drops it today, so a record edited to hold one tests
    # that the views leave it out.
    path = folder / "bp.data.result.yaml"
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    record["compiled"]["ZZ"] = record["compiled"]["ZZ"].replace(" q;\n", " q;\ngphase(1.0);\n", 1)
    assert "gphase" in record["compiled"]["ZZ"]
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    write_views(folder)


@pytest.mark.slow
def test_writing_a_run_leaves_the_matplotlib_backend_as_it_was(tmp_path):
    """A notebook's inline backend survives a run's write; a fresh process shows the import changes nothing either."""
    script = (
        "import sys, matplotlib; matplotlib.use('pdf'); "
        "from bellbench.run import CircuitRun; "
        f"CircuitRun('baseline-ibm2016', 'boston-2026', shots=50, base_seed=1).run().write(sys.argv[1]); "
        "print(matplotlib.get_backend())"
    )
    done = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True, check=True)
    assert done.stdout.strip().splitlines()[-1] == "pdf"


def test_command_line(tmp_path, capsys):
    folder = CircuitRun("baseline-ibm2016", "boston-2026", shots=100, base_seed=SEED).run().write(tmp_path)
    assert main(["rerun", str(folder)]) == 0
    assert main(["report", str(folder / RESULT_FILE)]) == 0
    assert main(["nonsense"]) == 2
    assert "usage" in capsys.readouterr().err
