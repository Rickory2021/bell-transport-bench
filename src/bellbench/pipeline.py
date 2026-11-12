# src/bellbench/pipeline.py
"""The steps a run takes between its circuit and its counts: compile, cost, schedule, simulate.

Each step is a plain function, so each can be tested alone (docs/DESIGN.md,
section 5). CircuitRun calls them in order:

1. `basis_circuits` adds each basis's rotation and the port measurement, into
   a classical register named `port`, to the transport's circuit.
2. `compile_bases` compiles the three at optimisation level 1 on the written
   physical qubits under one transpiler seed, keeping each one's routed
   circuit (after routing, before SWAPs become two-qubit gates) and its
   compiled circuit. Level 1 is the highest level that keeps explicit SWAPs
   (section 9).
3. `cost` takes the run's cost before scheduling: SWAPs from the routed
   circuit, everything else from the compiled ZZ circuit.
4. `schedule` turns idle time into timed delays, so qubits decay while they
   wait; a profile without durations is not scheduled.
5. `simulate` runs the three basis circuits in one Aer job and returns each
   basis's port counts with the seed and method Aer used.

`derive_seed` gives each run and each simulation its own seed from a base seed
and labels. `port_density_matrix` is for the organisers' cross-check only
(D-50): it computes the ports' state exactly, without shots.

How the compile is split: Qiskit's level 1 preset pass manager runs in three
pieces (init; layout and routing; translation and optimization), which
compile to the same circuit as one `transpile` call. Init cancels back-to-back
inverse pairs, including two identical SWAPs, so SWAPs are counted after it,
where they exist. A SWAP the router adds moves the pair, and the routed
circuit's final layout shows whether each port still holds its half of it
(`pair_on_ports`).
"""

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from qiskit import ClassicalRegister, QuantumCircuit
from qiskit.transpiler import PassManager, StagedPassManager, generate_preset_pass_manager
from qiskit.transpiler.exceptions import TranspilerError
from qiskit.transpiler.passes import ALAPScheduleAnalysis, PadDelay
from qiskit_aer import AerSimulator

from bellbench.fidelity import BASES
from bellbench.noise import NoiseControl

OPTIMIZATION_LEVEL = 1
PORT_REGISTER = "port"
NON_GATES = ("measure", "barrier", "delay", "reset")


@dataclass(frozen=True)
class Compiled:
    """One basis circuit compiled: the SWAPs left after init, the routed circuit, and the compiled circuit."""

    basis: str
    swaps_after_init: int
    routed: QuantumCircuit
    compiled: QuantumCircuit


@dataclass(frozen=True)
class Simulation:
    """One simulation's port counts per basis, with the seed and method Aer used for each basis circuit.

    `raw` holds each basis's counts with every classical register, keyed as
    Qiskit writes them (one bit string per register, the last register first),
    so a run can postselect on check bits and store the counts in full.
    """

    counts: dict[str, dict[str, int]]
    seeds: dict[str, int]
    methods: dict[str, str]
    shots: int
    raw: dict[str, dict[str, int]] = field(default_factory=dict)


# -- Basis circuits ----------------------------------------------------------------


def basis_circuits(circuit: QuantumCircuit, ports: Sequence[int]) -> dict[str, QuantumCircuit]:
    """The circuit three times, each with its basis rotation on the ports and the port measurement.

    ZZ measures directly, XX applies H to both ports first, and YY applies S
    dagger then H (docs/CHALLENGE.md, Verifying the pair). The first port is
    measured into port[0], the second into port[1].
    """
    a, b = _check_ports(circuit, ports)
    if any(reg.name == PORT_REGISTER for reg in circuit.cregs):
        raise ValueError(f"the circuit already has a classical register named {PORT_REGISTER!r}")
    out = {}
    for basis in BASES:
        qc = circuit.copy()
        port = ClassicalRegister(2, PORT_REGISTER)
        qc.add_register(port)
        for q in (a, b):
            if basis == "YY":
                qc.sdg(q)
            if basis in ("XX", "YY"):
                qc.h(q)
        qc.measure([a, b], [port[0], port[1]])
        out[basis] = qc
    return out


# -- Compile --------------------------------------------------------------------


