# tests/test_views.py
"""The views in src/bellbench/views/: what each shows, where its numbers come from, and how it is shown.

The views draw what the rest of the package computes, so each test reads a
committed run or benchmark and checks the view against the result's own
numbers. Only bellbench.workbench imports the views; they draw without pyplot,
and import IPython only at the moment a notebook shows one. The calls a
notebook already makes keep what they return: `show(...).circuit`,
`compare(...).tables`, a result's `tables()` and text. The tutorial's lesson
views display where a cell calls them.
"""

import re
import sys
from pathlib import Path

import numpy as np
import pytest
from qiskit import QuantumCircuit

from bellbench import builders
from bellbench.run import CircuitRun
from bellbench.views import base, lessons
from bellbench.views.base import View, emit, fold, markdown
from bellbench.views.compare import benchmark_line_parts, benchmark_parts, compare_parts
from bellbench.views.result import result_parts, result_view
from bellbench.views.show import Compiled, show_parts
from bellbench.workbench import Workbench

SOURCE = Path(__file__).resolve().parents[1] / "src" / "bellbench"
PROTECTED = ("move-chain", "spare-xx-contemporary")  # a committed run whose one check discards shots
CHANNEL = "mid_circuit_measurement_error"


def _kinds(parts):
    return [part.kind for part in parts]


def _text(parts):
    return "\n".join(part.text() for part in parts)


# -- Where the views sit -------------------------------------------------------------


def test_only_the_workbench_imports_the_views_and_no_view_imports_the_workbench():
    importers = {path.name for path in SOURCE.glob("*.py") if "bellbench.views" in path.read_text(encoding="utf-8")}
    assert importers == {"workbench.py"}
    for path in (SOURCE / "views").glob("*.py"):
        assert not re.search(r"^\s*(from|import) bellbench\.workbench", path.read_text(encoding="utf-8"), re.M), path


def test_no_view_draws_through_pyplot_and_ipython_is_imported_only_to_show_a_view():
    for path in (SOURCE / "views").glob("*.py"):
        code = "\n".join(line.split("#")[0] for line in path.read_text(encoding="utf-8").splitlines())
        assert not re.search(r"^\s*(from|import) matplotlib\.pyplot|\bplt\.", code, re.M), path
        ipython = re.findall(r"^(\s*)(?:from|import) IPython", code, re.M)
        assert ipython == ([" " * 8] if path.name == "base.py" else []), path  # inside emit alone


def test_a_view_prints_its_parts_as_text_where_ipython_is_absent(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "IPython.display", None)  # an import of it now raises ImportError
    emit([markdown("**F = 0.98**"), base.table([{"basis": "ZZ", "shots": 100}]), base.Part("png", "AAAA")])
    assert capsys.readouterr().out.splitlines()[0] == "**F = 0.98**"
    view = View([markdown("one line"), fold("More", "<p>inside</p><script>go()</script>")])
    assert repr(view) == "one line\nMoreinside"


def test_a_fold_keeps_its_script_after_it():
    """VS Code reads a script inside a closed fold as empty, so the script would never run there."""
    part = fold("Steps", '<div id="s">frames</div><script>(function () {})();</script>')
    assert part.content == (
        '<details><summary><b>Steps</b></summary><div id="s">frames</div></details><script>(function () {})();</script>'
    )


# -- One result ----------------------------------------------------------------------


def test_a_result_reads_point_first_with_its_own_numbers():
    result = Workbench().fetch(*PROTECTED)
    parts, noisy = result_parts(result), result.rows["noisy"]
    assert _kinds(parts) == ["markdown", "markdown", "html", "markdown", "html", "markdown", "markdown"]
    assert parts[0].content == "**move-chain-spare-xx-contemporary** under boston-2026 · 20,000 shots per basis · " \
                               "fetched from a run folder"
    low, high = noisy["acceptance_low"], noisy["acceptance_high"]
    assert parts[1].content == (
        f"**F = {noisy['fidelity']:.4f} ± {noisy['fidelity_se']:.4f} at acceptance {noisy['acceptance']:.4f}** "
        f"({low:.4f} to {high:.4f}) · F raw = {noisy['fidelity_raw']:.4f} ± {noisy['fidelity_raw_se']:.4f}"
        " · ideal run: F = 1, every shot kept ✓"
    )
    for basis in ("ZZ", "XX", "YY"):
        assert f"<td>{noisy[f'shots_accepted_{basis}']}</td>" in parts[2].content
    assert parts[3].content == "Shots each check flagged, noisy run:"
    assert parts[5].content.startswith(f"Cost: {result.record['cost']['two_qubit_gates']} two-qubit gates · ")
    assert "60,000 shots per simulation" in parts[5].content
    assert parts[6].content.startswith("± is one standard error")


