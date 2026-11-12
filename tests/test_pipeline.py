# tests/test_pipeline.py
"""The pipeline's steps, each alone, and the organisers' recorded fidelities reproduced exactly.

The reproduction (D-50) follows the organisers' recipe, which this file
rewrites from their example notebook's description
(docs/CHALLENGE.md, The organisers' worked example): Qiskit's basic router at
optimisation level 0 moves the pair out, the same SWAPs run in reverse, and the
final compile uses only H and CX. Under the organiser-cx2 profile the exact
fidelity from the ports' density matrix, through the one fidelity function,
rounds to their recorded values.
"""

import math

import networkx as nx
import pytest
from qiskit import QuantumCircuit, transpile
from qiskit.transpiler import CouplingMap, generate_preset_pass_manager

from bellbench.fidelity import fidelity_from_counts, fidelity_from_density
from bellbench.noise import NoiseControl
from bellbench.pipeline import (
    PORT_REGISTER,
    basis_circuits,
    compile_bases,
    cost,
    derive_seed,
    pair_on_ports,
    port_density_matrix,
    register_counts,
    schedule,
    scheduled_duration,
    simulate,
)

# The organisers' recorded results: SWAPs out, CX gates, depth, noisy fidelity.
ORGANISERS = {
    "ibm2016": (1, 7, 8, 0.915),
    "contemporary": (3, 19, 20, 0.795),
    "hyperbolic": (2, 13, 14, 0.852),
}


def _organiser_recipe(nc: NoiseControl) -> tuple[QuantumCircuit, int]:
    """The organisers' circuit on the processor's qubits, and the SWAPs the basic router added going out."""
    coupling = CouplingMap([list(e) for e in nc.edges])
    coupling.make_symmetric()
    bell = QuantumCircuit(2)
    bell.h(0)
    bell.cx(0, 1)
    routed = transpile(
        bell,
        coupling_map=coupling,
        initial_layout=list(nc.ports),
        routing_method="basic",
        basis_gates=["h", "cx", "swap"],
        optimization_level=0,
    )
    swaps = [tuple(routed.find_bit(q).index for q in i.qubits) for i in routed.data if i.operation.name == "swap"]
    there_and_back = QuantumCircuit(routed.num_qubits)
    there_and_back.compose(routed, inplace=True)
    for a, b in reversed(swaps):
        there_and_back.swap(a, b)
    compiled = transpile(
        there_and_back,
        coupling_map=coupling,
        initial_layout=list(range(there_and_back.num_qubits)),
        routing_method="none",
        basis_gates=["h", "cx"],
        optimization_level=0,
    )
    return compiled, len(swaps)


@pytest.mark.parametrize("processor", sorted(ORGANISERS))
def test_organisers_recorded_fidelities_reproduce_exactly(processor):
    swaps, cx, depth, recorded = ORGANISERS[processor]
    nc = NoiseControl(processor, "organiser-cx2")
    circuit, route_swaps = _organiser_recipe(nc)
    assert (route_swaps, circuit.count_ops()["cx"], circuit.depth()) == (swaps, cx, depth)

    ideal = fidelity_from_density(port_density_matrix(circuit, None, nc.ports))
    assert ideal.value == pytest.approx(1.0, abs=1e-12)
    noisy = fidelity_from_density(port_density_matrix(circuit, nc.noise_model, nc.ports))
    assert round(noisy.value, 3) == recorded


# -- Basis circuits ---------------------------------------------------------------


def _baseline(nc: NoiseControl) -> QuantumCircuit:
    """The pair made on the first port, moved next to the second with SWAPs, joined by CX, and moved back."""
    a, b = nc.ports
    path = nx.shortest_path(nc.graph, a, b)
    qc = QuantumCircuit(nc.num_qubits)
    qc.h(a)
    hops = list(zip(path[:-2], path[1:-1]))
    for u, v in hops:
        qc.swap(u, v)
    qc.cx(path[-2], b)
    for u, v in reversed(hops):
        qc.swap(u, v)
    return qc


def test_basis_circuits_rotate_and_measure_the_ports():
    nc = NoiseControl("ibm2016", "boston-2026")
    written = _baseline(nc)
    out = basis_circuits(written, nc.ports)
    expected = {
        "ZZ": ["measure", "measure"],
        "XX": ["h", "h", "measure", "measure"],
        "YY": ["sdg", "h", "sdg", "h", "measure", "measure"],
    }
    assert set(out) == set(expected)
    for basis, qc in out.items():
        assert [r.name for r in qc.cregs] == [PORT_REGISTER]
        added = qc.data[len(written.data):]
        assert [i.operation.name for i in added] == expected[basis]
        assert {qc.find_bit(i.qubits[0]).index for i in added} == set(nc.ports)
        measured = [(qc.find_bit(i.qubits[0]).index, qc.find_bit(i.clbits[0]).index) for i in added if i.operation.name == "measure"]
        assert measured == [(nc.ports[0], 0), (nc.ports[1], 1)]
    assert written.num_clbits == 0, "the written circuit is left unchanged"


