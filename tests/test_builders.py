# tests/test_builders.py
"""The builders: each ported transport, and each check after it, gives the Bell pair on the ports exactly.

Covers docs/DESIGN.md, section 7, as the template port settles it, with a
check placed on the pair's path or on a spare path. Each case is built on the
core graphs it can run on, compiled and simulated without noise through the
pipeline, read with the analysis the builders wrote, and must give F = 1 with
every shot kept and the pair on the ports.
"""

import pytest
from qiskit.circuit import CircuitInstruction, library

from bellbench import builders
from bellbench.analysis import read_shots
from bellbench.circuits import CORE_PROCESSORS, load_circuit
from bellbench.fidelity import BASES, fidelity_from_counts
from bellbench.noise import NoiseControl
from bellbench.pipeline import basis_circuits, compile_bases, cost, mid_circuit_measurements, simulate

TRANSPORTS = {
    "swap_forward": builders.swap_forward,
    "move_chain": builders.move_chain,
    "swap_middle_out": builders.swap_middle_out,
    "move_middle_out": builders.move_middle_out,
    "ghz_uncompute": builders.ghz_uncompute,
    "ghz_measure": builders.ghz_measure,
}
SHOTS = 400


def ideal(state: builders.BuildState) -> dict:
    """F, the fraction kept and the cost of a built circuit, simulated without noise, read by its own analysis."""
    nc = NoiseControl(state.processor, "boston-2026")
    compiled = compile_bases(basis_circuits(state.circuit, nc.ports), nc, seed=5)
    sim = simulate({b: c.compiled for b, c in compiled.items()}, None, shots=SHOTS, seed=3)
    layout = [(r.name, r.size) for r in compiled["ZZ"].compiled.cregs]
    ports = read_shots(state.analysis(), sim.raw, layout, SHOTS)
    kept = sum(sum(ports.kept[b].values()) for b in BASES) / (3 * SHOTS)
    return {"F": fidelity_from_counts(ports.kept).value, "kept": kept, "cost": cost(compiled, nc.ports)}


@pytest.mark.parametrize("processor", CORE_PROCESSORS)
@pytest.mark.parametrize("transport", sorted(TRANSPORTS))
def test_every_transport_puts_the_pair_on_the_ports(processor, transport):
    state = TRANSPORTS[transport](builders.start(processor))
    result = ideal(state)
    assert result["F"] == 1.0 and result["kept"] == 1.0
    assert result["cost"]["pair_on_ports"] is True and result["cost"]["router_swaps"] == 0
    expected = set() if transport == "ghz_measure" else set(state.interior)
    assert state.vacant & set(state.path) == expected


@pytest.mark.parametrize("processor", CORE_PROCESSORS)
@pytest.mark.parametrize("swapped, moved", [("swap_forward", "move_chain"), ("swap_middle_out", "move_middle_out")])
def test_a_move_saves_one_two_qubit_gate_per_hop(processor, swapped, moved):
    """A SWAP compiles to three two-qubit gates, a move onto |0> to two: one saved for every SWAP replaced."""
    swap_state, move_state = (TRANSPORTS[t](builders.start(processor)) for t in (swapped, moved))
    swaps = swap_state.circuit.count_ops().get("swap", 0)
    saved = ideal(swap_state)["cost"]["two_qubit_gates"] - ideal(move_state)["cost"]["two_qubit_gates"]
    assert swaps > 0 and saved == swaps


def test_ghz_measure_records_its_frame():
    state = builders.ghz_measure(builders.start("hyperbolic"))
    assert state.frame_z == ["frame_z_ghz[0]", "frame_z_ghz[1]"]
    assert state.analysis() == {"name": "parity", "settings": {"checks": [], "frame_z": state.frame_z}}


def test_ghz_measure_with_reset_leaves_the_interior_free():
    state = builders.ghz_measure(builders.start("hyperbolic"), reset=True)
    assert state.vacant & set(state.path) == set(state.interior)
    assert ideal(state)["F"] == 1.0


def test_a_transport_with_no_measurement_is_read_by_postselect():
    assert builders.ghz_uncompute(builders.start("ibm2016")).analysis() == {"name": "postselect"}