def test_a_result_that_keeps_every_shot_says_so_and_shows_no_check_table():
    parts = result_parts(Workbench().fetch("move-chain", "baseline-ibm2016"))
    assert _kinds(parts) == ["markdown", "markdown", "html", "markdown", "markdown"]
    assert re.fullmatch(r"\*\*F = 0\.\d{4} ± 0\.\d{4}\*\*, every shot kept · ideal run: F = 1, every shot kept ✓",
                        parts[1].content)


def test_a_result_warns_first_when_its_ideal_run_is_not_perfect_or_its_pair_is_off_the_ports():
    wb = Workbench()
    view = wb.fetch(*PROTECTED, analysis={"name": "postselect"})  # reads the check bit by bit: half the ideal shots
    assert result_parts(view)[0].content.startswith("**Warning: the ideal run is not perfect: F = ")
    off = wb.fetch("move-chain", "baseline-ibm2016")
    off.record["cost"]["pair_on_ports"] = False
    assert result_parts(off)[0].content == "**Warning: after routing the pair is not on the ports.**"


def test_a_result_under_a_profile_without_durations_says_its_noise_is_gate_noise_alone():
    text = _text(result_parts(Workbench().fetch("biased-noise", "baseline-ibm2016-cx-biased")))
    assert "not scheduled" in text
    assert "pauli-cx-biased is a pauli profile: gate noise alone, with no idle or timing noise." in text


def test_a_result_shows_the_new_layout_in_a_notebook_and_keeps_its_tables_and_text(monkeypatch):
    from bellbench import workbench as workbench_module

    shown = []
    monkeypatch.setattr(workbench_module, "emit", shown.append)
    result = Workbench().fetch(*PROTECTED)
    result._ipython_display_()
    assert _kinds(shown[0]) == _kinds(result_parts(result))
    assert [title for title, _ in result.tables()][0] == "F and acceptance" and "F and acceptance" in repr(result)
    assert "<table" in result._repr_html_()


# -- A circuit before it runs --------------------------------------------------------


def test_show_draws_a_header_the_written_circuit_and_the_cost_without_simulating():
    run = CircuitRun("move-chain-spare-xx-contemporary", "boston-2026", shots=50, base_seed=7).compile()
    parts = show_parts(Compiled.of_run(run))
    assert _kinds(parts) == ["markdown", "png", "markdown", "html"] and run.simulations == {}
    assert parts[0].content.startswith("**move-chain-spare-xx-contemporary**: ")
    assert "contemporary, ports 0 and 7, 4 hops · read by `parity`, 1 check group · compiled now under boston-2026, " \
           "base seed 7" in parts[0].content
    cost = run.cost
    assert parts[2].content.startswith(f"Cost: {cost['two_qubit_gates']} two-qubit gates · {cost['swaps']} SWAPs")
    assert "pair on the ports ✓" in parts[2].content and "compiled ZZ" in parts[3].content


def test_shows_debug_views_are_folded_and_the_stepper_script_follows_its_fold():
    run = CircuitRun("move-chain-ibm2016", "boston-2026", shots=50, base_seed=7).compile()
    parts = show_parts(Compiled.of_run(run), step=True, compiled="all", timeline="all")
    folds = [part.content for part in parts[4:]]
    assert [re.match(r"<details><summary><b>(.*?)</b>", f)[1] for f in folds] == [
        "Step-through of the written circuit (ideal, no noise)", "Compiled circuits",
        "Timelines of the compiled circuits",
    ]
    assert folds[0].index("</details>") < folds[0].index("<script>") and "<script>" not in folds[1]
    assert folds[1].count("<img") == 3 and folds[2].count("<img") == 3
    only_zz = show_parts(Compiled.of_run(run), compiled=True, timeline=True)
    assert only_zz[4].content.count("<img") == 1 and "Timeline of the compiled ZZ circuit" in only_zz[5].content
    assert "XX: the same" in only_zz[4].content


