# tests/test_fidelity.py
"""The one Bell fidelity function gives the known answers, and its standard error follows its stated method.

The example states are docs/CHALLENGE.md's table in Verifying the pair. The
infidelity removed per rejection gives a hand-computed answer, its standard
error matches the spread of the value over counts redrawn from the same
fractions, and it is undefined where no shot is discarded.
"""

import math

import numpy as np
import pytest
import yaml
from qiskit.quantum_info import DensityMatrix, Statevector

from bellbench.fidelity import (
    BASES,
    UNCERTAINTY_METHOD,
    bell_fidelity,
    correlator_from_counts,
    fidelity_from_counts,
    fidelity_from_density,
    infidelity_removed_per_rejection,
)


@pytest.mark.parametrize(
    "xx, yy, zz, expected",
    [
        (1, -1, 1, 1.0),  # |Phi+>, the target
        (0, 0, 1, 0.5),  # 00 or 11 at random, a classical mixture
        (0, 0, 0, 0.25),  # every outcome equally likely
        (-1, 1, 1, 0.0),  # (|00> - |11>)/sqrt(2), after a phase flip
    ],
)
def test_bell_fidelity_known_states(xx, yy, zz, expected):
    assert bell_fidelity(xx, yy, zz) == expected


def test_correlator_counts_agreement_minus_disagreement():
    c = correlator_from_counts({"00": 45, "11": 45, "01": 6, "10": 4})
    assert c.value == pytest.approx(0.8)
    assert c.shots == 100
    assert c.variance == pytest.approx((1 - 0.8**2) / 100)


def test_correlator_ignores_which_port_is_which():
    assert correlator_from_counts({"01": 3, "00": 7}).value == correlator_from_counts({"10": 3, "00": 7}).value


def test_fidelity_from_counts_and_its_standard_error():
    perfect = {"XX": {"00": 50, "11": 50}, "YY": {"01": 50, "10": 50}, "ZZ": {"00": 50, "11": 50}}
    f = fidelity_from_counts(perfect)
    assert f.value == 1.0 and f.standard_error == 0.0
    assert f.method == UNCERTAINTY_METHOD

    noisy = {"XX": {"00": 45, "11": 45, "01": 10}, "YY": {"01": 40, "10": 40, "00": 20}, "ZZ": {"00": 48, "11": 48, "10": 4}}
    f = fidelity_from_counts(noisy)
    xx, yy, zz = 0.8, -0.6, 0.92
    assert f.value == pytest.approx((1 + xx - yy + zz) / 4)
    expected_se = math.sqrt(sum((1 - c**2) / 100 for c in (xx, yy, zz))) / 4
    assert f.standard_error == pytest.approx(expected_se)


def test_a_basis_with_no_shots_warns_and_gives_nan():
    with pytest.warns(UserWarning, match="YY kept no shots"):
        f = fidelity_from_counts({"XX": {"00": 5}, "YY": {}, "ZZ": {"11": 5}})
    assert math.isnan(f.value) and math.isnan(f.standard_error)


def test_numpy_counts_give_plain_python_numbers():
    counts = {b: {"00": np.int64(45), "11": np.int64(40), "01": np.int64(15)} for b in BASES}
    fidelity = fidelity_from_counts(counts)
    assert type(fidelity.value) is float and type(fidelity.standard_error) is float
    assert all(type(c.value) is float for c in fidelity.correlators.values())
    assert yaml.safe_load(yaml.safe_dump({"f": fidelity.value})) == {"f": fidelity.value}


@pytest.mark.parametrize(
    "counts",
    [{"02": 3}, {"000": 3}, {"00": -1}, {"00": 1.5}, {"00": True}],
)
def test_malformed_counts_raise(counts):
    with pytest.raises(ValueError):
        correlator_from_counts(counts)


def test_counts_need_exactly_the_three_bases():
    with pytest.raises(ValueError, match="bases"):
        fidelity_from_counts({"XX": {"00": 1}, "ZZ": {"00": 1}})


