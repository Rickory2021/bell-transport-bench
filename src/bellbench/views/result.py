# src/bellbench/views/result.py
"""One run's result, point first, in the order a reader checks it.

`result_parts` lays a Workbench result out as: a warning when the ideal run is
not F = 1 with every shot kept, and when routing left the pair off the ports;
one header line; the headline, F of the kept shots with its standard error at
the acceptance with its 95% Wilson interval, then F raw; a table per basis of
shots, kept shots and the match-minus-differ score over kept and all shots; the
shots each check flagged, when the circuit has checks; one cost line; a line
saying a profile without durations is gate noise alone; and how the
uncertainty was computed. F is never shown without its acceptance (README,
Science rules).

`ResultView` is what this layout and `compare` read from a result, fresh or
fetched. Every number is the result's own: its scores, its flags and its
record.
"""

from dataclasses import dataclass

from qiskit import QuantumCircuit, qasm3

from bellbench import configs
from bellbench.analysis import check_flags
from bellbench.run import Score
from bellbench.views.base import Part, markdown, table

BASES = ("ZZ", "XX", "YY")  # the order every view lists the bases in


@dataclass(frozen=True)
class ResultView:
    """What the result layout and compare need from one Workbench result, fresh or fetched."""

    label: str                                  # how tables and figures name the run
    name: str                                   # the circuit file
    processor: str
    noise: str
    noise_record: dict                          # NoiseControl's part of a run record: profile, scale, overrides, channels
    shots: int                                  # per basis, per simulation
    origin: str
    cost: dict                                  # the keys pipeline.cost returns
    duration_s: float | None
    compiled_zz: QuantumCircuit
    analysis: dict                              # the circuit file's {name, settings}
    layout: list[tuple[str, int]]               # each classical register and its size; the port register last
    raw: dict[str, dict[str, dict[str, int]]]   # simulation -> basis -> count key -> count
    scores: dict[str, Score]                    # "ideal" and "noisy"


def result_view(result) -> ResultView:
    """What the views read from one Workbench result: its record, its raw counts and the scores it holds."""
    record = result.record
    name = configs.name_from_record(record["circuit"], "circuit")
    fresh = result.run is not None
    return ResultView(
        label=f"{name} ({'now' if fresh else 'fetched'})", name=name,
        processor=configs.name_from_record(record["noise_control"]["processor"], "processor"),
        noise=configs.name_from_record(record["noise_control"]["noise"], "noise"),
        noise_record=record["noise_control"], shots=record["shots"],
        origin=f"run now, base seed {record['base_seed']}" if fresh else "fetched from a run folder",
        cost=record["cost"], duration_s=record["scheduled_duration"],
        compiled_zz=qasm3.loads(record["compiled"]["ZZ"]), analysis=result.analysis,
        layout=result.registers, raw=result.raw, scores=result.scores)


def _flags(view: ResultView) -> list[dict]:
    """How many noisy shots each check flagged, per basis, counted by the package's analysis.check_flags."""
    flagged = check_flags(view.analysis, view.raw["noisy"], view.layout)
    return [{"check": check} | {basis: f"{counts[basis]} ({counts[basis] / view.shots:.1%})" for basis in BASES}
            for check, counts in flagged.items()]


def _signed(value: float) -> str:
    """A score with its sign, using a true minus sign."""
    return f"{value:+.4f}".replace("-", "−")


def result_parts(source) -> list[Part]:
    """One run's result, point first: warnings, the headline, each basis, what each check flagged, then the cost."""
    view = result_view(source)
    parts: list[Part] = []
    noisy, ideal = view.scores["noisy"], view.scores["ideal"]
    perfect = ideal.accepted.value == 1 and ideal.acceptance == 1
    if not perfect:
        parts.append(markdown(f"**Warning: the ideal run is not perfect: F = {ideal.accepted.value:.4f}, "
                         f"{ideal.acceptance:.1%} of shots kept. The circuit or its reading is wrong; noise is not "
                         "the cause.**"))
    if not view.cost["pair_on_ports"]:
        parts.append(markdown("**Warning: after routing the pair is not on the ports.**"))
    parts.append(markdown(f"**{view.name}** under {view.noise} · {view.shots:,} shots per basis · {view.origin}"))
    if noisy.acceptance < 1:
        low, high = noisy.interval
        headline = (f"**F = {noisy.accepted.value:.4f} ± {noisy.accepted.standard_error:.4f} at acceptance "
                    f"{noisy.acceptance:.4f}** ({low:.4f} to {high:.4f}) · F raw = {noisy.raw.value:.4f} ± "
                    f"{noisy.raw.standard_error:.4f}")
    else:
        headline = f"**F = {noisy.accepted.value:.4f} ± {noisy.accepted.standard_error:.4f}**, every shot kept"
    parts.append(markdown(headline + (" · ideal run: F = 1, every shot kept ✓" if perfect else "")))
    parts.append(table([{"basis": basis, "shots": noisy.raw_shots[basis], "kept": noisy.accepted_shots[basis],
                     "match − differ, kept shots": _signed(noisy.accepted.correlators[basis].value),
                     "match − differ, all shots": _signed(noisy.raw.correlators[basis].value)} for basis in BASES]))
    if any(register != "port" for register, _ in view.layout):
        parts.append(markdown("Shots each check flagged, noisy run:"))
        parts.append(table(_flags(view)))
    gates = ", ".join(f"{gate} {count}" for gate, count in view.compiled_zz.count_ops().items())
    duration = f"{view.duration_s * 1e6:.3f} µs" if view.duration_s is not None else "not scheduled"
    parts.append(markdown(f"Cost: {view.cost['two_qubit_gates']} two-qubit gates · depth {view.cost['depth']} · "
                     f"{len(view.cost['qubits_used'])} qubits · {duration} · {3 * view.shots:,} shots per simulation · "
                     f"compiled ZZ: {gates}"))
    kind = configs.load_noise(view.noise)["kind"]
    if kind != "snapshot":
        parts.append(markdown(f"{view.noise} is a {kind} profile: gate noise alone, with no idle or timing noise."))
    parts.append(markdown("± is one standard error, binomial per basis; the acceptance interval is a 95% Wilson interval."))
    return parts
