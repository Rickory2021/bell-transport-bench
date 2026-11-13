# src/bellbench/workbench.py
"""The Workbench: a notebook session's defaults, and results that show themselves.

A teammate's notebook needs one import:

    from bellbench.workbench import Workbench
    from bellbench import builders

    wb = Workbench()                                   # the core benchmark's noise profile, shots and seed
    wb.build("try-move-xx", "ibm2016", builders.move_chain, builders.bus_xx)
    wb.show("try-move-xx")                             # the written circuit, its analysis and the graph
    result = wb.run("try-move-xx")                     # shows F, the shots per basis, the cost and the checks
    base = wb.fetch("move-chain", "baseline-ibm2016")  # a committed run, without rerunning it
    wb.compare(base, result)
    wb.keep(result)                                    # writes the run folder; a trial's lands in workspace/
    wb.promote("try-move-xx")                          # moves the trial into config/circuit/, to commit

`build` saves every circuit it makes as a trial in workspace/circuits/, with
the analysis that reads its shots: the one the builders write, or the one
named for OpenQASM text or a Qiskit circuit, which is required when the circuit
measures any bit. A run, a benchmark and the score are CircuitRun's and
run.py's; the Workbench only holds the session's settings and calls them.

A result is the same whether it was just run or fetched from a run folder:
its record, its raw counts and its analysis, scored here by run.Score. With
`analysis=`, `fetch` re-reads the recorded counts another way; that result is
labelled a view, and is never kept, since no run made it. The display is plain
pandas tables, with a text form outside Jupyter.
"""

import base64
import io
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pandas as pd
import yaml
from matplotlib.figure import Figure
from qiskit import QuantumCircuit, qasm3

from bellbench import builders, configs
from bellbench.analysis import check_flags, read_shots
from bellbench.circuits import circuit_from_qasm, load_circuit, promote, save_circuit
from bellbench.fidelity import BASES
from bellbench.figures import draw_processor
from bellbench.run import RESULT_FILE, SIMULATIONS, CircuitRun, Score, current_benchmark, load_benchmark, read_table

DEFAULTS_FROM = "core"  # the benchmark whose noise profile, shots and base seed a session starts from

Step = Callable | tuple[Callable, Mapping]