def test_exact_fidelity_from_density_matrix():
    phi_plus = DensityMatrix(Statevector([1, 0, 0, 1] / np.sqrt(2)))
    f = fidelity_from_density(phi_plus)
    assert f.value == pytest.approx(1.0) and f.standard_error == 0.0
    assert {b: round(c.value, 12) for b, c in f.correlators.items()} == {"XX": 1.0, "YY": -1.0, "ZZ": 1.0}
    mixed = DensityMatrix(np.diag([0.5, 0, 0, 0.5]))
    assert fidelity_from_density(mixed).value == pytest.approx(0.5)
    with pytest.raises(ValueError, match="2 qubits"):
        fidelity_from_density(DensityMatrix.from_label("000"))


# Each basis: 100 shots, 90 kept and perfect, 10 discarded with as many agreeing as not. So F kept is 1, the
# discarded shots' F is 1/4, F raw is (1 + 0.9 + 0.9 + 0.9) / 4 = 0.925 and p is 0.9.
KEPT = {"XX": {"00": 45, "11": 45}, "YY": {"01": 45, "10": 45}, "ZZ": {"00": 45, "11": 45}}
EVERY = {
    "XX": {"00": 48, "11": 47, "01": 3, "10": 2},
    "YY": {"00": 3, "11": 2, "01": 47, "10": 48},
    "ZZ": {"00": 48, "11": 47, "01": 3, "10": 2},
}


def test_infidelity_removed_per_rejection_known_answer():
    value, error = infidelity_removed_per_rejection(EVERY, KEPT)
    assert value == pytest.approx((1 - 0.925) / (1 - 0.9))
    assert value == pytest.approx(1 - 0.25), "with one acceptance in every basis, F kept minus F discarded"
    assert type(value) is float and type(error) is float and error > 0


def _removed(cells):
    """The value from counts (..., basis, cell), cells kept-agree, kept-differ, discarded-agree, discarded-differ."""
    a, d, e, f = (cells[..., i] for i in range(4))
    shots, kept = cells.sum(axis=-1), a + d
    signs = np.array([1, -1, 1])
    f_kept = (1 + (signs * (a - d) / kept).sum(axis=-1)) / 4
    f_all = (1 + (signs * (a - d + e - f) / shots).sum(axis=-1)) / 4
    p = kept.sum(axis=-1) / shots.sum(axis=-1)
    return (f_kept - f_all) / (1 - p)


def test_infidelity_removed_per_rejection_standard_error_matches_redrawn_counts():
    # Shaped like a protected run: 20,000 shots a basis, about 3% discarded, the discarded F about 0.6.
    cells = np.array([[19060, 340, 360, 240], [330, 19070, 250, 350], [19050, 350, 370, 230]])
    every = {b: {"00": int(c[0] + c[2]), "01": int(c[1] + c[3])} for b, c in zip(BASES, cells)}
    kept = {b: {"00": int(c[0]), "01": int(c[1])} for b, c in zip(BASES, cells)}
    value, error = infidelity_removed_per_rejection(every, kept)
    assert value == pytest.approx(float(_removed(cells)))
    rng = np.random.default_rng(20261116)
    redrawn = np.stack([rng.multinomial(c.sum(), c / c.sum(), size=20000) for c in cells], axis=1)
    assert error == pytest.approx(float(_removed(redrawn).std()), rel=0.05)


@pytest.mark.parametrize(
    "every, kept",
    [
        (KEPT, KEPT),  # nothing discarded, p = 1
        (EVERY, {**KEPT, "YY": {}}),  # a basis that kept nothing has no F kept
    ],
)
def test_infidelity_removed_per_rejection_is_undefined_where_f_kept_or_a_discard_is_missing(every, kept):
    value, error = infidelity_removed_per_rejection(every, kept)
    assert math.isnan(value) and math.isnan(error)


def test_kept_counts_beyond_all_counts_raise():
    with pytest.raises(ValueError, match="basis XX's kept counts"):
        infidelity_removed_per_rejection(EVERY, {**KEPT, "XX": {"00": 49, "11": 45}})