def test_show_of_a_result_reads_its_record_and_a_profile_without_durations_has_no_timeline():
    result = Workbench().fetch("biased-noise", "baseline-ibm2016-cx-biased")
    parts = show_parts(Compiled.of_record(result.record, fresh=False), timeline=True)
    assert "a fetched run" in parts[0].content and "not scheduled" in parts[2].content
    assert "No timeline: pauli-cx-biased has no durations" in parts[4].content


# -- Runs side by side ---------------------------------------------------------------


def test_compare_numbers_its_runs_and_takes_the_first_as_the_reference():
    wb = Workbench()
    results = [wb.fetch("move-chain", run) for run in ("baseline-contemporary", "spare-xx-contemporary")]
    parts = compare_parts([result_view(r) for r in results])
    assert _kinds(parts) == ["html", "png"]  # the same noise settings, so no warning
    assert ">1</td>" in parts[0].content and "baseline-contemporary (fetched)" in parts[0].content
    noisy = results[1].rows["noisy"]
    assert f"{noisy['fidelity']:.4f} ± {noisy['fidelity_se']:.4f}" in parts[0].content
    with_circuits = compare_parts([result_view(r) for r in results],
                                  [Compiled.of_record(r.record, fresh=False) for r in results])
    assert _kinds(with_circuits) == ["html", "png", "markdown", "png", "markdown", "png"]
    assert with_circuits[4].content.startswith("**2 · move-chain-spare-xx-contemporary (fetched)**: ")


def test_compare_warns_when_noise_settings_differ_and_tells_same_named_runs_apart():
    wb = Workbench()
    points = [wb.fetch("mid-circuit-sweep", f"path-xx-ibm2016-mcm-{error}") for error in ("0", "5e-2")]
    parts = compare_parts([result_view(r) for r in points])
    assert _kinds(parts) == ["markdown", "html", "png"]
    name = "move-chain-path-xx-ibm2016 (fetched), boston-2026, scale 1"
    assert parts[0].content == (
        "**Warning: these runs differ in noise settings, so a difference between them is conditional on that, not "
        f"only on the circuits:** {name}, {CHANNEL} 0: boston-2026, scale 1, {CHANNEL} 0; "
        f"{name}, {CHANNEL} 0.05: boston-2026, scale 1, {CHANNEL} 0.05"
    )
    assert f"{name}, {CHANNEL} 0</td>" in parts[1].content and f"{name}, {CHANNEL} 0.05</td>" in parts[1].content


def test_a_benchmark_with_cases_shows_its_case_table_and_a_study_its_run_table():
    cases = benchmark_parts("move-chain")
    assert _kinds(cases) == ["markdown", "png", "html"]
    assert cases[0].content.startswith("**Move chain with an XX check, the nine cases** · `results/runs/benchmark/")
    assert cases[2].content.count("<tr>") == 9 and "<th>case</th>" in cases[2].content
    study = benchmark_parts("biased-noise")
    assert _kinds(study) == ["markdown", "png", "html", "markdown"]
    assert study[2].content.count("<tr>") == 27 and "<th>shots per simulation</th>" in study[2].content
    assert study[3].content.endswith(": gate noise alone, with no idle or timing noise.")


def test_the_benchmark_line_is_built_from_the_sessions_noise_settings():
    assert benchmark_line_parts("my-circuit", "boston-2026", None)[0].content == (
        "```yaml\n  - {run: my-circuit, circuit: my-circuit, noise: boston-2026}\n```"
    )
    line = benchmark_line_parts("my-circuit", "boston-2026", {CHANNEL: 0.01, "reset_error": None})[0].content
    assert line == ("```yaml\n  - {run: my-circuit, circuit: my-circuit, noise: boston-2026, conditional: "
                    "{mid_circuit_measurement_error: 0.01}}\n```")


# -- Through the Workbench -----------------------------------------------------------


