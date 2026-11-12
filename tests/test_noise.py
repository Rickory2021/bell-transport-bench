# tests/test_noise.py
"""NoiseControl builds the Target and noise model its profile states, and nothing else.

Covers docs/DESIGN.md, section 4: parity with Aer's own FakeFez model apart from
readout, idle decay, asymmetric readout, what the scale factor touches, the
invalid inputs that must raise, the conditional channels, the depolarising
cross-check profile, the pauli kind with its noise bias, and the export round
trip with its content hashes.
Some checks read the noise model's per-instruction errors through Aer's private
`_local_quantum_errors` and `_local_readout_errors`, which hold exactly what a
simulation applies.
"""

import copy
import math
import shutil
import warnings

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.quantum_info import Chi, Pauli, SuperOp
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error, pauli_error

from bellbench import configs
from bellbench import noise as noise_module
from bellbench.configs import content_hash, load_noise, noise_names, processor_names
from bellbench.circuits import swap_chain
from bellbench.noise import CONDITIONAL_CHANNELS, MID_CIRCUIT_LABEL, NoiseControl
from bellbench.pipeline import basis_circuits, compile_bases, port_density_matrix

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
        for misread in ((0, 1), (1, 0)):  # reads 1 when 0, and reads 0 when 1
            assert np.allclose(
                doubled.noise_model._local_readout_errors[(q,)].probabilities[misread],
                2 * base.noise_model._local_readout_errors[(q,)].probabilities[misread],
            )
        assert doubled.target["measure"][(q,)].duration == base.target["measure"][(q,)].duration
        assert doubled.target["reset"][(q,)].duration == base.target["reset"][(q,)].duration
    assert doubled.target.dt == base.target.dt
    assert all(props.error == 0 for props in doubled.target["rz"].values())


@pytest.mark.parametrize("scale", [0, -1, float("nan"), float("inf"), True, np.bool_(True), "2"])
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
        ({"qubits": [0], "field": "gates.sx.error_probability", "value": 1.5}, r"gates.sx.error_probability .* between 0 and 1"),
        ({"qubits": [0], "field": "qubit.t1_relaxation_time", "value": 0.0}, "must be greater than 0"),
        ({"qubits": [0], "field": "qubit.t2_dephasing_time", "value": -1e-6}, "must be greater than 0"),
        ({"qubits": [0], "field": "qubit.t1_relaxation_time"}, "exactly the keys"),
    ],
)
def test_invalid_override_raises(override, message):
    with pytest.raises(ValueError, match=message):
        NoiseControl("ibm2016", "fez-2025", overrides=[override])


@pytest.mark.parametrize("gate, qubits, highest", [("cz", [0, 1], 0.79), ("sx", [0], 0.66)])
def test_gate_error_up_to_aers_maximum_builds_as_stated(gate, qubits, highest):
    """Aer builds a gate error up to dim/(dim + 1), a little less with decay, and caps one above it."""
    from qiskit.quantum_info import average_gate_fidelity

    field = f"gates.{gate}.error_probability"
    nc = NoiseControl("ibm2016", "fez-2025", overrides=[{"qubits": qubits, "field": field, "value": highest}])
    built = nc.noise_model._local_quantum_errors[gate][tuple(qubits)]
    assert 1 - average_gate_fidelity(built) == pytest.approx(highest, abs=1e-9)
    above = 0.8 if gate == "cz" else 2 / 3
    with pytest.raises(ValueError, match=f"{field}.*above the .* Aer can build"):
        NoiseControl("ibm2016", "fez-2025", overrides=[{"qubits": qubits, "field": field, "value": above}])


def _aers_largest_cz_infidelity(t1_t2: list[tuple[float, float]], duration: float) -> float:
    """The largest cz infidelity Aer builds on qubits (0, 1) with these decay times: what it makes of an error of 1."""
    from qiskit.circuit.library import CZGate
    from qiskit.quantum_info import average_gate_fidelity
    from qiskit.transpiler import InstructionProperties, QubitProperties, Target

    target = Target(num_qubits=2, qubit_properties=[QubitProperties(t1=t1, t2=t2) for t1, t2 in t1_t2])
    target.add_instruction(CZGate(), {(0, 1): InstructionProperties(error=1.0, duration=duration)})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # Aer warns that it caps the error, which is the point
        model = NoiseModel.from_backend(noise_module._TargetBackend(target), readout_error=False)
    return 1 - average_gate_fidelity(model._local_quantum_errors["cz"][(0, 1)])