class Workbench:
    """A session's settings, and the methods a notebook calls: fetch, build, show, run, compare, keep, promote.

    Every setting defaults to the core benchmark's, so a baseline run repeats
    its seeds; any of them can be set for the session here, or for one run.
    """

    def __init__(
        self,
        noise: str | None = None,
        shots: int | None = None,
        base_seed: int | None = None,
        scale: float = 1.0,
        overrides: Sequence = (),
        conditional: Mapping | None = None,
    ):
        core, _ = load_benchmark(DEFAULTS_FROM)
        profiles = sorted({r["noise"] for r in core["runs"]})
        if noise is None and len(profiles) != 1:
            raise ValueError(f"the {DEFAULTS_FROM} benchmark's runs use {profiles}; name the session's noise profile")
        self.noise = noise if noise is not None else profiles[0]
        self.shots = shots if shots is not None else core["shots"]
        self.base_seed = base_seed if base_seed is not None else core["base_seed"]
        self.scale, self.overrides, self.conditional = scale, tuple(overrides), conditional

    def __repr__(self) -> str:
        return (
            f"Workbench(noise={self.noise!r}, shots={self.shots}, base_seed={self.base_seed}, scale={self.scale}, "
            f"overrides={list(self.overrides)}, conditional={self.conditional})"
        )

    # -- Circuits ----------------------------------------------------------------

    def build(
        self,
        name: str,
        source: str | QuantumCircuit,
        *steps: Step,
        processor: str | None = None,
        analysis: Mapping | None = None,
        label: str | None = None,
    ) -> str:
        """Save a trial circuit `name` in workspace/circuits/ and return its name, for `show` and `run`.

        `build(name, processor, *steps)` runs builder steps from bellbench.builders
        in order, each a function or a (function, keyword arguments) pair, and
        saves the analysis the builders wrote. `build(name, text_or_circuit,
        processor=..., analysis=...)` saves OpenQASM text or a Qiskit circuit on the
        processor's physical qubits; `analysis` is required when it measures any
        bit. Building a name again replaces that trial; a committed circuit's name
        is refused.
        """
        if processor is None:
            if not isinstance(source, str) or not steps:
                raise TypeError(
                    "build takes a name, a processor and builder steps, or a name, OpenQASM text or a Qiskit "
                    "circuit, and processor=..."
                )
            if analysis is not None:
                raise TypeError("builder steps write their own analysis; analysis= is for OpenQASM text or a circuit")
            state = builders.start(source)
            for step in steps:
                function, kwargs = step if isinstance(step, tuple) else (step, {})
                state = function(state, **kwargs)
            state.save(name, label or name, overwrite=True, trial=True)
            return name
        if steps:
            raise TypeError("builder steps go with a processor name as the second argument, not with processor=")
        proc = configs.load_processor(processor)
        if isinstance(source, str):
            circuit, made = circuit_from_qasm(source, len(proc["qubits"]), name, proc["ports"]), "OpenQASM text"
        else:
            circuit, made = source, "a Qiskit circuit"
        if analysis is None and circuit.num_clbits:
            raise ValueError(
                f"{name!r} measures {circuit.num_clbits} bit(s) besides the ports, so name the analysis that reads "
                "them, such as {'name': 'parity', 'settings': {'checks': [...]}}"
            )
        notes = f"Built in the Workbench from {made}."
        save_circuit(name, label or name, processor, circuit, notes, analysis=analysis, overwrite=True, trial=True)
        return name

    def show(self, circuit: str) -> "CircuitView":
        """The circuit file `circuit`, committed or a trial: its written gates, its analysis and its processor."""
        return CircuitView(load_circuit(circuit))

    def promote(self, name: str, overwrite: bool = False) -> Path:
        """Move the trial `name` into config/circuit/, to be committed (bellbench.circuits.promote)."""
        return promote(name, overwrite)

    # -- Runs --------------------------------------------------------------------

    def run(
        self,
        circuit: str,
        noise: str | None = None,
        shots: int | None = None,
        base_seed: int | None = None,
        scale: float | None = None,
        overrides: Sequence | None = None,
        conditional: Mapping | None = None,
    ) -> "Result":
        """Run the circuit file `circuit` ideal and noisy, with the session's settings or those given here."""
        run = CircuitRun(
            circuit,
            noise if noise is not None else self.noise,
            shots if shots is not None else self.shots,
            base_seed if base_seed is not None else self.base_seed,
            scale if scale is not None else self.scale,
            tuple(overrides) if overrides is not None else self.overrides,
            conditional if conditional is not None else self.conditional,
        ).run()
        return Result.from_run(run)

    def fetch(self, where: str | Path, run: str | None = None, analysis: Mapping | None = None) -> "Result":
        """A run that was already made: `fetch(folder)`, or `fetch(benchmark, run_id)` from its current folder.

        With `analysis`, the recorded counts are re-read with that analysis, and the
        result is labelled a view. The run's circuit file must be unchanged since.
        """
        folder = Path(where) if run is None else current_benchmark(str(where)) / run
        return Result.from_folder(folder, analysis)

    def keep(self, result: "Result") -> Path:
        """Write a fresh result's run folder: under results/runs/ only from a clean tree and committed files."""
        return result.keep()

    def compare(self, *results: "Result") -> "Table":
        """One row per result's noisy simulation, with whether its ideal run passed the self-test."""
        if not results:
            raise TypeError("compare takes one or more results")
        rows = []
        for r in results:
            noisy = r.rows["noisy"]
            rows.append({
                "result": r.label,
                "F": noisy["fidelity"],
                "standard error": noisy["fidelity_se"],
                "F raw": noisy["fidelity_raw"],
                "acceptance": noisy["acceptance"],
                "two-qubit gates": r.record["cost"]["two_qubit_gates"],
                "total shots": sum(noisy[f"shots_raw_{b}"] for b in BASES),
                "self-test": "passes" if r.self_test is None else "FAILS",
            })
        return Table([("Comparison, noisy simulations", pd.DataFrame(rows))])


