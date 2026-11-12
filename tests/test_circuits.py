# tests/test_circuits.py
"""Circuit files hold the gates as written, and the swap-chain transport builds the core baselines.

Covers docs/DESIGN.md, sections 2 and 7, as D-83 and D-86 settle them: the three
committed baseline files equal what the transport builds, a circuit file's gates
round-trip through OpenQASM 2, and a file whose gates do not fit its processor,
or that names a register outside its roles, fails to load naming the field.
"""

import pytest
import yaml
from qiskit import ClassicalRegister, QuantumCircuit

from bellbench import configs
from bellbench.circuits import (
    CORE_PROCESSORS,
    baseline_name,
    circuit_from_qasm,
    circuit_to_qasm,
    load_circuit,
    save_circuit,
    smallest_shortest_path,
    swap_chain,
)


@pytest.mark.parametrize("processor", CORE_PROCESSORS)
def test_committed_baseline_equals_what_the_transport_builds(processor):
    loaded = load_circuit(baseline_name(processor))
    proc = configs.load_processor(processor)
    path = smallest_shortest_path(configs.processor_graph(proc), *proc["ports"])
    assert loaded.processor == processor
    assert loaded.analysis == "postselect"
    assert loaded.circuit == swap_chain(processor)
    assert str(path) in loaded.notes
    assert loaded.record["path"] == f"config/circuit/bp.data.circuit.{baseline_name(processor)}.yaml"


@pytest.mark.parametrize("processor, path", [("ibm2016", [0, 3, 4]), ("contemporary", [0, 1, 2, 3, 7])])
def test_shortest_path_is_the_lexicographically_smallest(processor, path):
    proc = configs.load_processor(processor)
    assert smallest_shortest_path(configs.processor_graph(proc), *proc["ports"]) == path


def test_swap_chain_goes_out_and_back():
    circuit = swap_chain("contemporary", [0, 4, 5, 6, 7])
    ops = [(i.operation.name, [circuit.find_bit(q).index for q in i.qubits]) for i in circuit.data]
    assert ops == [
        ("h", [0]),
        ("swap", [0, 4]), ("swap", [4, 5]), ("swap", [5, 6]),
        ("cx", [6, 7]),
        ("swap", [5, 6]), ("swap", [4, 5]), ("swap", [0, 4]),
    ]


@pytest.mark.parametrize(
    "path, message",
    [([1, 2, 3, 7], "must run from the first port"), ([0, 2, 3, 7], "not a coupler"), ([0, 1, 0, 1, 2, 3, 7], "twice")],
)
def test_swap_chain_rejects_a_bad_path(path, message):
    with pytest.raises(ValueError, match=message):
        swap_chain("contemporary", path)


def test_gates_round_trip_through_openqasm_2():
    circuit = swap_chain("hyperbolic")
    check = ClassicalRegister(1, "check")
    circuit.add_register(check)
    circuit.reset(5)
    circuit.measure(6, check[0])
    assert circuit_from_qasm(circuit_to_qasm(circuit), circuit.num_qubits) == circuit


@pytest.mark.parametrize(
    "build, message",
    [
        (lambda: QuantumCircuit(4), r"needs one register q\[5\]"),
        (lambda: _with_register("port"), "classical register 'port' is not one of check, flag"),
    ],
)
def test_gates_that_do_not_fit_raise_naming_the_field(build, message):
    with pytest.raises(ValueError, match=r"\$\.circuit: " + message):
        circuit_from_qasm(circuit_to_qasm(build()), 5)


def test_unparseable_gates_raise():
    with pytest.raises(ValueError, match="do not parse as OpenQASM 2"):
        circuit_from_qasm("OPENQASM 2.0;\nqreg q[5];\nfoo q[0];\n", 5)


def _with_register(name):
    circuit = QuantumCircuit(5)
    reg = ClassicalRegister(1, name)
    circuit.add_register(reg)
    circuit.measure(0, reg[0])
    return circuit


def test_save_then_load(config_copy):
    path = save_circuit("trial", "Trial", "ibm2016", swap_chain("ibm2016"), "A test circuit.")
    assert path == config_copy / "config" / "circuit" / "bp.data.circuit.trial.yaml"
    assert path.read_text(encoding="utf-8").startswith("# config/circuit/bp.data.circuit.trial.yaml\n")
    assert load_circuit("trial").circuit == swap_chain("ibm2016")
    with pytest.raises(FileExistsError):
        save_circuit("trial", "Trial", "ibm2016", swap_chain("ibm2016"), "Again.")


def test_a_circuit_that_does_not_fit_is_never_left_on_disk(config_copy):
    with pytest.raises(ValueError, match="needs one register"):
        save_circuit("wrong", "Wrong", "ibm2016", swap_chain("contemporary"), "Built for another graph.")
    assert not (config_copy / "config" / "circuit" / "bp.data.circuit.wrong.yaml").exists()


def test_a_circuit_file_naming_an_unknown_processor_raises(config_copy):
    path = config_copy / "config" / "circuit" / "bp.data.circuit.orphan.yaml"
    data = yaml.safe_load(configs.config_path("circuit", "baseline-ibm2016").read_text(encoding="utf-8"))
    path.write_text(yaml.safe_dump({**data, "name": "orphan", "processor": "no-such-graph"}), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="no processor file named 'no-such-graph'"):
        load_circuit("orphan")
