# tests/test_noise.py
"""NoiseControl builds the Target and noise model its profile states, and nothing else.

Covers docs/DESIGN.md, section 4: parity with Aer's own FakeFez model apart from
readout, idle decay, asymmetric readout, what the scale factor touches, the
invalid inputs that must raise, the conditional channels, the depolarising
cross-check profile, and the export round trip with its content hashes.
Some checks read the noise model's per-instruction errors through Aer's private
`_local_quantum_errors` and `_local_readout_errors`, which hold exactly what a
simulation applies.
"""

import math
import shutil
import warnings

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.quantum_info import SuperOp
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error

from bellbench import configs
from bellbench.configs import content_hash, load_noise, noise_names, processor_names
from bellbench.noise import CONDITIONAL_CHANNELS, NoiseControl

FEZ = load_noise("fez-2025")


def _fake_fez():
    from qiskit_ibm_runtime.fake_provider import FakeFez

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return FakeFez()


def _same_channel(a, b) -> bool:
    return np.allclose(SuperOp(a).data, SuperOp(b).data, atol=1e-12)


# -- Every shipped file builds -------------------------------------------------


@pytest.mark.parametrize("noise", noise_names())
@pytest.mark.parametrize("processor", processor_names())
def test_every_profile_builds_on_every_graph(processor, noise):
    nc = NoiseControl(processor, noise)
    assert nc.target.num_qubits == nc.num_qubits == nc.graph.number_of_nodes()
    assert nc.ports == tuple(configs.load_processor(processor)["ports"])
    assert nc.has_durations == (nc.kind == "snapshot")


def test_target_coupling_is_the_graph_in_both_directions():
    nc = NoiseControl("contemporary", "fez-2025")
    directed = {qargs for qargs in nc.target["cz"]}
    assert directed == {qargs for a, b in nc.edges for qargs in ((a, b), (b, a))}


# -- Parity with Aer's FakeFez model ------------------------------------------


def test_fakefez_parity_apart_from_readout():
    """With qubits 0 and 1 and their coupler overridden to FakeFez's own values, the noise equals FakeFez's."""
    fez = _fake_fez()
    ft = fez.target
    overrides = [{"qubits": [0, 1], "field": "gates.cz.error_probability", "value": ft["cz"][(0, 1)].error}]
    for q in (0, 1):
        overrides += [
            {"qubits": [q], "field": "qubit.t1_relaxation_time", "value": ft.qubit_properties[q].t1},
            {"qubits": [q], "field": "qubit.t2_dephasing_time", "value": ft.qubit_properties[q].t2},
            {"qubits": [q], "field": "gates.sx.error_probability", "value": ft["sx"][(q,)].error},
            {"qubits": [q], "field": "gates.x.error_probability", "value": ft["x"][(q,)].error},
        ]
    ours = NoiseControl("ibm2016", "fez-2025", overrides=overrides).noise_model._local_quantum_errors
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        theirs = NoiseModel.from_backend(fez)._local_quantum_errors
    compared = 0
    for gate, qargs in [("cz", (0, 1)), ("cz", (1, 0))] + [(g, (q,)) for g in ("sx", "x", "reset") for q in (0, 1)]:
        assert _same_channel(ours[gate][qargs], theirs[gate][qargs]), f"{gate} on {qargs}"
        compared += 1
    assert compared == 8


# -- Idle decay and readout ------------------------------------------------------


def test_idle_decay_follows_t1():
    """The |1> population after a delay t is the population before it times exp(-t/T1)."""
    nc = NoiseControl("ibm2016", "fez-2025")
    t1 = FEZ["qubit"]["t1_relaxation_time"]
    sim = AerSimulator(method="density_matrix", noise_model=nc.noise_model)

    def population_of_1(delay):
        qc = QuantumCircuit(1)
        qc.x(0)
        if delay:
            qc.delay(delay, 0, unit="s")
        qc.save_density_matrix()
        return sim.run(qc).result().data()["density_matrix"].data[1, 1].real

    t = 20e-6
    assert population_of_1(t) == pytest.approx(population_of_1(0) * math.exp(-t / t1), rel=1e-9)


def test_readout_is_asymmetric():
    nc = NoiseControl("ibm2016", "fez-2025")
    p10 = FEZ["qubit"]["readout_error"]["reads_1_when_0"]
    p01 = FEZ["qubit"]["readout_error"]["reads_0_when_1"]
    assert p10 != p01
    for q in range(nc.num_qubits):
        matrix = nc.noise_model._local_readout_errors[(q,)].probabilities
        assert np.allclose(matrix, [[1 - p10, p10], [p01, 1 - p01]])
        assert nc.target["measure"][(q,)].error == pytest.approx((p10 + p01) / 2)


