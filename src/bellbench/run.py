# src/bellbench/run.py
"""CircuitRun: one circuit file under one noise profile, simulated ideal and noisy, written as a run folder.

A run (docs/DESIGN.md, section 5) reads its circuit file and builds a
NoiseControl for the circuit's processor, then compiles the three basis
circuits once under its transpiler seed, takes the cost before scheduling,
schedules, simulates ideal and noisy, and processes the shots as the circuit
file's analysis says. `postselect` keeps a shot only when every check and flag
bit is 0; with no checks, it keeps every shot. `correct` is a hook that raises
until a decoder is built (D-54).

A run stops before simulating when its circuit resets or measures before the
end while the matching conditional channel is unset, so neither is ever
silently perfect (D-48).

`write` makes the run folder: <root>/runs/workbench/<circuit>/<noise>/<stamp>/
for a run made on its own, or the folder a benchmark names for each of its runs.
<root> is results/ for a run made from committed code and config, workspace/
otherwise. A run folder holds bp.data.result.yaml, the settings and records,
checked against config/bp.schema.result.yaml; simulations.csv, one row of
numbers per simulation; and counts.csv, every outcome as the key Qiskit writes,
one bit string per register in reverse of the record's register order. Seeds derive from
the run's labels, never from its folder name, so a remade run repeats them.

`rerun` rebuilds a run from its folder and compares (D-79): `make run RUN=<path>`.
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
from bellbench.circuits import circuit_to_qasm, load_circuit
from bellbench.fidelity import BASES, fidelity_from_counts
from bellbench.noise import NoiseControl
from bellbench.pipeline import (
    PORT_REGISTER,
    basis_circuits,
    compile_bases,
    cost,
    derive_seed,
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
# the value it holds is built, and never renamed in place.
SIMULATION_COLUMNS = (
    "simulation",
    "fidelity", "fidelity_se", "fidelity_raw", "fidelity_raw_se", "se_method",
    *(f"corr_{b}" for b in BASES),
    "acceptance", "acceptance_low", "acceptance_high",
    *(f"shots_{kind}_{b}" for b in BASES for kind in ("raw", "accepted")),
)
COUNT_COLUMNS = ("simulation", "basis", "outcome", "count")
COMPARISON_COLUMNS = (
    "case", "run", "circuit", "processor", "noise", "scale", "overrides",
    *SIMULATION_COLUMNS,
    "swaps", "router_swaps", "two_qubit_gates", "depth", "qubits_used", "scheduled_duration",
    "two_qubit_gates_per_accepted_pair",
)


class CircuitRun:
    """One run: a circuit file under a noise profile, with its scale, overrides and conditional channels."""

    def __init__(
        self,
        circuit: str,
        noise: str,
        shots: int = 20_000,
        base_seed: int = 2026,
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
        if self.circuit.analysis == "correct":
            raise NotImplementedError(f"circuit {circuit!r}: analysis correct is a hook until a decoder is built (D-54)")
        self.nc = NoiseControl(self.circuit.processor, noise, scale, overrides, conditional)
        _check_conditional_channels(self.circuit, self.nc)
        self.shots, self.base_seed, self.diagrams = shots, base_seed, diagrams
        self.labels = (circuit, noise, repr(self.nc.scale), self.settings_hash or "none")
        self.seeds = {step: derive_seed(base_seed, *self.labels, step) for step in ("transpile", *SIMULATIONS)}
        self.compiled = self.cost = self.duration = None
        self.simulations, self.analysis = {}, {}

    @property
    def settings_hash(self) -> str | None:
        """8 hex digits of the overrides and conditional channels, or None when neither is set."""
        export = self.nc.export_as_yaml()
        if not export["overrides"] and not any(v is not None for v in export["conditional"].values()):
            return None
        return configs.hash_data({"overrides": export["overrides"], "conditional": export["conditional"]})[7:15]

    # -- Running ---------------------------------------------------------------

    def run(self, methods: dict[str, str] | None = None) -> "CircuitRun":
        """Compile, cost, schedule, simulate ideal and noisy, and analyse; `methods` repeats a recorded run's."""
        circuits = basis_circuits(self.circuit.circuit, self.nc.ports)
        self.compiled = compile_bases(circuits, self.nc, self.seeds["transpile"])
        self.cost = cost(self.compiled, self.nc.ports)
        scheduled = {basis: schedule(c.compiled, self.nc) for basis, c in self.compiled.items()}
        self.duration = scheduled_duration(scheduled["ZZ"], self.nc)
        for name, noise_model in (("ideal", None), ("noisy", self.nc.noise_model)):
            method = (methods or {}).get(name, "automatic")
            sim = simulate(scheduled, noise_model, self.shots, self.seeds[name], method)
            self.simulations[name] = sim
            self.analysis[name] = analyse(sim, self.registers)
        return self

    @property
    def registers(self) -> list[str]:
        """The compiled circuits' classical registers, in order; the port register is last."""
        return [r.name for r in self.compiled["ZZ"].compiled.cregs]

    # -- Records -----------------------------------------------------------------

    def export_as_yaml(self) -> dict:
        """The run's settings and records, as bp.data.result.yaml holds them."""
        if not self.simulations:
            raise RuntimeError("the run has not run yet; call run() first")
        commit, uncommitted = _git_state()
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
            "simulations": {
                name: {"seeds": dict(sim.seeds), "methods": dict(sim.methods)} for name, sim in self.simulations.items()
            },
            "provenance": {
                "commit": commit,
                "uncommitted": uncommitted,
                "packages": {"python": platform.python_version(), **{p: version(p) for p in PACKAGES}},
            },
        }

    @classmethod
    def from_yaml(cls, record: dict) -> "CircuitRun":
        """Rebuild a run from its record; refuses a referenced file whose content changed since."""
        configs.check_config("result", record, "the run record")
        _check_result_format(record)
        circuit = configs.name_from_record(record["circuit"], "circuit")
        nc_record = record["noise_control"]
        noise = configs.name_from_record(nc_record["noise"], "noise")
        run = cls(
            circuit, noise, record["shots"], record["base_seed"], nc_record["scale"],
            nc_record["overrides"], nc_record["conditional"], record["diagrams"],
        )
        configs.check_unchanged(record["circuit"], run.circuit.record)
        built = run.nc.export_as_yaml()
        for kind in ("processor", "noise"):
            configs.check_unchanged(nc_record[kind], built[kind])
        if run.seeds != record["seeds"]:
            raise ValueError(f"the recorded seeds {record['seeds']} are not the ones the run's labels give {run.seeds}")
        return run

    # -- Writing -------------------------------------------------------------------

    def write(self, root: Path | None = None, folder: Path | None = None) -> Path:
        """Write the run folder and return it.

        By default the folder is <root>/runs/workbench/<circuit>/<noise>/<stamp>/,
        with `root` results/ or workspace/ as the git state says. A benchmark
        passes `folder` instead, which must not exist yet.
        """
        record = self.export_as_yaml()
        configs.check_config("result", record, "the run record")
        if folder is None:
            if root is None:
                root = configs.ROOT / ("workspace" if record["provenance"]["uncommitted"] else "results")
            stamp = _stamp()
            if self.nc.scale != 1:
                stamp += f"-x{self.nc.scale:g}"
            if self.settings_hash:
                stamp += f"-{self.settings_hash}"
            folder = Path(root) / "runs" / "workbench" / self.circuit.name / self.nc.noise_name / stamp
        elif root is not None:
            raise ValueError("write takes a root or a folder, not both")
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=False)
        (folder / RESULT_FILE).write_text(yaml.dump(record, Dumper=_Dumper, sort_keys=False), encoding="utf-8")
        _write_csv(folder / "simulations.csv", self.simulation_rows(), SIMULATION_COLUMNS)
        _write_csv(folder / "counts.csv", self.count_rows(), COUNT_COLUMNS)
        write_views(folder)
        return folder

    def simulation_rows(self) -> list[dict]:
        """One row of numbers per simulation, as simulations.csv holds them."""
        return [self.analysis[name].row(name) for name in SIMULATIONS]

    def count_rows(self) -> list[dict]:
        """Every outcome of every basis circuit, keyed as Qiskit writes it: one bit string per register, last first."""
        return [
            {"simulation": name, "basis": basis, "outcome": key, "count": n}
            for name in SIMULATIONS
            for basis in BASES
            for key, n in self.simulations[name].raw[basis].items()
        ]