def test_a_path_that_does_not_run_port_to_port_is_refused():
    with pytest.raises(ValueError, match="must run from the first port"):
        builders.start("ibm2016", path=[0, 3])


def test_a_second_transport_is_refused():
    state = builders.swap_forward(builders.start("ibm2016"))
    with pytest.raises(builders.BuildError, match="a transport starts a circuit"):
        builders.ghz_uncompute(state)


def test_a_built_circuit_saves_with_its_analysis_and_how_it_was_built(config_copy):
    state = builders.ghz_measure(builders.start("contemporary"))
    state.save("ghz-measure-contemporary", "GHZ measure, contemporary")
    loaded = load_circuit("ghz-measure-contemporary")
    assert loaded.analysis == state.analysis()
    assert loaded.circuit == state.circuit
    assert "ghz_measure(reset=False)" in loaded.notes and str(state.path) in loaded.notes


# -- Checks ---------------------------------------------------------------------------

SEQUENCES = {
    "vacancy": [builders.vacancy],
    "bus_zz": [builders.bus_zz],
    "bus_xx": [builders.bus_xx],
    "bus_zz, then bus_xx": [lambda s: builders.bus_zz(s, reset=True), builders.bus_xx],
    "vacancy, then bus_zz": [builders.vacancy, builders.bus_zz],
}


def protected(processor: str, transport: str, checks: list) -> builders.BuildState:
    state = builders.start(processor)
    state = builders.ghz_measure(state, reset=True) if transport == "ghz_measure" else TRANSPORTS[transport](state)
    for check in checks:
        state = check(state)
    return state


@pytest.mark.parametrize("processor", CORE_PROCESSORS)
@pytest.mark.parametrize("transport", sorted(TRANSPORTS))
@pytest.mark.parametrize("sequence", sorted(SEQUENCES))
def test_every_check_sequence_after_every_transport_keeps_the_pair_exact(processor, transport, sequence):
    result = ideal(protected(processor, transport, SEQUENCES[sequence]))
    assert result["F"] == 1.0 and result["kept"] == 1.0 and result["cost"]["pair_on_ports"] is True


def kept_fraction(state: builders.BuildState) -> float:
    nc = NoiseControl(state.processor, "boston-2026")
    compiled = compile_bases(basis_circuits(state.circuit, nc.ports), nc, seed=5)
    sim = simulate({b: c.compiled for b, c in compiled.items()}, None, shots=SHOTS, seed=3)
    layout = [(r.name, r.size) for r in compiled["ZZ"].compiled.cregs]
    ports = read_shots(state.analysis(), sim.raw, layout, SHOTS)
    return sum(sum(ports.kept[b].values()) for b in BASES) / (3 * SHOTS)


@pytest.mark.parametrize(
    "error, where, check, kept",
    [
        ("x", "port", builders.bus_zz, 0.0),  # a bit flip on one port makes ZZ = -1
        ("z", "port", builders.bus_zz, 1.0),  # blind: a phase flip leaves ZZ alone
        ("z", "port", builders.bus_xx, 0.0),  # a phase flip on one port makes XX = -1
        ("x", "port", builders.bus_xx, 1.0),  # blind: a bit flip leaves XX alone
        ("x", "interior", builders.vacancy, 0.0),  # an excitation left on the path
        ("x", "interior", builders.bus_zz, 0.0),  # caught twice: the ZZ parity reads 1, and so does the vacancy read
        ("z", "interior", builders.vacancy, 1.0),  # blind: a phase on an empty qubit is no excitation
        # bus_xx's own parity cannot see an excitation on its last bus qubit, which turns the pair into Psi+ with
        # XX still +1: only the vacancy read before the bus is reused catches it.
        ("x", "last interior", builders.bus_xx, 0.0),
    ],
)
def test_each_check_catches_what_it_states_and_misses_its_blind_spots(error, where, check, kept):
    """One deliberate Pauli placed after the transport, on the hyperbolic graph's path 0-1-9-12."""
    state = builders.ghz_uncompute(builders.start("hyperbolic"))
    qubit = {"port": state.ports[0], "interior": state.interior[0], "last interior": state.interior[-1]}[where]
    getattr(state.circuit, error)(qubit)
    assert kept_fraction(check(state)) == kept


