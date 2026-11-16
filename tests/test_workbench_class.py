# tests/test_workbench_class.py
"""The Workbench class: its defaults, build, show, run, fetch, compare, keep and promote, and what a result shows.

The notebook built on it is tests/test_workbench.py's. Tests that write use a
copy of config/ in a temporary root; tests that fetch read the committed
move-chain benchmark and write nothing.
"""

import shutil
from pathlib import Path

import pytest
import yaml

from bellbench import builders, configs
from bellbench import run as run_module
from bellbench.analysis import check_flags, read_shots
from bellbench.fidelity import BASES
from bellbench.run import CircuitRun, current_benchmark, load_benchmark, read_table, rerun
from bellbench.workbench import Workbench

SHOTS = 200
OVERRIDE = {"qubits": [0, 3], "field": "gates.cz.error_probability", "value": 0.05}
CHANNEL = "mid_circuit_measurement_error"
PROTECTED = ("move-chain", "spare-xx-contemporary")  # a committed run whose one check discards shots
COMMITTED = sorted((Path(__file__).resolve().parents[1] / "results/runs/benchmark/move-chain").glob("*"))[-1]
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


def _settings(result):
    """The settings a run record holds: its base seed, scale, overrides and one conditional channel."""
    noise = result.record["noise_control"]
    return result.record["base_seed"], noise["scale"], noise["overrides"], noise["conditional"][CHANNEL]


def test_a_run_takes_every_setting_of_the_session(config_copy):
    wb = Workbench(shots=SHOTS, base_seed=7, scale=3.0, overrides=[OVERRIDE], conditional={CHANNEL: 0.02})
    assert _settings(wb.run("baseline-ibm2016")) == (7, 3.0, [OVERRIDE], 0.02)


def test_every_setting_given_for_one_run_wins_over_the_sessions(config_copy):
    wb = Workbench(shots=SHOTS, base_seed=7, scale=3.0, overrides=[OVERRIDE], conditional={CHANNEL: 0.02})
    result = wb.run("baseline-ibm2016", base_seed=8, scale=2.0, overrides=[], conditional={CHANNEL: 0.01})
    assert _settings(result) == (8, 2.0, [], 0.01)
    assert result.record["seeds"] != wb.run("baseline-ibm2016").record["seeds"]


def test_a_label_names_each_noise_setting_that_is_not_the_default(config_copy):
    wb = Workbench(shots=SHOTS)
    assert wb.run("baseline-ibm2016").label == "baseline-ibm2016 under boston-2026"
    assert wb.run("baseline-ibm2016", scale=3.0).label == "baseline-ibm2016 under boston-2026, scale 3"
    result = wb.run("baseline-ibm2016", scale=0.5, overrides=[OVERRIDE], conditional={CHANNEL: 0.02})
    assert result.label == f"baseline-ibm2016 under boston-2026, scale 0.5, 1 override, {CHANNEL} 0.02"
    assert repr(result).splitlines()[0] == result.label


def test_the_points_of_a_committed_sweep_read_apart():
    wb = Workbench()
    points = [wb.fetch("mid-circuit-sweep", f"path-xx-ibm2016-mcm-{error}") for error in ("0", "5e-2")]
    circuit = "move-chain-path-xx-ibm2016 under boston-2026"
    assert [p.label for p in points] == [f"{circuit}, {CHANNEL} 0", f"{circuit}, {CHANNEL} 0.05"]
    (_, compared), = wb.compare(*points).tables
    assert list(compared["result"]) == [p.label for p in points]
    view = wb.fetch("mid-circuit-sweep", "path-xx-ibm2016-mcm-5e-2", analysis={"name": "postselect"})
    assert view.label == f"{circuit}, {CHANNEL} 0.05, view read with postselect"


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


