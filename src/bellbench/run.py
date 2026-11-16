# src/bellbench/run.py
"""CircuitRun: one circuit file under one noise profile, simulated ideal and noisy, written as a run folder.

A run (docs/DESIGN.md, section 5) reads its circuit file and builds a
NoiseControl for the circuit's processor, then compiles the three basis
circuits once under its transpiler seed, takes the cost before scheduling,
schedules, simulates ideal and noisy, and reads the shots with the analysis the
circuit file names (src/bellbench/analysis.py), which returns the port counts
over all shots and over the shots kept. Every number after that is computed
here the same way for every strategy: F raw from all shots, F from the kept
ones, the acceptance and its Wilson interval, and the shots per basis.

A run stops before simulating when, in any compiled basis circuit, a qubit is
reset, or is measured and then acted on again, while the matching conditional
channel is unset, so neither is ever silently perfect (docs/DESIGN.md, section
4). A measurement with nothing after it on its qubit is final: its error is the
readout error every measurement gets, so it needs no channel. The rule is
judged on the compiled circuits, since a SWAP the router adds through a
measured qubit makes its measurement mid-circuit.

`write` makes the run folder: <root>/runs/workbench/<circuit>/<noise>/<stamp>/
for a run made on its own, or the folder a benchmark names for each of its runs.
<root> is results/ for a run made from committed code and config, workspace/
otherwise, as for a run of a trial circuit, which git does not track (configs.py).
The git state is read when `run` starts, so the record describes the
tree the numbers came from, and a write after a later commit still lands in
workspace/. A run folder holds bp.data.result.yaml, the settings and records,
checked against config/bp.schema.result.yaml; simulations.csv, one row of
numbers per simulation; and counts.csv, every outcome as the key Qiskit writes,
one bit string per register in reverse of the record's register order. Seeds derive from
the run's labels, never from its folder name, so a remade run repeats them.

`rerun` rebuilds a run from its folder with the recorded seeds and compares:
`make run RUN=<path>` (docs/DESIGN.md, section 5).
`write_views` draws a run folder's diagrams and report.md from its files, so the
views can be remade at any time (D-74): `make report RUN=<path>`.
`run_benchmark` makes every run a benchmark file lists, checks the core
benchmark's self-test, and writes a new folder,
<root>/runs/benchmark/<name>/<stamp>/, holding each run in a folder named by its
run id, the run list bp.data.runs.yaml (checked against
config/bp.schema.runs.yaml), comparison.csv and report.md:
`make benchmark NAME=<name>`. A remake never changes or deletes an earlier
folder, and `current_benchmark` finds the latest.
"""

import csv
import datetime
import math
import platform
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import yaml
from qiskit import qasm3

from bellbench import configs
from bellbench.analysis import PortCounts, read_shots
from bellbench.circuits import circuit_to_qasm, load_circuit
from bellbench.fidelity import BASES, REJECTION_METHOD, fidelity_from_counts, infidelity_removed_per_rejection
from bellbench.noise import STARTING_LABEL, NoiseControl
from bellbench.pipeline import (
    basis_circuits,
    compile_bases,
    cost,
    derive_seed,
    mark_mid_circuit_measurements,
    mark_starting_excitation,
    mid_circuit_measurements,
    schedule,
    scheduled_duration,
    simulate,
)

RESULT_FORMAT = 2  # 1: OpenQASM 2 and a counts.csv column per role; 2: OpenQASM 3 and the full outcome key
RESULT_FILE = "bp.data.result.yaml"
SIMULATIONS = ("ideal", "noisy")
DIAGRAMS = ("lean", "full")
PACKAGES = ("qiskit", "qiskit-aer", "qiskit-ibm-runtime", "qiskit-qasm3-import", "numpy")
WILSON_Z = 1.959963984540054  # a 95% interval
STAMP = "%Y%m%dT%H%M%SZ"  # the UTC time that names run and benchmark folders

# The CSV contract: the columns of each CSV a run or benchmark writes, in order.
# The writers take their headers from here and nowhere else, and the workbench
# and the submission notebook read these names, so a column is added only when
# the value it holds is built, and never renamed in place. counts.csv's outcome
# is the key Qiskit writes: one bit string per register, separated by spaces,
# the last register first, and inside each string the highest bit first, so the
# port register's string ends with the first port's bit. `read_table` reads any
# of the three with its text columns kept as text. A folder written before a
# column was added is never edited, so its table lacks that column and still
# reads: ADDED_COLUMNS lists each such column, and a reader selects by name.
SIMULATION_COLUMNS = (
    "simulation",
    "fidelity", "fidelity_se", "fidelity_raw", "fidelity_raw_se", "se_method",
    *(f"corr_{b}" for b in BASES),
    "acceptance", "acceptance_low", "acceptance_high",
    *(f"shots_{kind}_{b}" for b in BASES for kind in ("raw", "accepted")),
)
COUNT_COLUMNS = ("simulation", "basis", "outcome", "count")
TEXT_COLUMNS = ("simulation", "se_method", "basis", "outcome", "run", "circuit", "processor", "noise")
COMPARISON_COLUMNS = (
    "case", "run", "circuit", "processor", "noise", "scale", "overrides",
    *SIMULATION_COLUMNS,
    "swaps", "router_swaps", "two_qubit_gates", "depth", "qubits_used", "scheduled_duration", "shots_total",
    "two_qubit_gates_per_accepted_pair",
    "infidelity_removed_per_rejection", "infidelity_removed_per_rejection_se",
)
# The columns each CSV gained after folders holding it were committed, in the order they were added. A table
# written before one of them was added has the declared columns without it and without every later one.
ADDED_COLUMNS = {"comparison.csv": ("shots_total",)}