# -- Analysis ------------------------------------------------------------------------


class Analysis:
    """One simulation's shots processed by postselection: F raw and after, with acceptance and its interval."""

    def __init__(self, raw_port, accepted_port, raw_shots, accepted_shots):
        self.raw = fidelity_from_counts(raw_port)
        self.accepted = fidelity_from_counts(accepted_port)
        self.raw_shots, self.accepted_shots = raw_shots, accepted_shots
        kept, total = sum(accepted_shots.values()), sum(raw_shots.values())
        self.acceptance = kept / total
        self.interval = wilson_interval(kept, total)

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


def analyse(sim, registers: list[str]) -> Analysis:
    """Postselect each basis's shots: keep a shot when every register other than the ports reads all 0."""
    raw_port, accepted_port, raw_shots, accepted_shots = {}, {}, {}, {}
    for basis in BASES:
        raw_port[basis], accepted_port[basis] = {}, {}
        for key, n in sim.raw[basis].items():
            bits = dict(zip(reversed(registers), key.split(" ")))
            port = bits[PORT_REGISTER]
            raw_port[basis][port] = raw_port[basis].get(port, 0) + n
            if all(set(b) == {"0"} for r, b in bits.items() if r != PORT_REGISTER):
                accepted_port[basis][port] = accepted_port[basis].get(port, 0) + n
        raw_shots[basis] = sum(raw_port[basis].values())
        accepted_shots[basis] = sum(accepted_port[basis].values())
    return Analysis(raw_port, accepted_port, raw_shots, accepted_shots)


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

    2 when a referenced file changed, 1 when a circuit or a number differs, 0
    when they all match; a different commit or package version is reported
    either way. Nothing is written into the run folder.
    """
    folder = Path(path)
    folder = folder.parent if folder.name == RESULT_FILE else folder
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
    compare("counts", _read_csv(folder / "counts.csv"), _stringify(run.count_rows()))
    compare("simulations", _read_csv(folder / "simulations.csv"), _stringify(run.simulation_rows()))
    compare("commit", record["provenance"]["commit"], new["provenance"]["commit"], counts=False)
    compare("package versions", record["provenance"]["packages"], new["provenance"]["packages"], counts=False)
    return (DIFFER if differ else MATCH), lines


# -- Views ----------------------------------------------------------------------------

def write_views(folder: Path) -> list[Path]:
    """Draw a run folder's diagrams and report.md from its record and numbers; returns the files written.

    lean: the processor graph with its ports and the couplers the compiled ZZ
    circuit uses, and the compiled ZZ circuit. full adds the written circuit, the
    XX and YY circuits and the timeline of the scheduled ZZ circuit (D-74).
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from bellbench.figures import draw_processor

    folder = Path(folder)
    record = yaml.safe_load((folder / RESULT_FILE).read_text(encoding="utf-8"))
    _check_result_format(record)
    proc = yaml.safe_load((configs.ROOT / record["noise_control"]["processor"]["path"]).read_text(encoding="utf-8"))
    written = []

    def save(fig, name):
        fig.savefig(folder / name, dpi=150, facecolor="white", bbox_inches="tight", metadata={"Software": None})
        plt.close(fig)
        written.append(folder / name)

    fig, ax = plt.subplots(figsize=(4, 4.3), facecolor="white")
    used = [tuple(int(q) for q in edge.split("-")) for edge in record["cost"]["two_qubit_gates_by_edge"]["ZZ"]]
    draw_processor(ax, proc, used_edges=used)
    save(fig, "graph.png")
    drawings = {"circuit-zz.png": record["compiled"]["ZZ"]}
    if record["diagrams"] == "full":
        drawings |= {"written.png": record["written"], "circuit-xx.png": record["compiled"]["XX"],
                     "circuit-yy.png": record["compiled"]["YY"]}
    for name, text in drawings.items():
        circuit = qasm3.loads(text)
        save(circuit.draw("mpl", idle_wires=False, fold=40), name)
    if record["diagrams"] == "full" and record["scheduled_duration"] is not None:
        from qiskit.visualization import timeline_drawer

        nc = NoiseControl.from_yaml(record["noise_control"])
        zz = qasm3.loads(record["compiled"]["ZZ"])
        save(timeline_drawer(schedule(zz, nc), target=nc.target), "timeline.png")
    (folder / "report.md").write_text(_run_report(folder, record), encoding="utf-8")
    written.append(folder / "report.md")
    return written


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
        + f" | {'yes' if c['pair_on_ports'] else 'NO'} |",
        "",
        f"Standard error method: {rows[0]['se_method']}.",
        "",
    ]
    return "\n".join(lines)


