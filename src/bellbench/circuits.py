# src/bellbench/circuits.py
"""Circuit files, and the functions that build the circuits they hold.

A circuit file, config/circuit/bp.data.circuit.<name>.yaml, holds one written
circuit on one processor model's physical qubits: its gates as OpenQASM 3, the
analysis that reads its shots (a name from src/bellbench/analysis.py's registry,
with its settings), and notes saying how it was built
(docs/DESIGN.md, section 2). A run reads the gates as written; nothing
regenerates them from a transport's name, so the file shows exactly what runs.

`load_circuit` reads a file, which configs.py checks against its schema, and
then checks what spans fields: the gates parse, the circuit has one register q
with the processor's qubit count, and every classical register is named by its
role (ROLES), alone or followed by an underscore and a name for the check, such
as check_zz. A run adds each basis's rotation and the port measurement into a
register named port, so a written circuit never uses that name, and never
measures or resets a port. A circuit file holds no operation conditioned on a
measured bit, since the noise model has no feedforward latency; a Pauli owed
from a mid-circuit read goes in the analysis's frame instead. A delay is written
in real time (s, ms, us or ns), never in dt, which is a noise profile's clock
tick while a circuit file belongs to a processor (docs/DESIGN.md, section 7).

The transport and check functions build circuits; `save_circuit` writes what
they build as a circuit file, in config/circuit/, or with `trial=True` as a
trial in workspace/circuits/, which git ignores. `promote` moves a trial into
config/circuit/ to be committed. A circuit's name is never both a committed
circuit and a trial. `swap_chain` is the baseline transport: the
organisers' recipe of explicit SWAPs out along a port path, which paths.py
chooses, and back (D-30).
Run as a module, this writes the three core baseline circuit files.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml
from openqasm3.parser import QASM3ParsingError
from qiskit import QuantumCircuit, qasm3
from qiskit.circuit import ControlFlowOp
from qiskit.qasm3 import QASM3ImporterError

from bellbench import configs
from bellbench.analysis import check_analysis
from bellbench.paths import port_path, smallest_shortest_path
from bellbench.pipeline import PORT_REGISTER

# The roles a written circuit's classical registers take; a run adds "port". A check's bits flag an error, a
# flag's bits catch a fault in a check, and frame_z or frame_x bits say a Z or an X is owed on the first port.
ROLES = ("check", "flag", "frame_z", "frame_x")
REGISTER_NAME = re.compile(rf"(?:{'|'.join(ROLES)})(?:_[a-z0-9]+)*")
CORE_PROCESSORS = configs.CORE_PROCESSORS


@dataclass(frozen=True)
class CircuitFile:
    """A loaded circuit file: its fields, the circuit its gates build, and its `{path, hash}` record."""

    name: str
    label: str
    processor: str
    analysis: dict
    notes: str
    circuit: QuantumCircuit
    record: dict


def load_circuit(name: str, path: Path | None = None) -> CircuitFile:
    """The circuit file for `name`, checked; raises a ValueError naming the file and the field.

    `path` loads that file in place of the one the name finds: `promote` checks
    the file it has just written while the trial of the same name still exists.
    """
    data, record = configs.load_recorded("circuit", name, path)
    try:
        processor = configs.load_processor(data["processor"])
    except FileNotFoundError as e:
        raise ValueError(f"{record['path']}: $.processor: {e}") from None
    circuit = circuit_from_qasm(data["circuit"], len(processor["qubits"]), record["path"], processor["ports"])
    try:
        check_analysis(data["analysis"], [(r.name, r.size) for r in circuit.cregs] + [(PORT_REGISTER, 2)])
    except ValueError as e:
        raise ValueError(f"{record['path']}: $.analysis: {e}") from None
    return CircuitFile(
        data["name"], data["label"], data["processor"], data["analysis"], data["notes"], circuit, record
    )


def circuit_from_qasm(
    text: str, num_qubits: int, where: str = "circuit", ports: Sequence[int] = ()
) -> QuantumCircuit:
    """The circuit an OpenQASM 3 program builds, checked against the processor's qubits and ports, and ROLES."""
    try:
        circuit = qasm3.loads(text)
    except (QASM3ImporterError, QASM3ParsingError) as e:
        raise ValueError(f"{where}: $.circuit: the gates do not parse as OpenQASM 3: {e}") from None
    except Exception as e:  # a gate given one qubit twice, an index past its register, a text with no statement
        raise ValueError(f"{where}: $.circuit: the gates do not build a circuit: {type(e).__name__}: {e}") from None
    if [(r.name, r.size) for r in circuit.qregs] != [("q", num_qubits)]:
        got = ", ".join(f"{r.name}[{r.size}]" for r in circuit.qregs) or "none"
        raise ValueError(f"{where}: $.circuit: needs one register q[{num_qubits}], the processor's qubits; got {got}")
    named = f"named by a role ({', '.join(ROLES)}), alone or followed by _ and a name such as check_zz"
    for reg in circuit.cregs:
        if not REGISTER_NAME.fullmatch(reg.name):
            raise ValueError(
                f"{where}: $.circuit: classical register {reg.name!r} is not {named}; "
                "the run adds the port register itself"
            )
    loose = [i for i, bit in enumerate(circuit.clbits) if not circuit.find_bit(bit).registers]
    if loose:
        raise ValueError(
            f"{where}: $.circuit: classical bit(s) {loose} sit in no register; declare each in a register {named}"
        )
    for inst in circuit.data:
        op, qubits = inst.operation, [circuit.find_bit(q).index for q in inst.qubits]
        if isinstance(op, ControlFlowOp):
            raise ValueError(
                f"{where}: $.circuit: {op.name} on qubit(s) {qubits} depends on a measured bit; a circuit file holds "
                "no feedforward, which the noise model cannot time, so record a Pauli owed from a read in the "
                "analysis's frame_z or frame_x bits instead"
            )
        if op.name == "delay" and op.unit == "dt":
            raise ValueError(
                f"{where}: $.circuit: the delay on qubit(s) {qubits} is in dt, a noise profile's clock tick; write "
                "it in s, ms, us or ns, which mean the same under every profile"
            )
        if op.name in ("measure", "reset") and set(qubits) & set(ports):
            raise ValueError(
                f"{where}: $.circuit: the circuit {op.name}s port qubit {qubits[0]}; the run measures the ports "
                "itself, in each basis, after the circuit ends"
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
    analysis: Mapping | None = None,
    overwrite: bool = False,
    trial: bool = False,
) -> Path:
    """Write `circuit` as the circuit file `name`, then load it back so a bad file never stays on disk.

    `analysis` is `{name, settings}` from the registry in analysis.py; by default postselect.
    The file goes in config/circuit/, or with `trial=True` in workspace/circuits/;
    a name the other folder already holds is refused, so one name is one circuit.
    """
    committed = configs.config_folder("circuit") / configs.file_name("circuit", name)
    trial_path = configs.trial_folder() / configs.file_name("circuit", name)
    path, other = (trial_path, committed) if trial else (committed, trial_path)
    if other.exists():
        kind = "a committed circuit" if trial else "a trial circuit"
        raise ValueError(
            f"{configs.repo_path(other)} is {kind} named {name!r}; one name is one circuit, so choose another name"
            + ("" if trial else " or promote the trial")
        )
    if path.exists() and not overwrite:
        raise FileExistsError(f"{configs.repo_path(path)} exists; pass overwrite=True to replace it")
    if analysis is not None and not isinstance(analysis, Mapping):
        raise ValueError(
            f"{configs.repo_path(path)}: $.analysis: an analysis is a mapping {{name, settings}}, such as "
            f"{{'name': 'postselect'}}; got {analysis!r}"
        )
    data = {
        "name": name,
        "label": label,
        "processor": processor,
        "analysis": dict(analysis) if analysis is not None else {"name": "postselect"},
        "notes": notes,
        "circuit": circuit_to_qasm(circuit),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    path.write_text(_file_text(path, data), encoding="utf-8")
    try:
        load_circuit(name)
    except Exception:
        if previous is None:
            path.unlink()
        else:
            path.write_text(previous, encoding="utf-8")
        raise
    return path


def _file_text(path: Path, data: Mapping) -> str:
    """A circuit file's text: a comment naming its path from the repo's root, then its fields as YAML."""
    return f"# {configs.repo_path(path)}\n\n" + yaml.dump(data, Dumper=configs.Dumper, sort_keys=False)


def promote(name: str, overwrite: bool = False) -> Path:
    """Move the trial circuit `name` from workspace/circuits/ into config/circuit/, to be committed.

    The file is written in config/circuit/ from the trial's parsed content, then
    loaded back and checked, and only then is the trial deleted. If the written
    file does not load, or the check is interrupted, config/circuit/ is put back
    as it was and the trial is left untouched, so a bad trial moves nowhere. A
    committed circuit of that name is refused unless `overwrite=True`. A run made
    from the trial keeps its record, which then names a file that no longer
    exists, so it can be neither rerun nor fetched; a run of the promoted
    circuit under the same settings repeats its numbers, since the seeds derive
    from the circuit's name.
    """
    trial_path = configs.trial_folder() / configs.file_name("circuit", name)
    target = configs.config_folder("circuit") / configs.file_name("circuit", name)
    if not trial_path.is_file():
        trials = ", ".join(configs.trial_names()) or "none"
        folder = configs.repo_path(configs.trial_folder())
        raise FileNotFoundError(f"no trial circuit named {name!r} in {folder}; trials: {trials}")
    if target.exists() and not overwrite:
        raise FileExistsError(f"{configs.repo_path(target)} exists; pass overwrite=True to replace it")
    trial_text = trial_path.read_text(encoding="utf-8")
    previous = target.read_text(encoding="utf-8") if target.exists() else None
    try:
        data = yaml.safe_load(trial_text)
    except yaml.YAMLError as e:
        raise ValueError(f"{configs.repo_path(trial_path)}: the trial does not parse as YAML: {e}") from None
    target.write_text(_file_text(target, data), encoding="utf-8")
    try:
        load_circuit(name, target)
    except BaseException:  # an interrupt too: an unchecked file must not stay in config/circuit/
        if previous is None:
            target.unlink()
        else:
            target.write_text(previous, encoding="utf-8")
        raise
    trial_path.unlink()
    return target


# -- Transports ------------------------------------------------------------------


def swap_chain(processor: str, path: Sequence[int] | None = None) -> QuantumCircuit:
    """The baseline transport: H on the first port, SWAPs along `path` until the pair's qubits are neighbours,
    CX onto the second port, then the same SWAPs in reverse so the pair ends on the ports (D-30).

    `path` runs from the first port to the second along couplers of the graph;
    by default it is the lexicographically smallest shortest path.
    """
    graph, path = port_path(processor, path)
    a, b = path[0], path[-1]
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


if __name__ == "__main__":
    for name in CORE_PROCESSORS:
        print(configs.repo_path(write_baseline(name, overwrite=True)))
