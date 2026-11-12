# tests/test_builders.py
"""The builders: each ported transport, and each check after it, gives the Bell pair on the ports exactly.

Covers docs/DESIGN.md, section 7, as the template port settles it. Each case is
built on the three core graphs, compiled and simulated without noise through
the pipeline, read with the analysis the builders wrote, and must give F = 1
with every shot kept and the pair on the ports.
"""

import pytest

from bellbench import builders
from bellbench.analysis import read_shots
from bellbench.circuits import CORE_PROCESSORS, load_circuit
from bellbench.fidelity import BASES, fidelity_from_counts
from bellbench.noise import NoiseControl
from bellbench.pipeline import basis_circuits, compile_bases, cost, simulate

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
