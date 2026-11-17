# tests/test_deliverable.py
"""The deliverable and its extended benchmarks: the nine cases the submission reports, and each graph's alternatives.

Covers docs/DESIGN.md, section 6. deliverable-2026-11-17 fills the nine cases
with the organisers' baseline and one protection strategy, ghz_uncompute then
vacancy, on every graph, and runs nothing else, at five times the core's shots
under its noise profile and seed. Each graph's extended benchmark runs the protected case beside the circuits
that differ from it by one step, with no case filled, under the deliverable's
noise profile, shots and seed, so a run they share repeats its numbers exactly.
Every circuit they add is what the builders make, so "the same builder steps on
every graph" holds by construction.
"""

import pytest

from bellbench import builders, configs
from bellbench.circuits import load_circuit
from bellbench.run import load_benchmark, read_table, run_benchmark

DELIVERABLE = "deliverable-2026-11-17"
EXTENDED = {p: f"{DELIVERABLE}-extended-{p}" for p in configs.CORE_PROCESSORS}

# Every circuit the deliverable and its extended benchmarks add, and the builder steps that make it.
BUILT = {}
for _p in configs.CORE_PROCESSORS:
    BUILT |= {
        f"ghz-measure-{_p}": (_p, [builders.ghz_measure]),
        f"ghz-uncompute-{_p}": (_p, [builders.ghz_uncompute]),
        f"move-chain-vacancy-{_p}": (_p, [builders.move_chain, builders.vacancy]),
        f"ghz-uncompute-vacancy-{_p}": (_p, [builders.ghz_uncompute, builders.vacancy]),
    }


def _core():
    data, _ = load_benchmark("core")
    return data["runs"][0]["noise"], data["shots"], data["base_seed"]


def test_the_deliverable_fills_the_nine_cases_with_the_baseline_and_the_vacancy_read():
    """Each row's ideal and noisy cases are the organisers' baseline and its protected case ghz_uncompute with its
    vacancy read, and every run fills a case, all under the core's noise profile and seed."""
    data, _ = load_benchmark(DELIVERABLE)
    runs = {r["run"]: r for r in data["runs"]}
    expected = {}
    for row, processor in enumerate(configs.CORE_PROCESSORS):
        expected |= {3 * row + 1: f"baseline-{processor}", 3 * row + 2: f"baseline-{processor}",
                     3 * row + 3: f"ghz-uncompute-vacancy-{processor}"}
    assert {c["case"]: runs[c["run"]]["circuit"] for c in data["cases"]} == expected
    assert set(runs) == {c["run"] for c in data["cases"]}  # nothing runs that fills no case
    noise, _, seed = _core()
    assert {r["noise"] for r in data["runs"]} == {noise}
    assert (data["shots"], data["base_seed"]) == (100_000, seed)  # five times the core's shots, its seed
    assert not any("conditional" in r for r in data["runs"])  # no case reads a qubit mid-circuit


@pytest.mark.parametrize("processor", configs.CORE_PROCESSORS)
def test_each_extended_benchmark_sets_the_protected_case_beside_its_alternatives_on_one_graph(processor):
    data, _ = load_benchmark(EXTENDED[processor])
    circuits = [r["circuit"] for r in data["runs"]]
    assert {load_circuit(c).processor for c in circuits} == {processor}
    assert {f"baseline-{processor}", f"ghz-uncompute-{processor}", f"ghz-uncompute-vacancy-{processor}"} <= set(circuits)
    assert not data.get("cases")
    deliverable, _ = load_benchmark(DELIVERABLE)
    assert {r["noise"] for r in data["runs"]} == {deliverable["runs"][0]["noise"]}
    assert (data["shots"], data["base_seed"]) == (deliverable["shots"], deliverable["base_seed"])


@pytest.mark.parametrize("processor", configs.CORE_PROCESSORS)
def test_the_readout_off_run_differs_from_ghz_measure_only_in_its_interior_readout(processor):
    """The one run that changes the profile: ghz_measure's own circuit, with both readout errors at 0 on exactly the
    interior qubits it reads, so its difference from ghz_measure is readout error alone."""
    runs = {r["run"]: r for r in load_benchmark(EXTENDED[processor])[0]["runs"]}
    plain, off = runs[f"ghz-measure-{processor}"], runs[f"ghz-measure-{processor}-readout-0"]
    assert off["circuit"] == plain["circuit"] and off["noise"] == plain["noise"]
    fields = {"qubit.readout_error.reads_1_when_0", "qubit.readout_error.reads_0_when_1"}
    expected = {(q, f, 0.0) for q in builders.start(processor).interior for f in fields}
    assert {(o["qubits"], o["field"], o["value"]) for o in off["overrides"]} == expected
    assert [r for r in runs.values() if r.get("overrides")] == [off]


@pytest.mark.parametrize("benchmark", [DELIVERABLE, *EXTENDED.values()])
def test_each_run_is_named_for_its_circuit(benchmark):
    """A run's name is its circuit's name, plus a suffix only where the benchmark runs that circuit again under other
    settings, so one name means one circuit in the file, the results folder and every table."""
    runs = load_benchmark(benchmark)[0]["runs"]
    plain = [r for r in runs if r["run"] == r["circuit"]]
    assert {r["circuit"] for r in plain} == {r["circuit"] for r in runs}  # every circuit runs once under its own name
    for r in runs:
        assert r["run"] == r["circuit"] or (r["run"].startswith(r["circuit"] + "-") and r.get("overrides"))


@pytest.mark.parametrize("name", sorted(BUILT))
def test_each_added_circuit_file_is_what_the_builders_make(name):
    processor, steps = BUILT[name]
    state = builders.start(processor)
    for step in steps:
        state = step(state)
    loaded = load_circuit(name)
    assert loaded.circuit == state.circuit and loaded.analysis == state.analysis()


@pytest.mark.slow
def test_the_deliverable_runs_end_to_end(tmp_path):
    """Every case passes the self-test: the pair ends on the ports, and every ideal simulation gives F = 1 with
    every shot kept."""
    folder = run_benchmark(DELIVERABLE, tmp_path, shots=100)
    table = read_table(folder / "comparison.csv")
    assert sorted(table["case"].dropna()) == list(range(1, 10))
    ideal = table[table["simulation"] == "ideal"]
    assert (ideal["fidelity"] == 1.0).all() and (ideal["acceptance"] == 1.0).all()
