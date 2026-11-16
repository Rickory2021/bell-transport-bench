# src/bellbench/views/stepper.py
"""A step-through of a written circuit: its ideal state after each gate, shown one step at a time.

`steps_of` follows a circuit gate by gate with one state vector, without noise.
`stepper_html` shows a list of frames like slides: a label per step to jump to,
Back and Next, and the arrow keys, never playing on its own; beside each frame
are the state after that step as a ket and a one-line note. `journey_html` is
the stepper of a circuit on its processor graph, which `show` folds into its
output and the tutorial shows on its own.

States are kets read qubit 0 first, left to right. Qiskit's bit strings and
matrices put qubit 0 last, so `ket` reorders them.
"""

import uuid
from html import escape
from typing import NamedTuple

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from qiskit import QuantumCircuit
from qiskit.quantum_info import Pauli, Statevector

from bellbench import configs
from bellbench.figures import draw_processor, processor_layout
from bellbench.views.base import Part, png

GATE_COLOR = "#e07b00"  # the gate just applied, in a step-through


PAULIS = {name: Pauli(name) for name in "XYZ"}


Position = tuple[float, float]  # a qubit's drawing coordinates on its processor graph


# -- The ideal state after each gate ----------------------------------------------------------


class Step(NamedTuple):
    """One gate of a step-through, and the ideal state after it."""

    label: str                 # such as "cx 0→1"
    qubits: tuple[int, ...]    # the qubits the gate acts on; empty for the starting state
    state: Statevector         # the whole register's state after the gate, without noise


def steps_of(circuit: QuantumCircuit) -> tuple[list[Step], str]:
    """The written circuit's gates one by one, and a note when the step-through stops early.

    The final measurements are left out. A measurement or reset before the end stops the
    step-through there, since a single state vector cannot follow a measured qubit.
    """
    unmeasured = circuit.remove_final_measurements(inplace=False)
    state = Statevector.from_label("0" * unmeasured.num_qubits)
    steps = [Step("start: every qubit in |0⟩", (), state)]
    for instruction in unmeasured.data:
        name = instruction.operation.name
        if name == "barrier":
            continue
        qubits = tuple(unmeasured.find_bit(q).index for q in instruction.qubits)
        if name in ("measure", "reset"):
            return steps, f"The step-through stops at a {name} on qubit {qubits[0]}, before the end of the circuit."
        state = state.evolve(instruction.operation, list(qubits))
        arrow = "↔" if name == "swap" else "→"
        label = f"{name} on {qubits[0]}" if len(qubits) == 1 else f"{name} {qubits[0]}{arrow}{qubits[1]}"
        steps.append(Step(label, qubits, state))
    return steps, ""


def bloch_vectors(state: Statevector) -> np.ndarray:
    """Each qubit's own Bloch vector (⟨X⟩, ⟨Y⟩, ⟨Z⟩), one row per qubit.

    A row's length is 1 when reading that qubit alone gives a certain result along some axis, and 0 when
    every reading of it alone is a coin flip.
    """
    return np.array([[state.expectation_value(PAULIS[axis], [qubit]).real for axis in "XYZ"]
                     for qubit in range(state.num_qubits)])


def ket(state: Statevector, qubits: list[int]) -> str:
    """The state written as a ket over `qubits`, left to right in that order, such as (|00> + |11>)/sqrt 2.

    Every other qubit must be in |0> in every term, as an untouched qubit is. A global phase changes no
    measurement, so the first term is written with a positive coefficient. Equal-weight terms share one
    factor; anything else is written term by term.
    """
    amplitudes = state.data
    nonzero = [i for i in range(len(amplitudes)) if abs(amplitudes[i]) > 1e-9]
    others = sum(1 << q for q in range(state.num_qubits) if q not in qubits)
    if any(i & others for i in nonzero):
        raise ValueError("a qubit outside the ones written is not in |0>")
    phase = amplitudes[nonzero[0]] / abs(amplitudes[nonzero[0]])
    terms = sorted(("".join(str((i >> q) & 1) for q in qubits), amplitudes[i] / phase) for i in nonzero)
    weights = {round(abs(c) ** 2, 9) for _, c in terms}
    if len(weights) == 1:
        count = round(1 / weights.pop())
        signs = {1: "+", -1: "−", 1j: "+ i", -1j: "− i"}
        parts = []
        for k, (label, c) in enumerate(terms):
            unit = complex(round((c / abs(c)).real), round((c / abs(c)).imag))
            if unit not in signs:
                break
            sign = signs[unit]
            parts.append(f"|{label}⟩" if k == 0 and sign == "+" else f"{sign} |{label}⟩")
        else:
            body = " ".join(parts).replace("+ i |", "+ i|").replace("− i |", "− i|")
            if count == 1:
                return body
            root = int(round(count ** 0.5))
            factor = str(root) if root * root == count else f"√{count}"
            return f"({body})/{factor}"
    return " + ".join(f"({c.real:.3f}{c.imag:+.3f}i)|{label}⟩" for label, c in terms)


