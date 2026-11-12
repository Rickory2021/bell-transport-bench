# tests/test_analysis.py
"""The analysis registry: the contract every analysis keeps, postselect, and parity with its Pauli frame.

Covers docs/DESIGN.md, section 7, as the analysis registry settles it: an
analysis returns port counts over all shots and over kept shots, frame applied
to both, and `read_shots` refuses an answer that does not add up. The known
answer is the team's exploration template's ghz_uncompute transport with its
bus_zz check, built here by hand: with its frame applied the ideal F is 1 and
every shot is kept.
"""

import pytest
from qiskit import ClassicalRegister, QuantumCircuit

from bellbench import analysis as analysis_module
from bellbench.analysis import PortCounts, check_analysis, read_shots
from bellbench.circuits import load_circuit, save_circuit, smallest_shortest_path
from bellbench.fidelity import BASES, fidelity_from_counts
from bellbench.noise import NoiseControl
from bellbench.pipeline import basis_circuits, compile_bases, simulate

POSTSELECT = {"name": "postselect"}
BUS_ZZ = {"name": "parity", "settings": {"checks": [["check_zz[0]"]], "frame_z": ["frame_z[0]"]}}


def _same(counts):
    return {basis: dict(counts) for basis in BASES}


# -- The contract -------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec, message",
    [
        ({"name": "correct"}, "no analysis named 'correct'; known: postselect, parity"),
        ({"settings": {}}, r"an analysis is \{name, settings\}"),
        ({"name": "postselect", "extra": 1}, r"an analysis is \{name, settings\}"),
        ({"name": "parity", "settings": ["check[0]"]}, "settings are a mapping"),
    ],
)
def test_a_malformed_analysis_is_refused(spec, message):
    with pytest.raises(ValueError, match=message):
        check_analysis(spec, [("check", 1), ("port", 2)])


def test_the_registers_must_end_with_the_port():
    with pytest.raises(ValueError, match="end with the one port register"):
        check_analysis(POSTSELECT, [("port", 2), ("check", 1)])


def test_an_answer_that_does_not_add_up_is_refused(monkeypatch):
    """The run scores what an analysis returns, so an analysis that drops or invents shots never reaches F."""

    def loses_a_shot(raw, registers, settings):
        return PortCounts(_same({"00": 9}), _same({"00": 9}))

    def keeps_too_many(raw, registers, settings):
        return PortCounts(_same({"00": 10}), _same({"00": 11}))

    for read, message in ((loses_a_shot, "counted 9 shots of 10"), (keeps_too_many, "kept more shots than were run")):
        monkeypatch.setitem(analysis_module.REGISTRY, "broken", analysis_module.Entry(lambda s, r: None, read))
        with pytest.raises(ValueError, match=message):
            read_shots({"name": "broken"}, _same({"00": 10}), [("port", 2)], 10)


# -- postselect ---------------------------------------------------------------------


def test_postselect_keeps_a_shot_when_every_other_register_reads_zero():
    # Keys as Qiskit writes them: the last register first, so "port flag check".
    raw = _same({"00 0 00": 50, "11 0 00": 30, "00 1 00": 10, "11 0 01": 10})
    ports = read_shots(POSTSELECT, raw, [("check", 2), ("flag", 1), ("port", 2)], 100)
    assert ports.all["ZZ"] == {"00": 60, "11": 40}
    assert ports.kept["ZZ"] == {"00": 50, "11": 30}


@pytest.mark.parametrize(
    "spec, registers, message",
    [
        ({"name": "postselect", "settings": {"checks": []}}, [("port", 2)], "takes no settings"),
        (POSTSELECT, [("check", 1), ("frame_z", 1), ("port", 2)], "frame_z carries a Pauli frame"),
    ],
)
def test_postselect_refuses_settings_and_frames(spec, registers, message):
    with pytest.raises(ValueError, match=message):
        check_analysis(spec, registers)


# -- parity -------------------------------------------------------------------------


def test_a_frame_flips_the_first_ports_outcome_in_the_bases_it_reaches():
    """An owed Z flips the first port in XX and YY, an owed X in ZZ and YY, and both (a Y) in XX and ZZ."""
    registers = [("frame_z", 1), ("frame_x", 1), ("port", 2)]
    settings = {"checks": [], "frame_z": ["frame_z[0]"], "frame_x": ["frame_x[0]"]}
    # "port frame_x frame_z"; port "01" is the first port reading 1 and the second 0.
    owed = {"z": "01 0 1", "x": "01 1 0", "y": "01 1 1"}
    flipped = {"z": {"XX", "YY"}, "x": {"ZZ", "YY"}, "y": {"XX", "ZZ"}}
    for pauli, key in owed.items():
        ports = read_shots({"name": "parity", "settings": settings}, _same({key: 1}), registers, 1)
        for basis in BASES:
            assert ports.all[basis] == ({"00": 1} if basis in flipped[pauli] else {"01": 1}), (pauli, basis)


def test_a_check_group_reads_its_bits_by_index_and_may_fold_in_a_frame_bit():
    registers = [("check_a", 2), ("frame_z", 1), ("port", 2)]
    settings = {"checks": [["check_a[1]"], ["check_a[0]", "frame_z[0]"]], "frame_z": ["frame_z[0]"]}
    # "port frame_z check_a"; check_a "01" is bit 0 reading 1 and bit 1 reading 0.
    raw = _same({"00 1 01": 7, "00 0 10": 3})
    ports = read_shots({"name": "parity", "settings": settings}, raw, registers, 10)
    assert sum(ports.kept["ZZ"].values()) == 7, "the first passes both groups, its frame bit folded in"