def compile_bases(circuits: Mapping[str, QuantumCircuit], nc: NoiseControl, seed: int) -> dict[str, Compiled]:
    """Compile each basis circuit at level 1 on the written physical qubits, under one transpiler seed."""
    _check_seed(seed, "transpiler seed")
    out = {}
    for basis, circuit in circuits.items():
        if circuit.num_qubits != nc.num_qubits:
            raise ValueError(
                f"the {basis} circuit has {circuit.num_qubits} qubits; it must be written on the processor's "
                f"{nc.num_qubits} physical qubits"
            )
        _check_operations_supported(circuit, basis, nc)
        pm = generate_preset_pass_manager(
            optimization_level=OPTIMIZATION_LEVEL,
            target=nc.target,
            initial_layout=list(range(nc.num_qubits)),
            seed_transpiler=seed,
        )
        initialised = StagedPassManager(stages=["init"], init=pm.init).run(circuit)
        routed = StagedPassManager(stages=["layout", "routing"], layout=pm.layout, routing=pm.routing).run(initialised)
        try:
            compiled = StagedPassManager(
                stages=["translation", "optimization"], translation=pm.translation, optimization=pm.optimization
            ).run(routed)
        except TranspilerError as err:
            gates = sorted(set(nc.target.operation_names) - set(NON_GATES))
            outside = sorted({i.operation.name for i in routed.data} - set(nc.target.operation_names) - set(NON_GATES))
            raise ValueError(
                f"the {basis} circuit cannot be compiled to the {nc.noise_name!r} profile's gates {gates}: of its "
                f"gates, {outside} are outside that set, and at least one cannot be built from it; add the missing "
                "gate to the profile or change the circuit"
            ) from err
        out[basis] = Compiled(basis, initialised.count_ops().get("swap", 0), routed, compiled)
    return out


def pair_on_ports(routed: QuantumCircuit, ports: Sequence[int]) -> bool:
    """Whether each port still holds its half of the pair after routing, read from the final layout."""
    final = routed.layout.final_layout if routed.layout is not None else None
    if final is None:  # routing moved no qubit
        return True
    return all(final[routed.qubits[p]] == p for p in ports)


# -- Cost ------------------------------------------------------------------------


def cost(compiled: Mapping[str, Compiled], ports: Sequence[int]) -> dict:
    """The run's cost before scheduling, from the routed circuits and the compiled ZZ circuit.

    - `swaps`: SWAPs in the routed ZZ circuit, the ones that exist after init;
      `router_swaps` of them were added by the router.
    - `qubits_used`: physical qubits any instruction of the compiled ZZ circuit
      acts on, the ports included.
    - `depth`: the compiled ZZ circuit's depth counting gates only, without
      measurement, delays, resets or barriers.
    - `two_qubit_gates`: in the compiled ZZ circuit; `two_qubit_gates_by_edge`
      counts them per coupler for each basis, as "a-b" with a < b.
    - `pair_on_ports`: from the routed ZZ circuit.
    """
    if "ZZ" not in compiled:
        raise ValueError(f"cost reads the compiled ZZ circuit; got the bases {sorted(compiled)}")
    zz = compiled["ZZ"]
    swaps = zz.routed.count_ops().get("swap", 0)
    by_edge = {basis: _two_qubit_by_edge(c.compiled) for basis, c in compiled.items()}
    used = sorted({zz.compiled.find_bit(q).index for inst in zz.compiled.data for q in inst.qubits if inst.operation.name != "barrier"})
    return {
        "swaps": swaps,
        "router_swaps": swaps - zz.swaps_after_init,
        "qubits_used": used,
        "depth": zz.compiled.depth(lambda inst: inst.operation.name not in NON_GATES),
        "two_qubit_gates": sum(by_edge["ZZ"].values()),
        "two_qubit_gates_by_edge": by_edge,
        "pair_on_ports": pair_on_ports(zz.routed, ports),
    }


def _two_qubit_by_edge(circuit: QuantumCircuit) -> dict[str, int]:
    counts = Counter()
    for inst in circuit.data:
        if len(inst.qubits) == 2 and inst.operation.name not in NON_GATES:
            a, b = sorted(circuit.find_bit(q).index for q in inst.qubits)
            counts[f"{a}-{b}"] += 1
    return dict(sorted(counts.items()))


# -- Schedule ----------------------------------------------------------------------


def schedule(circuit: QuantumCircuit, nc: NoiseControl) -> QuantumCircuit:
    """The compiled circuit scheduled as late as possible, its idle time padded with timed delays.

    A profile without durations (a depolarising one) has nothing to schedule,
    so the circuit comes back unchanged.
    """
    if not nc.has_durations:
        return circuit
    return PassManager([ALAPScheduleAnalysis(target=nc.target), PadDelay(target=nc.target)]).run(circuit)


def scheduled_duration(circuit: QuantumCircuit, nc: NoiseControl) -> float | None:
    """The scheduled circuit's duration in seconds, or None for a profile without durations."""
    if not nc.has_durations:
        return None
    return float(circuit.estimate_duration(nc.target, unit="s"))