@pytest.mark.parametrize("ports", [(0,), (0, 0), (0, 9), (True, 1)])
def test_basis_circuits_reject_bad_ports(ports):
    with pytest.raises(ValueError):
        basis_circuits(QuantumCircuit(5), ports)


# -- Compile and cost --------------------------------------------------------------


@pytest.mark.parametrize("processor, swaps, cz", [("ibm2016", 2, 7), ("contemporary", 6, 19), ("hyperbolic", 4, 13)])
def test_baseline_keeps_its_swaps_and_the_pair_on_the_ports(processor, swaps, cz):
    nc = NoiseControl(processor, "boston-2026")
    compiled = compile_bases(basis_circuits(_baseline(nc), nc.ports), nc, seed=5)
    c = cost(compiled, nc.ports)
    assert (c["swaps"], c["router_swaps"], c["two_qubit_gates"]) == (swaps, 0, cz)
    assert c["pair_on_ports"] is True
    assert set(c["qubits_used"]) >= set(nc.ports)
    assert all(sum(edges.values()) == cz for edges in c["two_qubit_gates_by_edge"].values())
    allowed = {f"{min(e)}-{max(e)}" for e in nc.edges}
    assert all(set(edges) <= allowed for edges in c["two_qubit_gates_by_edge"].values())


def test_router_swaps_are_counted_and_move_the_pair_off_the_ports():
    nc = NoiseControl("contemporary", "boston-2026")
    a, b = nc.ports
    qc = QuantumCircuit(nc.num_qubits)
    qc.h(a)
    qc.cx(a, b)  # four hops apart, so the router must add SWAPs
    c = cost(compile_bases(basis_circuits(qc, nc.ports), nc, seed=5), nc.ports)
    assert c["router_swaps"] == c["swaps"] == 3
    assert c["pair_on_ports"] is False


def test_a_back_to_back_swap_pair_is_not_counted():
    nc = NoiseControl("ibm2016", "boston-2026")
    a, b = nc.ports
    qc = QuantumCircuit(nc.num_qubits)
    qc.h(a)
    qc.swap(0, 3)
    qc.swap(0, 3)  # cancels: the pair never moves
    qc.cx(0, 3)
    qc.swap(3, 4)
    qc.swap(3, 4)
    compiled = compile_bases(basis_circuits(qc, nc.ports), nc, seed=5)
    assert compiled["ZZ"].swaps_after_init == 0
    assert cost(compiled, nc.ports)["swaps"] == 0


@pytest.mark.parametrize("processor", ["ibm2016", "contemporary", "hyperbolic"])
def test_staged_compile_equals_one_transpile(processor):
    nc = NoiseControl(processor, "boston-2026")
    circuits = basis_circuits(_baseline(nc), nc.ports)
    compiled = compile_bases(circuits, nc, seed=17)
    for basis, qc in circuits.items():
        pm = generate_preset_pass_manager(
            optimization_level=1, target=nc.target, initial_layout=list(range(nc.num_qubits)), seed_transpiler=17
        )
        assert compiled[basis].compiled == pm.run(qc)


def test_depth_counts_gates_only():
    nc = NoiseControl("ibm2016", "boston-2026")
    compiled = compile_bases(basis_circuits(_baseline(nc), nc.ports), nc, seed=5)
    gates_only = compiled["ZZ"].compiled.remove_final_measurements(inplace=False)
    assert cost(compiled, nc.ports)["depth"] == gates_only.depth() < compiled["ZZ"].compiled.depth()


def test_compile_rejects_a_circuit_not_on_the_physical_qubits():
    nc = NoiseControl("ibm2016", "boston-2026")
    with pytest.raises(ValueError, match="physical qubits"):
        compile_bases(basis_circuits(QuantumCircuit(3), (0, 2)), nc, seed=1)


def test_pair_on_ports_is_true_when_routing_moved_nothing():
    nc = NoiseControl("ibm2016", "boston-2026")
    zz = compile_bases(basis_circuits(_baseline(nc), nc.ports), nc, seed=5)["ZZ"]
    assert pair_on_ports(zz.routed, nc.ports)


