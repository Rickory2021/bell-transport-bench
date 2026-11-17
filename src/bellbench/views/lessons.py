# src/bellbench/views/lessons.py
"""What the tutorial notebook's lessons display: algebra, and a state followed one gate at a time.

`algebra` shows lines of LaTeX; `tex` writes a vector or a matrix for it, and
`matrix_of` gives a circuit's unitary with qubit 0 first, the order the lessons
write in. `bloch_steps` and `state_steps` step through a circuit's ideal state,
on the Bloch sphere for one qubit and as outcome probabilities for more;
`journey` steps through a circuit on its processor graph. `ket` and `whole`
write a state and a whole-number expectation value for a lesson's own tables.

Each of these displays where it is called, through `emit`, so a lesson cell can
call one inside a loop. Outside a notebook they print text.
"""

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator, Statevector

from bellbench.views.base import emit, html, latex, markdown, png
from bellbench.views.stepper import bloch_vectors, journey_html, ket, stepper_part, steps_of

__all__ = ["algebra", "bloch_steps", "journey", "ket", "matrix_of", "state_steps", "tex", "whole"]


def _show_steps(frames: list[tuple[str, str]], notes: list[str], states: list[str], stop_note: str) -> None:
    """Show a stepper, then the note saying where a circuit's ideal state stopped being followed, when there is one."""
    emit([stepper_part(frames, notes=notes, states=states), *([markdown(stop_note)] if stop_note else [])])


def bloch_steps(circuit: QuantumCircuit, notes: list[str]) -> None:
    """One qubit's arrow on the Bloch sphere after each gate, one step at a time, with its ket and a note."""
    if circuit.num_qubits != 1:
        raise ValueError("the Bloch sphere draws one qubit; state_steps shows more")
    from qiskit.visualization import plot_bloch_vector  # loaded when a lesson draws a sphere, not with the package

    steps, stop_note = steps_of(circuit)
    frames = []
    for step in steps:
        fig = Figure(figsize=(2.8, 3.0))
        plot_bloch_vector(bloch_vectors(step.state)[0], ax=fig.add_subplot(1, 1, 1, projection="3d"))
        frames.append((step.label, png(fig)))
    _show_steps(frames, notes, [ket(step.state, [0]) for step in steps], stop_note)


def _probability_bars(state: Statevector, ax: Axes) -> None:
    """Each outcome's probability, the squared size of its amplitude, as a bar; outcomes are written qubit 0 first."""
    probabilities = state.probabilities()            # Qiskit's index holds qubit k as bit k
    width = state.num_qubits
    labels = ["".join(str((index >> qubit) & 1) for qubit in range(width)) for index in range(len(probabilities))]
    order = sorted(range(len(labels)), key=lambda index: labels[index])
    ax.bar([labels[index] for index in order], [probabilities[index] for index in order], color="#7139cc")
    for x, index in enumerate(order):
        if probabilities[index] > 0.005:
            ax.text(x, probabilities[index] + 0.03, f"{probabilities[index]:.0%}", ha="center", fontsize=8)
    ax.set_ylim(0, 1.18)
    ax.set_yticks([0, 0.5, 1], ["0", "50%", "100%"], fontsize=8)
    ax.set_xlabel("outcome, qubit 0 first", fontsize=8)
    ax.set_ylabel("probability", fontsize=8)


def state_steps(circuit: QuantumCircuit, notes: list[str]) -> None:
    """The state after each gate, one step at a time: its ket, each outcome's probability as a bar, and a note."""
    steps, stop_note = steps_of(circuit)
    frames = []
    for step in steps:
        fig = Figure(figsize=(3.6, 2.6))
        _probability_bars(step.state, fig.subplots())
        frames.append((step.label, png(fig)))
    _show_steps(frames, notes, [ket(step.state, list(range(circuit.num_qubits))) for step in steps], stop_note)


def journey(circuit: QuantumCircuit, processor_name: str, title: str) -> None:
    """The pair's journey through a written circuit: one graph frame at a time, its state and a note beside it.

    How to read the shading is explained once, in lesson 1.4 and in Part 2's reading guide, not in the output.
    """
    emit([html(journey_html(circuit, processor_name, title))])


def matrix_of(circuit: QuantumCircuit) -> np.ndarray:
    """The circuit's unitary matrix, rows and columns ordered with qubit 0 first; Operator(circuit) has it last."""
    return Operator(circuit).reverse_qargs().data


def _entry(z: complex) -> str:
    """One number as LaTeX: 0, 1 and i exactly, anything else to three figures."""
    z = complex(z)
    if abs(z) < 1e-9:
        return "0"
    for value, written in ((1, "1"), (-1, "-1"), (1j, "i"), (-1j, "-i")):
        if abs(z - value) < 1e-9:
            return written
    if abs(z.imag) < 1e-9:
        return f"{z.real:.3g}"
    if abs(z.real) < 1e-9:
        return f"{z.imag:.3g}i"
    return f"{z.real:.3g}{z.imag:+.3g}i"


def tex(array: np.ndarray) -> str:
    """A vector, as a column, or a matrix as LaTeX; a size every nonzero entry shares, such as 1/sqrt 2, goes in front."""
    values = np.asarray(array, dtype=complex)
    values = values.reshape(-1, 1) if values.ndim == 1 else values
    sizes = {round(abs(z), 9) for z in values.flat if abs(z) > 1e-9}
    factor, scale = "", 1.0
    if len(sizes) == 1 and abs(next(iter(sizes)) - 1) > 1e-9:
        scale = next(iter(sizes))
        count = round(1 / scale**2)
        if abs(1 / scale**2 - count) < 1e-6:
            root = round(count**0.5)
            factor = rf"\frac{{1}}{{{root}}}" if root * root == count else rf"\frac{{1}}{{\sqrt{{{count}}}}}"
        else:
            factor = f"{scale:.3g}"
    rows = r" \\ ".join(" & ".join(_entry(z / scale) for z in row) for row in values)
    return rf"{factor}\begin{{pmatrix}} {rows} \end{{pmatrix}}"


def algebra(*lines: str) -> None:
    """Show lines of LaTeX, one equation each."""
    emit([latex(line) for line in lines])


def whole(value: float) -> str:
    """An expectation value that is a whole number, written with a true minus sign: +1, 0 or −1."""
    return f"{round(value):+d}".replace("+0", "0").replace("-0", "0").replace("-", "−")