class CircuitRun:
    """One run: a circuit file under a noise profile, with its scale, overrides and conditional channels.

    `shots` (per basis circuit, in each simulation) and `base_seed` have no
    default: the caller states both, as a benchmark file or the workbench does, so
    every seed a run uses traces to a value written down.
    """

    def __init__(
        self,
        circuit: str,
        noise: str,
        shots: int,
        base_seed: int,
        scale: float = 1.0,
        overrides=(),
        conditional=None,
        diagrams: str = "lean",
    ):
        if isinstance(shots, bool) or not isinstance(shots, int) or shots < 1:
            raise ValueError(f"shots must be a positive integer; got {shots!r}")
        if diagrams not in DIAGRAMS:
            raise ValueError(f"diagrams is one of {', '.join(DIAGRAMS)}; got {diagrams!r}")
        self.circuit = load_circuit(circuit)
        self.nc = NoiseControl(self.circuit.processor, noise, scale, overrides, conditional)
        self.shots, self.base_seed, self.diagrams = shots, base_seed, diagrams
        self.labels = (circuit, noise, repr(self.nc.scale), self.settings_hash or "none")
        self.seeds = {step: derive_seed(base_seed, *self.labels, step) for step in ("transpile", *SIMULATIONS)}
        self.derived_seeds = dict(self.seeds)  # what the labels give; from_yaml may run with recorded seeds instead
        self.compiled = self.cost = self.duration = self.git_state = None
        self.simulations, self.scores = {}, {}

    @property
    def settings_hash(self) -> str | None:
        """8 hex digits of the overrides and conditional channels, or None when neither is set."""
        export = self.nc.export_as_yaml()
        if not export["overrides"] and not any(v is not None for v in export["conditional"].values()):
            return None
        return configs.hash_data({"overrides": export["overrides"], "conditional": export["conditional"]})[7:15]

    # -- Running ---------------------------------------------------------------

    def run(self, methods: dict[str, str] | None = None) -> "CircuitRun":
        """Compile, cost, schedule, simulate ideal and noisy, and read the shots; `methods` repeats a recorded run's.

        The commit and whether src/ or config/ has uncommitted changes are read
        first, so they describe the code and config the numbers came from.
        """
        self.git_state = _git_state()
        circuits = basis_circuits(self.circuit.circuit, self.nc.ports)
        self.compiled = compile_bases(circuits, self.nc, self.seeds["transpile"])
        _check_conditional_channels(self.circuit.name, self.compiled, self.nc)
        self.cost = cost(self.compiled, self.nc.ports)
        scheduled = {basis: schedule(c.compiled, self.nc) for basis, c in self.compiled.items()}
        self.duration = scheduled_duration(scheduled["ZZ"], self.nc)
        if self.nc.conditional["mid_circuit_measurement_error"] is not None:
            scheduled = {basis: mark_mid_circuit_measurements(c) for basis, c in scheduled.items()}
        if self.nc.conditional["starting_excitation"] is not None:
            scheduled = {basis: mark_starting_excitation(c) for basis, c in scheduled.items()}
            _check_starting_marker(self.circuit.name, scheduled, self.nc)
        for name, noise_model in (("ideal", None), ("noisy", self.nc.noise_model)):
            method = (methods or {}).get(name, "automatic")
            sim = simulate(scheduled, noise_model, self.shots, self.seeds[name], method)
            self.simulations[name] = sim
            self.scores[name] = Score(read_shots(self.circuit.analysis, sim.raw, self.layout, self.shots))
        return self

    @property
    def registers(self) -> list[str]:
        """The compiled circuits' classical registers, in order; the port register is last."""
        return [name for name, _ in self.layout]

    @property
    def layout(self) -> list[tuple[str, int]]:
        """Each of the compiled circuits' classical registers with its size, in order; the port register is last."""
        return [(r.name, r.size) for r in self.compiled["ZZ"].compiled.cregs]

    # -- Records -----------------------------------------------------------------

    def export_as_yaml(self) -> dict:
        """The run's settings and records, as bp.data.result.yaml holds them."""
        if not self.simulations:
            raise RuntimeError("the run has not run yet; call run() first")
        commit, uncommitted = self.git_state
        return {
            "result_format": RESULT_FORMAT,
            "circuit": dict(self.circuit.record),
            "noise_control": self.nc.export_as_yaml(),
            "shots": self.shots,
            "base_seed": self.base_seed,
            "seeds": dict(self.seeds),
            "diagrams": self.diagrams,
            "registers": self.registers,
            "written": circuit_to_qasm(self.circuit.circuit),
            "compiled": {basis: circuit_to_qasm(c.compiled) for basis, c in self.compiled.items()},
            "cost": self.cost,
            "scheduled_duration": self.duration,
            "simulations": {name: self._simulation_record(name) for name in self.simulations},
            "provenance": {
                "commit": commit,
                "uncommitted": uncommitted,
                "packages": {"python": platform.python_version(), **{p: version(p) for p in PACKAGES}},
            },
        }

    def _simulation_record(self, name: str) -> dict:
        """Aer's seeds and methods for one simulation, and `empty_bases`, the bases that kept no shot, when any."""
        sim = self.simulations[name]
        record = {"seeds": dict(sim.seeds), "methods": dict(sim.methods)}
        empty = [b for b in BASES if self.scores[name].accepted_shots[b] == 0]
        if empty:
            record["empty_bases"] = empty
        return record

    @classmethod
    def from_yaml(cls, record: dict) -> "CircuitRun":
        """Rebuild a run from its record; refuses a referenced file whose content changed since.

        Each file's hash is compared before the build and again after it. The run
        uses the recorded seeds; `derived_seeds` keeps what its labels give now, so
        a rerun can report a derivation that changed.
        """
        configs.check_config("result", record, "the run record")
        _check_result_format(record)
        circuit = configs.name_from_record(record["circuit"], "circuit")
        configs.check_file_unchanged(record["circuit"])
        nc_record = record["noise_control"]
        _, noise, scale, overrides, conditional = NoiseControl.args_from_record(nc_record)
        shots, base_seed, diagrams = record["shots"], record["base_seed"], record["diagrams"]
        run = cls(circuit, noise, shots, base_seed, scale, overrides, conditional, diagrams)
        configs.check_unchanged(record["circuit"], run.circuit.record)
        run.nc.check_record(nc_record)
        run.derived_seeds, run.seeds = run.seeds, dict(record["seeds"])
        return run

    # -- Writing -------------------------------------------------------------------

    def write(self, root: Path | None = None, folder: Path | None = None) -> Path:
        """Write the run folder and return it.

        By default the folder is <root>/runs/workbench/<circuit>/<noise>/<stamp>/,
        with `root` results/ only when the git state was clean and every file the
        run used is in config/, and workspace/ otherwise, as for a trial circuit. A benchmark
        passes `folder` instead, which must not exist yet. A circuit, processor or
        noise file that changed since the run was built is refused before the
        folder is made, so a refused write leaves no folder.
        """
        record = self.export_as_yaml()
        configs.check_config("result", record, "the run record")
        if folder is None:
            if root is None:
                kept = not record["provenance"]["uncommitted"] and not _uses_files_outside_config(record)
                root = configs.ROOT / ("results" if kept else "workspace")
            stamp = _stamp()
            if self.nc.scale != 1:
                stamp += f"-x{self.nc.scale:g}"
            if self.settings_hash:
                stamp += f"-{self.settings_hash}"
            folder = Path(root) / "runs" / "workbench" / self.circuit.name / self.nc.noise_name / stamp
        elif root is not None:
            raise ValueError("write takes a root or a folder, not both")
        folder = Path(folder)
        _check_recorded_files(record)  # before the folder exists, so a refusal leaves nothing behind
        folder.mkdir(parents=True, exist_ok=False)
        (folder / RESULT_FILE).write_text(yaml.dump(record, Dumper=configs.Dumper, sort_keys=False), encoding="utf-8")
        _write_csv(folder / "simulations.csv", self.simulation_rows(), SIMULATION_COLUMNS)
        _write_csv(folder / "counts.csv", self.count_rows(), COUNT_COLUMNS)
        write_views(folder)
        return folder

    def simulation_rows(self) -> list[dict]:
        """One row of numbers per simulation, as simulations.csv holds them."""
        return [self.scores[name].row(name) for name in SIMULATIONS]

    def count_rows(self) -> list[dict]:
        """Every outcome of every basis circuit, keyed as Qiskit writes it: one bit string per register, last first."""
        return [
            {"simulation": name, "basis": basis, "outcome": key, "count": n}
            for name in SIMULATIONS
            for basis in BASES
            for key, n in self.simulations[name].raw[basis].items()
        ]


