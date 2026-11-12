# tests/test_circuits.py
"""Circuit files hold the gates as written, and the swap-chain transport builds the core baselines.

Covers docs/DESIGN.md, sections 2 and 7, as D-83 and D-86 settle them: the three
committed baseline files equal what the transport builds, a circuit file's gates
round-trip through OpenQASM 3, and a file whose gates do not fit its processor,
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
    assert loaded.analysis == {"name": "postselect"}
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


def test_gates_round_trip_through_openqasm_3():
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
        (lambda: _with_register("port"), "classical register 'port' is not named by a role"),
        (lambda: _with_register("checks"), "classical register 'checks' is not named by a role"),
        (lambda: _with_register("frame_y"), "classical register 'frame_y' is not named by a role"),
        (lambda: _with_register("check_"), "classical register 'check_' is not named by a role"),
    ],
)
def test_gates_that_do_not_fit_raise_naming_the_field(build, message):
    with pytest.raises(ValueError, match=r"\$\.circuit: " + message):
        circuit_from_qasm(circuit_to_qasm(build()), 5)


@pytest.mark.parametrize(
    "name", ["check", "flag", "frame_z", "frame_x", "check_zz", "flag_zz", "frame_z_bus", "check_vac_3"]
)
def test_registers_named_by_a_role_load(name):
    circuit = _with_register(name)
    assert [r.name for r in circuit_from_qasm(circuit_to_qasm(circuit), 5).cregs] == [name]


def _conditioned():
    circuit = _with_register("check")
    with circuit.if_test((circuit.cregs[0][0], 1)):
        circuit.x(1)
    return circuit


def _delay(unit):
    circuit = QuantumCircuit(5)
    circuit.delay(250 if unit == "dt" else 1, 1, unit=unit)
    return circuit


def _on_port(operation):
    circuit = _with_register("check")
    if operation == "reset":
        circuit.reset(4)
    else:
        circuit.measure(4, circuit.cregs[0][0])
    return circuit


@pytest.mark.parametrize(
    "build, message",
    [
        (_conditioned, r"if_else on qubit\(s\) \[1\] depends on a measured bit"),
        (lambda: _delay("dt"), r"the delay on qubit\(s\) \[1\] is in dt"),
        (lambda: _on_port("measure"), "the circuit measures port qubit 4"),
        (lambda: _on_port("reset"), "the circuit resets port qubit 4"),
    ],
)
def test_what_a_circuit_file_may_not_hold_is_refused(build, message):
    with pytest.raises(ValueError, match=r"\$\.circuit: " + message):
        circuit_from_qasm(circuit_to_qasm(build()), 5, ports=(2, 4))  # _with_register reads qubit 0


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
def test_a_delay_in_real_time_keeps_its_unit(unit):
    loaded = circuit_from_qasm(circuit_to_qasm(_delay(unit)), 5)
    delay = loaded.data[0].operation
    assert (delay.name, delay.unit, float(delay.duration)) == ("delay", unit, 1.0)


def test_save_refuses_a_conditioned_circuit_and_leaves_no_file(config_copy):
    circuit = swap_chain("ibm2016")
    check = ClassicalRegister(1, "check")
    circuit.add_register(check)
    circuit.measure(1, check[0])
    with circuit.if_test((check[0], 1)):
        circuit.x(1)
    with pytest.raises(ValueError, match="depends on a measured bit"):
        save_circuit("fed-forward", "Fed forward", "ibm2016", circuit, "A test circuit.")
    assert not (config_copy / "config" / "circuit" / "bp.data.circuit.fed-forward.yaml").exists()


def test_a_circuit_file_measuring_its_processors_port_is_refused(config_copy):
    circuit = swap_chain("ibm2016")
    check = ClassicalRegister(1, "check")
    circuit.add_register(check)
    circuit.measure(4, check[0])  # 4 is the 2016 graph's second port
    with pytest.raises(ValueError, match="measures port qubit 4"):
        save_circuit("port-read", "Port read", "ibm2016", circuit, "A test circuit.")


def test_unparseable_gates_raise():
    with pytest.raises(ValueError, match="do not parse as OpenQASM 3"):
        circuit_from_qasm("OPENQASM 3.0;\nqubit[5] q;\nfoo q[0];\n", 5)


def test_an_openqasm_2_file_is_refused():
    with pytest.raises(ValueError, match="do not parse as OpenQASM 3"):
        circuit_from_qasm('OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[5];\nh q[0];\n', 5)


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


def test_an_overwrite_that_does_not_fit_restores_the_earlier_file(config_copy):
    path = save_circuit("trial", "Trial", "ibm2016", swap_chain("ibm2016"), "A test circuit.")
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="needs one register"):
        save_circuit("trial", "Trial", "ibm2016", swap_chain("contemporary"), "For another graph.", overwrite=True)
    assert path.read_text(encoding="utf-8") == before
    assert load_circuit("trial").circuit == swap_chain("ibm2016")


def test_a_circuit_file_naming_an_unknown_processor_raises(config_copy):
    path = config_copy / "config" / "circuit" / "bp.data.circuit.orphan.yaml"
    data = yaml.safe_load(configs.config_path("circuit", "baseline-ibm2016").read_text(encoding="utf-8"))
    path.write_text(yaml.safe_dump({**data, "name": "orphan", "processor": "no-such-graph"}), encoding="utf-8")
    message = r"config/circuit/bp\.data\.circuit\.orphan\.yaml: \$\.processor: no processor file named 'no-such-graph'"
    with pytest.raises(ValueError, match=message):
        load_circuit("orphan")