# -- Benchmarks -------------------------------------------------------------------------

RUN_LIST = "bp.data.runs.yaml"


def load_benchmark(name: str) -> tuple[dict, dict]:
    """The benchmark file for `name`, checked, and its `{path, hash}` record."""
    data, record = configs.load_recorded("benchmark", name)
    ids = [r["id"] for r in data["runs"]]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{record['path']}: $.runs: run ids must be unique; got {ids}")
    cases = [c["case"] for c in data.get("cases", [])]
    if len(set(cases)) != len(cases):
        raise ValueError(f"{record['path']}: $.cases: each case is filled once; got {cases}")
    for c in data.get("cases", []):
        if c["run"] not in ids:
            raise ValueError(f"{record['path']}: $.cases: case {c['case']} names run {c['run']!r}, which is not in runs")
    return data, record


def run_benchmark(name: str, root: Path | None = None, shots: int | None = None) -> Path:
    """Make every run the benchmark lists and write a new folder; refuses before writing if a case fails its self-test.

    The folder is <root>/runs/benchmark/<name>/<stamp>/, with `root` results/ or
    workspace/ as the git state says, and each run is written in it under its run
    id. Earlier folders are never changed or deleted. `shots` overrides the
    file's, for tests only.
    """
    data, record = load_benchmark(name)
    runs = {}
    for spec in data["runs"]:
        runs[spec["id"]] = CircuitRun(
            spec["circuit"], spec["noise"], shots or data["shots"], data["base_seed"],
            spec.get("scale", 1.0), spec.get("overrides", ()), spec.get("conditional"),
        ).run()
    for case in data.get("cases", []):
        run = runs[case["run"]]
        if not run.cost["pair_on_ports"]:
            raise ValueError(f"benchmark {name!r}: case {case['case']}: run {case['run']!r} left the pair off its ports")
        if run.analysis["ideal"].accepted.value != 1.0:
            ideal = run.analysis["ideal"].accepted.value
            raise ValueError(f"benchmark {name!r}: case {case['case']}: run {case['run']!r} has ideal F {ideal}, not 1")
    run_list = {"benchmark": record, "runs": list(runs), "cases": data.get("cases", [])}
    if root is None:
        root = configs.ROOT / ("workspace" if _git_state()[1] else "results")
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