def test_the_gate_error_ceiling_is_where_aer_starts_to_cap():
    """With decay strong enough that Aer's depolarising cap binds first, an error at the ceiling builds as stated
    and one just above it raises; the ceiling is Aer's own, computed here without NoiseControl."""
    from qiskit.quantum_info import average_gate_fidelity

    t1, t2 = FEZ["qubit"]["t1_relaxation_time"], FEZ["qubit"]["t2_dephasing_time"]
    fast = t1 / 40  # qubit 0 decays 40 times faster, as both its T1 and its T2
    decay = [{"qubits": [0], "field": f"qubit.{f}", "value": fast} for f in ("t1_relaxation_time", "t2_dephasing_time")]
    # Qubit 0's other gates get an error above what its faster decay alone now causes, so they still build.
    graph = configs.processor_graph(configs.load_processor("ibm2016"))
    decay += [{"qubits": [0], "field": f"gates.{g}.error_probability", "value": 0.05} for g in ("sx", "x")]
    field = "gates.cz.error_probability"
    decay += [{"qubits": [0, q], "field": field, "value": 0.05} for q in sorted(graph[0]) if q != 1]
    ceiling = _aers_largest_cz_infidelity([(fast, fast), (t1, t2)], FEZ["gates"]["cz"]["duration"])
    assert ceiling < 0.8 - 5e-4, "the case must be one where decay lowers the ceiling below dim/(dim + 1)"
    def build(value):
        overrides = [*decay, {"qubits": [0, 1], "field": field, "value": value}]
        return NoiseControl("ibm2016", "fez-2025", overrides=overrides)

    built = build(ceiling - 1e-9).noise_model._local_quantum_errors["cz"][(0, 1)]
    assert 1 - average_gate_fidelity(built) == pytest.approx(ceiling - 1e-9, abs=1e-9)
    with pytest.raises(ValueError, match=f"{field}.*above the .* Aer can build"):
        build(ceiling + 1e-6)


def test_numpy_numbers_are_accepted_and_exported_as_plain_ones():
    """A sweep may pass numpy numbers; the export stays plain YAML data and rebuilds the same model."""
    import yaml

    nc = NoiseControl(
        "ibm2016",
        "fez-2025",
        scale=np.int64(2),
        overrides=[{"qubits": [np.int64(3), np.int64(4)], "field": "gates.cz.error_probability", "value": np.float64(0.01)}],
    )
    record = yaml.safe_load(yaml.safe_dump(nc.export_as_yaml()))
    assert record == nc.export_as_yaml()
    assert type(record["scale"]) is float and type(record["overrides"][0]["value"]) is float
    assert all(type(q) is int for q in record["overrides"][0]["qubits"])
    assert NoiseControl.from_yaml(record).noise_model == nc.noise_model


def test_same_override_twice_raises():
    o = {"qubits": [1, 0], "field": "gates.cz.error_probability", "value": 0.01}
    with pytest.raises(ValueError, match="twice"):
        NoiseControl("ibm2016", "fez-2025", overrides=[o, {**o, "qubits": [0, 1]}])


def test_depolarising_profile_takes_no_overrides():
    o = {"qubits": [0], "field": "qubit.t1_relaxation_time", "value": 1e-4}
    with pytest.raises(ValueError, match="no overrides"):
        NoiseControl("ibm2016", "organiser-cx2", overrides=[o])


# -- Profiles the schema accepts but NoiseControl cannot build ------------------


def _edit_profile(name, change):
    import yaml

    path = configs.noise_path(name)
    profile = load_noise(name)
    change(profile)
    path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize(
    "name, change, message",
    [
        ("organiser-cx2", lambda p: p["depolarising"].update(after_gate="cz"), "after_gate 'cz' is not in its gates"),
        ("fez-2025", lambda p: p["gates"].update(foo=dict(p["gates"]["sx"])), "'foo' is not one of Qiskit's standard"),
        ("fez-2025", lambda p: p["gates"]["cz"].update(qubits=1), "'cz' acts on 2 qubit"),
    ],
)
def test_a_profile_noisecontrol_cannot_build_raises(config_copy, name, change, message):
    _edit_profile(name, change)
    with pytest.raises(ValueError, match=message):
        NoiseControl("ibm2016", name)