def test_bus_zz_catches_with_its_vacancy_read_what_its_parity_misses():
    """A flipped port and an excitation on the first bus qubit leave the ZZ parity even, so only the vacancy read
    before the bus is reused discards the shot, on the hyperbolic graph's path 0-1-9-12."""
    state = builders.ghz_uncompute(builders.start("hyperbolic"))
    state.circuit.x(state.ports[0])
    state.circuit.x(state.interior[0])
    assert kept_fraction(builders.bus_zz(state)) == 0.0


@pytest.mark.parametrize(
    "check, registers",
    [
        (builders.bus_zz, ["check_vac_zz", "check_zz", "frame_z_zz"]),
        (builders.bus_xx, ["check_vac_xx", "check_xx"]),
    ],
)
def test_a_bus_check_reads_its_qubits_as_vacant_before_reusing_them(check, registers):
    state = check(builders.ghz_uncompute(builders.start("hyperbolic")))
    assert [r.name for r in state.circuit.cregs] == registers
    assert state.checks[:2] == [[f"{registers[0]}[0]"], [f"{registers[0]}[1]"]]


def test_a_check_before_a_transport_is_refused():
    with pytest.raises(builders.BuildError, match="follows a transport"):
        builders.vacancy(builders.start("ibm2016"))


@pytest.mark.parametrize(
    "build",
    [
        lambda: builders.vacancy(builders.ghz_measure(builders.start("hyperbolic"))),
        lambda: builders.bus_xx(builders.bus_zz(builders.ghz_uncompute(builders.start("hyperbolic")))),
    ],
)
def test_a_check_on_measured_qubits_is_refused_until_they_are_reset(build):
    with pytest.raises(builders.BuildError, match="are not in |0>; give the step that measured them reset=True"):
        build()


def test_a_repeated_check_gets_a_register_of_its_own():
    state = builders.vacancy(builders.vacancy(builders.ghz_uncompute(builders.start("ibm2016"))))
    assert [r.name for r in state.circuit.cregs] == ["check_vac", "check_vac_2"]
    assert ideal(state)["F"] == 1.0


def test_bus_xx_after_ghz_measure_folds_in_the_frame():
    state = builders.bus_xx(builders.ghz_measure(builders.start("hyperbolic"), reset=True))
    assert state.checks[-1] == ["check_xx[0]", "check_xx[1]", "frame_z_ghz[0]", "frame_z_ghz[1]"]
    assert ideal(state)["F"] == 1.0


# -- Checks on a spare path ---------------------------------------------------------

SPARE_SEQUENCES = {
    "bus_zz on a spare": ["contemporary", "hyperbolic"],
    "bus_xx on a spare": ["contemporary", "hyperbolic"],
    "bus_zz on the path, then bus_xx on a spare": ["contemporary", "hyperbolic"],
    "bus_zz on a spare, then bus_xx on the next": ["hyperbolic"],
}
SPARE_STEPS = {
    "bus_zz on a spare": [lambda s: builders.bus_zz(s, on="spare")],
    "bus_xx on a spare": [lambda s: builders.bus_xx(s, on="spare")],
    "bus_zz on the path, then bus_xx on a spare": [builders.bus_zz, lambda s: builders.bus_xx(s, on="spare")],
    "bus_zz on a spare, then bus_xx on the next": [
        lambda s: builders.bus_zz(s, on="spare"),
        lambda s: builders.bus_xx(s, on="spare"),
    ],
}


@pytest.mark.parametrize(
    "processor, sequence", [(p, seq) for seq, processors in SPARE_SEQUENCES.items() for p in processors]
)
@pytest.mark.parametrize("transport", sorted(TRANSPORTS))
def test_every_transport_with_checks_on_a_spare_keeps_the_pair_exact(processor, sequence, transport):
    result = ideal(protected(processor, transport, SPARE_STEPS[sequence]))
    assert result["F"] == 1.0 and result["kept"] == 1.0 and result["cost"]["pair_on_ports"] is True