def factor_notes(steps: list[Step]) -> list[str]:
    """One sentence per step saying which qubits joined or left an entangled state.

    A qubit factors out of the rest exactly when its own state is pure, which is when its Bloch vector has length 1.
    """
    notes = ["Every qubit starts in |0⟩, on its own."]
    for before, after in zip(steps, steps[1:]):
        old = np.linalg.norm(bloch_vectors(before.state), axis=1)
        new = np.linalg.norm(bloch_vectors(after.state), axis=1)
        changes = []
        for qubit in range(len(new)):
            a, b = round(float(old[qubit]), 2), round(float(new[qubit]), 2)
            if a == b:
                continue
            if b == 1:
                changes.append(f"qubit {qubit} factors out again, on its own")
            elif a == 1:
                changes.append(f"qubit {qubit} joins an entangled state")
            else:
                changes.append(f"qubit {qubit} stays entangled, with a different share")
        notes.append("; ".join(changes).capitalize() + "." if changes else
                     "No qubit joins or leaves an entangled state.")
    return notes


# -- The stepper ------------------------------------------------------------------------------

_STEPPER_SCRIPT = """<script>(function () {
  var id = "%s", here = document.currentScript;
  var root = document.getElementById(id);
  if (!root && here) {
    var scope = here.parentNode || (here.getRootNode && here.getRootNode());
    root = scope && scope.querySelector ? scope.querySelector("#" + id) : null;
  }
  if (!root) return;
  var holder = root.querySelector(".rows"), later = root.querySelector(".static");
  if (later) {
    later.querySelectorAll("[data-row]").forEach(function (row) { holder.appendChild(row); });
    later.remove();
  }
  var rows = root.querySelectorAll("[data-row]");
  var chips = root.querySelectorAll("button[data-step]"), count = root.querySelector(".count"), current = 0;
  function go(n) {
    current = Math.max(0, Math.min(rows.length - 1, n));
    rows.forEach(function (el, k) { el.style.display = k === current ? "" : "none"; });
    chips.forEach(function (chip, k) {
      chip.style.fontWeight = k === current ? "700" : "400";
      chip.style.outline = k === current ? "2px solid #e07b00" : "";
    });
    count.textContent = (current + 1) + " / " + rows.length;
  }
  chips.forEach(function (chip) { chip.addEventListener("click", function () { go(+chip.dataset.step); }); });
  root.querySelector(".back").addEventListener("click", function () { go(current - 1); });
  root.querySelector(".next").addEventListener("click", function () { go(current + 1); });
  root.addEventListener("keydown", function (e) {
    if (e.key === "ArrowRight") { go(current + 1); e.preventDefault(); }
    if (e.key === "ArrowLeft") { go(current - 1); e.preventDefault(); }
  });
  root.querySelector(".controls").style.display = "";
  go(0);
})();</script>"""