def test_a_kind_with_no_builder_raises_naming_kind(monkeypatch):
    """The guard for the schema's kinds and the builders drifting apart: a kind the schema accepts, with no builder."""
    monkeypatch.delitem(noise_module._BUILDERS, "depolarising")
    with pytest.raises(ValueError, match="unknown kind 'depolarising'; known: snapshot"):
        NoiseControl("ibm2016", "organiser-cx2")


def test_a_kind_the_schema_lacks_is_refused_when_the_profile_loads(config_copy):
    _edit_profile("organiser-cx2", lambda p: p.update(kind="biased"))
    with pytest.raises(ValueError, match=r"\$\.kind: 'biased' is not one of"):
        NoiseControl("ibm2016", "organiser-cx2")


# -- Conditional channels -------------------------------------------------------


@pytest.mark.parametrize("noise", ["boston-2026", "organiser-cx2"])
def test_the_mid_circuit_channel_is_a_bit_flip_on_its_marker(noise):
    from qiskit_aer.noise import pauli_error

    nc = NoiseControl("ibm2016", noise, conditional={"mid_circuit_measurement_error": 0.2})
    errors = nc.noise_model._local_quantum_errors[noise_module.MID_CIRCUIT_LABEL]
    assert set(errors) == {(q,) for q in range(nc.num_qubits)}
    assert all(_same_channel(e, pauli_error([("X", 0.2), ("I", 0.8)])) for e in errors.values())
    assert noise_module.MID_CIRCUIT_LABEL not in NoiseControl("ibm2016", noise).noise_model._local_quantum_errors


def _after_reset(nc: NoiseControl) -> float:
    """Qubit 0's |1> population right after a reset of |1>, exactly, under the model."""
    from qiskit_aer import AerSimulator

    qc = QuantumCircuit(1)
    qc.x(0)
    qc.reset(0)
    qc.save_density_matrix([0])
    rho = AerSimulator(method="density_matrix", noise_model=nc.noise_model).run(qc).result().data()["density_matrix"]
    return rho.data[1, 1].real


@pytest.mark.parametrize("p", [0.0, 0.3, 1.0])
@pytest.mark.parametrize("scale", [1, 2])
def test_reset_error_leaves_the_qubit_in_one_with_its_probability(p, scale):
    """Exactly p: the flip comes after the reset's own decay, which leaves |0> alone, and the scale leaves p alone.
    Were the flip before the decay, the population would be p times the decay over the reset's 2.232 us."""
    nc = NoiseControl("ibm2016", "boston-2026", scale=scale, conditional={"reset_error": p})
    assert _after_reset(nc) == pytest.approx(p, abs=1e-12)
    assert nc.export_as_yaml()["conditional"] == {"reset_error": p, "mid_circuit_measurement_error": None}


def test_reset_error_keeps_the_resets_decay():
    from qiskit_aer.noise import pauli_error

    nc = NoiseControl("ibm2016", "boston-2026", conditional={"reset_error": 0.3})
    built = nc.noise_model._local_quantum_errors["reset"][(0,)]
    assert not _same_channel(built, pauli_error([("X", 0.3), ("I", 0.7)])), "the decay is still part of the reset"
    unset = NoiseControl("ibm2016", "boston-2026")
    assert _after_reset(unset) == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("conditional", [{"reset_error": 1.5}, {"reset_error": True}, {"leakage": 0.01}, [0.01]])
def test_invalid_conditional_raises(conditional):
    with pytest.raises(ValueError, match="conditional"):
        NoiseControl("ibm2016", "fez-2025", conditional=conditional)


def test_unset_conditional_channels_are_recorded():
    nc = NoiseControl("ibm2016", "fez-2025", conditional={"reset_error": None})
    unset = {"reset_error": None, "mid_circuit_measurement_error": None}
    assert nc.conditional == unset
    assert nc.export_as_yaml()["conditional"] == unset


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


# -- The pauli kind --------------------------------------------------------------


def _pauli_profile(name="pauli-test", after_gate="cx", probability=0.01, bias=100.0, gates=None, **pauli):
    """Write a pauli profile into the copied config/ (the config_copy fixture) and return its name."""
    import yaml

    data = {
        "name": name,
        "label": "A pauli profile for a test",
        "kind": "pauli",
        "reference": "ideal-and-noisy-example",
        "notes": "Written by tests/test_noise.py.",
        "pauli": {
            "after_gate": after_gate,
            "probability": probability,
            "bias": bias,
            "gates": gates or ["h", after_gate, "sdg"],
            **pauli,
        },
    }
    path = configs.ROOT / "config" / "noise" / f"bp.data.noise.{name}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return name


