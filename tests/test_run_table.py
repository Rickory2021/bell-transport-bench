# tests/test_run_table.py
"""comparison.csv's total shots, and the run table a benchmark without cases writes into report.md.

`shots_total` is the raw shots of a simulation's three bases together, placed
after `scheduled_duration` with the cost columns. A benchmark without cases
lists every run's noisy simulation in report.md; one with cases keeps its case
table alone.
"""

import yaml

from bellbench.run import BASES, COMPARISON_COLUMNS, read_table, run_benchmark

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


def test_the_total_shots_follow_the_scheduled_duration():
    i = COMPARISON_COLUMNS.index("scheduled_duration")
    assert COMPARISON_COLUMNS[i + 1] == "shots_total"


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
