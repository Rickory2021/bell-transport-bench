# src/bellbench/views/show.py
"""A circuit before it runs: its header, its processor graph beside its written gates, and what compiling costs.

`Compiled` is what the view draws from: a circuit file with its three compiled
basis circuits, their cost and duration, from a run that compiled without
simulating (CircuitRun.compile) or from a run's record. `show_parts` lays it
out, as data and warnings only: a two-line header, the graph with numbered
qubits and each coupler the written circuit uses labelled with its gate count,
the written circuit, one cost line and the gates by type. `step`, `compiled`
and `timeline` each add a debug view, folded until clicked: the stepper on the
written circuit, the compiled circuits in short rows, and a busy and idle
chart in µs. How to read each view is explained once, in the tutorial.
"""

from dataclasses import dataclass
from html import escape
from typing import Literal

import networkx as nx
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from qiskit import QuantumCircuit, qasm3

from bellbench import configs
from bellbench.circuits import CircuitFile, load_circuit
from bellbench.figures import COLORS, DEFAULT_COLOR, draw_processor, processor_layout
from bellbench.noise import NoiseControl
from bellbench.pipeline import schedule, two_qubit_by_edge
from bellbench.run import CircuitRun, circuit_size, drawn_figure, timeline_figure
from bellbench.views.base import Part, fold, html, image, img, markdown
from bellbench.views.stepper import journey_html

Basis = Literal["ZZ", "XX", "YY"]
BASES: tuple[Basis, ...] = ("ZZ", "XX", "YY")  # the order every view lists the bases in


@dataclass(frozen=True)
class Compiled:
    """What show draws: one circuit file, compiled, with its cost."""

    circuit_file: CircuitFile
    compiled: dict[Basis, QuantumCircuit]  # on physical qubits, before scheduling
    cost: dict                             # the keys pipeline.cost returns
    duration_s: float | None               # None under a profile without durations
    origin: str                            # where the compiled circuits came from, for the header
    noise_record: dict                     # NoiseControl's part of a run record

    def noise_control(self) -> NoiseControl:
        """The run's noise control, built only when a view needs it, since building one takes a moment."""
        return NoiseControl.from_yaml(self.noise_record)

    @classmethod
    def of_run(cls, run: CircuitRun) -> "Compiled":
        """A run that has compiled (CircuitRun.compile), whether or not it has simulated."""
        return cls(
            circuit_file=run.circuit,
            compiled={basis: c.compiled for basis, c in run.compiled.items()},
            cost=run.cost,
            duration_s=run.duration,
            origin=f"compiled now under {run.nc.noise_name}, base seed {run.base_seed}",
            noise_record=run.nc.export_as_yaml(),
        )

    @classmethod
    def of_record(cls, record: dict, fresh: bool) -> "Compiled":
        """A run's record, as a result holds it; `fresh` says the run was made in this session."""
        return cls(
            circuit_file=load_circuit(configs.name_from_record(record["circuit"], "circuit")),
            compiled={basis: qasm3.loads(text) for basis, text in record["compiled"].items()},
            cost=record["cost"],
            duration_s=record["scheduled_duration"],
            origin="this session's run" if fresh else "a fetched run",
            noise_record=record["noise_control"],
        )


def _couplers(circuit: QuantumCircuit) -> dict[tuple[int, int], int]:
    """Two-qubit gates per coupler, as {(a, b): count} with a < b, counted by the pipeline's own counter."""
    return {tuple(int(q) for q in edge.split("-")): count for edge, count in two_qubit_by_edge(circuit).items()}


def _size(circuit: QuantumCircuit) -> tuple[float, float]:
    """The size in inches Qiskit's circuit drawer gives a figure of its own, from a probe drawing."""
    ax = Figure().add_subplot()
    circuit.draw("mpl", idle_wires=False, fold=40, ax=ax)
    return circuit_size(ax)


def _reading(analysis: dict, circuit: QuantumCircuit) -> str:
    """How the analysis reads the shots, in a few words."""
    if analysis["name"] == "parity":
        groups = len(analysis["settings"]["checks"])
        frames = [frame for frame in ("frame_z", "frame_x") if analysis["settings"].get(frame)]
        return (f"`parity`, {groups} check group{'s' if groups != 1 else ''}"
                + (f", frame {', '.join(frames)}" if frames else ""))
    return "`postselect`, every shot kept" if not circuit.cregs else "`postselect`, other bits must read 0"


def _show_header(view: Compiled, processor: dict) -> Part:
    """Two lines: the circuit file and its label; the processor, ports, reading and source."""
    circuit_file = view.circuit_file
    port_a, port_b = processor["ports"]
    hops = nx.shortest_path_length(configs.processor_graph(processor), port_a, port_b)
    return markdown(
        f"**{circuit_file.name}**: {circuit_file.label}  \n"
        f"{circuit_file.processor}, ports {port_a} and {port_b}, {hops} hops · read by "
        f"{_reading(circuit_file.analysis, circuit_file.circuit)} · {view.origin}")