class Result:
    """One run's numbers, from a fresh CircuitRun or a run folder, scored by run.Score from its raw counts."""

    def __init__(self, label: str, record: dict, raw: dict, analysis: Mapping, run: CircuitRun | None = None,
                 view: bool = False):
        self.label, self.record, self.raw, self.analysis = label, record, raw, dict(analysis)
        self.run, self.view = run, view
        compiled = {basis: qasm3.loads(text) for basis, text in record["compiled"].items()}
        self.registers = [(r.name, r.size) for r in compiled["ZZ"].cregs]
        self.gates = {basis: dict(c.count_ops()) for basis, c in compiled.items()}
        self.rows = {
            name: Score(read_shots(self.analysis, raw[name], self.registers, record["shots"])).row(name)
            for name in SIMULATIONS
        }

    @classmethod
    def from_run(cls, run: CircuitRun) -> "Result":
        raw = {name: run.simulations[name].raw for name in SIMULATIONS}
        return cls(f"{run.circuit.name} under {run.nc.noise_name}", run.export_as_yaml(), raw, run.circuit.analysis,
                   run=run)

    @classmethod
    def from_folder(cls, folder: Path, analysis: Mapping | None = None) -> "Result":
        folder = Path(folder)
        folder = folder.parent if folder.name == RESULT_FILE else folder
        if not (folder / RESULT_FILE).is_file():
            raise FileNotFoundError(f"{folder / RESULT_FILE} does not exist; give a run folder or its {RESULT_FILE}")
        record = yaml.safe_load((folder / RESULT_FILE).read_text(encoding="utf-8"))
        configs.check_file_unchanged(record["circuit"])
        circuit = load_circuit(configs.name_from_record(record["circuit"], "circuit"))
        noise = configs.name_from_record(record["noise_control"]["noise"], "noise")
        raw = {name: {b: {} for b in BASES} for name in SIMULATIONS}
        for row in read_table(folder / "counts.csv").itertuples(index=False):
            raw[row.simulation][row.basis][row.outcome] = int(row.count)
        label = f"{circuit.name} under {noise}"
        if analysis is None:
            return cls(label, record, raw, circuit.analysis)
        return cls(f"{label}, view read with {analysis.get('name')}", record, raw, analysis, view=True)

    @property
    def self_test(self) -> str | None:
        """None when the pair ends on the ports and the ideal simulation gives F = 1 with every shot kept;
        otherwise what failed."""
        ideal = self.rows["ideal"]
        if not self.record["cost"]["pair_on_ports"]:
            return "the pair ends off its ports"
        if ideal["fidelity"] != 1.0 or ideal["acceptance"] != 1.0:
            return f"the ideal run gave F = {ideal['fidelity']:.4f} keeping {ideal['acceptance']:.4f} of its shots"
        return None

    def keep(self) -> Path:
        """Write this run's folder; refused for a view or a fetched run, which no run here made."""
        if self.view:
            raise ValueError(f"{self.label} re-reads recorded counts; it is not a run, so there is nothing to keep")
        if self.run is None:
            raise ValueError(f"{self.label} was fetched from a run folder, which already holds it")
        return self.run.write()

    def tables(self) -> list[tuple[str, pd.DataFrame]]:
        """The display's tables, each with its title."""
        summary = pd.DataFrame({
            name: {
                "F": r["fidelity"], "F standard error": r["fidelity_se"],
                "F raw": r["fidelity_raw"], "F raw standard error": r["fidelity_raw_se"],
                "acceptance": r["acceptance"],
                "acceptance 95% interval": f"{r['acceptance_low']:.4f} to {r['acceptance_high']:.4f}",
                "total shots": sum(r[f"shots_raw_{b}"] for b in BASES),
            }
            for name, r in self.rows.items()
        }).T
        bases = pd.DataFrame([
            {"simulation": name, "basis": b, "shots": r[f"shots_raw_{b}"], "kept": r[f"shots_accepted_{b}"],
             "correlator (kept)": r[f"corr_{b}"]}
            for name, r in self.rows.items() for b in BASES
        ]).set_index(["simulation", "basis"])
        cost = self.record["cost"]
        duration = self.record["scheduled_duration"]
        costs = pd.DataFrame([{
            "two-qubit gates": cost["two_qubit_gates"], "SWAPs (router's)": f"{cost['swaps']} ({cost['router_swaps']})",
            "depth": cost["depth"], "qubits used": len(cost["qubits_used"]),
            "scheduled duration (µs)": round(duration * 1e6, 3) if duration is not None else "not scheduled",
        }])
        gates = pd.DataFrame(self.gates).fillna(0).astype(int).sort_index()
        flagged = {
            name: check_flags(self.analysis, self.raw[name], self.registers) for name in SIMULATIONS
        }
        checks = pd.DataFrame({
            f"{name} {b}": {check: counts[b] for check, counts in flagged[name].items()}
            for name in SIMULATIONS for b in BASES
        })
        tables = [("F and acceptance", summary), ("Per basis", bases), ("Cost", costs),
                  ("Gates in each compiled basis circuit", gates)]
        if not checks.empty:
            tables.append(("Shots each check flagged", checks))
        return tables

    def _heading(self) -> list[str]:
        lines = [self.label, f"{self.record['shots']} shots per basis, analysis {self.analysis['name']}"]
        if self.self_test is not None:
            lines.append(f"Warning: the self-test fails: {self.self_test}. Check the circuit and its analysis.")
        return lines

    def _repr_html_(self) -> str:
        return Table(self.tables(), self._heading())._repr_html_()

    def __repr__(self) -> str:
        return repr(Table(self.tables(), self._heading()))


