# src/bellbench/circuits.py
"""Circuit files, and the functions that build the circuits they hold.

A circuit file, config/circuit/bp.data.circuit.<name>.yaml, holds one written
circuit on one processor model's physical qubits: its gates as OpenQASM 3, the
analysis that processes its shots, and notes saying how it was built
(docs/DESIGN.md, section 2). A run reads the gates as written; nothing
regenerates them from a transport's name, so the file shows exactly what runs.

`load_circuit` reads a file, which configs.py checks against its schema, and
then checks what spans fields: the gates parse, the circuit has one register q
with the processor's qubit count, and every classical register is named by its
role (ROLES), alone or followed by an underscore and a name for the check, such
as check_zz. A run adds each basis's rotation and the port measurement into a
register named port, so a written circuit never uses that name.

The transport and check functions build circuits; `save_circuit` writes what
they build as a circuit file. `swap_chain` is the baseline transport: the
organisers' recipe of explicit SWAPs out along a port path and back (D-30).
Run as a module, this writes the three core baseline circuit files.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import yaml
from openqasm3.parser import QASM3ParsingError
from qiskit import QuantumCircuit, qasm3
from qiskit.qasm3 import QASM3ImporterError

from bellbench import configs

# The roles a written circuit's classical registers take; a run adds "port". A check's bits flag an error, a
# flag's bits catch a fault in a check, and frame_z or frame_x bits say a Z or an X is owed on the first port.
ROLES = ("check", "flag", "frame_z", "frame_x")
REGISTER_NAME = re.compile(rf"(?:{'|'.join(ROLES)})(?:_[a-z0-9]+)*")
CORE_PROCESSORS = ("ibm2016", "contemporary", "hyperbolic")


@dataclass(frozen=True)
class CircuitFile:
    """A loaded circuit file: its fields, the circuit its gates build, and its `{path, hash}` record."""

    name: str
    label: str
    processor: str
    analysis: str
    notes: str
    circuit: QuantumCircuit
    record: dict


def load_circuit(name: str) -> CircuitFile:
    """The circuit file for `name`, checked; raises a ValueError naming the file and the field."""
    data, record = configs.load_recorded("circuit", name)
    num_qubits = len(configs.load_processor(data["processor"])["qubits"])
    circuit = circuit_from_qasm(data["circuit"], num_qubits, record["path"])
    return CircuitFile(
        data["name"], data["label"], data["processor"], data["analysis"], data["notes"], circuit, record
    )


def circuit_from_qasm(text: str, num_qubits: int, where: str = "circuit") -> QuantumCircuit:
    """The circuit an OpenQASM 3 program builds, checked against the processor's qubit count and ROLES."""
    try:
        circuit = qasm3.loads(text)
    except (QASM3ImporterError, QASM3ParsingError) as e:
        raise ValueError(f"{where}: $.circuit: the gates do not parse as OpenQASM 3: {e}") from None
    if [(r.name, r.size) for r in circuit.qregs] != [("q", num_qubits)]:
        got = ", ".join(f"{r.name}[{r.size}]" for r in circuit.qregs) or "none"
        raise ValueError(f"{where}: $.circuit: needs one register q[{num_qubits}], the processor's qubits; got {got}")
    for reg in circuit.cregs:
        if not REGISTER_NAME.fullmatch(reg.name):
            raise ValueError(
                f"{where}: $.circuit: classical register {reg.name!r} is not named by a role ({', '.join(ROLES)}), "
                "alone or followed by _ and a name such as check_zz; the run adds the port register itself"
            )
    return circuit


def circuit_to_qasm(circuit: QuantumCircuit) -> str:
    """A circuit as the OpenQASM 3 text a circuit file holds, ending in one newline."""
    return qasm3.dumps(circuit).rstrip("\n") + "\n"