# -- Score ---------------------------------------------------------------------------


class Score:
    """One simulation's port counts, scored: F over all shots and over kept ones, the acceptance and its interval."""

    def __init__(self, ports: PortCounts):
        self.raw = fidelity_from_counts(ports.all)
        self.accepted = fidelity_from_counts(ports.kept)
        self.raw_shots = {b: sum(ports.all[b].values()) for b in BASES}
        self.accepted_shots = {b: sum(ports.kept[b].values()) for b in BASES}
        kept, total = sum(self.accepted_shots.values()), sum(self.raw_shots.values())
        self.acceptance = kept / total
        self.interval = wilson_interval(kept, total)
        self.removed_per_rejection = infidelity_removed_per_rejection(ports.all, ports.kept)

    def row(self, simulation: str) -> dict:
        row = {
            "simulation": simulation,
            "fidelity": self.accepted.value,
            "fidelity_se": self.accepted.standard_error,
            "fidelity_raw": self.raw.value,
            "fidelity_raw_se": self.raw.standard_error,
            "se_method": self.accepted.method,
            **{f"corr_{b}": self.accepted.correlators[b].value for b in BASES},
            "acceptance": self.acceptance,
            "acceptance_low": self.interval[0],
            "acceptance_high": self.interval[1],
        }
        for b in BASES:
            row[f"shots_raw_{b}"] = self.raw_shots[b]
            row[f"shots_accepted_{b}"] = self.accepted_shots[b]
        return row


def wilson_interval(kept: int, total: int, z: float = WILSON_Z) -> tuple[float, float]:
    """The Wilson score interval for a fraction kept/total, which stays between 0 and 1."""
    if total == 0:
        return (math.nan, math.nan)
    p = kept / total
    centre = (p + z**2 / (2 * total)) / (1 + z**2 / total)
    half = z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / (1 + z**2 / total)
    return (max(0.0, centre - half), min(1.0, centre + half))


# -- Rerun ---------------------------------------------------------------------------

REFUSED, MATCH, DIFFER = 2, 0, 1