def test_a_run_whose_circuit_file_changed_is_not_fetched(config_copy):
    wb = Workbench()
    assert wb.fetch(COMMITTED / "baseline-ibm2016").self_test is None
    path = config_copy / "config" / "circuit" / configs.file_name("circuit", "baseline-ibm2016")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    path.write_text(yaml.safe_dump(data | {"label": "Another circuit"}, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match=r"bp\.data\.circuit\.baseline-ibm2016\.yaml changed since it was recorded"):
        wb.fetch(COMMITTED / "baseline-ibm2016")


def _copied_run(tmp_path, edit=lambda record: None):
    """A committed run folder copied out of the repo, its record changed by `edit`."""
    folder = tmp_path / "run"
    shutil.copytree(COMMITTED / "baseline-ibm2016", folder)
    record = yaml.safe_load((folder / run_module.RESULT_FILE).read_text(encoding="utf-8"))
    edit(record)
    (folder / run_module.RESULT_FILE).write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    return folder


@pytest.mark.parametrize("edit, message", [
    (lambda r: r.update(result_format=1), "the run was recorded in result format 1, and this code reads format 2"),
    (lambda r: r.pop("seeds"), r"the run record: \$: 'seeds' is a required property"),
    (lambda r: r.update(stray=1), r"the run record: \$: Additional properties are not allowed"),
])
def test_fetch_refuses_a_run_folder_in_the_words_a_rerun_and_a_redraw_use(tmp_path, edit, message):
    assert Workbench().fetch(_copied_run(tmp_path / "good")).self_test is None
    folder = _copied_run(tmp_path, edit)
    with pytest.raises(ValueError, match=message) as refusal:
        Workbench().fetch(folder)
    assert rerun(folder) == (run_module.REFUSED, [f"refused: {refusal.value}"])
    with pytest.raises(ValueError, match=message):
        run_module.write_views(folder)


def test_fetch_says_a_runs_circuit_file_is_gone_as_a_rerun_does(config_copy):
    (config_copy / "config" / "circuit" / configs.file_name("circuit", "move-chain-ibm2016")).unlink()
    with pytest.raises(FileNotFoundError, match=r"move-chain-ibm2016\.yaml recorded by the run no longer exists") as gone:
        Workbench().fetch(COMMITTED / "move-ibm2016")
    assert rerun(COMMITTED / "move-ibm2016") == (run_module.REFUSED, [f"refused: {gone.value}"])


def test_fetch_refuses_an_analysis_given_as_text_and_names_the_runs_of_a_benchmark():
    wb = Workbench()
    with pytest.raises(ValueError, match=r"analysis= is a mapping \{name, settings\}.*got 'postselect'"):
        wb.fetch("move-chain", "baseline-contemporary", analysis="postselect")
    with pytest.raises(FileNotFoundError, match=r"benchmark 'move-chain' has no run 'move-chain-contemporary' in "
                                                r"results/runs/benchmark/move-chain/.*run id: .*move-contemporary"):
        wb.fetch("move-chain", "move-chain-contemporary")
    with pytest.raises(FileNotFoundError, match=r"bp\.data\.result\.yaml does not exist; give a run folder"):
        wb.fetch(COMMITTED)


def test_a_results_tables_and_compare_hold_its_numbers():
    wb = Workbench()
    result = wb.fetch(*PROTECTED)
    tables = dict(result.tables())
    for name, row in result.rows.items():
        summary = tables["F and acceptance"].loc[name]
        assert summary["F"] == row["fidelity"] and summary["F standard error"] == row["fidelity_se"]
        assert summary["F raw"] == row["fidelity_raw"] and summary["F raw standard error"] == row["fidelity_raw_se"]
        assert summary["acceptance"] == row["acceptance"]
        assert summary["acceptance 95% interval"] == f"{row['acceptance_low']:.4f} to {row['acceptance_high']:.4f}"
        assert summary["total shots"] == sum(row[f"shots_raw_{b}"] for b in BASES) == 3 * result.record["shots"]
        for b in BASES:
            basis = tables["Per basis"].loc[(name, b)]
            assert basis["shots"] == row[f"shots_raw_{b}"] and basis["kept"] == row[f"shots_accepted_{b}"]
            assert basis["correlator (kept)"] == row[f"corr_{b}"]
    noisy, cost = result.rows["noisy"], result.record["cost"]
    assert all(noisy[f"shots_accepted_{b}"] < noisy[f"shots_raw_{b}"] for b in BASES)  # so kept is not raw
    assert tables["Cost"].iloc[0]["two-qubit gates"] == cost["two_qubit_gates"]
    assert tables["Cost"].iloc[0]["depth"] == cost["depth"]
    (label, flagged), = check_flags(result.analysis, result.raw["noisy"], result.registers).items()
    assert tables["Shots each check flagged"].loc[label, "noisy ZZ"] == flagged["ZZ"] > 0
    (_, compared), = wb.compare(result).tables
    row = compared.iloc[0]
    assert (row["F"], row["standard error"], row["F raw"]) == (
        noisy["fidelity"], noisy["fidelity_se"], noisy["fidelity_raw"]
    )
    assert (row["acceptance"], row["two-qubit gates"]) == (noisy["acceptance"], cost["two_qubit_gates"])
    assert row["total shots"] == 3 * result.record["shots"] and row["self-test"] == "passes"


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


def test_build_answers_three_argument_mistakes_in_its_own_words(config_copy):
    wb = Workbench()
    with pytest.raises(TypeError, match=r"with processor=\.\.\., the second argument is OpenQASM text or a Qiskit"):
        wb.build("trial", builders.move_chain, processor="ibm2016")  # a builder where the circuit goes
    with pytest.raises(TypeError, match="the second argument reads as OpenQASM text; pass the text with processor="):
        wb.build("trial", _qasm(), builders.move_chain)  # OpenQASM text where the processor's name goes
    for step in ([builders.move_chain, {}], (builders.move_chain,), ("move_chain", {}), (builders.move_chain, "on")):
        with pytest.raises(TypeError, match=r"a builder step is a function .* or a \(function, keyword arguments\)"):
            wb.build("trial", "ibm2016", step)
    assert configs.trial_names() == []  # nothing was saved
    with pytest.raises(FileNotFoundError, match="no processor file named 'ibm2061'"):
        wb.build("trial", "ibm2061", builders.move_chain)  # a misspelt processor keeps its own message
    assert wb.build("trial", "ibm2016", builders.move_chain, (builders.bus_xx, {})) == "trial"


def test_a_result_whose_ideal_run_fails_the_self_test_says_so(config_copy):
    wb = Workbench(shots=SHOTS)
    wb.build("lossy", _qasm("bit[1] check;\n", "h q[1];\ncheck[0] = measure q[1];\n"), processor="ibm2016",
             analysis={"name": "postselect"})
    result = wb.run("lossy")
    assert "Warning: the self-test fails" in repr(result) and "Warning" in result._repr_html_()
    table = repr(wb.compare(result, wb.run("baseline-ibm2016")))
    assert "FAILS" in table and "passes" in table


def test_a_result_whose_pair_ends_off_its_ports_fails_the_self_test():
    wb = Workbench()
    result = wb.fetch("move-chain", "baseline-ibm2016")
    assert result.self_test is None
    result.record["cost"]["pair_on_ports"] = False  # as a run records routing that left the pair elsewhere
    assert result.self_test == "the pair ends off its ports"
    assert "Warning: the self-test fails: the pair ends off its ports" in repr(result)
    assert "FAILS" in repr(wb.compare(result))


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


def test_show_sizes_the_circuit_drawing_from_its_content(monkeypatch):
    """A figure of one fixed size, 3.5 inches high, squeezed a larger circuit until its register's name was cut."""
    from bellbench import workbench as workbench_module

    sizes, real = [], workbench_module.drawn_figure
    monkeypatch.setattr(workbench_module, "drawn_figure", lambda draw, size: sizes.append(size) or real(draw, size))
    wb = Workbench()
    small, large = (wb.show(name)._figures()[0] for name in ("baseline-ibm2016", "move-chain-spare-xx-contemporary"))
    assert sizes[0] is sizes[2] is run_module.circuit_size  # sized as a run folder's circuit views are
    height = [int.from_bytes(png[20:24], "big") for png in (small, large)]  # a PNG's height in pixels
    assert height[0] < 3.5 * 110 < height[1]  # at show's 110 dots per inch


def test_check_flags_counts_each_check_per_basis():
    # Port last-first, then check. The flagged and unflagged shots differ in number, so a flag cannot pass as
    # its opposite: 40 shots read a check bit as 1, and 60 read none.
    raw = {b: {"00 00": 60, "11 01": 30, "00 11": 10} for b in ("XX", "YY", "ZZ")}
    registers = [("check", 2), ("port", 2)]
    assert check_flags({"name": "postselect"}, raw, registers) == {"check": {"XX": 40, "YY": 40, "ZZ": 40}}
    parity = {"name": "parity", "settings": {"checks": [["check[0]", "check[1]"]]}}
    assert check_flags(parity, raw, registers) == {"check[0] + check[1]": {"XX": 30, "YY": 30, "ZZ": 30}}


def test_the_shots_no_check_flags_are_the_shots_kept():
    """With one check, a shot is either flagged by it or kept, under each analysis and on a committed run."""
    raw = {b: {"00 00": 60, "11 01": 30, "00 11": 10} for b in BASES}
    registers = [("check", 2), ("port", 2)]
    for spec in ({"name": "postselect"}, {"name": "parity", "settings": {"checks": [["check[0]", "check[1]"]]}}):
        (flagged,) = check_flags(spec, raw, registers).values()
        kept = read_shots(spec, raw, registers, 100).kept
        assert all(flagged[b] + sum(kept[b].values()) == 100 for b in BASES)
    result = Workbench().fetch(*PROTECTED)
    for name, row in result.rows.items():
        (flagged,) = check_flags(result.analysis, result.raw[name], result.registers).values()
        assert all(flagged[b] + row[f"shots_accepted_{b}"] == row[f"shots_raw_{b}"] for b in BASES)


def test_an_analysis_that_does_not_say_what_its_checks_flag_is_refused(monkeypatch):
    from bellbench import analysis as analysis_module

    entry = analysis_module.REGISTRY["postselect"]
    monkeypatch.setitem(analysis_module.REGISTRY, "silent", analysis_module.Entry(entry.check, entry.read))
    with pytest.raises(ValueError, match="does not say which of its checks flag a shot"):
        check_flags({"name": "silent"}, {b: {"00": 1} for b in ("XX", "YY", "ZZ")}, [("port", 2)])
