# tests/test_workbench_class.py
"""The Workbench class: its defaults, build, show, run, fetch, compare, keep and promote, and what a result shows.

The notebook built on it is tests/test_workbench.py's. Tests that write use a
copy of config/ in a temporary root; tests that fetch read the committed
move-chain benchmark and write nothing.
"""

import pytest

from bellbench import builders, configs
from bellbench import run as run_module
from bellbench.analysis import check_flags
from bellbench.run import CircuitRun, current_benchmark, load_benchmark, read_table
from bellbench.workbench import Workbench

SHOTS = 200
# A Bell pair on ibm2016's ports 0 and 4 along 0-3-4, with an optional read of the idle qubit 1.
QASM = """OPENQASM 3.0;
include "stdgates.inc";
qubit[5] q;
{bits}h q[0];
cx q[0], q[3];
swap q[3], q[4];
{extra}"""


def _qasm(bits="", extra=""):
    return QASM.format(bits=bits, extra=extra)


def test_a_session_starts_from_the_core_benchmarks_settings():
    core, _ = load_benchmark("core")
    wb = Workbench()
    assert (wb.noise, wb.shots, wb.base_seed) == ("boston-2026", core["shots"], core["base_seed"])
    assert Workbench(noise="pauli-cx-biased", shots=500).shots == 500


def test_a_run_scores_as_circuitrun_does(config_copy):
    result = Workbench(shots=SHOTS).run("baseline-ibm2016")
    run = CircuitRun("baseline-ibm2016", "boston-2026", SHOTS, Workbench().base_seed).run()
    assert result.rows == {name: run.scores[name].row(name) for name in ("ideal", "noisy")}
    assert result.self_test is None


def test_a_run_takes_one_runs_settings_over_the_sessions(config_copy):
    wb = Workbench(shots=SHOTS)
    assert wb.run("baseline-ibm2016", shots=100).record["shots"] == 100
    assert wb.run("baseline-ibm2016", noise="organiser-cx2").label == "baseline-ibm2016 under organiser-cx2"


def test_a_result_shows_every_table_as_html_and_text(config_copy):
    wb = Workbench(shots=SHOTS)
    wb.build("trial-xx", "contemporary", builders.move_chain, (builders.bus_xx, {"on": [0, 4, 5, 6, 7]}))
    result = wb.run("trial-xx")
    titles = ["F and acceptance", "Per basis", "Cost", "Gates in each compiled basis circuit",
              "Shots each check flagged"]
    assert [title for title, _ in result.tables()] == titles
    html, text = result._repr_html_(), repr(result)
    assert all(title in html and title in text for title in titles)
    assert "Warning" not in text


def test_a_fetched_run_gives_the_recorded_numbers():
    folder = current_benchmark("move-chain") / "path-xx-ibm2016"
    result = Workbench().fetch("move-chain", "path-xx-ibm2016")
    recorded = read_table(folder / "simulations.csv").set_index("simulation")
    for name in ("ideal", "noisy"):
        assert result.rows[name]["fidelity"] == pytest.approx(recorded.loc[name, "fidelity"], abs=1e-12)
        assert result.rows[name]["acceptance"] == pytest.approx(recorded.loc[name, "acceptance"], abs=1e-12)
    assert Workbench().fetch(folder).rows == result.rows


def test_a_view_re_reads_the_counts_and_is_never_kept():
    """Plain postselection reads a three-bit XX check bit by bit and discards most of the ideal shots."""
    wb = Workbench()
    view = wb.fetch("move-chain", "spare-xx-contemporary", analysis={"name": "postselect"})
    assert view.view and "view read with postselect" in view.label
    assert view.rows["ideal"]["acceptance"] < 0.5 and "keeping" in view.self_test
    with pytest.raises(ValueError, match="not a run, so there is nothing to keep"):
        view.keep()
    with pytest.raises(ValueError, match="already holds it"):
        wb.fetch("move-chain", "spare-xx-contemporary").keep()


def test_build_saves_builder_steps_as_a_trial_with_the_builders_analysis(config_copy):
    wb = Workbench(shots=SHOTS)
    state = builders.bus_xx(builders.move_chain(builders.start("contemporary")), on=[0, 4, 5, 6, 7])
    assert wb.build("trial-xx", "contemporary", builders.move_chain, (builders.bus_xx, {"on": [0, 4, 5, 6, 7]})) \
        == "trial-xx"
    assert configs.trial_names() == ["trial-xx"]
    assert wb.show("trial-xx").circuit.analysis == state.analysis()
    wb.build("trial-xx", "contemporary", builders.move_chain)  # building a name again replaces that trial
    assert wb.show("trial-xx").circuit.analysis == {"name": "postselect"}