def rerun(path: Path) -> tuple[int, list[str]]:
    """Rebuild the run at `path` (its folder or its result file), compare, and return the exit code and lines.

    It runs with the recorded seeds and simulator methods, and compares the
    circuits, the cost, the scheduled duration, the seeds and methods Aer
    reported for each basis, the counts and the numbers. 2 when the path holds
    no run record or a referenced file changed, 1 when any of those differs, 0
    when they all match; a different commit, package version or seed derivation
    is reported either way without changing the code. Nothing is written into the run
    folder. `make run` exits 2 whenever this returns 1 or 2, as make does for any
    failed recipe; the printed lines say which.
    """
    folder = Path(path)
    folder = folder.parent if folder.name == RESULT_FILE else folder
    if not (folder / RESULT_FILE).is_file():
        return REFUSED, [f"refused: {folder / RESULT_FILE} does not exist; give a run folder or its {RESULT_FILE}"]
    record = yaml.safe_load((folder / RESULT_FILE).read_text(encoding="utf-8"))
    try:
        run = CircuitRun.from_yaml(record)
    except (ValueError, FileNotFoundError) as e:
        return REFUSED, [f"refused: {e}"]
    methods = {}
    for name in SIMULATIONS:
        recorded = set(record["simulations"][name]["methods"].values())
        methods[name] = recorded.pop() if len(recorded) == 1 else "automatic"
    new = run.run(methods).export_as_yaml()
    lines, differ = [], False

    def compare(what, old, now, counts=True):
        nonlocal differ
        same = old == now
        lines.append(f"{'same' if same else 'DIFFERS'}: {what}")
        differ |= counts and not same

    compare("written circuit", record["written"], new["written"])
    for basis in BASES:
        compare(f"compiled {basis} circuit", record["compiled"][basis], new["compiled"][basis])
    compare("cost", record["cost"], new["cost"])
    compare("scheduled duration", record["scheduled_duration"], new["scheduled_duration"])
    compare("simulator seeds and methods", record["simulations"], new["simulations"])
    compare("counts", _read_csv(folder / "counts.csv"), _stringify(run.count_rows()))
    compare("simulations", _read_csv(folder / "simulations.csv"), _stringify(run.simulation_rows()))
    compare("seeds the labels derive now", record["seeds"], run.derived_seeds, counts=False)
    compare("commit", record["provenance"]["commit"], new["provenance"]["commit"], counts=False)
    compare("package versions", record["provenance"]["packages"], new["provenance"]["packages"], counts=False)
    return (DIFFER if differ else MATCH), lines


# -- Views ----------------------------------------------------------------------------

def _uses_files_outside_config(record: dict) -> bool:
    """Whether the run used a file outside config/, such as a trial circuit, which git does not track."""
    nc = record["noise_control"]
    paths = (record["circuit"]["path"], nc["processor"]["path"], nc["noise"]["path"])
    return any(not path.startswith("config/") for path in paths)


def _check_recorded_files(record: dict) -> None:
    """Refuse a circuit, processor or noise file that a run record names and that changed since the run."""
    configs.name_from_record(record["circuit"], "circuit")
    configs.check_file_unchanged(record["circuit"])
    NoiseControl.args_from_record(record["noise_control"])


def write_views(folder: Path) -> list[Path]:
    """Draw a run folder's diagrams and report.md from its record and numbers; returns the files written.

    lean: the processor graph with its ports and the couplers the compiled ZZ
    circuit uses, and the compiled ZZ circuit. full adds the written circuit, the
    XX and YY circuits and the timeline of the scheduled ZZ circuit
    (docs/DESIGN.md, section 5). Before drawing anything it refuses a circuit,
    processor or noise file that changed since the run, so no view is ever drawn
    from files the run did not use. Each view is drawn on its own matplotlib
    Figure, never through pyplot, so matplotlib's backend is never switched and no
    window object is made: a notebook keeps its inline plots, and a GUI backend
    such as TkAgg has nothing that Aer's worker threads could free.
    """
    from qiskit.visualization import timeline_drawer

    from bellbench.figures import draw_processor

    folder = Path(folder)
    record = yaml.safe_load((folder / RESULT_FILE).read_text(encoding="utf-8"))
    _check_result_format(record)
    _check_recorded_files(record)
    proc = yaml.safe_load((configs.ROOT / record["noise_control"]["processor"]["path"]).read_text(encoding="utf-8"))
    written = []

    def save(fig, name):
        fig.savefig(folder / name, dpi=150, facecolor="white", bbox_inches="tight", metadata={"Software": None})
        written.append(folder / name)

    used = [tuple(int(q) for q in edge.split("-")) for edge in record["cost"]["two_qubit_gates_by_edge"]["ZZ"]]
    save(_figure(lambda ax: draw_processor(ax, proc, used_edges=used), lambda ax: (4, 4.3)), "graph.png")
    drawings = {"circuit-zz.png": record["compiled"]["ZZ"]}
    if record["diagrams"] == "full":
        drawings |= {"written.png": record["written"], "circuit-xx.png": record["compiled"]["XX"],
                     "circuit-yy.png": record["compiled"]["YY"]}
    for name, text in drawings.items():
        circuit = qasm3.loads(text)
        # qiskit draws a global phase through pyplot even on a given axis, which would make a window object; the
        # phase changes no measured outcome, so the views leave it out.
        circuit.global_phase = 0
        save(_figure(lambda ax: circuit.draw("mpl", idle_wires=False, fold=40, ax=ax), _circuit_size), name)
    if record["diagrams"] == "full" and record["scheduled_duration"] is not None:
        nc = NoiseControl.from_yaml(record["noise_control"])
        scheduled = schedule(qasm3.loads(record["compiled"]["ZZ"]), nc)
        save(_figure(lambda ax: timeline_drawer(scheduled, target=nc.target, axis=ax), _timeline_size), "timeline.png")
    (folder / "report.md").write_text(_run_report(folder, record), encoding="utf-8")
    written.append(folder / "report.md")
    return written