def _per_qubit(error, qubit: int) -> dict[str, float]:
    """The probability of X, Y and Z on one qubit of a two-qubit Pauli channel, read from its chi matrix, whose
    diagonal holds each Pauli's probability (index a + 4 b for Pauli a on qubit 0 and b on qubit 1, in I X Y Z)."""
    diagonal = np.real(np.diag(Chi(SuperOp(error)).data))
    diagonal = diagonal / diagonal.sum()
    pick = (lambda a, b: a) if qubit == 0 else (lambda a, b: b)
    return {
        label: float(sum(diagonal[a + 4 * b] for a in range(4) for b in range(4) if pick(a, b) == k))
        for k, label in ((1, "X"), (2, "Y"), (3, "Z"))
    }


@pytest.mark.parametrize("bias", [0.5, 3.0, 100.0])
def test_pauli_split_gives_each_qubit_probability_p_and_noise_bias_eta(config_copy, bias):
    nc = NoiseControl("contemporary", _pauli_profile(probability=0.01, bias=bias))
    errors = nc.noise_model._local_quantum_errors
    assert set(errors) == {"cx"}
    assert set(errors["cx"]) == {qargs for a, b in nc.edges for qargs in ((a, b), (b, a))}
    for qubit in (0, 1):
        p = _per_qubit(errors["cx"][(0, 1)], qubit)
        assert sum(p.values()) == pytest.approx(0.01, abs=1e-12)
        assert p["X"] == pytest.approx(p["Y"], abs=1e-15)
        assert p["Z"] / (p["X"] + p["Y"]) == pytest.approx(bias, rel=1e-9)


def test_unbiased_pauli_noise_is_depolarising_on_each_qubit(config_copy):
    """At eta = 0.5 each Pauli has probability p/3, which is Aer's one-qubit depolarising channel of parameter 4p/3,
    since that parameter leaves each of X, Y and Z with a quarter of it. The two-qubit error is two independent
    copies, not Aer's two-qubit depolarising channel."""
    nc = NoiseControl("ibm2016", _pauli_profile(probability=0.03, bias=0.5))
    one = depolarizing_error(4 * 0.03 / 3, 1)
    assert _same_channel(nc.noise_model._local_quantum_errors["cx"][(0, 3)], one.tensor(one))
    assert not _same_channel(nc.noise_model._local_quantum_errors["cx"][(0, 3)], depolarizing_error(0.06, 2))


def test_pauli_profile_has_no_readout_error_decay_or_durations(config_copy):
    nc = NoiseControl("hyperbolic", _pauli_profile(gates=["h", "cx", "sdg", "x"]))
    assert not nc.noise_model._local_readout_errors and nc.noise_model._default_readout_error is None
    assert set(nc.target.operation_names) == {"h", "cx", "sdg", "x", "measure"}
    assert nc.has_durations is False


@pytest.mark.parametrize("scale", [1, 2.5])
def test_pauli_scale_multiplies_the_probability_and_leaves_the_bias(config_copy, scale):
    nc = NoiseControl("ibm2016", _pauli_profile(probability=0.01, bias=100.0), scale=scale)
    p = _per_qubit(nc.noise_model._local_quantum_errors["cx"][(0, 3)], 0)
    assert sum(p.values()) == pytest.approx(0.01 * scale, abs=1e-12)
    assert p["Z"] / (p["X"] + p["Y"]) == pytest.approx(100.0, rel=1e-9)


def test_pauli_scale_that_exceeds_one_raises(config_copy):
    with pytest.raises(ValueError, match=r"pauli.probability is 1.5 after scale 150"):
        NoiseControl("ibm2016", _pauli_profile(probability=0.01), scale=150)


def test_pauli_profile_takes_no_overrides(config_copy):
    o = {"qubits": [0], "field": "qubit.t1_relaxation_time", "value": 1e-4}
    with pytest.raises(ValueError, match="a pauli noise profile takes no overrides"):
        NoiseControl("ibm2016", _pauli_profile(), overrides=[o])


def test_pauli_profile_carries_the_mid_circuit_channel_and_holds_no_reset(config_copy):
    nc = NoiseControl("ibm2016", _pauli_profile(), conditional={"mid_circuit_measurement_error": 0.02})
    assert set(nc.noise_model._local_quantum_errors) == {"cx", MID_CIRCUIT_LABEL}
    assert "reset" not in nc.target.operation_names


