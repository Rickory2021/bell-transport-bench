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

import pytest
from qiskit import QuantumCircuit, transpile
from qiskit.transpiler import CouplingMap, generate_preset_pass_manager

from bellbench.circuits import smallest_shortest_path, swap_chain
from bellbench.configs import load_noise
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


@pytest.mark.parametrize("processor", sorted(ORGANISERS))
def test_our_pipeline_matches_the_organisers_under_their_noise(processor):
    """Our baseline transport, compiled by our pipeline, gives the organisers' recorded fidelity and CX count."""
    _, cx, _, recorded = ORGANISERS[processor]
    nc = NoiseControl(processor, "organiser-cx2")
    compiled = compile_bases(basis_circuits(_baseline(nc), nc.ports), nc, seed=5)
    assert cost(compiled, nc.ports)["two_qubit_gates"] == cx
    for c in compiled.values():  # every basis compiles under the profile's gates
        assert set(c.compiled.count_ops()) <= {"h", "cx", "sdg", "measure", "barrier"}
    exact = fidelity_from_density(port_density_matrix(compiled["ZZ"].compiled, nc.noise_model, nc.ports))
    assert round(exact.value, 3) == recorded


def test_a_gate_the_profile_lacks_raises_naming_the_basis_and_gates():
    nc = NoiseControl("ibm2016", "organiser-cx2")
    qc = _baseline(nc)
    qc.t(nc.ports[0])  # T cannot be made from H, CX and S dagger
    # The bases compile in the order XX, YY, ZZ, so the first to fail is XX.
    message = r"the XX circuit cannot be compiled to the 'organiser-cx2' profile's gates \['cx', 'h', 'sdg'\]"
    with pytest.raises(ValueError, match=message):
        compile_bases(basis_circuits(qc, nc.ports), nc, seed=5)


@pytest.mark.parametrize(
    "noise, add, message",
    [
        ("burlington-2020", lambda qc: qc.reset(1), "uses reset, which the 'burlington-2020' profile"),
        ("organiser-cx2", lambda qc: qc.delay(1e-6, 1, unit="s"), "uses delay, which the 'organiser-cx2' profile"),
    ],
)
def test_an_operation_the_profile_lacks_raises_naming_it(noise, add, message):
    nc = NoiseControl("ibm2016", noise)
    qc = _baseline(nc)
    add(qc)
    with pytest.raises(ValueError, match=message):
        compile_bases(basis_circuits(qc, nc.ports), nc, seed=5)


def test_a_missing_gate_is_named_among_those_outside_the_profile():
    nc = NoiseControl("ibm2016", "organiser-cx2")
    qc = _baseline(nc)
    qc.t(nc.ports[0])
    with pytest.raises(ValueError, match=r"of its gates, \['swap', 't'\] are outside that set"):
        compile_bases(basis_circuits(qc, nc.ports), nc, seed=5)


def test_cost_without_a_zz_circuit_raises_naming_the_bases():
    nc = NoiseControl("ibm2016", "boston-2026")
    compiled = compile_bases(basis_circuits(_baseline(nc), nc.ports), nc, seed=5)
    with pytest.raises(ValueError, match=r"cost reads the compiled ZZ circuit; got the bases \['XX', 'YY'\]"):
        cost({b: c for b, c in compiled.items() if b != "ZZ"}, nc.ports)


# -- Basis circuits ---------------------------------------------------------------


def _baseline(nc: NoiseControl) -> QuantumCircuit:
    """The core baseline the run uses: the swap-chain transport on the processor's smallest shortest path."""
    return swap_chain(nc.processor_name)


def test_basis_circuits_rotate_and_measure_the_ports():
    nc = NoiseControl("ibm2016", "boston-2026")
    written = _baseline(nc)
    out = basis_circuits(written, nc.ports)
    a, b = nc.ports
    expected = {  # each added operation with the port it acts on, in order
        "ZZ": [("measure", a), ("measure", b)],
        "XX": [("h", a), ("h", b), ("measure", a), ("measure", b)],
        "YY": [("sdg", a), ("h", a), ("sdg", b), ("h", b), ("measure", a), ("measure", b)],
    }
    assert set(out) == set(expected)
    for basis, qc in out.items():
        assert [r.name for r in qc.cregs] == [PORT_REGISTER]
        added = qc.data[len(written.data):]
        assert [(i.operation.name, qc.find_bit(i.qubits[0]).index) for i in added] == expected[basis]
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
    assert c["qubits_used"] == sorted(smallest_shortest_path(nc.graph, *nc.ports)), "the path's qubits and no other"
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