def _figure(draw, size):
    """A matplotlib Figure, made without pyplot, holding what `draw(ax)` puts on an axis.

    `size(ax)` gives the figure's size in inches from an axis the drawing was
    first made on, so a drawer that sizes its own figure from its content keeps
    that size here.
    """
    from matplotlib.figure import Figure

    probe = Figure()
    ax = probe.add_subplot()
    draw(ax)
    fig = Figure(figsize=size(ax), facecolor="white")
    draw(fig.add_subplot())
    return fig


def _circuit_size(ax) -> tuple[float, float]:
    """The size qiskit's circuit drawer gives a figure of its own: its axis limits times its scale factor."""
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    return (x1 - x0) * 0.8361111, (y1 - y0) * 0.8361111


def _timeline_size(ax) -> tuple[float, float]:
    """The size qiskit's timeline drawer gives a figure of its own, from its default style and the axis height."""
    from qiskit.visualization.timeline.stylesheet import default_style

    style = default_style()
    y0, y1 = ax.get_ylim()
    return style["formatter.general.fig_width"], style["formatter.general.fig_unit_height"] * (y1 - y0)


def _run_report(folder: Path, record: dict) -> str:
    rows = _read_csv(folder / "simulations.csv")
    c = record["cost"]
    lines = [
        f"# Run {configs.name_from_record(record['circuit'], 'circuit')} under "
        f"{configs.name_from_record(record['noise_control']['noise'], 'noise')}",
        "",
        f"- **Circuit file:** `{record['circuit']['path']}`",
        f"- **Noise profile:** `{record['noise_control']['noise']['path']}`, scale {record['noise_control']['scale']:g}",
        f"- **Overrides:** {len(record['noise_control']['overrides'])}"
        + (" (flagged: per-qubit values differ from the profile)" if record["noise_control"]["overrides"] else ""),
        f"- **Shots:** {record['shots']} per basis per simulation",
        f"- **Commit:** `{record['provenance']['commit']}`"
        + (", with uncommitted changes" if record["provenance"]["uncommitted"] else ""),
        "",
        "| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['simulation']} | {float(r['fidelity']):.4f} | {float(r['fidelity_se']):.4f} | "
            f"{float(r['fidelity_raw']):.4f} | {float(r['acceptance']):.4f} "
            f"({float(r['acceptance_low']):.4f} to {float(r['acceptance_high']):.4f}) |"
        )
    duration = record["scheduled_duration"]
    lines += [
        "",
        "| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |",
        "|---|---|---|---|---|---|",
        f"| {c['swaps']} ({c['router_swaps']}) | {c['two_qubit_gates']} | {c['depth']} | {len(c['qubits_used'])} | "
        + (f"{duration * 1e6:.3f} µs" if duration is not None else "not scheduled")
        + f" | {_pair_arrived(c['pair_on_ports'], rows)} |",
        "",
        f"Standard error method: {rows[0]['se_method']}.",
        "",
    ]
    for name, sim in record["simulations"].items():
        if sim.get("empty_bases"):
            lines += [
                f"**The {name} simulation kept no shot in {', '.join(sim['empty_bases'])},** so its F and that "
                "basis's correlator are undefined (nan).",
                "",
            ]
    return "\n".join(lines)


def _pair_arrived(on_ports: bool, rows: list[dict]) -> str:
    """"yes" when the layout puts the pair on the ports and the ideal F is 1, else "NO" with the ideal F, since a
    circuit the router leaves alone can keep the layout on the ports without ever making the pair there."""
    ideal = float(next(r["fidelity"] for r in rows if r["simulation"] == "ideal"))
    return "yes" if on_ports and ideal == 1.0 else f"NO (ideal F {ideal:.4f})"


# -- Benchmarks -------------------------------------------------------------------------

RUN_LIST = "bp.data.runs.yaml"

# The challenge's nine cases: case -> (processor model, simulation). One row per model; the columns are the ideal
# baseline, the noisy baseline and noisy with protection (docs/CHALLENGE.md, The nine core cases).
CASE_GRID = {
    3 * row + column + 1: (model, "ideal" if column == 0 else "noisy")
    for row, model in enumerate(configs.CORE_PROCESSORS)
    for column in range(3)
}
PROTECTED_CASES = {case for case in CASE_GRID if case % 3 == 0}  # the third column: cases 3, 6 and 9


