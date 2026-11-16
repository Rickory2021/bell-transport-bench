# src/bellbench/builders.py
"""Builders: transports and checks that write a circuit file, with the analysis that reads its shots.

A transport makes the Bell pair and brings it to the ports; checks then add
measurements that detect errors along the way (docs/DESIGN.md, section 7). They
share one build state, `BuildState`, which starts from a processor file and a
checked path between its ports, and holds the circuit, the qubits known to be in
|0>, and each measured bit with its role and its analysis settings. `save`
writes the circuit file, with the analysis the builders have written, and a run
reads only that file: the gates are what runs, and the notes record which
builders made them and with which arguments.

The transports are the team's exploration template's, plus two that move a
half onto a qubit known to be in |0> with two CX gates where a SWAP takes three:

- `swap_forward`: the pair is made on the first port and its neighbour, and that
  half is swapped along the path to the second port (the template's swap_chain;
  `circuits.swap_chain` is the organisers' out-and-back baseline).
- `move_chain`: as swap_forward, each SWAP replaced by a move.
- `swap_middle_out`: the pair is made in the middle of the path and both halves
  are swapped outward to the ports.
- `move_middle_out`: as swap_middle_out, each SWAP replaced by a move.
- `ghz_uncompute`: a GHZ state along the path, then the interior uncomputed.
- `ghz_measure`: a GHZ state from the middle, then the interior read in X; each
  1 owes a Z on the first port, which the analysis applies as a Pauli frame.

Every transport leaves the interior of the path in |0>, except ghz_measure,
which leaves it measured unless it resets it.

The checks follow the transport, in the order called:

- `vacancy` reads each interior qubit of the path, which must be in |0>.
- `bus_zz` collects the ports' ZZ parity on a bus, read as one check.
- `bus_xx` turns a bus into a GHZ ancilla and reads the ports' XX parity.

A bus is the interior of a port-to-port path, placed by the check's `on`
argument (docs/DESIGN.md, section 7, check placement): `"path"`, the default,
is the interior of the pair's own path; `"spare"` is the interior of a spare
path, one that shares no qubit with the pair's path or with a spare an earlier
check used (`paths.spare_path`); a list of qubits names a port-to-port path
whose interior no step has touched.

A check reuses a qubit only after reading it as a vacancy check, so an
excitation left there is caught rather than carried into the check; a kept shot
then has the qubit in |0> again. A spare qubit has never been touched, so it
needs no such read: a check on a spare path reads its bus only at the end, with
no mid-circuit measurement and no reset. It trusts the spare to be in |0>,
which every noise model here keeps, since none excites an idle qubit (leftover
excitation is not modelled, docs/DESIGN.md, section 4). A check on the path
that leaves its qubits measured takes `reset` to return them to |0> for a later
check, and a run then needs the reset channel; reading a qubit and acting on it
again needs the mid-circuit measurement channel. Each check folds into its
parity the frame bits that flip it, as a check measured after a frame bit must,
and states what it cannot see.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import networkx as nx
from qiskit import ClassicalRegister, QuantumCircuit

from bellbench.circuits import REGISTER_NAME, save_circuit
from bellbench.paths import port_path, spare_path


class BuildError(ValueError):
    """A builder that cannot follow what the circuit holds so far, such as a check needing qubits not in |0>."""


@dataclass
class BuildState:
    """A circuit being built, with what the builders know about it and the analysis that will read it."""

    processor: str
    path: list[int]
    circuit: QuantumCircuit
    graph: nx.Graph  # the processor's coupling graph, which places a check on a spare path
    vacant: set[int] = field(default_factory=set)  # qubits known to be in |0>
    checks: list[list[str]] = field(default_factory=list)  # each a group of bits that must have even parity
    frame_z: list[str] = field(default_factory=list)  # bits whose parity owes a Z on the first port
    frame_x: list[str] = field(default_factory=list)  # bits whose parity owes an X on the first port
    steps: list[str] = field(default_factory=list)  # each builder and its arguments, for the notes

    @property
    def ports(self) -> tuple[int, int]:
        return self.path[0], self.path[-1]

    @property
    def interior(self) -> list[int]:
        return self.path[1:-1]

    @property
    def touched(self) -> set[int]:
        """The qubits any step has acted on so far."""
        return {self.circuit.find_bit(q).index for instruction in self.circuit.data for q in instruction.qubits}

    def register(self, name: str, size: int) -> ClassicalRegister:
        """A new classical register named `name`, or `name_2`, `name_3` when taken; the name starts with its role."""
        taken = {r.name for r in self.circuit.cregs}
        unique, n = name, 1
        while unique in taken:
            n += 1
            unique = f"{name}_{n}"
        if not REGISTER_NAME.fullmatch(unique):
            raise BuildError(f"register name {unique!r} does not start with a role")
        register = ClassicalRegister(size, unique)
        self.circuit.add_register(register)
        return register

    def measure(self, qubit: int, register: ClassicalRegister, index: int, basis: str = "Z") -> str:
        """Read `qubit` in Z or X into `register[index]`, and return that bit as the analysis names it."""
        if basis == "X":
            self.circuit.h(qubit)
        elif basis != "Z":
            raise BuildError(f"a builder reads a qubit in Z or X; got {basis!r}")
        self.circuit.measure(qubit, register[index])
        self.vacant.discard(qubit)
        return f"{register.name}[{index}]"

    def analysis(self) -> dict:
        """The analysis the builders wrote: postselect with no measured bits, parity with its groups and frames."""
        if not self.circuit.cregs:
            return {"name": "postselect"}
        settings = {"checks": [list(g) for g in self.checks]}
        for frame in ("frame_z", "frame_x"):
            if getattr(self, frame):
                settings[frame] = list(getattr(self, frame))
        return {"name": "parity", "settings": settings}

    def notes(self) -> str:
        return (
            f"Built by src/bellbench/builders.py on {self.processor} along the path {self.path}: "
            + "; then ".join(self.steps)
            + "."
        )

    def save(self, name: str, label: str, overwrite: bool = False, trial: bool = False) -> Path:
        """Write the circuit file `name`, with the analysis the builders wrote and the notes saying how.

        With `trial=True` it is a trial, in workspace/circuits/ (circuits.save_circuit).
        """
        return save_circuit(
            name, label, self.processor, self.circuit, self.notes(), analysis=self.analysis(), overwrite=overwrite,
            trial=trial,
        )


def start(processor: str, path: Sequence[int] | None = None) -> BuildState:
    """A build state on `processor`, along a checked path between its ports (by default the smallest shortest)."""
    graph, path = port_path(processor, path)
    return BuildState(processor, path, QuantumCircuit(graph.number_of_nodes()), graph, vacant=set(graph.nodes))


# -- Transports ----------------------------------------------------------------------


def swap_forward(state: BuildState) -> BuildState:
    """The pair on the first port and its neighbour, then that half swapped along the path to the second port."""
    p, qc = state.path, state.circuit
    _make_pair(state, p[0], p[1])
    for u, v in zip(p[1:-1], p[2:]):
        qc.swap(u, v)
    return _arrived(state, "swap_forward")


def move_chain(state: BuildState) -> BuildState:
    """As swap_forward, with each SWAP a move: two CX gates carry the half onto the next qubit, which is in |0>."""
    p = state.path
    _make_pair(state, p[0], p[1])
    for u, v in zip(p[1:-1], p[2:]):
        _move(state, u, v)
    return _arrived(state, "move_chain")


def swap_middle_out(state: BuildState) -> BuildState:
    """The pair in the middle of the path, then both halves swapped outward to the ports."""
    p, qc = state.path, state.circuit
    i = (len(p) - 2) // 2
    _make_pair(state, p[i], p[i + 1])
    for k in range(i, 0, -1):
        qc.swap(p[k], p[k - 1])
    for k in range(i + 1, len(p) - 1):
        qc.swap(p[k], p[k + 1])
    return _arrived(state, "swap_middle_out")


def move_middle_out(state: BuildState) -> BuildState:
    """As swap_middle_out, with each SWAP a move onto a qubit in |0>."""
    p = state.path
    i = (len(p) - 2) // 2
    _make_pair(state, p[i], p[i + 1])
    for k in range(i, 0, -1):
        _move(state, p[k], p[k - 1])
    for k in range(i + 1, len(p) - 1):
        _move(state, p[k], p[k + 1])
    return _arrived(state, "move_middle_out")


def ghz_uncompute(state: BuildState) -> BuildState:
    """A GHZ state along the whole path, then the interior uncomputed back to |0>, leaving the pair on the ports."""
    p, qc = state.path, state.circuit
    _fresh(state, p)
    qc.h(p[0])
    for u, v in zip(p, p[1:]):
        qc.cx(u, v)
    for i in range(len(p) - 2, 0, -1):
        qc.cx(p[i - 1], p[i])
    return _arrived(state, "ghz_uncompute")


def ghz_measure(state: BuildState, reset: bool = False) -> BuildState:
    """A GHZ state grown from the middle of the path, then each interior qubit read in X.

    Reading an interior qubit in X releases it from the GHZ state; an outcome of
    1 turns the pair into Phi-, a Z owed on the first port, which the analysis
    applies as a Pauli frame instead of a gate. With `reset`, each read qubit is
    reset to |0>, so a check can reuse it; a run then needs the reset channel.
    """
    p, qc = state.path, state.circuit
    _fresh(state, p)
    m = (len(p) - 1) // 2
    qc.h(p[m])
    for i in range(m, len(p) - 1):
        qc.cx(p[i], p[i + 1])
    for i in range(m, 0, -1):
        qc.cx(p[i], p[i - 1])
    if state.interior:
        register = state.register("frame_z_ghz", len(state.interior))
        state.frame_z += [state.measure(q, register, k, "X") for k, q in enumerate(state.interior)]
        if reset:
            for q in state.interior:
                qc.reset(q)
            state.vacant |= set(state.interior)
    state.vacant -= set(state.ports)
    state.steps.append(f"ghz_measure(reset={reset})")
    return state


# -- Checks ----------------------------------------------------------------------------


def vacancy(state: BuildState) -> BuildState:
    """Read each interior qubit, which the transport left in |0>; a shot is kept only when all read 0.

    Catches an excitation left on the path, such as a SWAP or a move gone wrong
    on a qubit that should be empty. Blind to an error on the ports themselves,
    to any phase error, and to a flip a later gate undoes.
    """
    _read_vacant(state, _bus(state, "vacancy", "path", reset=False)[0], "check_vac")
    state.steps.append("vacancy()")
    return state


def bus_zz(state: BuildState, reset: bool = False, on: str | Sequence[int] = "path") -> BuildState:
    """The ports' ZZ parity collected on a bus and read as one check; the other bus qubits read in X.

    Catches a bit flip (X or Y) on one port, which makes ZZ = -1. Blind to a
    phase flip (Z), to the same flip on both ports, and to an error on the bus
    during the check, which it carries no flag for. The bus qubits other than
    the last end holding copies of the first port's Z value; reading them in X
    releases them and owes a Z on the first port, recorded as a frame. `on`
    places the bus (see the module docstring); `reset` applies only on the path.
    """
    bus, placed = _bus(state, "bus_zz", on, reset)
    _read_vacant(state, [q for q in bus if q in state.touched], "check_vac_zz")
    (a, b), qc = state.ports, state.circuit
    qc.cx(a, bus[0])
    for u, v in zip(bus, bus[1:]):
        qc.cx(u, v)
    qc.cx(b, bus[-1])
    zz = state.register("check_zz", 1)
    state.checks.append([state.measure(bus[-1], zz, 0), *state.frame_x])  # an owed X on the first port flips ZZ
    if len(bus) > 1:
        frame = state.register("frame_z_zz", len(bus) - 1)
        state.frame_z += [state.measure(q, frame, k, "X") for k, q in enumerate(bus[:-1])]
    _release(state, bus, reset)
    state.steps.append(f"bus_zz({placed}reset={reset})")
    return state


def bus_xx(state: BuildState, reset: bool = False, on: str | Sequence[int] = "path") -> BuildState:
    """The ports' XX parity, read off a bus prepared as a GHZ ancilla, as one check over every bus bit.

    Catches a phase flip (Z or Y) on one port, which makes XX = -1. Blind to a
    bit flip (X), to the same flip on both ports, and to an error on the bus
    during the check, which it carries no flag for. `on` places the bus (see
    the module docstring); `reset` applies only on the path.
    """
    bus, placed = _bus(state, "bus_xx", on, reset)
    _read_vacant(state, [q for q in bus if q in state.touched], "check_vac_xx")
    (a, b), qc = state.ports, state.circuit
    qc.h(bus[0])
    for u, v in zip(bus, bus[1:]):
        qc.cx(u, v)
    qc.cx(bus[0], a)
    qc.cx(bus[-1], b)
    xx = state.register("check_xx", len(bus))
    bits = [state.measure(q, xx, k, "X") for k, q in enumerate(bus)]
    state.checks.append([*bits, *state.frame_z])  # an owed Z on the first port flips XX
    _release(state, bus, reset)
    state.steps.append(f"bus_xx({placed}reset={reset})")
    return state


# -- Helpers -------------------------------------------------------------------------


def _fresh(state: BuildState, qubits) -> None:
    """A transport starts from qubits in |0>; refuse one that would run over a circuit already built."""
    busy = [q for q in qubits if q not in state.vacant]
    if busy or state.steps:
        raise BuildError(f"a transport starts a circuit; qubits {busy or qubits} are already in use")


def _make_pair(state: BuildState, a: int, b: int) -> None:
    _fresh(state, state.path)
    state.circuit.h(a)
    state.circuit.cx(a, b)


def _bus(state: BuildState, check: str, on: str | Sequence[int], reset: bool) -> tuple[list[int], str]:
    """The qubits a check works on, placed by `on`, all in |0>, and how the notes record the placement.

    On the path, the bus is its interior once a transport has run and left it
    in |0>. Elsewhere it is the interior of a port-to-port path that no step has
    touched, chosen as the next spare or named as a list; a spare is used once,
    so `reset`, which returns a bus for a later check, applies only on the path.
    """
    if not state.steps:
        raise BuildError(f"{check} follows a transport; build one first")
    if on == "path":
        if not state.interior:
            raise BuildError(f"{check}: the ports are neighbours, so the path has no interior qubit to use")
        bus, placed = list(state.interior), ""
    else:
        if reset:
            raise BuildError(f"{check}: reset returns a bus for a later check on the path; a spare is used once")
        if on == "spare":
            try:
                path = spare_path(state.graph, state.path, sorted(state.touched))
            except ValueError as error:
                raise BuildError(f"{check}: {state.processor!r} has no spare path left: {error}") from None
        elif isinstance(on, str):
            raise BuildError(f'{check}: on is "path", "spare" or a list of qubits; got {on!r}')
        else:
            path = port_path(state.processor, on)[1]
            if len(path) < 3:
                raise BuildError(f"{check}: path {path} has no interior qubit to use")
        bus = path[1:-1]
        used = sorted(set(bus) & state.touched)
        if used:
            raise BuildError(f"{check}: qubits {used} of path {path} are already in use; a spare is untouched")
        placed = f"on={path}, "
    busy = [q for q in bus if q not in state.vacant]
    if busy:
        raise BuildError(f"{check}: interior qubits {busy} are not in |0>; give the step that measured them reset=True")
    return bus, placed


def _read_vacant(state: BuildState, qubits: list[int], name: str) -> None:
    """Read each qubit as its own check that it is in |0>; in a kept shot it is in |0> again afterwards. A bus
    with nothing to read gets no register."""
    if not qubits:
        return
    register = state.register(name, len(qubits))
    for k, q in enumerate(qubits):
        state.checks.append([state.measure(q, register, k)])
        state.vacant.add(q)


def _release(state: BuildState, qubits: list[int], reset: bool) -> None:
    if reset:
        for q in qubits:
            state.circuit.reset(q)
        state.vacant |= set(qubits)


def _move(state: BuildState, source: int, target: int) -> None:
    """Carry `source`'s state onto `target`, which is in |0>, and leave `source` in |0>: two CX gates."""
    state.circuit.cx(source, target)
    state.circuit.cx(target, source)


def _arrived(state: BuildState, name: str) -> BuildState:
    """The pair is on the ports and the interior is back in |0>."""
    state.vacant = (state.vacant - set(state.path)) | set(state.interior)
    state.steps.append(f"{name}()")
    return state
