# tests/test_workspace.py
"""Trial circuits in workspace/circuits/, `promote`, and where a run that used one lands.

A trial circuit loads by its name like a committed one, and one name is never
both; `promote` moves a trial into config/circuit/, deleting the trial only
once the written file has loaded, and puts config/circuit/ back when it does
not; a run of a trial lands in workspace/ even from a clean tree; and a
benchmark names only committed circuits.
"""

import pytest
import yaml

from bellbench import builders, configs
from bellbench import circuits as circuits_module
from bellbench import run as run_module
from bellbench.circuits import load_circuit, promote, save_circuit, swap_chain
from bellbench.run import RESULT_FILE, CircuitRun, rerun, run_benchmark

SEED = 2026
NOTES = "A test circuit."


def _trial(root, name="trial-chain"):
    return root / "workspace" / "circuits" / configs.file_name("circuit", name)


def _committed(root, name="trial-chain"):
    return root / "config" / "circuit" / configs.file_name("circuit", name)


def _save_trial(name="trial-chain", **kwargs):
    return save_circuit(name, "Trial chain", "ibm2016", swap_chain("ibm2016"), NOTES, trial=True, **kwargs)


def test_a_trial_is_saved_in_workspace_and_loads_by_its_name(config_copy):
    path = _save_trial()
    assert path == _trial(config_copy) and not _committed(config_copy).exists()
    assert path.read_text(encoding="utf-8").startswith("# workspace/circuits/bp.data.circuit.trial-chain.yaml\n")
    loaded = load_circuit("trial-chain")
    assert loaded.record["path"] == "workspace/circuits/bp.data.circuit.trial-chain.yaml"
    assert configs.trial_names() == ["trial-chain"]


def test_a_builder_saves_a_trial_with_its_analysis(config_copy):
    state = builders.ghz_uncompute(builders.start("ibm2016"))
    path = state.save("trial-ghz", "Trial GHZ", trial=True)
    assert path == _trial(config_copy, "trial-ghz")
    assert load_circuit("trial-ghz").analysis == state.analysis()


def test_a_trial_may_not_take_a_committed_circuits_name(config_copy):
    with pytest.raises(ValueError, match=r"config/circuit/bp\.data\.circuit\.baseline-ibm2016\.yaml is a committed"):
        save_circuit("baseline-ibm2016", "Trial", "ibm2016", swap_chain("ibm2016"), NOTES, trial=True)
    assert not _trial(config_copy, "baseline-ibm2016").exists()


def test_a_committed_circuit_may_not_take_a_trials_name(config_copy):
    _save_trial()
    with pytest.raises(ValueError, match=r"is a trial circuit named 'trial-chain'.*promote the trial"):
        save_circuit("trial-chain", "Trial chain", "ibm2016", swap_chain("ibm2016"), NOTES)
    assert not _committed(config_copy).exists()


def test_a_name_found_in_both_places_is_refused(config_copy):
    """A trial copied into config/circuit/ by hand, rather than promoted."""
    path = _save_trial()
    _committed(config_copy).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError, match=r"is both config/circuit/.*and the trial workspace/circuits/"):
        load_circuit("trial-chain")


def test_promote_moves_the_trial_into_config(config_copy):
    _save_trial()
    before = load_circuit("trial-chain").record["hash"]
    target = promote("trial-chain")
    assert target == _committed(config_copy) and not _trial(config_copy).exists()
    assert target.read_text(encoding="utf-8").startswith("# config/circuit/bp.data.circuit.trial-chain.yaml\n")
    after = load_circuit("trial-chain").record
    assert after["path"] == "config/circuit/bp.data.circuit.trial-chain.yaml" and after["hash"] == before
    assert configs.trial_names() == []


def test_promote_refuses_an_existing_target_unless_told_to_overwrite(config_copy):
    _save_trial()
    promote("trial-chain")
    _trial(config_copy).write_text(
        _committed(config_copy).read_text(encoding="utf-8").replace("Trial chain", "Trial again"), encoding="utf-8"
    )
    with pytest.raises(FileExistsError, match="pass overwrite=True"):
        promote("trial-chain")
    assert _trial(config_copy).exists()
    promote("trial-chain", overwrite=True)
    assert not _trial(config_copy).exists() and load_circuit("trial-chain").label == "Trial again"


def test_promote_refuses_a_name_with_no_trial(config_copy):
    with pytest.raises(FileNotFoundError, match="no trial circuit named 'missing'"):
        promote("missing")


def test_a_bad_trial_moves_nowhere(config_copy):
    path = _save_trial()
    path.write_text(path.read_text(encoding="utf-8").replace("processor: ibm2016", "processor: nowhere"), "utf-8")
    with pytest.raises(ValueError, match=r"\$\.processor"):
        promote("trial-chain")
    assert path.exists() and not _committed(config_copy).exists()


