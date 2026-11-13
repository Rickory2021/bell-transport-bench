# tests/test_self_test.py
"""Every run a benchmark lists passes the self-test, whether it fills a case or not.

The self-test: the pair ends on the ports, and the ideal simulation gives F = 1
and keeps every shot. A study, a benchmark with no cases, is refused for a run
that fails it, before anything is written; a refusal names the run, and the
cases it fills.
"""

import pytest
import yaml
from qiskit import ClassicalRegister, QuantumCircuit

from bellbench.circuits import save_circuit, swap_chain
from bellbench.run import run_benchmark

GOOD = {"run": "good", "circuit": "baseline-ibm2016", "noise": "boston-2026"}


def _write_benchmark(root, name, runs, cases=()):
    data = {"name": name, "label": "Test", "notes": "A test benchmark.", "shots": 100, "base_seed": 7, "runs": runs}
    if cases:
        data["cases"] = list(cases)
    path = root / "config" / "benchmark" / f"bp.data.benchmark.{name}.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _off_ports():
    off = QuantumCircuit(5)  # CX between the ports with no SWAPs, so the router moves the pair
    off.h(0)
    off.cx(0, 4)
    return off


def _lossy():
    circuit = swap_chain("ibm2016")  # a check on a qubit in superposition keeps half the ideal shots
    check = ClassicalRegister(1, "check")
    circuit.add_register(check)
    circuit.h(1)
    circuit.measure(1, check[0])
    return circuit


def _unpaired():
    unpaired = QuantumCircuit(5)  # a superposition on one port and no entangling gate, so ideal F is about 1/4
    unpaired.h(0)
    return unpaired


@pytest.mark.parametrize("build, message", [
    (_off_ports, r"benchmark 'study': run 'bad' left the pair off its ports"),
    (_lossy, r"benchmark 'study': run 'bad' kept 0\.\d+ of its ideal shots, not every one"),
    (_unpaired, r"benchmark 'study': run 'bad' has ideal F .*, not 1"),
])
def test_a_study_run_that_fails_the_self_test_is_refused(config_copy, build, message):
    save_circuit("bad", "Bad", "ibm2016", build(), "A test circuit that fails the self-test.")
    _write_benchmark(config_copy, "study", [GOOD, {"run": "bad", "circuit": "bad", "noise": "boston-2026"}])
    with pytest.raises(ValueError, match=message):
        run_benchmark("study", config_copy / "results")
    assert not (config_copy / "results").exists(), "a refused benchmark writes nothing"


def test_a_run_that_fills_two_cases_names_both(config_copy):
    save_circuit("bad", "Bad", "ibm2016", _unpaired(), "A test circuit that fails the self-test.")
    _write_benchmark(config_copy, "both", [{"run": "a", "circuit": "bad", "noise": "boston-2026"}],
                     [{"case": 1, "run": "a", "simulation": "ideal"}, {"case": 2, "run": "a", "simulation": "noisy"}])
    with pytest.raises(ValueError, match=r"benchmark 'both': cases 1, 2: run 'a' has ideal F"):
        run_benchmark("both", config_copy / "results")


def test_a_study_whose_runs_pass_is_written(config_copy):
    _write_benchmark(config_copy, "study", [GOOD])
    assert (run_benchmark("study", config_copy / "results", shots=50) / "report.md").is_file()