def load_benchmark(name: str) -> tuple[dict, dict]:
    """The benchmark file for `name`, checked, and its `{path, hash}` record.

    Besides its schema: run ids are unique, each case is filled once by a run the
    file lists, no two cases name one run and simulation, and each case sits
    where the challenge's grid puts it (docs/CHALLENGE.md, The nine core cases):
    its run's circuit is on the case's model, one row per model in
    CORE_PROCESSORS order, and cases 1, 4 and 7 are ideal, all others noisy.
    A protected case, 3, 6 or 9, needs a run whose circuit measures into a
    check register, so it cannot repeat its baseline. A benchmark names only
    committed circuits, never a trial, since its file is committed and others run it.
    """
    data, record = configs.load_recorded("benchmark", name)
    where = f"{record['path']}: $.cases"
    ids = [r["run"] for r in data["runs"]]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{record['path']}: $.runs: run ids must be unique; got {ids}")
    for r in data["runs"]:
        try:
            path = configs.config_path("circuit", r["circuit"])
        except FileNotFoundError:
            continue  # a missing circuit is refused where the run loads it, naming the known ones
        if configs.is_trial(path):
            raise ValueError(
                f"{record['path']}: $.runs: run {r['run']!r} names the trial circuit {r['circuit']!r}; a benchmark "
                "names only committed circuits, so promote it and commit it first"
            )
    cases = [c["case"] for c in data.get("cases", [])]
    if len(set(cases)) != len(cases):
        raise ValueError(f"{where}: each case is filled once; got {cases}")
    circuit_of = {r["run"]: r["circuit"] for r in data["runs"]}
    filled = {}
    for c in data.get("cases", []):
        if c["run"] not in ids:
            raise ValueError(f"{where}: case {c['case']} names run {c['run']!r}, which is not in runs")
        key = (c["run"], c["simulation"])
        if key in filled:
            message = f"cases {filled[key]} and {c['case']} both name run {c['run']!r}, {c['simulation']}"
            raise ValueError(f"{where}: {message}")
        filled[key] = c["case"]
        model, simulation = CASE_GRID[c["case"]]
        processor = configs.load_config("circuit", circuit_of[c["run"]])["processor"]
        if processor != model or c["simulation"] != simulation:
            raise ValueError(
                f"{where}: case {c['case']} is the {model} model's {simulation} simulation; "
                f"run {c['run']!r} is on {processor} and the case names its {c['simulation']} simulation"
            )
        if c["case"] in PROTECTED_CASES and not _measures_a_check(load_circuit(circuit_of[c["run"]]).circuit):
            raise ValueError(
                f"{where}: case {c['case']} is a protected case; run {c['run']!r}'s circuit "
                f"{circuit_of[c['run']]!r} measures no check register, so it would repeat its baseline"
            )
    return data, record


def _measures_a_check(circuit) -> bool:
    """Whether a measurement in `circuit` writes a bit of a check register, `check` or `check_<name>`."""
    checks = {bit for reg in circuit.cregs if reg.name == "check" or reg.name.startswith("check_") for bit in reg}
    return any(inst.operation.name == "measure" and checks & set(inst.clbits) for inst in circuit.data)


def run_benchmark(name: str, root: Path | None = None, shots: int | None = None) -> Path:
    """Make every run the benchmark lists and write a new folder; refuses before writing if a run fails its self-test.

    The self-test, which every run passes, whether it fills a case or not: the
    pair ends on the ports, and the ideal simulation gives F = 1 and keeps every
    shot. A refusal names the run, and the cases it fills.

    The folder is <root>/runs/benchmark/<name>/<stamp>/, and each run is written
    in it under its run id. `root` is results/ only when the git state read as the
    benchmark starts and as each of its runs starts is the same commit with
    nothing uncommitted in src/ or config/, and workspace/ otherwise, so an edit
    or a commit during the make lands on the safe side. Earlier folders are never
    changed or deleted. `shots` overrides the file's, for tests only.
    """
    start = _git_state()
    data, record = load_benchmark(name)
    runs = {}
    for spec in data["runs"]:
        runs[spec["run"]] = CircuitRun(
            spec["circuit"], spec["noise"], shots or data["shots"], data["base_seed"],
            spec.get("scale", 1.0), spec.get("overrides", ()), spec.get("conditional"),
        ).run()
    cases_of = {}
    for case in data.get("cases", []):
        cases_of.setdefault(case["run"], []).append(case["case"])
    for run_id, run in runs.items():
        _self_test(name, run_id, run, cases_of.get(run_id, []))
    run_list = {"benchmark": record, "runs": list(runs), "cases": data.get("cases", [])}
    if root is None:
        clean = not start[1] and all(run.git_state == start for run in runs.values())
        root = configs.ROOT / ("results" if clean else "workspace")
    folder = Path(root) / "runs" / "benchmark" / name / _stamp()
    configs.check_config("runs", run_list, (folder / RUN_LIST).as_posix())
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        message = f"{folder} exists: benchmark {name!r} was made this second already; make it again"
        raise FileExistsError(message) from None
    for run_id, run in runs.items():
        run.write(folder=folder / run_id)
    (folder / RUN_LIST).write_text(yaml.safe_dump(run_list, sort_keys=False), encoding="utf-8")
    rows = comparison_rows(runs, data)
    _write_csv(folder / "comparison.csv", rows, COMPARISON_COLUMNS)
    (folder / "report.md").write_text(_benchmark_report(data, rows), encoding="utf-8")
    return folder


def _self_test(benchmark: str, run_id: str, run: CircuitRun, cases: list[int]) -> None:
    """Refuse a run whose pair ends off its ports, or whose ideal simulation does not give F = 1 with every shot kept.

    The message names the benchmark, the cases the run fills, if any, and the run.
    """
    filled = f"case{'s' if len(cases) > 1 else ''} {', '.join(map(str, cases))}: " if cases else ""
    where = f"benchmark {benchmark!r}: {filled}run {run_id!r}"
    if not run.cost["pair_on_ports"]:
        raise ValueError(f"{where} left the pair off its ports")
    ideal = run.scores["ideal"]
    if ideal.accepted.value != 1.0:
        raise ValueError(f"{where} has ideal F {ideal.accepted.value}, not 1")
    if ideal.acceptance != 1.0:
        raise ValueError(
            f"{where} kept {ideal.acceptance} of its ideal shots, not every one, so a check fires with no noise"
        )


