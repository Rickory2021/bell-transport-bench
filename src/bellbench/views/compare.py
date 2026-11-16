# src/bellbench/views/compare.py
"""Runs side by side, and a benchmark's runs: a table and bars of F, with the warning a fair comparison needs.

`compare_parts` warns when its runs differ in noise settings (profile, scale,
overrides, conditional channels), since a difference between them is then
conditional on that (README, Science rules), then shows a numbered table and a
bar chart of F with one column per run: a grey bar for F of every shot and,
when the run discards shots, a purple bar for F of the kept shots with the
acceptance on it. The first run's F of every shot, with one standard error, is
a band. `benchmark_parts` shows one panel of such bars per processor on a
shared F axis, then the case table, or a run table for a benchmark without
cases. `benchmark_line_parts` is the line that adds a circuit to a benchmark
file.

The F axis starts just below the shortest bar, not at 0: its label says where
it starts, it carries a break mark, and each bar carries its F.
"""

from dataclasses import replace
from pathlib import Path

import numpy as np
import yaml
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from bellbench import configs
from bellbench.run import current_benchmark, read_table
from bellbench.views.base import Part, image, markdown, table
from bellbench.views.result import BASES, ResultView
from bellbench.views.show import Compiled, written_part


def _noise_settings(view: ResultView) -> str:
    """A run's noise settings in one comparable string: profile, scale, overrides and conditional channels."""
    record = view.noise_record
    channels = {k: v for k, v in record.get("conditional", {}).items() if v is not None}
    return (f"{view.noise}, scale {record['scale']:g}" + (f", {len(record['overrides'])} overrides" if record["overrides"] else "")
            + "".join(f", {k} {v:g}" for k, v in channels.items()))


def _named_apart(views: list[ResultView]) -> list[ResultView]:
    """The views, with the noise settings added to the label of each one whose label another shares.

    Two fetched runs of one circuit, as the points of a sweep are, would otherwise read alike in the table, on the
    axis and in the warning.
    """
    labels = [view.label for view in views]
    return [replace(view, label=f"{view.label}, {_noise_settings(view)}") if labels.count(view.label) > 1 else view
            for view in views]


def compare_parts(views: list[ResultView], shown: list[Compiled] | None = None) -> list[Part]:
    """Runs side by side: a warning when their noise settings differ, a table, and a bar per run of its F.

    The first run is the reference: its noisy F raw, with one standard error, is the band. `shown`, one
    compiled circuit per run, adds each run's written circuit beside its processor graph, numbered as in
    the table.
    """
    views = _named_apart(views)
    parts: list[Part] = []
    settings = [(view.label, _noise_settings(view)) for view in views]
    if len({s for _, s in settings}) > 1:
        parts.append(markdown("**Warning: these runs differ in noise settings, so a difference between them is "
                              "conditional on that, not only on the circuits:** "
                              + "; ".join(f"{label}: {s}" for label, s in settings)))
    rows = []
    for number, view in enumerate(views, 1):
        noisy = view.scores["noisy"]
        rows.append({"#": number, "run": view.label, "processor": view.processor,
                     "F": f"{noisy.accepted.value:.4f} ± {noisy.accepted.standard_error:.4f}",
                     "F raw": f"{noisy.raw.value:.4f} ± {noisy.raw.standard_error:.4f}",
                     "acceptance": f"{noisy.acceptance:.4f}", "two-qubit gates": view.cost["two_qubit_gates"],
                     "shots per basis": f"{view.shots:,}"})
    parts.append(table(rows))
    # Bars show F on an axis that starts just below the shortest bar, not at zero: every F here lies within a few
    # hundredths of the others, and from zero the bars would all look alike. On a cut axis a bar's length no
    # longer shows its size, so the axis says where it starts, a break mark sits on it, and each bar carries its F.
    fig = Figure(figsize=(max(5.0, 1.9 * len(views) + 1.6), 4.4))
    ax = fig.subplots()
    columns = []  # per run: its bars as (fidelity, colour, acceptance text)
    for view in views:
        noisy = view.scores["noisy"]
        bars = [(noisy.raw, "#9aa6b8", "")]
        if noisy.acceptance < 1:
            bars.append((noisy.accepted, "#7139cc", f"\np {noisy.acceptance:.3f}"))
        columns.append(bars)
    lowest = min(f.value - f.standard_error for bars in columns for f, _, _ in bars)
    highest = max(f.value + f.standard_error for bars in columns for f, _, _ in bars)
    span = max(highest - lowest, 0.002)
    start = float(np.floor((lowest - 0.35 * span) / 0.005) * 0.005)  # a round number below every bar
    reference = views[0].scores["noisy"].raw
    band = ax.axhspan(reference.value - reference.standard_error, reference.value + reference.standard_error,
                      color="#e5e7eb", zorder=0)
    width = 0.36
    for x, bars in enumerate(columns):  # one column per run, in the table's order
        for k, (fidelity, color, acceptance) in enumerate(bars):
            at = x + (k - (len(bars) - 1) / 2) * width
            ax.bar(at, fidelity.value - start, bottom=start, width=0.92 * width, color=color,
                   yerr=fidelity.standard_error, ecolor="#1f2937", capsize=3, zorder=2)
            ax.text(at, fidelity.value + fidelity.standard_error, f"{fidelity.value:.4f}{acceptance}",
                    ha="center", va="bottom", fontsize=7.5)
    ax.set_xticks(range(len(views)),
                  [f"{number}. {view.label}\n{view.cost['two_qubit_gates']} two-qubit gates" for number, view in enumerate(views, 1)],
                  rotation=20, ha="right", fontsize=8)
    ax.set_xlim(-0.6, len(views) - 0.4)
    ax.set_ylim(start, highest + 0.45 * span)
    ax.set_ylabel(f"F, noisy run\n(the axis starts at {start:.3f}, not at 0)")
    for offset in (0.03, 0.055):  # the break mark on the cut axis
        ax.plot([-0.012, 0.012], [offset - 0.012, offset + 0.012], transform=ax.transAxes, color="#1f2937", lw=1, clip_on=False)
    ax.legend([band, Rectangle((0, 0), 1, 1, color="#9aa6b8"), Rectangle((0, 0), 1, 1, color="#7139cc")],
              [f"{views[0].label}: every shot ± 1 SE", "every shot", "kept shots; p is the acceptance"],
              fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.34), ncol=3, frameon=False)
    parts.append(image(fig))
    for number, (view, compiled) in enumerate(zip(views, shown or []), 1):
        parts.append(markdown(f"**{number} · {view.label}**: {compiled.circuit_file.label}"))
        parts.append(written_part(compiled, configs.load_processor(compiled.circuit_file.processor)))
    return parts