def test_pair_on_ports_is_false_when_routing_moves_one_port():
    """A CX between the 2016 graph's ports makes the router move port 0 and leave port 4, under seed 1."""
    nc = NoiseControl("ibm2016", "boston-2026")
    a, b = nc.ports
    qc = QuantumCircuit(nc.num_qubits)
    qc.h(a)
    qc.cx(a, b)
    zz = compile_bases(basis_circuits(qc, nc.ports), nc, seed=1)["ZZ"]
    final = zz.routed.layout.final_layout
    assert [final[zz.routed.qubits[p]] != p for p in (a, b)] == [True, False], "the case needs exactly one port moved"
    assert pair_on_ports(zz.routed, nc.ports) is False


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


def test_staged_compile_equals_one_transpile_when_the_router_works_under_each_seed():
    """On a circuit the router must change, the staged compile follows the transpiler seed as one transpile does."""
    nc = NoiseControl("hyperbolic", "boston-2026")
    a, b = nc.ports
    qc = QuantumCircuit(nc.num_qubits)
    qc.h(a)
    qc.cx(a, b)
    qc.cx(1, 7)
    qc.cx(2, 10)
    circuits = basis_circuits(qc, nc.ports)
    compiled = {seed: compile_bases(circuits, nc, seed=seed) for seed in (1, 2)}
    assert compiled[1]["ZZ"].compiled != compiled[2]["ZZ"].compiled, "the two seeds must route differently"
    for seed, by_basis in compiled.items():
        assert by_basis["ZZ"].routed.count_ops().get("swap", 0) > 0
        pm = generate_preset_pass_manager(
            optimization_level=1, target=nc.target, initial_layout=list(range(nc.num_qubits)), seed_transpiler=seed
        )
        for basis, c in circuits.items():
            assert by_basis[basis].compiled == pm.run(c)


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


def test_schedule_is_as_late_as_possible_and_its_duration_is_in_seconds():
    """The second port idles until the CX reaches it: as late as possible, its wait comes first. The duration,
    2.868 us under boston-2026, is the longest path summed by hand from the profile's durations (code review CA3)."""
    nc = NoiseControl("ibm2016", "boston-2026")
    zz = compile_bases(basis_circuits(_baseline(nc), nc.ports), nc, seed=5)["ZZ"].compiled
    scheduled = schedule(zz, nc)
    on_second_port = [i.operation.name for i in scheduled.data if scheduled.find_bit(i.qubits[0]).index == nc.ports[1]]
    assert on_second_port[0] == "delay" and on_second_port[-1] == "measure"
    assert scheduled_duration(scheduled, nc) == pytest.approx(2.868e-6, rel=1e-12)


def _idle_population_of_1(nc: NoiseControl, busy_gates: int) -> tuple[float, float]:
    """Qubit 1's idle time in seconds while qubit 0 runs `busy_gates` sx gates, and its |1> population after."""
    from qiskit_aer import AerSimulator

    qc = QuantumCircuit(nc.num_qubits)
    qc.x(1)
    qc.barrier(0, 1)
    for _ in range(busy_gates):
        qc.sx(0)
    qc.barrier(0, 1)
    scheduled = schedule(qc, nc)
    idle = 0.0
    for instruction in scheduled.data:
        if instruction.operation.name == "delay" and scheduled.find_bit(instruction.qubits[0]).index == 1:
            op = instruction.operation
            idle += op.duration * nc.target.dt if op.unit == "dt" else op.duration
    scheduled.save_density_matrix(qubits=[1])
    rho = AerSimulator(method="density_matrix", noise_model=nc.noise_model).run(scheduled).result().data()
    return idle, rho["density_matrix"].data[1, 1].real


@pytest.mark.parametrize("noise", ["boston-2026", "burlington-2020"])
def test_scheduling_reads_the_targets_timings_and_an_idle_qubit_decays(noise):
    """Scheduling takes the delay, the time step and the durations from the Target, and the idle qubit decays by T1.

    boston-2026 has a time step, so delays come in dt; burlington-2020 has none, so they come in seconds.
    """
    nc = NoiseControl("ibm2016", noise)
    profile = load_noise(noise)
    assert nc.target.dt == profile["time_step"]
    assert all(p.duration == profile["measure"]["duration"] for p in nc.target["measure"].values())
    idle, after = _idle_population_of_1(nc, busy_gates=40)
    no_idle, before = _idle_population_of_1(nc, busy_gates=0)
    assert no_idle == 0.0
    assert idle == pytest.approx(40 * profile["gates"]["sx"]["duration"], rel=1e-12, abs=40 * (nc.target.dt or 0))
    assert after == pytest.approx(before * math.exp(-idle / profile["qubit"]["t1_relaxation_time"]), rel=1e-9)