def written_part(view: Compiled, processor: dict) -> Part:
    """The processor graph with the couplers the written circuit uses, beside the written circuit."""
    circuit_file = view.circuit_file
    drawn = circuit_file.circuit.copy()
    drawn.global_phase = 0  # changes no outcome; drawing it would go through pyplot
    written = _couplers(drawn)
    width, height = _size(drawn)
    fig = Figure(figsize=(4.2 + width, max(4.4, height)))
    graph_ax, circuit_ax = fig.subplots(1, 2, gridspec_kw={"width_ratios": [4.2, width]})
    draw_processor(graph_ax, processor, COLORS.get(circuit_file.processor, DEFAULT_COLOR), used_edges=list(written))
    layout = processor_layout(processor, configs.processor_graph(processor))
    for qubit, (x, y) in layout.items():  # numbered, so each coupler maps to the circuit's wires
        graph_ax.text(x, y, str(qubit), ha="center", va="center", fontsize=7, color="white", zorder=6)
    for (a, b), count in written.items():
        (x1, y1), (x2, y2) = layout[a], layout[b]
        graph_ax.text((x1 + x2) / 2, (y1 + y2) / 2, str(count), ha="center", va="center", fontsize=8, zorder=7,
                      bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none"})
    graph_ax.set_title(f"{circuit_file.processor}: couplers the written circuit uses", fontsize=10)
    drawn.draw("mpl", idle_wires=False, fold=40, ax=circuit_ax)
    circuit_ax.set_title("The written circuit", fontsize=10)
    return image(fig)


def _show_cost(view: Compiled) -> list[Part]:
    """One cost line, the gates by type in each circuit, and a warning only when compiling added a coupler."""
    costs = view.cost
    duration = f"{view.duration_s * 1e6:.3f} µs" if view.duration_s is not None else "not scheduled"
    on_ports = "pair on the ports ✓" if costs["pair_on_ports"] else "**pair NOT on the ports**"
    parts = [markdown(
        f"Cost: {costs['two_qubit_gates']} two-qubit gates · {costs['swaps']} SWAPs ({costs['router_swaps']} by the "
        f"router) · depth {costs['depth']} · {len(costs['qubits_used'])} qubits "
        f"({', '.join(map(str, costs['qubits_used']))}) · {duration} · {on_ports}")]
    gates = {"written": dict(view.circuit_file.circuit.count_ops())}
    gates |= {f"compiled {basis}": dict(view.compiled[basis].count_ops()) for basis in BASES}
    table = pd.DataFrame(gates).T.fillna(0).astype(int)
    table = table[[gate for gate in table.columns if gate != "measure"] + ["measure"] * ("measure" in table.columns)]
    parts.append(html(table.to_html(border=0)))
    added = set(two_qubit_by_edge(view.compiled["ZZ"])) - set(two_qubit_by_edge(view.circuit_file.circuit))
    if added:
        parts.append(markdown(f"**Warning: compiling uses couplers the written circuit does not:** "
                              f"{', '.join(sorted(added))}. The router moved qubits; `compiled=True` shows where."))
    return parts


def _single_qubit_gates(circuit: QuantumCircuit, qubit: int) -> list[str]:
    """The names of the single-qubit gates on `qubit`, in order."""
    return [i.operation.name for i in circuit.data
            if len(i.qubits) == 1 and circuit.find_bit(i.qubits[0]).index == qubit
            and i.operation.name not in ("measure", "barrier", "delay")]


def _compiled_html(view: Compiled, draw_all: bool) -> str:
    """The compiled ZZ circuit in short rows, and one computed line on how XX and YY differ from it."""
    def draw(basis: Basis) -> str:
        circuit = view.compiled[basis].copy()
        circuit.global_phase = 0  # changes no outcome; the drawer would print it on every circuit
        fig = drawn_figure(lambda ax: circuit.draw("mpl", idle_wires=False, fold=12, ax=ax), circuit_size)
        fig.suptitle(f"Compiled {basis} circuit", fontsize=11)
        return img(fig)

    parts = [draw("ZZ")]
    zz = view.compiled["ZZ"]
    two_qubit = lambda c: [(i.operation.name, tuple(c.find_bit(q).index for q in i.qubits))
                           for i in c.data if len(i.qubits) == 2 and i.operation.name != "barrier"]
    qubits = sorted({zz.find_bit(q).index for i in zz.data for q in i.qubits})
    for basis in ("XX", "YY"):
        other = view.compiled[basis]
        same = "the same" if two_qubit(other) == two_qubit(zz) else "<b>different</b>"
        differ = [q for q in qubits if _single_qubit_gates(other, q) != _single_qubit_gates(zz, q)]
        parts.append(f"<p>{basis}: {same} {len(two_qubit(zz))} two-qubit gates in the same order; single-qubit "
                     f"gates differ on qubit{'s' if len(differ) != 1 else ''} {', '.join(map(str, differ)) or 'none'}</p>")
        if draw_all:
            parts.append(draw(basis))
    return "".join(parts)


BUSY_COLORS = {"two-qubit gate": "#7139cc", "single-qubit gate": "#c4b2ec", "measurement": "#4a5568"}


def _timeline_html(view: Compiled, basis: Basis = "ZZ") -> str:
    """A compiled circuit over time, twice: our chart of when each qubit is busy, then qiskit's own timeline.

    The chart gives time in µs for the qubits that act: a two-qubit gate, a single-qubit gate, a measurement, or
    waiting. Qiskit's timeline names each gate on every qubit, in the processor's time steps; it is the picture
    a run folder keeps in timeline/, drawn by the same function.
    """
    noise = view.noise_control()
    if not noise.has_durations:
        return f"<p>No timeline: {escape(noise.noise_name)} has no durations, so the run is not scheduled.</p>"
    scheduled = schedule(view.compiled[basis], noise)
    tick = noise.target.dt
    clock: dict[int, float] = {}                    # each qubit's time so far, in seconds
    busy: dict[int, dict[str, list[tuple[float, float]]]] = {}
    for instruction in scheduled.data:
        name = instruction.operation.name
        if name == "barrier":
            continue
        qubits = tuple(scheduled.find_bit(q).index for q in instruction.qubits)
        if name == "delay":
            unit = instruction.operation.unit
            seconds = instruction.operation.duration * (tick if unit == "dt" else {"s": 1, "us": 1e-6, "ns": 1e-9}[unit])
        else:
            seconds = noise.target[name][qubits].duration or 0.0
        start = max(clock.get(q, 0.0) for q in qubits)
        for q in qubits:
            clock[q] = start + seconds
            if name != "delay" and seconds > 0:
                kind = "measurement" if name == "measure" else ("two-qubit gate" if len(qubits) == 2 else "single-qubit gate")
                busy.setdefault(q, {}).setdefault(kind, []).append((start * 1e6, seconds * 1e6))
    total = max(clock.values()) * 1e6
    rows = sorted(busy)
    fig = Figure(figsize=(9, 0.45 * len(rows) + 1.3))
    ax = fig.subplots()
    for row, qubit in enumerate(rows):
        ax.broken_barh([(0, total)], (row - 0.35, 0.7), color="#eef0f4")  # waiting: the background
        for kind, spans in busy[qubit].items():
            ax.broken_barh(spans, (row - 0.35, 0.7), color=BUSY_COLORS[kind])
    ax.set_yticks(range(len(rows)), [f"qubit {q}" for q in rows])
    ax.invert_yaxis()
    ax.set_xlim(0, total)
    ax.set_xlabel("time (µs)")
    handles = [Rectangle((0, 0), 1, 1, color=c) for c in BUSY_COLORS.values()]
    handles.append(Rectangle((0, 0), 1, 1, color="#eef0f4"))
    ax.legend(handles, list(BUSY_COLORS) + ["waiting"], loc="upper center", bbox_to_anchor=(0.5, -0.12 - 0.45 / len(rows)),
              ncol=4, frameon=False, fontsize=8)
    ax.set_title(f"Compiled {basis} circuit over time: {total:.3f} µs", fontsize=10)
    caption = (f"<p>The same {basis} schedule as Qiskit draws it: every gate by name, on every qubit, in the "
               "processor's time steps (dt). A run folder keeps this picture in <code>timeline/</code>.</p>")
    return img(fig) + caption + img(timeline_figure(view.compiled[basis], noise))


def show_parts(view: Compiled, *, step: bool = False, compiled: bool | Literal["all"] = False,
               timeline: bool | Literal["all"] = False) -> list[Part]:
    """The parts of show: header, graph and written circuit, then what compiling costs.

    step, compiled and timeline add the debug views, each folded until clicked; compiled="all" and
    timeline="all" draw all three basis circuits instead of ZZ alone.
    """
    processor = configs.load_processor(view.circuit_file.processor)
    parts = [_show_header(view, processor), written_part(view, processor), *_show_cost(view)]
    if step:
        parts.append(fold("Step-through of the written circuit (ideal, no noise)",
                          journey_html(view.circuit_file.circuit, view.circuit_file.processor, view.circuit_file.name)))
    if compiled:
        parts.append(fold("Compiled circuits", _compiled_html(view, draw_all=compiled == "all")))
    if timeline:
        bases = BASES if timeline == "all" else ("ZZ",)
        charts = list(dict.fromkeys(_timeline_html(view, basis) for basis in bases))  # one line when there are no durations
        parts.append(fold("Timelines of the compiled circuits" if timeline == "all" else "Timeline of the compiled ZZ circuit",
                          "".join(charts)))
    return parts