class CircuitView:
    """A circuit file shown before it runs: its written gates, its analysis and its processor's graph."""

    def __init__(self, circuit):
        self.circuit = circuit

    def _figures(self) -> list[bytes]:
        proc = configs.load_processor(self.circuit.processor)
        written = self.circuit.circuit.copy()
        written.global_phase = 0  # a phase changes no outcome; drawing it would go through pyplot
        images = []
        for draw, size in ((lambda ax: written.draw("mpl", idle_wires=False, fold=40, ax=ax), (9, 3.5)),
                           (lambda ax: draw_processor(ax, proc), (4, 4))):
            fig = Figure(figsize=size)
            draw(fig.subplots())
            buffer = io.BytesIO()
            fig.savefig(buffer, format="png", dpi=110, bbox_inches="tight", facecolor="white")
            images.append(buffer.getvalue())
        return images

    def _lines(self) -> list[str]:
        c = self.circuit
        return [f"{c.name}: {c.label}", f"processor {c.processor}, file {c.record['path']}",
                f"analysis {c.analysis}", c.notes]

    def _repr_html_(self) -> str:
        images = "".join(
            f'<img src="data:image/png;base64,{base64.b64encode(png).decode()}"/>' for png in self._figures()
        )
        return "".join(f"<p>{_escape(line)}</p>" for line in self._lines()) + images

    def __repr__(self) -> str:
        return "\n".join(self._lines() + ["", str(self.circuit.circuit.draw("text", idle_wires=False))])


class Table:
    """Titled pandas tables, shown as HTML in Jupyter and as text elsewhere."""

    def __init__(self, tables: list[tuple[str, pd.DataFrame]], heading: Sequence[str] = ()):
        self.tables, self.heading = tables, list(heading)

    def _repr_html_(self) -> str:
        parts = [f"<p>{_escape(line)}</p>" for line in self.heading]
        for title, frame in self.tables:
            parts += [f"<p>{_escape(title)}</p>", frame.to_html()]
        return "".join(parts)

    def __repr__(self) -> str:
        parts = list(self.heading)
        for title, frame in self.tables:
            parts += ["", title, frame.to_string()]
        return "\n".join(parts)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