# -- Schedule ----------------------------------------------------------------------


def test_schedule_turns_idle_time_into_delays():
    nc = NoiseControl("contemporary", "boston-2026")
    zz = compile_bases(basis_circuits(_baseline(nc), nc.ports), nc, seed=5)["ZZ"].compiled
    scheduled = schedule(zz, nc)
    assert "delay" in scheduled.count_ops()
    assert scheduled_duration(scheduled, nc) > 0


def test_a_depolarising_profile_is_not_scheduled():
    nc = NoiseControl("contemporary", "organiser-cx2")
    zz_only = {"ZZ": basis_circuits(_baseline(nc), nc.ports)["ZZ"]}
    zz = compile_bases(zz_only, nc, seed=5)["ZZ"].compiled
    assert schedule(zz, nc) is zz
    assert scheduled_duration(zz, nc) is None


# -- Simulate and fidelity ---------------------------------------------------------


def _run(nc: NoiseControl, noise_model, seed: int, shots: int = 2000, method: str = "automatic"):
    compiled = compile_bases(basis_circuits(_baseline(nc), nc.ports), nc, seed=5)
    scheduled = {basis: schedule(c.compiled, nc) for basis, c in compiled.items()}
    return simulate(scheduled, noise_model, shots=shots, seed=seed, method=method)


@pytest.mark.parametrize("processor", ["ibm2016", "contemporary", "hyperbolic"])
def test_ideal_simulation_gives_fidelity_one(processor):
    nc = NoiseControl(processor, "boston-2026")
    sim = _run(nc, None, seed=1)
    f = fidelity_from_counts(sim.counts)
    assert f.value == 1.0 and f.standard_error == 0.0
    assert all(sum(c.values()) == sim.shots for c in sim.counts.values())


def test_noisy_simulation_is_repeatable_by_seed():
    nc = NoiseControl("contemporary", "boston-2026")
    first, again, other = (_run(nc, nc.noise_model, seed=s) for s in (7, 7, 8))
    assert first.counts == again.counts and first.seeds == again.seeds
    assert first.counts != other.counts
    f = fidelity_from_counts(first.counts)
    assert 0.5 < f.value < 1 and f.standard_error > 0
    assert set(first.methods) == {"XX", "YY", "ZZ"} and all(first.methods.values())


def test_a_recorded_method_can_be_forced():
    nc = NoiseControl("ibm2016", "boston-2026")
    assert set(_run(nc, nc.noise_model, seed=3, shots=200, method="density_matrix").methods.values()) == {"density_matrix"}


@pytest.mark.parametrize("shots", [0, -5, 2.5, True])
def test_invalid_shots_raise(shots):
    nc = NoiseControl("ibm2016", "boston-2026")
    with pytest.raises(ValueError, match="shots"):
        _run(nc, None, seed=1, shots=shots)


def test_register_counts_sum_over_other_registers():
    from qiskit import ClassicalRegister

    qc = QuantumCircuit(2)
    qc.add_register(ClassicalRegister(2, "port"))
    qc.add_register(ClassicalRegister(1, "check"))
    counts = {"0 00": 5, "1 00": 2, "1 11": 3}  # the last register is written first
    assert register_counts(counts, qc, "port") == {"00": 7, "11": 3}
    assert register_counts(counts, qc, "check") == {"0": 5, "1": 5}
    with pytest.raises(ValueError, match="no classical register"):
        register_counts(counts, qc, "flag")


# -- Seeds -------------------------------------------------------------------------


def test_derive_seed_is_stable_distinct_and_32_bit():
    a = derive_seed(2026, "run-a", "noisy")
    assert a == derive_seed(2026, "run-a", "noisy")
    assert len({a, derive_seed(2026, "run-a", "ideal"), derive_seed(2026, "run-b", "noisy"), derive_seed(2027, "run-a", "noisy")}) == 4
    assert 0 <= a < 2**32


@pytest.mark.parametrize("base, labels", [(True, ()), (-1, ()), (2**32, ()), (1.5, ()), (1, (1.5,)), (1, (None,))])
def test_derive_seed_rejects_bad_input(base, labels):
    with pytest.raises(ValueError):
        derive_seed(base, *labels)


def test_ideal_fidelity_is_exactly_one_without_shots():
    nc = NoiseControl("hyperbolic", "boston-2026")
    zz = compile_bases(basis_circuits(_baseline(nc), nc.ports), nc, seed=5)["ZZ"].compiled
    f = fidelity_from_density(port_density_matrix(zz, None, nc.ports))
    assert math.isclose(f.value, 1.0, abs_tol=1e-12)
