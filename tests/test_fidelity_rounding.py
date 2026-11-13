# tests/test_fidelity_rounding.py
"""A variance of exactly 0 that floating point sums to a tiny negative number gives a standard error of 0.

An ideal run whose check discards shots, where every kept and discarded shot
agrees, has an infidelity removed per rejection of 0 with a variance of exactly
0. Summed in floating point, that variance can come out just below 0, which
math.sqrt refuses; a sum below 0 by more than rounding is a real error and
still raises.
"""

import pytest

from bellbench.fidelity import ROUNDING, _standard_error, infidelity_removed_per_rejection

# The ideal port counts of a run whose check reads a qubit in superposition: every shot agrees, about half are
# kept, and this draw's variance sums to -2.2e-18.
ALL = {"XX": {"00": 49, "11": 51}, "YY": {"01": 51, "10": 49}, "ZZ": {"00": 51, "11": 49}}
KEPT = {"XX": {"00": 25, "11": 26}, "YY": {"01": 27, "10": 22}, "ZZ": {"00": 31, "11": 24}}


def test_every_shot_agreeing_gives_0_removed_with_a_standard_error_of_0():
    assert infidelity_removed_per_rejection(ALL, KEPT) == (0.0, 0.0)


def test_a_sum_below_0_by_rounding_is_0():
    assert _standard_error([1.0, -1.0 - ROUNDING / 2]) == 0.0


def test_a_sum_below_0_by_more_than_rounding_raises():
    with pytest.raises(ValueError, match="below 0 by more than rounding"):
        _standard_error([1.0, -1.0 - 10 * ROUNDING])


def test_a_positive_sum_is_its_square_root():
    assert _standard_error([2.25, 0.0]) == 1.5