def test_build_saves_openqasm_text_or_a_circuit_with_its_analysis(config_copy):
    wb = Workbench(shots=SHOTS)
    wb.build("trial-qasm", _qasm(), processor="ibm2016")
    assert wb.run("trial-qasm").self_test is None
    with pytest.raises(ValueError, match="measures 1 bit"):
        wb.build("trial-read", _qasm("bit[1] check;\n", "check[0] = measure q[1];\n"), processor="ibm2016")
    wb.build("trial-read", _qasm("bit[1] check;\n", "check[0] = measure q[1];\n"), processor="ibm2016",
             analysis={"name": "postselect"})
    assert wb.show("trial-read").circuit.analysis == {"name": "postselect"}
    circuit = wb.show("trial-qasm").circuit.circuit
    wb.build("trial-circuit", circuit, processor="ibm2016")
    assert "from a Qiskit circuit" in wb.show("trial-circuit").circuit.notes


def test_build_refuses_a_committed_name_and_mixed_arguments(config_copy):
    wb = Workbench()
    with pytest.raises(ValueError, match="is a committed circuit"):
        wb.build("baseline-ibm2016", "ibm2016", builders.move_chain)
    with pytest.raises(TypeError, match="builder steps"):
        wb.build("trial", "ibm2016")
    with pytest.raises(TypeError, match="write their own analysis"):
        wb.build("trial", "ibm2016", builders.move_chain, analysis={"name": "postselect"})
    with pytest.raises(TypeError, match="not with processor="):
        wb.build("trial", _qasm(), builders.move_chain, processor="ibm2016")


def test_a_result_whose_ideal_run_fails_the_self_test_says_so(config_copy):
    wb = Workbench(shots=SHOTS)
    wb.build("lossy", _qasm("bit[1] check;\n", "h q[1];\ncheck[0] = measure q[1];\n"), processor="ibm2016",
             analysis={"name": "postselect"})
    result = wb.run("lossy")
    assert "Warning: the self-test fails" in repr(result) and "Warning" in result._repr_html_()
    table = repr(wb.compare(result, wb.run("baseline-ibm2016")))
    assert "FAILS" in table and "passes" in table


def test_keep_writes_a_trials_run_into_workspace(config_copy, monkeypatch):
    monkeypatch.setattr(run_module, "_git_state", lambda: ("abc123", False))
    wb = Workbench(shots=SHOTS)
    wb.build("trial-qasm", _qasm(), processor="ibm2016")
    folder = wb.keep(wb.run("trial-qasm"))
    assert folder.relative_to(config_copy).parts[:3] == ("workspace", "runs", "workbench")


def test_promote_moves_a_trial_into_config(config_copy):
    wb = Workbench()
    wb.build("trial-qasm", _qasm(), processor="ibm2016")
    assert wb.promote("trial-qasm").parent == config_copy / "config" / "circuit"
    assert configs.trial_names() == []


def test_show_draws_the_circuit_and_its_graph(config_copy):
    view = Workbench().show("baseline-ibm2016")
    assert view._repr_html_().count("<img") == 2
    assert "analysis {'name': 'postselect'}" in repr(view)


def test_check_flags_counts_each_check_per_basis():
    raw = {b: {"00 00": 50, "11 01": 30, "00 11": 20} for b in ("XX", "YY", "ZZ")}  # port last-first, then check
    registers = [("check", 2), ("port", 2)]
    assert check_flags({"name": "postselect"}, raw, registers) == {"check": {"XX": 50, "YY": 50, "ZZ": 50}}
    parity = {"name": "parity", "settings": {"checks": [["check[0]", "check[1]"]]}}
    assert check_flags(parity, raw, registers) == {"check[0] + check[1]": {"XX": 30, "YY": 30, "ZZ": 30}}


def test_an_analysis_that_does_not_say_what_its_checks_flag_is_refused(monkeypatch):
    from bellbench import analysis as analysis_module

    entry = analysis_module.REGISTRY["postselect"]
    monkeypatch.setitem(analysis_module.REGISTRY, "silent", analysis_module.Entry(entry.check, entry.read))
    with pytest.raises(ValueError, match="does not say which of its checks flag a shot"):
        check_flags({"name": "silent"}, {b: {"00": 1} for b in ("XX", "YY", "ZZ")}, [("port", 2)])