# -- The scale factor ------------------------------------------------------------


def test_scale_touches_errors_and_decay_rates_only():
    base = NoiseControl("contemporary", "fez-2025")
    doubled = NoiseControl("contemporary", "fez-2025", scale=2)
    for gate in FEZ["gates"]:
        for qargs, props in base.target[gate].items():
            scaled = doubled.target[gate][qargs]
            assert scaled.error == pytest.approx(2 * props.error)
            assert scaled.duration == props.duration
    for q in range(base.num_qubits):
        assert doubled.target.qubit_properties[q].t1 == pytest.approx(base.target.qubit_properties[q].t1 / 2)
        assert doubled.target.qubit_properties[q].t2 == pytest.approx(base.target.qubit_properties[q].t2 / 2)
        assert np.allclose(
            doubled.noise_model._local_readout_errors[(q,)].probabilities[0, 1],
            2 * base.noise_model._local_readout_errors[(q,)].probabilities[0, 1],
        )
        assert doubled.target["measure"][(q,)].duration == base.target["measure"][(q,)].duration
        assert doubled.target["reset"][(q,)].duration == base.target["reset"][(q,)].duration
    assert doubled.target.dt == base.target.dt
    assert all(props.error == 0 for props in doubled.target["rz"].values())


@pytest.mark.parametrize("scale", [0, -1, float("nan"), float("inf"), True, "2"])
def test_invalid_scale_raises(scale):
    with pytest.raises(ValueError, match="scale"):
        NoiseControl("ibm2016", "fez-2025", scale=scale)


def test_scale_that_makes_a_probability_invalid_raises_naming_the_field():
    with pytest.raises(ValueError, match="reads_0_when_1"):
        NoiseControl("ibm2016", "fez-2025", scale=100)


# -- Overrides ------------------------------------------------------------------


def test_override_sets_one_qubit_and_one_coupler_in_both_directions():
    nc = NoiseControl(
        "ibm2016",
        "fez-2025",
        overrides=[
            {"qubits": 3, "field": "qubit.t1_relaxation_time", "value": 100e-6},
            {"qubits": [3, 4], "field": "gates.cz.error_probability", "value": 0.01},
        ],
    )
    assert nc.target.qubit_properties[3].t1 == 100e-6
    assert nc.target.qubit_properties[2].t1 == FEZ["qubit"]["t1_relaxation_time"]
    assert nc.target["cz"][(3, 4)].error == nc.target["cz"][(4, 3)].error == 0.01
    assert nc.target["cz"][(0, 3)].error == FEZ["gates"]["cz"]["error_probability"]
    assert nc.overrides[0]["qubits"] == [3]


def test_scale_applies_after_overrides():
    override = [{"qubits": [3, 4], "field": "gates.cz.error_probability", "value": 0.01}]
    nc = NoiseControl("ibm2016", "fez-2025", scale=3, overrides=override)
    assert nc.target["cz"][(3, 4)].error == pytest.approx(0.03)


@pytest.mark.parametrize(
    "override, message",
    [
        ({"qubits": [0], "field": "qubit.t3", "value": 1.0}, "not one of"),
        ({"qubits": [0, 1], "field": "gates.cz.duration", "value": 1e-7}, "durations cannot be overridden"),
        ({"qubits": [0], "field": "measure.duration", "value": 1e-6}, "durations cannot be overridden"),
        ({"qubits": [0, 4], "field": "gates.cz.error_probability", "value": 0.01}, "not a coupler"),
        ({"qubits": [0], "field": "gates.cz.error_probability", "value": 0.01}, "takes 2"),
        ({"qubits": [0, 1], "field": "qubit.t1_relaxation_time", "value": 1e-4}, "takes 1"),
        ({"qubits": [9], "field": "qubit.t1_relaxation_time", "value": 1e-4}, "not on the processor graph"),
        ({"qubits": [0], "field": "gates.cx.error_probability", "value": 0.01}, "no gate 'cx'"),
        ({"qubits": [0], "field": "qubit.t1_relaxation_time", "value": "long"}, "finite number"),
        ({"qubits": [0], "field": "qubit.t2_dephasing_time", "value": 3 * FEZ["qubit"]["t1_relaxation_time"]}, "above 2 x"),
        ({"qubits": [0], "field": "qubit.readout_error.reads_1_when_0", "value": 1.5}, "between 0 and 1"),
        ({"qubits": [0], "field": "gates.sx.error_probability", "value": 1e-7}, "decay alone"),
        ({"qubits": [0], "field": "qubit.t1_relaxation_time"}, "exactly the keys"),
    ],
)
def test_invalid_override_raises(override, message):
    with pytest.raises(ValueError, match=message):
        NoiseControl("ibm2016", "fez-2025", overrides=[override])