def current_benchmark(name: str, root: Path | None = None) -> Path:
    """The benchmark's current folder: the one with the latest stamp under <root>/runs/benchmark/<name>/.

    `root` defaults to results/, where the benchmarks made from committed code are.
    """
    parent = (configs.ROOT / "results" if root is None else Path(root)) / "runs" / "benchmark" / name
    stamps = sorted(p for p in parent.glob("*") if p.is_dir() and re.fullmatch(r"\d{8}T\d{6}Z", p.name))
    if not stamps:
        raise FileNotFoundError(f"no {name!r} benchmark in {parent}; make benchmark NAME={name} makes one")
    return stamps[-1]


def comparison_rows(runs: dict, data: dict) -> list[dict]:
    """One row per run and simulation, with the cost and D-7's two-qubit gates per accepted pair."""
    case_of = {(c["run"], c["simulation"]): c["case"] for c in data.get("cases", [])}
    rows = []
    for run_id, run in runs.items():
        for name in SIMULATIONS:
            a = run.analysis[name]
            rows.append({
                "case": case_of.get((run_id, name), ""),
                "run": run_id,
                "circuit": run.circuit.name,
                "processor": run.circuit.processor,
                "noise": run.nc.noise_name,
                "scale": run.nc.scale,
                "overrides": len(run.nc.overrides),
                **a.row(name),
                "swaps": run.cost["swaps"],
                "router_swaps": run.cost["router_swaps"],
                "two_qubit_gates": run.cost["two_qubit_gates"],
                "depth": run.cost["depth"],
                "qubits_used": len(run.cost["qubits_used"]),
                "scheduled_duration": run.duration if run.duration is not None else "",
                "two_qubit_gates_per_accepted_pair": run.cost["two_qubit_gates"] / a.acceptance,
            })
    return rows


def _benchmark_report(data: dict, rows: list[dict]) -> str:
    lines = [f"# {data['label']}", "", data["notes"], ""]
    if data.get("cases"):
        lines += [
            "| Case | Processor | Simulation | F | Standard error | Acceptance | Two-qubit gates | SWAPs |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in sorted((r for r in rows if r["case"] != ""), key=lambda r: r["case"]):
            lines.append(
                f"| {r['case']} | {r['processor']} | {r['simulation']} | {r['fidelity']:.4f} | "
                f"{r['fidelity_se']:.4f} | {r['acceptance']:.4f} | {r['two_qubit_gates']} | {r['swaps']} |"
            )
        lines += ["", "Cases not listed have no run yet.", ""]
    lines += [f"Every row, with the derived metrics, is in comparison.csv. Standard error method: {rows[0]['se_method']}.", ""]
    return "\n".join(lines)


# -- Helpers -------------------------------------------------------------------------


def _check_conditional_channels(circuit, nc: NoiseControl) -> None:
    """Stop a circuit that resets or measures before the end while the matching channel is unset."""
    names = {i.operation.name for i in circuit.circuit.data}
    for operation, channel in (("reset", "reset_error"), ("measure", "mid_circuit_measurement_error")):
        if operation in names and nc.conditional[channel] is None:
            raise ValueError(
                f"circuit {circuit.name!r} uses {operation} before the end, but the conditional channel {channel} "
                "is unset, so it would be silently perfect (D-48)"
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


class _Dumper(yaml.SafeDumper):
    """Writes circuits as literal blocks, so a record's OpenQASM reads as written."""


_Dumper.add_representer(
    str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None)
)


USAGE = """usage: python -m bellbench.run benchmark [NAME]     make a benchmark (default core)
       python -m bellbench.run rerun PATH           rerun a run folder or its bp.data.result.yaml
       python -m bellbench.run report PATH          redraw a run folder's diagrams and report.md"""


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
        for path in write_views(folder.parent if folder.name == RESULT_FILE else folder):
            print(path)
        return 0
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