def benchmark_parts(folder: Path | str) -> list[Part]:
    """A benchmark folder: bars of F per processor on one shared axis and a case table, or, without cases, a run table.

    `folder` is a benchmark folder, or a benchmark's name, which means its current folder. Reads
    comparison.csv only, through run.read_table, so a folder made before a column was added still shows.
    """
    folder = Path(folder) if Path(folder).is_dir() else current_benchmark(str(folder))
    rows = read_table(folder / "comparison.csv")  # a run that fills no case has no case number
    title = (folder / "report.md").read_text(encoding="utf-8").splitlines()[0].lstrip("# ")
    parts = [markdown(f"**{title}** · `{configs.repo_path(folder)}`")]
    noisy = rows[rows.simulation == "noisy"].copy()
    noisy["shots per simulation"] = noisy[[f"shots_raw_{b}" for b in BASES]].sum(axis=1)
    processors = [p for p in configs.CORE_PROCESSORS if p in set(noisy.processor)]
    has_cases = rows["case"].notna().any()
    profiles = list(dict.fromkeys(noisy.noise))  # one marker shape per noise profile
    shapes = dict(zip(profiles, ["o", "s", "^", "D", "v"]))
    # Bars of F on a cut axis, as in compare: the axis says where it starts, and every value is in the table below.
    # One noise profile: a grey bar for every shot and a purple one for kept shots. Several: one colour per profile,
    # pale for every shot and solid for kept shots, and one panel per row so the bars stay wide enough to read.
    many = len(profiles) > 1
    palette = dict(zip(profiles, ["#7139cc", "#137665", "#2151c7", "#c62639", "#e07b00"]))
    low = min((noisy.fidelity_raw - noisy.fidelity_raw_se).min(), (noisy.fidelity - noisy.fidelity_se).min())
    high = max((noisy.fidelity_raw + noisy.fidelity_raw_se).max(), (noisy.fidelity + noisy.fidelity_se).max())
    span = max(high - low, 0.002)
    start = float(np.floor((low - 0.2 * span) / 0.005) * 0.005)  # a round number below every bar
    layout = (len(processors), 1) if many else (1, len(processors))
    size = (9.6, 3.3 * len(processors)) if many else (3.8 * len(processors), 4.3)
    fig = Figure(figsize=size)
    axes = fig.subplots(*layout, sharey=True, squeeze=False)
    slot = 0.8 / len(profiles)  # each circuit's column is split between the profiles
    for ax, processor in zip(axes.flat, processors):
        mine = noisy[noisy.processor == processor]
        circuits = list(dict.fromkeys(mine.circuit))  # the circuits along the axis, as the benchmark lists them
        for j, noise in enumerate(profiles):
            for row in mine[mine.noise == noise].itertuples():
                centre = circuits.index(row.circuit) - 0.4 + slot * (j + 0.5)
                bars = [(row.fidelity_raw, row.fidelity_raw_se, False)]
                if row.acceptance < 1:
                    bars.append((row.fidelity, row.fidelity_se, True))
                for k, (value, error, kept) in enumerate(bars):
                    at = centre + (k - (len(bars) - 1) / 2) * slot / 2
                    if many:
                        color = to_rgba(palette[noise], 1.0 if kept else 0.4)
                    else:
                        color = "#7139cc" if kept else "#9aa6b8"
                    ax.bar(at, value - start, bottom=start, width=0.45 * slot, color=color, yerr=error,
                           ecolor="#1f2937", capsize=2, zorder=2)
                    if not many:
                        ax.text(at, value + error, f"{value:.4f}" + (f"\np {row.acceptance:.3f}" if kept else ""),
                                ha="center", va="bottom", fontsize=6.5)
        labels = []
        for circuit in circuits:
            case = mine.loc[mine.circuit == circuit, "case"].dropna()
            labels.append(circuit.replace(f"-{processor}", "") + (f"\ncase {int(case.iloc[0])}" if len(case) else ""))
        ax.set_xticks(range(len(circuits)), labels, rotation=0 if many else 20, ha="center" if many else "right", fontsize=8)
        ax.set_xlim(-0.6, len(circuits) - 0.4)
        ax.set_title(processor, fontsize=10)
    for ax in axes[:, 0]:
        ax.set_ylim(start, high + 0.35 * span)
        ax.set_ylabel(f"F, noisy run\n(the axis starts at {start:.3f}, not at 0)", fontsize=9)
        for offset in (0.03, 0.055):  # the break mark on the cut axis
            ax.plot([-0.012, 0.012], [offset - 0.012, offset + 0.012], transform=ax.transAxes, color="#1f2937", lw=1, clip_on=False)
    patch = lambda color: Rectangle((0, 0), 1, 1, color=color)
    if many:
        handles = [patch(palette[noise]) for noise in profiles] + [patch(to_rgba("#4a5568", 0.4)), patch("#4a5568")]
        names = profiles + ["pale: every shot", "solid: kept shots"]
    else:
        handles, names = [patch("#9aa6b8"), patch("#7139cc")], ["every shot", "kept shots; p is the acceptance"]
    fig.legend(handles, names, loc="lower center", bbox_to_anchor=(0.5, -0.02 if many else -0.06), ncol=len(names),
               frameon=False, fontsize=8)
    fig.tight_layout(rect=(0, 0.03 if many else 0, 1, 1))
    parts.append(image(fig))
    if has_cases:
        cases = rows[rows["case"].notna()].copy()
        cases["case"] = cases["case"].astype(int)
        rows_shown = [{"case": r.case, "processor": r.processor, "simulation": r.simulation, "run": r.run,
                  "F": f"{r.fidelity:.4f} ± {r.fidelity_se:.4f}", "acceptance": f"{r.acceptance:.4f}",
                  "two-qubit gates": r.two_qubit_gates} for r in cases.sort_values("case").itertuples()]
    else:
        rows_shown = [{"run": r["run"], "F": f"{r['fidelity']:.4f} ± {r['fidelity_se']:.4f}", "F raw": f"{r['fidelity_raw']:.4f}",
                  "acceptance": f"{r['acceptance']:.4f}", "two-qubit gates": r["two_qubit_gates"],
                  "shots per simulation": int(r["shots per simulation"])} for r in noisy.to_dict("records")]
    parts.append(table(rows_shown))
    kinds = {noise: configs.load_noise(noise)["kind"] for noise in sorted(set(noisy.noise))}
    gate_only = [noise for noise, kind in kinds.items() if kind != "snapshot"]
    if gate_only:
        parts.append(markdown(f"{', '.join(gate_only)}: gate noise alone, with no idle or timing noise."))
    return parts


def benchmark_line_parts(name: str, noise: str, conditional: dict | None) -> list[Part]:
    """The line that adds the circuit `name` to a benchmark file's runs, under a session's noise profile and channels."""
    entry = {"run": name, "circuit": name, "noise": noise}
    channels = {channel: value for channel, value in (conditional or {}).items() if value is not None}
    if channels:
        entry["conditional"] = channels
    return [markdown(f"```yaml\n  - {yaml.dump(entry, default_flow_style=True, sort_keys=False).strip()}\n```")]