@pytest.mark.parametrize(
    "pauli, message",
    [
        ({"bias": 0}, r"\$\.pauli\.bias: 0 is less than or equal to the minimum of 0"),
        ({"bias": -1.0}, r"\$\.pauli\.bias: -1\.0 is less than or equal"),
        ({"probability": 1.5}, r"\$\.pauli\.probability: 1\.5 is greater than the maximum of 1"),
        ({"extra": 1}, r"\$\.pauli: Additional properties are not allowed"),
    ],
)
def test_the_schema_refuses_a_bad_pauli_block(config_copy, pauli, message):
    with pytest.raises(ValueError, match=message):
        NoiseControl("ibm2016", _pauli_profile(**pauli))


def test_a_pauli_profile_with_no_pauli_block_is_refused(config_copy):
    _edit_profile("organiser-cx2", lambda p: p.update(kind="pauli"))
    with pytest.raises(ValueError, match="'pauli' is a required property"):
        NoiseControl("ibm2016", "organiser-cx2")


def test_a_pauli_profile_whose_after_gate_is_not_in_its_gates_raises(config_copy):
    with pytest.raises(ValueError, match="after_gate 'cx' is not in its gates"):
        NoiseControl("ibm2016", _pauli_profile(gates=["h", "cz", "sdg"]))


@pytest.mark.parametrize(
    "name, gate, bias",
    [("pauli-cx-biased", "cx", 100), ("pauli-cz-biased", "cz", 100), ("pauli-cx-unbiased", "cx", 0.5)],
)
def test_the_study_profiles_match_organiser_cx2_per_two_qubit_gate(name, gate, bias):
    """The three pauli profiles differ only in the native gate and the noise bias, and each two-qubit gate's total
    error, 1 - (1 - p)^2, matches organiser-cx2's, a depolarising channel of strength 0.02 leaving the gate's qubits
    untouched with probability 1/16 of it: 15/16 x 0.02 = 0.01875."""
    profile = load_noise(name)["pauli"]
    assert (profile["after_gate"], profile["bias"], profile["gates"]) == (gate, bias, ["h", gate, "sdg"])
    organiser = load_noise("organiser-cx2")["depolarising"]["probability"]
    assert 1 - (1 - profile["probability"]) ** 2 == pytest.approx(15 / 16 * organiser, abs=5e-6)


def _correlators(processor: str, noise: str) -> dict[str, float]:
    """The baseline pair's exact correlators under `noise`, from its compiled ZZ circuit's port density matrix."""
    nc = NoiseControl(processor, noise)
    compiled = compile_bases(basis_circuits(swap_chain(processor), nc.ports), nc, seed=5)["ZZ"].compiled
    rho = port_density_matrix(compiled, nc.noise_model, nc.ports)
    return {basis: float(np.real(rho.expectation_value(Pauli(basis)))) for basis in ("XX", "ZZ")}


@pytest.mark.parametrize("processor", ["contemporary", "hyperbolic"])
def test_biased_noise_spares_zz_under_cx_and_reaches_it_under_cz(config_copy, processor):
    """At eta = 100 with CX native, a Z error stays a Z, which leaves ZZ alone, so ZZ falls far less than XX. With CZ
    native, a CX compiles as H CZ H, and the second H turns a Z on the target into an X, which flips ZZ: ZZ then falls
    by a sizeable share of what XX falls (about 0.6 here, near unbiased noise's), measured, not assumed."""
    cx = _correlators(processor, _pauli_profile("biased-cx", "cx", probability=0.02, bias=100.0))
    cz = _correlators(processor, _pauli_profile("biased-cz", "cz", probability=0.02, bias=100.0))
    assert (1 - cx["ZZ"]) < 0.02 * (1 - cx["XX"])
    assert (1 - cz["ZZ"]) > 0.4 * (1 - cz["XX"])
    assert cz["ZZ"] < cx["ZZ"] and cz["XX"] > cx["XX"]


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