def current_benchmark(name: str, root: Path | None = None) -> Path:
    """The benchmark's current folder: the finished one with the latest stamp under <root>/runs/benchmark/<name>/.

    A folder is finished once it holds report.md, which a benchmark writes last,
    so a make that failed partway never becomes the current one. `root` defaults
    to results/, where the benchmarks made from committed code are.
    """
    parent = (configs.ROOT / "results" if root is None else Path(root)) / "runs" / "benchmark" / name
    stamps = sorted(
        p for p in parent.glob("*")
        if p.is_dir() and re.fullmatch(r"\d{8}T\d{6}Z", p.name) and (p / "report.md").is_file()
    )
    if not stamps:
        raise FileNotFoundError(f"no {name!r} benchmark in {parent}; make benchmark NAME={name} makes one")
    return stamps[-1]


def comparison_rows(runs: dict, data: dict) -> list[dict]:
    """One row per run and simulation, with the cost, the total shots and the derived metrics.

    The total shots are the raw shots of the simulation's three bases together.

    The gates per accepted pair are undefined (NaN) where a simulation kept no
    shot, as its F is. The infidelity removed per rejection and its standard
    error are undefined where a simulation discarded no shot.
    """
    case_of = {(c["run"], c["simulation"]): c["case"] for c in data.get("cases", [])}
    rows = []
    for run_id, run in runs.items():
        for name in SIMULATIONS:
            s = run.scores[name]
            rows.append({
                "case": case_of.get((run_id, name), ""),
                "run": run_id,
                "circuit": run.circuit.name,
                "processor": run.circuit.processor,
                "noise": run.nc.noise_name,
                "scale": run.nc.scale,
                "overrides": len(run.nc.overrides),
                **s.row(name),
                "swaps": run.cost["swaps"],
                "router_swaps": run.cost["router_swaps"],
                "two_qubit_gates": run.cost["two_qubit_gates"],
                "depth": run.cost["depth"],
                "qubits_used": len(run.cost["qubits_used"]),
                "scheduled_duration": run.duration if run.duration is not None else "",
                "shots_total": sum(s.raw_shots.values()),
                "two_qubit_gates_per_accepted_pair": (
                    run.cost["two_qubit_gates"] / s.acceptance if s.acceptance else math.nan
                ),
                "infidelity_removed_per_rejection": s.removed_per_rejection[0],
                "infidelity_removed_per_rejection_se": s.removed_per_rejection[1],
            })
    return rows