def stepper_html(frames: list[tuple[str, str]], *, notes: list[str] | None = None, states: list[str] | None = None) -> str:
    """Show frames one at a time, like slides: a label per step to jump to, Back and Next, and the arrow keys.

    `frames` holds (label, base64 PNG) pairs; `notes`, when given, one sentence per frame shown beside it;
    and `states`, one ket per frame, shown above its note in a fixed-width font so the digits line up. The
    two columns stack on a narrow screen. Where JavaScript does not run (GitHub, or a JupyterLab notebook
    not yet trusted), the controls stay hidden and the first step shows, with every later step folded below
    it; where it runs, the fold is emptied into the stepper and removed. The script finds its stepper from
    its own place in the page, so it works where the output is not yet in the document. The buttons are
    text, so the stepper needs no network.
    """
    uid = f"stepper-{uuid.uuid4().hex[:8]}"

    def row(k: int) -> str:
        label, png = frames[k]
        image = f'<img alt="{escape(label)}" src="data:image/png;base64,{png}" style="max-width:100%">'
        if not notes:
            return f'<div data-row="{k}">{image}</div>'
        state = (f'<div style="font-family:monospace;margin:0.3em 0">'  # wraps between terms, never inside a ket
                 f'{escape(states[k]).replace("|", "&#8288;|")}</div>') if states else ""
        return (f'<div data-row="{k}"><div style="display:flex;flex-wrap:wrap;gap:1.2em;align-items:center;margin:0.4em 0">'
                f'<div style="flex:0 1 auto;max-width:100%">{image}</div>'
                f'<div style="flex:1 1 16em;max-width:34em;line-height:1.5"><b>{escape(label)}</b>{state}'
                f'<p style="margin:0">{escape(notes[k])}</p></div></div></div>')

    chips = "".join(f'<button type="button" data-step="{k}" style="margin:2px">{escape(label)}</button>'
                    for k, (label, _) in enumerate(frames))
    later = "".join(row(k) for k in range(1, len(frames)))
    fallback = (f'<details class="static"><summary>Every later step (static view)</summary>{later}</details>'
                if later else "")
    controls = ('<div class="controls" style="display:none">'
                '<div><button type="button" class="back">‹ Back</button> '
                '<span class="count" style="margin:0 0.6em"></span>'
                '<button type="button" class="next">Next ›</button>'
                ' <span style="opacity:0.7">or the arrow keys, after a click here</span></div>'
                f'<div style="margin:0.3em 0">{chips}</div></div>')
    return f'<div id="{uid}" tabindex="0">{controls}<div class="rows">{row(0)}</div>{fallback}</div>' + _STEPPER_SCRIPT % uid


def stepper_part(frames: list[tuple[str, str]], *, notes: list[str] | None = None,
                 states: list[str] | None = None) -> Part:
    """`stepper_html` as a view's part; a viewer that cannot show HTML shows the first frame instead."""
    return Part("stepper", stepper_html(frames, notes=notes, states=states), frames[0][1])


# -- A circuit's journey on its processor graph ------------------------------------------------


def _journey_frame(ax: Axes, processor: dict, layout: dict[int, Position], step: Step) -> None:
    """One step on the processor graph: each qubit shaded by how far its own arrow has shrunk, the gate in orange."""
    ax.clear()
    draw_processor(ax, processor)
    shrink = 1 - np.linalg.norm(bloch_vectors(step.state), axis=1)  # 0: predictable alone; 1: a coin flip alone
    xs, ys = zip(*(layout[qubit] for qubit in range(len(shrink))))
    ax.scatter(xs, ys, s=260, c=shrink, cmap="Purples", vmin=0, vmax=1, edgecolors="#4a5568", zorder=4)
    for qubit, (x, y) in layout.items():
        ax.text(x, y, str(qubit), ha="center", va="center", fontsize=7, zorder=6,
                color="white" if shrink[qubit] > 0.55 else "#1f2937")
    if len(step.qubits) == 2:
        ax.plot(*zip(layout[step.qubits[0]], layout[step.qubits[1]]), color=GATE_COLOR, lw=5, zorder=2.5)
    elif len(step.qubits) == 1:
        ax.scatter(*layout[step.qubits[0]], s=560, facecolors="none", edgecolors=GATE_COLOR, linewidths=2.5, zorder=5)
    ax.set_title("")  # the stepper names the step; the processor's caption would repeat on every frame


def journey_html(circuit: QuantumCircuit, processor_name: str, title: str) -> str:
    """The pair's journey through a written circuit as HTML: a stepper of graph frames, each with its state and a note."""
    processor = configs.load_processor(processor_name)
    layout = processor_layout(processor, configs.processor_graph(processor))
    steps, stop_note = steps_of(circuit)
    qubits = sorted({q for step in steps for q in step.qubits})
    frames = []
    for step in steps:
        fig = Figure(figsize=(4.4, 4.6))
        ax = fig.subplots()
        _journey_frame(ax, processor, layout, step)
        frames.append((step.label, png(fig)))
    header = (f"<p><b>{escape(title)}</b> · {len(steps) - 1} gates · states on qubits {', '.join(map(str, qubits))}, "
              "read left to right; every other qubit stays in |0⟩</p>")
    page = stepper_html(frames, notes=factor_notes(steps), states=[ket(step.state, qubits) for step in steps])
    return header + page + (f"<p>{escape(stop_note)}</p>" if stop_note else "")
