# tests/test_run_table.py
"""comparison.csv's total shots, and the run table a benchmark without cases writes into report.md.

`shots_total` is the raw shots of a simulation's three bases together, placed
after `scheduled_duration` with the cost columns. A table written before the
column was added still reads, without it, as every committed one does. A
benchmark without cases lists every run's noisy simulation in report.md; one
with cases keeps its case table alone.
"""

import csv
from pathlib import Path

import pytest
import yaml

from bellbench.run import ADDED_COLUMNS, BASES, COMPARISON_COLUMNS, read_table, run_benchmark

COMMITTED = Path(__file__).resolve().parents[1] / "results" / "runs" / "benchmark"
BEFORE_TOTAL_SHOTS = tuple(c for c in COMPARISON_COLUMNS if c != "shots_total")

RUNS = [
    {"run": "ibm2016", "circuit": "baseline-ibm2016", "noise": "boston-2026"},
    {"run": "contemporary", "circuit": "baseline-contemporary", "noise": "boston-2026"},
]


def _write_benchmark(root, name, runs, cases=()):
    data = {"name": name, "label": "Test study", "notes": "A test benchmark.", "shots": 100, "base_seed": 7,
            "runs": runs}
    if cases:
        data["cases"] = list(cases)
    path = root / "config" / "benchmark" / f"bp.data.benchmark.{name}.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _write_table(path, header):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerow(["3" if c == "case" else "x" if c in ("run", "circuit") else "1" for c in header])
    return path


def test_the_total_shots_follow_the_scheduled_duration():
    i = COMPARISON_COLUMNS.index("scheduled_duration")
    assert COMPARISON_COLUMNS[i + 1] == "shots_total"
    assert ADDED_COLUMNS["comparison.csv"] == ("shots_total",)


def test_every_committed_comparison_table_reads():
    """Committed folders are never edited, so each keeps the header it was written with."""
    tables = sorted(COMMITTED.glob("*/*/comparison.csv"))
    assert {p.parts[-3] for p in tables} == {
        "core", "move-chain", "biased-noise", "mid-circuit-sweep", "starting-excitation", "middle-out",
        "vacancy-read",
    }
    for path in tables:
        table = read_table(path)
        assert tuple(table.columns) in (COMPARISON_COLUMNS, BEFORE_TOTAL_SHOTS), path
        assert len(table) and table["run"].map(type).eq(str).all() and table["fidelity"].dtype == float, path


def test_a_table_written_before_the_total_shots_reads_without_them(tmp_path):
    table = read_table(_write_table(tmp_path / "comparison.csv", BEFORE_TOTAL_SHOTS))
    assert tuple(table.columns) == BEFORE_TOTAL_SHOTS and table["case"][0] == 3 and table["run"][0] == "x"


@pytest.mark.parametrize(
    "header",
    [
        tuple(c for c in COMPARISON_COLUMNS if c != "depth"),                   # a column that was never added later
        tuple(c for c in BEFORE_TOTAL_SHOTS if c != "depth"),
        (*BEFORE_TOTAL_SHOTS, "shots_total"),                                   # the added column, out of its place
        tuple("total" if c == "shots_total" else c for c in COMPARISON_COLUMNS),  # the added column, renamed
    ],
)
def test_a_table_missing_any_other_column_is_still_refused(tmp_path, header):
    with pytest.raises(ValueError, match="the header is not the declared columns of comparison.csv"):
        read_table(_write_table(tmp_path / "comparison.csv", header))


def test_the_total_shots_are_the_three_bases_raw_shots(config_copy):
    _write_benchmark(config_copy, "study", RUNS)
    table = read_table(run_benchmark("study", config_copy / "results", shots=50) / "comparison.csv")
    raw = sum(table[f"shots_raw_{b}"] for b in BASES)
    assert (table["shots_total"] == raw).all() and (table["shots_total"] == 150).all()


def test_a_study_report_lists_every_runs_noisy_simulation(config_copy):
    _write_benchmark(config_copy, "study", RUNS)
    folder = run_benchmark("study", config_copy / "results", shots=50)
    report = (folder / "report.md").read_text(encoding="utf-8")
    table = read_table(folder / "comparison.csv")
    assert "| Run | F | Standard error | F raw | Acceptance | Two-qubit gates | Total shots |" in report
    for _, r in table[table["simulation"] == "noisy"].iterrows():
        row = (f"| {r['run']} | {r['fidelity']:.4f} | {r['fidelity_se']:.4f} | {r['fidelity_raw']:.4f} | "
               f"{r['acceptance']:.4f} | {r['two_qubit_gates']} | {r['shots_total']} |")
        assert row in report
    assert sum(line.startswith("| ") for line in report.splitlines()) == 1 + len(RUNS)


def test_a_benchmark_with_cases_keeps_its_case_table_alone(config_copy):
    _write_benchmark(config_copy, "cased", RUNS[:1], [{"case": 1, "run": "ibm2016", "simulation": "ideal"}])
    report = (run_benchmark("cased", config_copy / "results", shots=50) / "report.md").read_text(encoding="utf-8")
    assert "| Case | Processor |" in report and "| Run | F |" not in report