def _benchmark_report(data: dict, rows: list[dict]) -> str:
    lines = [f"# {data['label']}", "", data["notes"], ""]
    if data.get("cases"):
        lines += [
            "| Case | Processor | Simulation | F | Standard error | Acceptance | Two-qubit gates | SWAPs "
            "| Infidelity removed per rejection |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in sorted((r for r in rows if r["case"] != ""), key=lambda r: r["case"]):
            lines.append(
                f"| {r['case']} | {r['processor']} | {r['simulation']} | {r['fidelity']:.4f} | "
                f"{r['fidelity_se']:.4f} | {r['acceptance']:.4f} | {r['two_qubit_gates']} | {r['swaps']} | "
                f"{_removed_cell(r)} |"
            )
        lines += [
            "",
            "Cases not listed have no run yet. The infidelity removed per rejection is (F - F raw) / (1 - p) "
            f"within the run, with its standard error by the {REJECTION_METHOD}; it is n/a where no shot was "
            "discarded.",
            "",
        ]
    else:
        lines += [
            "| Run | F | Standard error | F raw | Acceptance | Two-qubit gates | Total shots |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in (r for r in rows if r["simulation"] == "noisy"):
            lines.append(
                f"| {r['run']} | {r['fidelity']:.4f} | {r['fidelity_se']:.4f} | {r['fidelity_raw']:.4f} | "
                f"{r['acceptance']:.4f} | {r['two_qubit_gates']} | {r['shots_total']} |"
            )
        lines += [
            "",
            "One row per run, its noisy simulation; every run's ideal simulation passed the self-test, F = 1 with "
            "every shot kept. Total shots are the raw shots of the three bases together.",
            "",
        ]
    lines += [
        "Every row, with the derived metrics, is in comparison.csv. "
        f"F's standard error method: {rows[0]['se_method']}.",
        "",
    ]
    return "\n".join(lines)


# -- Helpers -------------------------------------------------------------------------


def _removed_cell(row: dict) -> str:
    """The report's cell for the infidelity removed per rejection: the value and its standard error, or n/a."""
    value, error = row["infidelity_removed_per_rejection"], row["infidelity_removed_per_rejection_se"]
    return "n/a" if math.isnan(value) else f"{value:.3f} ± {error:.3f}"


def _check_conditional_channels(name: str, compiled: dict, nc: NoiseControl) -> None:
    """Stop a run whose compiled circuits reset a qubit, or measure one and act on it again, while the matching
    conditional channel is unset, so neither is silently perfect."""
    for basis, c in compiled.items():
        circuit = c.compiled
        resets = sorted({circuit.find_bit(i.qubits[0]).index for i in circuit.data if i.operation.name == "reset"})
        if resets and nc.conditional["reset_error"] is None:
            raise ValueError(
                f"circuit {name!r} resets qubit(s) {resets} in its {basis} circuit, but the conditional channel "
                "reset_error is unset, so each reset would be perfect; set it, as a value swept over a range"
            )
        reused = sorted({q for _, q in mid_circuit_measurements(circuit)})
        if reused and nc.conditional["mid_circuit_measurement_error"] is None:
            raise ValueError(
                f"circuit {name!r} measures qubit(s) {reused} and then acts on them again in its {basis} circuit, "
                "but the conditional channel mid_circuit_measurement_error is unset, so the qubit would come out "
                "of each read perfect; set it, as a value swept over a range, or measure the qubit last"
            )


def _check_starting_marker(name: str, scheduled: dict, nc: NoiseControl) -> None:
    """Stop a run whose starting_excitation is set but would change nothing: the noise model holds no error on the
    starting marker though the value is above 0 (at 0 there is nothing to hold, since Aer keeps no error that does
    nothing), or a circuit about to be simulated does not open every qubit with it."""
    if nc.conditional["starting_excitation"] > 0 and STARTING_LABEL not in nc.noise_model.noise_instructions:
        raise ValueError(
            f"conditional starting_excitation is set, but the noise model for {nc.noise_name!r} holds no error on "
            f"{STARTING_LABEL!r}, so it would change nothing"
        )
    for basis, circuit in scheduled.items():
        first = {}
        for inst in circuit.data:
            for q in inst.qubits:
                first.setdefault(q, inst.operation.label)
        unmarked = [circuit.find_bit(q).index for q in circuit.qubits if first.get(q) != STARTING_LABEL]
        if unmarked:
            raise ValueError(
                f"circuit {name!r}: conditional starting_excitation is set, but its {basis} circuit does not open "
                f"qubit(s) {unmarked} with the starting marker, so the excitation would not reach them"
            )


def _check_result_format(record: dict) -> None:
    """Refuse a run recorded in another result format: its circuits and CSVs are in an older shape."""
    if record["result_format"] != RESULT_FORMAT:
        commit = record["provenance"]["commit"] or "unknown"
        raise ValueError(
            f"the run was recorded in result format {record['result_format']}, and this code reads format "
            f"{RESULT_FORMAT}; rebuild it from the commit that made it, {commit}"
        )


def _stamp() -> str:
    """The UTC time now, as STAMP names run and benchmark folders."""
    return datetime.datetime.now(datetime.UTC).strftime(STAMP)


def _git_state() -> tuple[str | None, bool]:
    """The commit, and whether src/ or config/ has uncommitted changes; outside git, (None, True)."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=configs.ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "src", "config"],
            cwd=configs.ROOT, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None, True
    return commit, bool(status.strip())


def read_table(path):
    """simulations.csv, counts.csv or comparison.csv as a pandas DataFrame, checked against its declared columns.

    Text columns stay text, so an outcome such as "01" or "01 0" keeps its bits
    (read as a number, "01" would become 1; the bit order is in the CSV
    contract above). comparison.csv's case is a nullable integer, empty (<NA>)
    for a run that fills no case; nan in a number column is NaN. A table written
    before a column was added (ADDED_COLUMNS) reads as it was written, without
    that column, so select columns by name. A file of another name, or whose
    header is neither its declared columns nor an earlier set of them, raises a
    ValueError naming it.
    """
    import pandas as pd

    path = Path(path)
    tables = {"simulations.csv": SIMULATION_COLUMNS, "counts.csv": COUNT_COLUMNS, "comparison.csv": COMPARISON_COLUMNS}
    if path.name not in tables:
        raise ValueError(f"{path}: read_table reads {', '.join(tables)}; got {path.name}")
    columns = tables[path.name]
    with open(path, newline="", encoding="utf-8") as f:
        header = tuple(next(csv.reader(f), ()))
    added = ADDED_COLUMNS.get(path.name, ())
    written = [tuple(c for c in columns if c not in added[k:]) for k in range(len(added) + 1)]
    if header not in written:
        raise ValueError(f"{path}: the header is not the declared columns of {path.name}; got {list(header)}")
    dtype = {c: str for c in header if c in TEXT_COLUMNS} | ({"case": "Int64"} if "case" in header else {})
    return pd.read_csv(path, dtype=dtype, keep_default_na=False, na_values=["", "nan"])


def _write_csv(path: Path, rows: list[dict], columns) -> None:
    """Write `rows` under the header `columns`; a row with a key outside them, or one missing, raises."""
    for row in rows:
        if set(row) != set(columns):
            extra, missing = sorted(set(row) - set(columns)), sorted(set(columns) - set(row))
            raise ValueError(f"{path.name}: a row does not fit the declared columns; extra {extra}, missing {missing}")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _stringify(rows: list[dict]) -> list[dict]:
    """Rows as csv reads them back, so a fresh run compares with a written one exactly."""
    return [{k: str(v) for k, v in row.items()} for row in rows]


USAGE = """usage: python -m bellbench.run benchmark [NAME]     make a benchmark (default core)
       python -m bellbench.run rerun PATH           rerun a run folder or its bp.data.result.yaml;
                                                    exit 0 a match, 1 a difference, 2 a refusal
       python -m bellbench.run report PATH          redraw a run folder's diagrams and report.md;
                                                    exit 2 when a file it was made from changed"""


def main(argv: list[str]) -> int:
    if argv[:1] == ["benchmark"] and len(argv) <= 2:
        print(configs.repo_path(run_benchmark(argv[1] if len(argv) == 2 else "core")))
        return 0
    if argv[:1] == ["rerun"] and len(argv) == 2:
        code, lines = rerun(Path(argv[1]))
        print("\n".join(lines))
        return code
    if argv[:1] == ["report"] and len(argv) == 2:
        folder = Path(argv[1])
        try:
            written = write_views(folder.parent if folder.name == RESULT_FILE else folder)
        except (ValueError, FileNotFoundError) as e:
            print(f"refused: {e}")
            return REFUSED
        for path in written:
            print(path)
        return 0
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