@pytest.mark.parametrize(
    "settings, message",
    [
        ({"checks": [["check_zz[0]"]], "frame_z": ["frame_z[0]"], "decoder": {}}, r"got \['decoder'\]"),
        ({"frame_z": ["frame_z[0]"]}, "list of non-empty lists"),
        ({"checks": [[]], "frame_z": ["frame_z[0]"]}, "list of non-empty lists"),
        ({"checks": [["check_zz[0]"]]}, r"reads no group or frame with frame_z\[0\]"),
        ({"checks": [["check_zz[0]"]], "frame_x": ["frame_z[0]"]}, r"frame_x lists frame_z\[0\]"),
        ({"checks": [["check_zz[0]"], ["port[0]"]], "frame_z": ["frame_z[0]"]}, r"port\[0\] is not a bit"),
        ({"checks": [["check_zz[1]"]], "frame_z": ["frame_z[0]"]}, r"check_zz\[1\] is past the end"),
        ({"checks": [["check_zz"]], "frame_z": ["frame_z[0]"]}, r"written register\[index\]"),
    ],
)
def test_parity_refuses_settings_that_do_not_fit(settings, message):
    with pytest.raises(ValueError, match=message):
        check_analysis({"name": "parity", "settings": settings}, [("check_zz", 1), ("frame_z", 1), ("port", 2)])


# -- The known answer: the template's bus_zz check ---------------------------------------


def _bus_zz(nc: NoiseControl, flip_check: bool = False) -> QuantumCircuit:
    """ghz_uncompute along the path, then bus_zz on its two interior qubits, as the exploration template builds them.

    The ports' ZZ parity collects on the second interior qubit, the check. The
    first interior qubit ends holding a copy of the first port's Z; read in X it
    releases that copy at the price of a Z owed on the first port, the frame.
    """
    a, i, j, b = smallest_shortest_path(nc.graph, *nc.ports)
    qc = QuantumCircuit(nc.num_qubits)
    check, frame = ClassicalRegister(1, "check_zz"), ClassicalRegister(1, "frame_z")
    qc.add_register(check)
    qc.add_register(frame)
    qc.h(a)
    for u, v in ((a, i), (i, j), (j, b), (i, j), (a, i)):  # a GHZ state out to b, then the interior uncomputed
        qc.cx(u, v)
    for u, v in ((a, i), (i, j), (b, j)):  # the ports' ZZ parity onto j, a copy of a's Z left on i
        qc.cx(u, v)
    if flip_check:
        qc.x(j)
    qc.measure(j, check[0])
    qc.h(i)
    qc.measure(i, frame[0])
    return qc


def _ideal(nc: NoiseControl, qc: QuantumCircuit, spec, shots: int = 2000) -> PortCounts:
    compiled = compile_bases(basis_circuits(qc, nc.ports), nc, seed=5)
    sim = simulate({b: c.compiled for b, c in compiled.items()}, None, shots=shots, seed=3)
    layout = [(r.name, r.size) for r in compiled["ZZ"].compiled.cregs]
    return read_shots(spec, sim.raw, layout, shots)


def test_bus_zz_with_its_frame_keeps_every_ideal_shot_at_fidelity_one():
    nc = NoiseControl("hyperbolic", "boston-2026")
    assert smallest_shortest_path(nc.graph, *nc.ports) == [0, 1, 9, 12]
    ports = _ideal(nc, _bus_zz(nc), BUS_ZZ)
    assert all(sum(ports.kept[b].values()) == 2000 for b in BASES)
    assert fidelity_from_counts(ports.kept).value == 1.0


def test_bus_zz_read_as_plain_checks_throws_away_half_the_ideal_shots():
    """Reading the frame bit as one more check, as postselect would, keeps only the shots where it reads 0."""
    nc = NoiseControl("hyperbolic", "boston-2026")
    as_checks = {"name": "parity", "settings": {"checks": [["check_zz[0]"], ["frame_z[0]"]]}}
    ports = _ideal(nc, _bus_zz(nc), as_checks)
    kept = sum(sum(ports.kept[b].values()) for b in BASES) / (3 * 2000)
    assert 0.4 < kept < 0.6


def test_bus_zz_discards_every_shot_whose_check_flips():
    nc = NoiseControl("hyperbolic", "boston-2026")
    ports = _ideal(nc, _bus_zz(nc, flip_check=True), BUS_ZZ, shots=200)
    assert all(ports.kept[b] == {} for b in BASES)
    assert all(sum(ports.all[b].values()) == 200 for b in BASES)


def test_a_circuit_file_carries_its_analysis(config_copy):
    nc = NoiseControl("hyperbolic", "boston-2026")
    save_circuit("bus-zz", "GHZ uncompute with bus_zz", "hyperbolic", _bus_zz(nc), "A test circuit.", analysis=BUS_ZZ)
    assert load_circuit("bus-zz").analysis == BUS_ZZ
    with pytest.raises(ValueError, match="frame_z carries a Pauli frame"):
        save_circuit("bus-zz-plain", "Plain", "hyperbolic", _bus_zz(nc), "A test circuit.")