def save_circuit(
    name: str,
    label: str,
    processor: str,
    circuit: QuantumCircuit,
    notes: str,
    analysis: str = "postselect",
    overwrite: bool = False,
) -> Path:
    """Write `circuit` as the circuit file `name`, then load it back so a bad file never stays on disk."""
    path = configs.config_folder("circuit") / configs.file_name("circuit", name)
    if path.exists() and not overwrite:
        raise FileExistsError(f"{configs.repo_path(path)} exists; pass overwrite=True to replace it")
    data = {
        "name": name,
        "label": label,
        "processor": processor,
        "analysis": analysis,
        "notes": notes,
        "circuit": circuit_to_qasm(circuit),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    text = f"# {configs.repo_path(path)}\n\n" + yaml.dump(data, Dumper=_Dumper, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    try:
        load_circuit(name)
    except Exception:
        if previous is None:
            path.unlink()
        else:
            path.write_text(previous, encoding="utf-8")
        raise
    return path


# -- Transports ------------------------------------------------------------------


def smallest_shortest_path(graph: nx.Graph, a: int, b: int) -> list[int]:
    """The lexicographically smallest of the shortest paths from `a` to `b`, so the choice never depends on networkx."""
    return min(nx.all_shortest_paths(graph, a, b))


def swap_chain(processor: str, path: Sequence[int] | None = None) -> QuantumCircuit:
    """The baseline transport: H on the first port, SWAPs along `path` until the pair's qubits are neighbours,
    CX onto the second port, then the same SWAPs in reverse so the pair ends on the ports (D-30).

    `path` runs from the first port to the second along couplers of the graph;
    by default it is the lexicographically smallest shortest path.
    """
    proc = configs.load_processor(processor)
    graph = configs.processor_graph(proc)
    a, b = proc["ports"]
    path = list(path) if path is not None else smallest_shortest_path(graph, a, b)
    if len(path) < 2 or path[0] != a or path[-1] != b:
        raise ValueError(f"path {path} must run from the first port {a} to the second port {b}")
    for u, v in zip(path, path[1:]):
        if not graph.has_edge(u, v):
            raise ValueError(f"path {path}: qubits {u} and {v} are not a coupler of {processor!r}")
    if len(set(path)) != len(path):
        raise ValueError(f"path {path} visits a qubit twice")
    circuit = QuantumCircuit(graph.number_of_nodes())
    circuit.h(a)
    hops = list(zip(path[:-2], path[1:-1]))
    for u, v in hops:
        circuit.swap(u, v)
    circuit.cx(path[-2], b)
    for u, v in reversed(hops):
        circuit.swap(u, v)
    return circuit


def baseline_name(processor: str) -> str:
    return f"baseline-{processor}"


def write_baseline(processor: str, overwrite: bool = False) -> Path:
    """Write the core baseline circuit file for `processor`: swap_chain along its smallest shortest path."""
    proc = configs.load_processor(processor)
    path = smallest_shortest_path(configs.processor_graph(proc), *proc["ports"])
    notes = (
        "The baseline transport (swap_chain in src/bellbench/circuits.py), the organisers' recipe: H on the "
        f"first port, explicit SWAPs out along the path {path}, the lexicographically smallest shortest path "
        "between the ports, CX onto the second port, and the same SWAPs back, so the pair ends on the ports. "
        "No checks, so postselection keeps every shot."
    )
    return save_circuit(
        baseline_name(processor), f"Baseline, {proc['label']}", processor, swap_chain(processor, path), notes,
        overwrite=overwrite,
    )


class _Dumper(yaml.SafeDumper):
    """Writes the gates as a literal block, so they read as written, and long prose as a folded block."""


def _block_text(dumper, text):
    style = "|" if "\n" in text else (">" if len(text) > 80 else None)
    return dumper.represent_scalar("tag:yaml.org,2002:str", text, style=style)


_Dumper.add_representer(str, _block_text)


if __name__ == "__main__":
    for name in CORE_PROCESSORS:
        print(configs.repo_path(write_baseline(name, overwrite=True)))
