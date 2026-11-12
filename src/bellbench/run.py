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

`write` makes the run folder, <root>/runs/<circuit>/<noise>/<stamp>/, with root
results/ for a run made from committed code and config, workspace/ otherwise
(D-76, D-79). It holds bp.data.result.yaml, the settings and records, checked
against config/bp.schema.result.yaml; simulations.csv, one row of numbers per
simulation; and counts.csv, every outcome with each register's bits in a column
of its own. Seeds derive from the run's labels, never from its folder name
(D-76), so a remade run repeats them.

`rerun` rebuilds a run from its folder and compares (D-80): `make run RUN=<path>`.
"""

import csv
import datetime
import math
import platform
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import yaml
from qiskit import qasm2

from bellbench import configs
from bellbench.circuits import load_circuit
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

RESULT_FORMAT = 1
RESULT_FILE = "bp.data.result.yaml"
SIMULATIONS = ("ideal", "noisy")
DIAGRAMS = ("lean", "full")
PACKAGES = ("qiskit", "qiskit-aer", "qiskit-ibm-runtime", "numpy")
WILSON_Z = 1.959963984540054  # a 95% interval


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
            "written": qasm2.dumps(self.circuit.circuit) + "\n",
            "compiled": {basis: qasm2.dumps(c.compiled) + "\n" for basis, c in self.compiled.items()},
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

    def write(self, root: Path | None = None) -> Path:
        """Write the run folder under `root`, by default results/ or workspace/ as the git state says."""
        record = self.export_as_yaml()
        configs.check_config("result", record, "the run record")
        if root is None:
            root = configs.ROOT / ("workspace" if record["provenance"]["uncommitted"] else "results")
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        if self.nc.scale != 1:
            stamp += f"-x{self.nc.scale:g}"
        if self.settings_hash:
            stamp += f"-{self.settings_hash}"
        folder = Path(root) / "runs" / self.circuit.name / self.nc.noise_name / stamp
        folder.mkdir(parents=True, exist_ok=False)
        (folder / RESULT_FILE).write_text(yaml.dump(record, Dumper=_Dumper, sort_keys=False), encoding="utf-8")
        _write_csv(folder / "simulations.csv", self.simulation_rows())
        _write_csv(folder / "counts.csv", self.count_rows())
        return folder

    def simulation_rows(self) -> list[dict]:
        """One row of numbers per simulation, as simulations.csv holds them."""
        return [self.analysis[name].row(name) for name in SIMULATIONS]

    def count_rows(self) -> list[dict]:
        """Every outcome of every basis circuit, each register's bits in a column of its own."""
        rows = []
        for name in SIMULATIONS:
            for basis in BASES:
                for key, n in self.simulations[name].raw[basis].items():
                    bits = dict(zip(reversed(self.registers), key.split(" ")))
                    rows.append({"simulation": name, "basis": basis, **{r: bits[r] for r in self.registers}, "count": n})
        return rows


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


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
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


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "rerun":
        print("usage: python -m bellbench.run rerun <run folder or its bp.data.result.yaml>", file=sys.stderr)
        return 2
    code, lines = rerun(Path(argv[1]))
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