def test_the_workbench_offers_the_views_and_keeps_what_its_calls_return(monkeypatch):
    from bellbench import workbench as workbench_module

    shown = []
    monkeypatch.setattr(workbench_module, "emit", shown.append)
    wb = Workbench(shots=50)
    assert wb.builders is builders and Workbench.builders is builders
    view = wb.show("move-chain-ibm2016", step=True)
    assert view.circuit.name == "move-chain-ibm2016" and view._repr_html_().count("<img") == 2  # as before
    view._ipython_display_()
    assert _kinds(shown[-1]) == ["markdown", "png", "markdown", "html", "html"]
    results = [wb.fetch("move-chain", run) for run in ("baseline-ibm2016", "move-ibm2016")]
    table = wb.compare(*results, circuits=True)
    assert "Comparison, noisy simulations" in repr(table) and len(table.tables) == 1  # as before
    table._ipython_display_()
    assert _kinds(shown[-1]) == ["html", "png", "markdown", "png", "markdown", "png"]
    wb.show(results[0])._ipython_display_()
    assert "a fetched run" in shown[-1][0].content
    assert _kinds(wb.benchmark("move-chain").parts) == ["markdown", "png", "html"]
    assert "noise: boston-2026" in repr(wb.benchmark_line("my-circuit"))


def test_show_does_not_compile_until_a_notebook_shows_it(monkeypatch):
    """A notebook written against the plain Workbench calls show for circuits it then reads, not displays."""
    from bellbench import workbench as workbench_module

    monkeypatch.setattr(workbench_module.CircuitRun, "compile", lambda self: pytest.fail("show compiled"))
    assert Workbench().show("move-chain-path-xx-ibm2016").circuit.processor == "ibm2016"


# -- The tutorial's lesson views ------------------------------------------------------


@pytest.fixture
def shown(monkeypatch):
    """The parts the lesson views display, in order, instead of displaying them."""
    parts = []
    monkeypatch.setattr(lessons, "emit", parts.extend)
    return parts


def test_tex_writes_a_vector_as_a_column_and_takes_a_shared_size_out_in_front():
    assert lessons.tex(np.array([1, 1j]) / np.sqrt(2)) == r"\frac{1}{\sqrt{2}}\begin{pmatrix} 1 \\ i \end{pmatrix}"
    assert lessons.tex(np.array([[0, 1], [1, 0]])) == r"\begin{pmatrix} 0 & 1 \\ 1 & 0 \end{pmatrix}"
    assert lessons.tex(np.array([1, -1, 1, -1]) / 2).startswith(r"\frac{1}{2}\begin{pmatrix} 1 \\ -1")
    assert lessons.tex(np.array([0.6, 0.8])) == r"\begin{pmatrix} 0.6 \\ 0.8 \end{pmatrix}"  # no shared size


def test_matrix_of_orders_rows_and_columns_with_qubit_0_first():
    cx = QuantumCircuit(2)
    cx.cx(0, 1)  # control qubit 0: |10> and |11> swap when qubit 0 is written first
    assert np.array_equal(lessons.matrix_of(cx), [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]])


def test_whole_writes_a_whole_expectation_value_with_a_true_minus_sign():
    assert [lessons.whole(v) for v in (0.9999999, -1.0000001, 1e-12, -1e-12)] == ["+1", "−1", "0", "0"]


def test_algebra_shows_one_equation_per_line(shown):
    lessons.algebra("a = b", r"c = \frac{1}{2}")
    assert [(part.kind, part.content) for part in shown] == [("latex", "a = b"), ("latex", r"c = \frac{1}{2}")]


def test_the_steppers_show_one_frame_per_gate_and_say_where_they_stop(shown):
    one = QuantumCircuit(1)
    one.h(0)
    one.s(0)
    lessons.bloch_steps(one, notes=["start", "after H", "after S"])
    assert _kinds(shown) == ["stepper"] and shown[0].still  # a still for a viewer without HTML
    assert all(f"after {gate}" in shown[0].content for gate in "HS") and shown[0].content.count("data:image/png") >= 1
    with pytest.raises(ValueError, match="the Bloch sphere draws one qubit"):
        lessons.bloch_steps(QuantumCircuit(2), notes=[])
    shown.clear()
    stopped = QuantumCircuit(2, 1)
    stopped.h(0)
    stopped.measure(0, 0)
    stopped.cx(0, 1)
    lessons.state_steps(stopped, notes=["start", "after H"])
    assert _kinds(shown) == ["stepper", "markdown"]
    assert shown[1].content == "The step-through stops at a measure on qubit 0, before the end of the circuit."


def test_journey_shows_a_circuit_on_its_processor_graph(shown):
    pair = QuantumCircuit(5)
    pair.h(0)
    pair.cx(0, 3)
    lessons.journey(pair, "ibm2016", "a pair on 0 and 3")
    assert _kinds(shown) == ["html"] and "a pair on 0 and 3" in shown[0].content and "<script>" in shown[0].content