def test_a_depolarising_profile_is_not_scheduled():
    nc = NoiseControl("contemporary", "organiser-cx2")
    zz = compile_bases(basis_circuits(_baseline(nc), nc.ports), nc, seed=5)["ZZ"].compiled
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
    """Aer picks density_matrix for this noisy run by itself, so the test forces another method."""
    nc = NoiseControl("ibm2016", "boston-2026")
    assert set(_run(nc, nc.noise_model, seed=3, shots=200).methods.values()) == {"density_matrix"}
    assert set(_run(nc, nc.noise_model, seed=3, shots=200, method="statevector").methods.values()) == {"statevector"}


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


def test_simulate_records_each_basis_circuits_own_seed():
    nc = NoiseControl("ibm2016", "boston-2026")
    sim = _run(nc, nc.noise_model, seed=1234, shots=100)
    assert sim.seeds["XX"] == 1234, "Aer seeds the job's first circuit with the job seed"
    assert len(set(sim.seeds.values())) == 3, "and each later circuit with a seed of its own"


def test_register_counts_reads_the_keys_aer_writes():
    """Aer writes one bit string per register, the last-added register first and its highest bit first."""
    from qiskit import ClassicalRegister
    from qiskit_aer import AerSimulator

    qc = QuantumCircuit(3)
    port, check = ClassicalRegister(2, "port"), ClassicalRegister(1, "check")
    qc.add_register(port)
    qc.add_register(check)
    qc.x(0)  # port[0] reads 1, port[1] reads 0
    qc.x(2)  # check reads 1
    qc.measure([0, 1], port)
    qc.measure(2, check[0])
    counts = AerSimulator().run(qc, shots=10, seed_simulator=1).result().get_counts()
    assert counts == {"1 01": 10}
    assert register_counts(counts, qc, "port") == {"01": 10}
    assert register_counts(counts, qc, "check") == {"1": 10}


def _expected_measured_fidelity(nc: NoiseControl, scheduled: dict) -> float:
    """F from each basis's exact port probabilities, with each port's two misread rates applied: what the
    measured F converges to. A misread turns an outcome's sign factor into 1 - 2 e0 for a 0 and -(1 - 2 e1) for a 1."""
    e0 = nc.profile["qubit"]["readout_error"]["reads_1_when_0"]
    e1 = nc.profile["qubit"]["readout_error"]["reads_0_when_1"]
    sign = (1 - 2 * e0, -(1 - 2 * e1))
    corr = {}
    for basis, qc in scheduled.items():
        probs = port_density_matrix(qc, nc.noise_model, nc.ports).probabilities()  # index = a + 2 b
        corr[basis] = sum(p * sign[i & 1] * sign[i >> 1] for i, p in enumerate(probs))
    return (1 + corr["XX"] - corr["YY"] + corr["ZZ"]) / 4


def test_noisy_measured_fidelity_agrees_with_the_exact_expectation():
    """The measured F under noise sits within four standard errors of the value the exact state predicts (D-20)."""
    nc = NoiseControl("ibm2016", "boston-2026")
    compiled = compile_bases(basis_circuits(_baseline(nc), nc.ports), nc, seed=5)
    scheduled = {basis: schedule(c.compiled, nc) for basis, c in compiled.items()}
    measured = fidelity_from_counts(simulate(scheduled, nc.noise_model, shots=100_000, seed=11).counts)
    expected = _expected_measured_fidelity(nc, scheduled)
    assert 0.9 < expected < 1
    assert abs(measured.value - expected) < 4 * measured.standard_error


def test_derive_seed_is_stable_distinct_and_32_bit():
    a = derive_seed(2026, "run-a", "noisy")
    assert a == derive_seed(2026, "run-a", "noisy")
    assert len({a, derive_seed(2026, "run-a", "ideal"), derive_seed(2026, "run-b", "noisy"), derive_seed(2027, "run-a", "noisy")}) == 4
    # The documented rule: the first four bytes, big-endian, of a SHA-256 of the base seed and labels as compact JSON.
    import hashlib

    digest = hashlib.sha256(b'[2026,"run-a","noisy"]').digest()
    assert a == int.from_bytes(digest[:4], "big")
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