def test_same_override_twice_raises():
    o = {"qubits": [1, 0], "field": "gates.cz.error_probability", "value": 0.01}
    with pytest.raises(ValueError, match="twice"):
        NoiseControl("ibm2016", "fez-2025", overrides=[o, {**o, "qubits": [0, 1]}])


def test_depolarising_profile_takes_no_overrides():
    o = {"qubits": [0], "field": "qubit.t1_relaxation_time", "value": 1e-4}
    with pytest.raises(ValueError, match="no overrides"):
        NoiseControl("ibm2016", "organiser-cx2", overrides=[o])


# -- Conditional channels -------------------------------------------------------


@pytest.mark.parametrize("channel", CONDITIONAL_CHANNELS)
def test_setting_a_conditional_channel_raises_until_it_is_built(channel):
    with pytest.raises(NotImplementedError, match=channel):
        NoiseControl("ibm2016", "fez-2025", conditional={channel: 0.01})


@pytest.mark.parametrize("conditional", [{"reset_error": 1.5}, {"reset_error": True}, {"leakage": 0.01}, [0.01]])
def test_invalid_conditional_raises(conditional):
    with pytest.raises(ValueError, match="conditional"):
        NoiseControl("ibm2016", "fez-2025", conditional=conditional)


def test_unset_conditional_channels_are_recorded():
    nc = NoiseControl("ibm2016", "fez-2025", conditional={"reset_error": None})
    assert nc.conditional == {"reset_error": None, "mid_circuit_measurement_error": None}


# -- The depolarising cross-check profile ---------------------------------------


@pytest.mark.parametrize("scale", [1, 2])
def test_depolarising_profile_puts_errors_only_after_cx(scale):
    nc = NoiseControl("contemporary", "organiser-cx2", scale=scale)
    errors = nc.noise_model._local_quantum_errors
    assert set(errors) == {"cx"}
    assert set(errors["cx"]) == {qargs for a, b in nc.edges for qargs in ((a, b), (b, a))}
    expected = depolarizing_error(0.02 * scale, 2)
    assert all(_same_channel(e, expected) for e in errors["cx"].values())
    assert not nc.noise_model._local_readout_errors and nc.noise_model._default_readout_error is None
    assert not nc.noise_model._custom_noise_passes
    assert set(nc.target.operation_names) == set(load_noise("organiser-cx2")["depolarising"]["gates"]) | {"measure"}


def test_depolarising_scale_that_exceeds_one_raises():
    with pytest.raises(ValueError, match="depolarising.probability"):
        NoiseControl("ibm2016", "organiser-cx2", scale=60)


# -- Export, rebuild and hashes --------------------------------------------------


def test_export_round_trip():
    nc = NoiseControl(
        "hyperbolic",
        "fez-2025",
        scale=1.5,
        overrides=[{"qubits": [0, 1], "field": "gates.cz.error_probability", "value": 0.005}],
    )
    record = nc.export_as_yaml()
    assert record["processor"]["path"] == "config/processor/bp.data.processor.hyperbolic.yaml"
    assert record["noise"]["hash"] == content_hash(configs.noise_path("fez-2025"))
    rebuilt = NoiseControl.from_yaml(record)
    assert rebuilt.export_as_yaml() == record
    assert rebuilt.noise_model == nc.noise_model


def test_changed_hash_is_refused():
    record = NoiseControl("ibm2016", "fez-2025").export_as_yaml()
    record["noise"]["hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="changed since it was recorded"):
        NoiseControl.from_yaml(record)


def test_record_outside_the_config_folder_is_refused():
    record = NoiseControl("ibm2016", "fez-2025").export_as_yaml()
    record["noise"]["path"] = "docs/bp.data.noise.fez-2025.yaml"
    with pytest.raises((ValueError, FileNotFoundError)):
        NoiseControl.from_yaml(record)


def test_hash_ignores_comments_but_not_values(tmp_path):
    original = configs.noise_path("fez-2025")
    copy = tmp_path / original.name
    shutil.copy(original, copy)
    text = copy.read_text(encoding="utf-8")
    copy.write_text("# an added comment\n" + text.replace("  # T1", "  # a reworded T1 comment\n  # T1"), encoding="utf-8")
    assert content_hash(copy) == content_hash(original)
    copy.write_text(text.replace("cz: {qubits: 2, error_probability: 0.0039", "cz: {qubits: 2, error_probability: 0.0049"), encoding="utf-8")
    assert content_hash(copy) != content_hash(original)