def _bad_trial_under_a_committed_circuit(root, name="baseline-ibm2016"):
    """A trial copied by hand under a committed circuit's name, naming a processor that does not exist."""
    committed = _committed(root, name).read_text(encoding="utf-8")
    trial = _trial(root, name)
    trial.parent.mkdir(parents=True)
    trial.write_text(committed.replace("processor: ibm2016", "processor: nowhere"), encoding="utf-8")
    return committed, trial.read_text(encoding="utf-8")


def test_a_failed_promote_over_a_committed_circuit_restores_it(config_copy):
    committed, trial = _bad_trial_under_a_committed_circuit(config_copy)
    with pytest.raises(ValueError, match=r"config/circuit/bp\.data\.circuit\.baseline-ibm2016\.yaml: \$\.processor"):
        promote("baseline-ibm2016", overwrite=True)
    assert _committed(config_copy, "baseline-ibm2016").read_text(encoding="utf-8") == committed
    assert _trial(config_copy, "baseline-ibm2016").read_text(encoding="utf-8") == trial


def test_the_trial_stays_until_the_promoted_file_has_loaded(config_copy, monkeypatch):
    _save_trial()
    seen = []

    def load_back(name, path=None):
        seen.append((path, _trial(config_copy).exists()))
        return load_circuit(name, path)

    monkeypatch.setattr(circuits_module, "load_circuit", load_back)
    promote("trial-chain")
    assert seen == [(_committed(config_copy), True)] and not _trial(config_copy).exists()


@pytest.mark.parametrize("over_committed", [False, True])
def test_an_interrupted_promote_moves_nowhere(config_copy, monkeypatch, over_committed):
    if over_committed:
        name = "baseline-ibm2016"
        committed, trial = _bad_trial_under_a_committed_circuit(config_copy)
    else:
        name, committed = "trial-chain", None
        trial = _save_trial().read_text(encoding="utf-8")

    def interrupted(name, path=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(circuits_module, "load_circuit", interrupted)
    with pytest.raises(KeyboardInterrupt):
        promote(name, overwrite=over_committed)
    assert _trial(config_copy, name).read_text(encoding="utf-8") == trial
    target = _committed(config_copy, name)
    assert target.read_text(encoding="utf-8") == committed if over_committed else not target.exists()


def test_a_trial_that_does_not_parse_is_refused_by_its_file(config_copy):
    path = _save_trial()
    path.write_text("name: [unclosed", encoding="utf-8")
    with pytest.raises(ValueError, match=r"workspace/circuits/bp\.data\.circuit\.trial-chain\.yaml: the trial does not"):
        promote("trial-chain")
    assert path.exists() and not _committed(config_copy).exists()


@pytest.mark.parametrize("circuit, root", [("trial-chain", "workspace"), ("baseline-ibm2016", "results")])
def test_a_run_of_a_trial_lands_in_workspace_even_from_a_clean_tree(config_copy, monkeypatch, circuit, root):
    monkeypatch.setattr(run_module, "_git_state", lambda: ("abc123", False))
    _save_trial()
    folder = CircuitRun(circuit, "boston-2026", shots=100, base_seed=SEED).run().write()
    assert folder.relative_to(config_copy).parts[0] == root


def test_a_trial_run_reruns_until_the_trial_is_promoted(config_copy, monkeypatch):
    monkeypatch.setattr(run_module, "_git_state", lambda: ("abc123", False))
    _save_trial()
    folder = CircuitRun("trial-chain", "boston-2026", shots=100, base_seed=SEED).run().write()
    assert rerun(folder)[0] == run_module.MATCH
    promote("trial-chain")
    code, lines = rerun(folder)
    assert code == run_module.REFUSED and "no longer exists" in lines[0]


def test_a_benchmark_naming_a_trial_is_refused_before_anything_runs(config_copy, monkeypatch):
    _save_trial()
    path = config_copy / "config" / "benchmark" / configs.file_name("benchmark", "with-trial")
    data = yaml.safe_load((config_copy / "config" / "benchmark" / configs.file_name("benchmark", "core")).read_text())
    data["name"] = "with-trial"
    data["runs"][0]["circuit"] = "trial-chain"
    path.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(run_module, "CircuitRun", lambda *args, **kwargs: pytest.fail("a run was built"))
    with pytest.raises(ValueError, match=r"run 'ibm2016' names the trial circuit 'trial-chain'.*promote it"):
        run_benchmark("with-trial", shots=50)
    assert not (config_copy / "workspace" / "runs").exists() and not (config_copy / "results").exists()


def test_the_record_of_a_trial_run_names_its_file_in_workspace(config_copy, monkeypatch):
    monkeypatch.setattr(run_module, "_git_state", lambda: ("abc123", False))
    _save_trial()
    folder = CircuitRun("trial-chain", "boston-2026", shots=100, base_seed=SEED).run().write()
    record = yaml.safe_load((folder / RESULT_FILE).read_text(encoding="utf-8"))
    assert record["circuit"]["path"] == "workspace/circuits/bp.data.circuit.trial-chain.yaml"
    assert record["provenance"]["uncommitted"] is False