@pytest.mark.parametrize("kind", ["processor", "noise"])
def test_changed_hash_is_refused(kind):
    record = NoiseControl("ibm2016", "fez-2025").export_as_yaml()
    record[kind]["hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match=f"{record[kind]['path']} changed since it was recorded"):
        NoiseControl.from_yaml(record)


def test_record_outside_the_config_folder_is_refused(config_copy):
    """An identical copy of a profile outside config/noise/ is refused for where it is, not for being missing."""
    record = NoiseControl("ibm2016", "fez-2025").export_as_yaml()
    (config_copy / "docs").mkdir()
    shutil.copy(configs.noise_path("fez-2025"), config_copy / "docs" / "bp.data.noise.fez-2025.yaml")
    record["noise"]["path"] = "docs/bp.data.noise.fez-2025.yaml"
    with pytest.raises(ValueError, match="is not where noise files live"):
        NoiseControl.from_yaml(record)


def test_a_record_missing_its_file_is_refused():
    record = NoiseControl("ibm2016", "fez-2025").export_as_yaml()
    record["noise"]["path"] = "config/noise/bp.data.noise.no-such-profile.yaml"
    with pytest.raises(FileNotFoundError, match="no longer exists"):
        NoiseControl.from_yaml(record)


def test_a_record_with_other_keys_is_refused():
    record = NoiseControl("ibm2016", "fez-2025").export_as_yaml()
    with pytest.raises(ValueError, match="a NoiseControl record has the keys"):
        NoiseControl.from_yaml({**record, "seed": 1})


@pytest.mark.parametrize(
    "kind, name, old, new",
    [
        ("processor", "ibm2016", "label: 2016-inspired reference", "label: 2016-inspired reference, edited"),
        ("noise", "fez-2025", "error_probability: 0.0039", "error_probability: 0.0139"),
    ],
)
def test_export_records_the_files_the_model_was_built_from(config_copy, kind, name, old, new):
    """A file edited after the build leaves the export on the build's hash, and a rebuild refuses it."""
    nc = NoiseControl("ibm2016", "fez-2025")
    path = configs.config_path(kind, name)
    built = configs.content_hash(path)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    assert configs.content_hash(path) != built
    record = nc.export_as_yaml()
    assert record[kind]["hash"] == built
    with pytest.raises(ValueError, match="changed since it was recorded"):
        NoiseControl.from_yaml(record)


def test_a_build_reads_each_config_file_once(monkeypatch):
    """The record's hash is of the content the model was built from, so the build never reads a file twice."""
    import builtins

    reads = []

    def counting_open(file, *args, **kwargs):
        reads.append(str(file))
        return builtins.open(file, *args, **kwargs)

    monkeypatch.setattr(configs, "open", counting_open, raising=False)
    NoiseControl("ibm2016", "fez-2025")
    config_reads = sorted(r for r in reads if "/config/processor/" in r or "/config/noise/" in r)
    assert config_reads == sorted([str(configs.noise_path("fez-2025")), str(configs.processor_path("ibm2016"))])


def test_settings_cannot_change_after_the_build():
    """Edits to the caller's input, to each property's value and to an export never reach the next export."""
    override = {"qubits": [3, 4], "field": "gates.cz.error_probability", "value": 0.01}
    nc = NoiseControl("ibm2016", "fez-2025", scale=1.5, overrides=[override])
    before = copy.deepcopy(nc.export_as_yaml())  # shares no object with nc, so an edit cannot change both sides
    assert before["overrides"] == [{"qubits": [3, 4], "field": "gates.cz.error_probability", "value": 0.01}]
    assert before["conditional"] == {"reset_error": None, "mid_circuit_measurement_error": None}
    with pytest.raises(AttributeError):
        nc.scale = 2.0
    override["value"] = 0.9
    override["qubits"].append(0)
    nc.overrides[0]["value"] = 0.05
    nc.overrides[0]["qubits"].append(2)
    nc.conditional["reset_error"] = 0.5
    export = nc.export_as_yaml()
    export["overrides"][0]["value"] = 0.05
    export["conditional"]["mid_circuit_measurement_error"] = 0.5
    export["processor"]["hash"] = "sha256:edited"
    export["noise"]["path"] = "edited"
    assert nc.export_as_yaml() == before
    assert nc.target["cz"][(3, 4)].error == pytest.approx(0.015)


def test_hash_ignores_comments_but_not_values(tmp_path):
    original = configs.noise_path("fez-2025")
    copy = tmp_path / original.name
    shutil.copy(original, copy)
    text = copy.read_text(encoding="utf-8")
    copy.write_text("# an added comment\n" + text.replace("  # T1", "  # a reworded T1 comment\n  # T1"), encoding="utf-8")
    assert content_hash(copy) == content_hash(original)
    copy.write_text(text.replace("cz: {qubits: 2, error_probability: 0.0039", "cz: {qubits: 2, error_probability: 0.0049"), encoding="utf-8")
    assert content_hash(copy) != content_hash(original)