# -- Seeds -------------------------------------------------------------------------


def derive_seed(base_seed: int, *labels) -> int:
    """A 32-bit seed that depends only on the base seed and the labels, never on the order runs are made.

    The first four bytes of a SHA-256 of the base seed and labels written as
    JSON. Labels are strings or integers, such as a run's name and "noisy".
    """
    _check_seed(base_seed, "base seed")
    for label in labels:
        if isinstance(label, bool) or not isinstance(label, (str, int)):
            raise ValueError(f"seed labels are strings or integers; got {label!r}")
    text = json.dumps([base_seed, *labels], separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:4], "big")


# -- Simulate ----------------------------------------------------------------------


def simulate(
    circuits: Mapping[str, QuantumCircuit],
    noise_model,
    shots: int,
    seed: int,
    method: str = "automatic",
) -> Simulation:
    """Run the basis circuits in one Aer job, ideal when `noise_model` is None, and return the port counts.

    Aer gives each circuit its own seed derived from `seed`; the seeds and the
    method it reports for each are returned, so a rerun can repeat them.
    """
    if isinstance(shots, bool) or not isinstance(shots, int) or shots < 1:
        raise ValueError(f"shots must be a positive integer; got {shots!r}")
    _check_seed(seed, "simulator seed")
    bases = list(circuits)
    simulator = AerSimulator(method=method, noise_model=noise_model, seed_simulator=seed)
    result = simulator.run([circuits[b] for b in bases], shots=shots).result()
    counts, seeds, methods, raw = {}, {}, {}, {}
    for i, basis in enumerate(bases):
        raw[basis] = dict(sorted(result.get_counts(i).items()))
        counts[basis] = register_counts(raw[basis], circuits[basis], PORT_REGISTER)
        seeds[basis] = int(result.results[i].seed_simulator)
        methods[basis] = str(result.results[i].metadata["method"])
    return Simulation(counts, seeds, methods, shots, raw)


def register_counts(counts: Mapping[str, int], circuit: QuantumCircuit, name: str) -> dict[str, int]:
    """The counts of one classical register, summed over every other register's outcomes.

    Qiskit writes a count's key as one bit string per register, separated by
    spaces, with the last register first.
    """
    names = [reg.name for reg in circuit.cregs]
    if name not in names:
        raise ValueError(f"the circuit has no classical register named {name!r}; it has {names}")
    position = len(names) - 1 - names.index(name)
    out = Counter()
    for key, n in counts.items():
        parts = key.split(" ")
        if len(parts) != len(names):
            raise ValueError(f"count key {key!r} does not have one part per register {names}")
        out[parts[position]] += n
    return dict(sorted(out.items()))


def port_density_matrix(circuit: QuantumCircuit, noise_model, ports: Sequence[int]):
    """The two ports' density matrix, computed exactly; only the organisers' cross-check uses it (D-50)."""
    a, b = _check_ports(circuit, ports)
    qc = circuit.remove_final_measurements(inplace=False)
    qc.save_density_matrix([a, b], label="ports")
    result = AerSimulator(method="density_matrix", noise_model=noise_model).run(qc, shots=1).result()
    return result.data(0)["ports"]


# -- Checks ------------------------------------------------------------------------


def _check_ports(circuit: QuantumCircuit, ports: Sequence[int]) -> tuple[int, int]:
    if len(ports) != 2 or ports[0] == ports[1]:
        raise ValueError(f"a run has two different ports; got {ports!r}")
    for p in ports:
        if isinstance(p, bool) or not isinstance(p, int) or not 0 <= p < circuit.num_qubits:
            raise ValueError(f"port {p!r} is not a qubit of the {circuit.num_qubits}-qubit circuit")
    return ports[0], ports[1]


def _check_operations_supported(circuit: QuantumCircuit, basis: str, nc: NoiseControl) -> None:
    """Raise when the circuit resets, waits or measures and the profile defines no such operation.

    A missing gate may still be built from the profile's gates, so only the
    compile can tell; a missing reset, delay or measurement never can.
    """
    used = {i.operation.name for i in circuit.data}
    lacking = sorted(used & {"reset", "delay", "measure"} - set(nc.target.operation_names))
    if lacking:
        raise ValueError(
            f"the {basis} circuit uses {', '.join(lacking)}, which the {nc.noise_name!r} profile does not define, "
            "so it cannot run under this profile"
        )


def _check_seed(seed, what: str) -> None:
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError(f"{what} must be an integer from 0 to 2**32 - 1; got {seed!r}")