@pytest.mark.parametrize("processor, checks", [("contemporary", 1), ("hyperbolic", 2)])
def test_checks_on_spares_read_only_at_the_end(processor, checks):
    """A spare qubit has never been touched, so it is used without a vacancy read: no mid-circuit read, no reset."""
    state = builders.move_chain(builders.start(processor))
    for check in (builders.bus_zz, builders.bus_xx)[:checks]:
        state = check(state, on="spare")
    for circuit in basis_circuits(state.circuit, state.ports).values():
        assert mid_circuit_measurements(circuit) == [] and "reset" not in circuit.count_ops()
    assert not any(r.name.startswith("check_vac") for r in state.circuit.cregs)


def test_spares_are_taken_in_turn_recorded_and_then_refused():
    state = builders.bus_zz(builders.move_chain(builders.start("hyperbolic")), on="spare")
    state = builders.bus_xx(state, on="spare")
    assert "bus_zz(on=[0, 3, 11, 12], reset=False); then bus_xx(on=[0, 2, 6, 10, 12], reset=False)" in state.notes()
    with pytest.raises(builders.BuildError, match="'hyperbolic' has no spare path left"):
        builders.bus_zz(state, on="spare")


def test_a_graph_with_no_spare_path_refuses_a_spare_check():
    with pytest.raises(builders.BuildError, match="'ibm2016' has no spare path left"):
        builders.bus_xx(builders.move_chain(builders.start("ibm2016")), on="spare")


def test_a_check_on_a_named_spare_path():
    state = builders.bus_xx(builders.move_chain(builders.start("hyperbolic")), on=[0, 2, 6, 10, 12])
    assert state.checks[-1] == ["check_xx[0]", "check_xx[1]", "check_xx[2]"]
    assert ideal(state)["F"] == 1.0


@pytest.mark.parametrize(
    "on, reset, error, message",
    [
        ([0, 1, 9, 12], False, builders.BuildError, r"qubits \[1, 9\] of path \[0, 1, 9, 12\] are already in use"),
        ([0, 1, 12], False, ValueError, "not a coupler"),
        ("sideways", False, builders.BuildError, 'on is "path", "spare" or a list of qubits'),
        ("spare", True, builders.BuildError, "a spare is used once"),
    ],
)
def test_a_placement_that_cannot_hold_a_check_is_refused(on, reset, error, message):
    state = builders.move_chain(builders.start("hyperbolic"))
    with pytest.raises(error, match=message):
        builders.bus_xx(state, reset=reset, on=on)


def test_a_named_path_with_no_interior_is_refused(monkeypatch):
    """Only ports that are neighbours give such a path, which no core graph has, so the path check is stood in for."""
    state = builders.move_chain(builders.start("hyperbolic"))
    monkeypatch.setattr(builders, "port_path", lambda processor, path: (state.graph, list(path)))
    with pytest.raises(builders.BuildError, match="has no interior qubit to use"):
        builders.bus_zz(state, on=[0, 12])


@pytest.mark.parametrize(
    "error, where, check, kept",
    [
        ("x", "port", builders.bus_zz, 0.0),
        ("z", "port", builders.bus_xx, 0.0),
        # Blind: with no vacancy read, a check on a spare trusts that an untouched qubit is in |0>. An excitation
        # already on its last qubit, which no noise model here puts there, turns the pair into Psi+ with XX still +1.
        ("x", "last spare", builders.bus_xx, 1.0),
    ],
)
def test_a_check_on_a_spare_catches_what_it_states_and_trusts_its_spare(error, where, check, kept):
    """One deliberate Pauli placed after the transport and before the check, on the hyperbolic graph with its
    spare 0-3-11-12; it goes in after the check is built, since a qubit it touched would no longer be a spare."""
    state = builders.ghz_uncompute(builders.start("hyperbolic"))
    before = len(state.circuit.data)
    state = check(state, on="spare")
    qubit = {"port": state.ports[0], "last spare": 11}[where]
    gate = getattr(library, f"{error.upper()}Gate")()
    state.circuit.data.insert(before, CircuitInstruction(gate, [state.circuit.qubits[qubit]]))
    assert "on=[0, 3, 11, 12]" in state.notes()
    assert kept_fraction(state) == kept
    if kept:
        assert ideal(state)["F"] == 0.0, "every shot kept, and every one the wrong pair"
