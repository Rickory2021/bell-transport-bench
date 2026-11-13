# src/bellbench/fidelity.py
"""The one Bell fidelity function, F = [1 + <XX> - <YY> + <ZZ>] / 4, and its correlators.

Every fidelity the benchmark reports comes through `bell_fidelity`, from three
correlators (docs/CHALLENGE.md, Verifying the pair):

- `fidelity_from_counts` estimates them from the port register's counts, one
  basis per circuit, and gives F with its standard error. Every result reports
  this measured F (docs/DESIGN.md, section 8).
- `fidelity_from_density` computes them exactly from the ports' density
  matrix. Only the cross-check that reproduces the organisers' recorded numbers
  uses it (section 8).
- `infidelity_removed_per_rejection` sets F after postselection against F over
  every shot of the same simulation, per unit of the shots discarded, with its
  standard error (REJECTION_METHOD).

A correlator <BB> is P(00) + P(11) - P(01) - P(10) over the shots of basis B:
+1 where the two bits agree and -1 where they differ, so the bit order of the
two ports does not matter. Its variance over N shots is (1 - c^2) / N, and the
three bases are measured on separate shots, so the standard error of F is a
quarter of the square root of the three variances summed (UNCERTAINTY_METHOD).
A basis with no shots leaves its correlator, and so F, undefined: it warns and
gives NaN rather than a number; a run's record and report flag such a basis
(src/bellbench/run.py). Every value returned is a plain Python number, whatever
integer type the counts hold, so it writes to YAML as it is.
"""

import math
import warnings
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from qiskit.quantum_info import DensityMatrix, Pauli

BASES = ("XX", "YY", "ZZ")
OUTCOMES = ("00", "01", "10", "11")
UNCERTAINTY_METHOD = "binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4"
REJECTION_METHOD = "delta method over each basis's kept and discarded counts, independent bases"
SIGNS = {"XX": 1, "YY": -1, "ZZ": 1}  # each correlator's sign in F


@dataclass(frozen=True)
class Correlator:
    """One basis's correlator <BB> and the shots it came from; `shots` is None when computed exactly."""

    value: float
    shots: int | None

    @property
    def variance(self) -> float:
        """The variance of the estimate: (1 - c^2) / N, 0 for an exact value, NaN with no shots."""
        if self.shots is None:
            return 0.0
        if self.shots == 0:
            return math.nan
        return (1 - self.value**2) / self.shots


@dataclass(frozen=True)
class Fidelity:
    """F with its standard error, the correlators it came from, and how the error was computed."""

    value: float
    standard_error: float
    correlators: dict[str, Correlator]
    method: str


def bell_fidelity(xx: float, yy: float, zz: float) -> float:
    """F(Phi+) = [1 + <XX> - <YY> + <ZZ>] / 4, the overlap of the pair's state with |Phi+>."""
    return (1 + xx - yy + zz) / 4


def correlator_from_counts(counts: Mapping[str, int], basis: str = "") -> Correlator:
    """<BB> from one basis's two-bit port counts; warns and gives NaN when there are no shots."""
    unknown = set(counts) - set(OUTCOMES)
    if unknown:
        raise ValueError(f"port counts{_for(basis)} have keys other than {OUTCOMES}: {sorted(unknown)}")
    if any(not isinstance(n, (int, np.integer)) or isinstance(n, bool) or n < 0 for n in counts.values()):
        raise ValueError(f"port counts{_for(basis)} must be non-negative integers; got {dict(counts)}")
    shots = int(sum(counts.values()))
    if shots == 0:
        warnings.warn(f"basis {basis or '?'} kept no shots, so its correlator and F are undefined", stacklevel=2)
        return Correlator(math.nan, 0)
    agree = int(counts.get("00", 0) + counts.get("11", 0))
    return Correlator((2 * agree - shots) / shots, shots)


def fidelity_from_counts(counts_by_basis: Mapping[str, Mapping[str, int]]) -> Fidelity:
    """Measured F and its standard error from each basis's port counts."""
    _check_bases(counts_by_basis)
    correlators = {basis: correlator_from_counts(counts_by_basis[basis], basis) for basis in BASES}
    return _fidelity(correlators, UNCERTAINTY_METHOD)


def fidelity_from_density(rho) -> Fidelity:
    """Exact F from the two ports' density matrix; only the organisers' cross-check uses it (DESIGN.md, 8)."""
    rho = DensityMatrix(rho)
    if rho.num_qubits != 2:
        raise ValueError(f"the ports' density matrix is over 2 qubits; got {rho.num_qubits}")
    correlators = {basis: Correlator(float(np.real(rho.expectation_value(Pauli(basis)))), None) for basis in BASES}
    return _fidelity(correlators, "exact, from the density matrix")


def infidelity_removed_per_rejection(
    all_by_basis: Mapping[str, Mapping[str, int]], kept_by_basis: Mapping[str, Mapping[str, int]]
) -> tuple[float, float]:
    """(F kept - F all) / (1 - p) for one simulation, with its standard error; (NaN, NaN) where undefined.

    F all is F over every shot, F kept is F over the shots postselection kept,
    and p is the fraction kept, pooled over the three bases. The value is how
    much postselection lowers 1 - F per unit of shots it discards. With the same
    acceptance in every basis it equals F of the kept shots minus F of the
    discarded ones, so it is 0 where the check discards shots no better or worse
    than those it keeps. It is undefined where no shot is discarded (p = 1) or a
    basis keeps none, since F kept is then undefined.

    The standard error is the delta method's (REJECTION_METHOD): each basis's
    shots split into four counts, kept or discarded and agreeing or not, drawn
    as one multinomial over that basis's fixed number of shots, and the three
    bases are measured on separate shots, so their variances add. The sums are
    plain Python arithmetic in a fixed order, through math.fsum, never numpy's
    vectorised sums, whose order can differ between processors, so the error is
    the same to the last digit on any machine.
    """
    _check_bases(all_by_basis)
    _check_bases(kept_by_basis)
    cells = {}
    for basis in BASES:
        every, kept = all_by_basis[basis], kept_by_basis[basis]
        if set(kept) - set(OUTCOMES) or any(kept.get(o, 0) > every.get(o, 0) for o in OUTCOMES):
            raise ValueError(f"basis {basis}'s kept counts {dict(kept)} are not a part of its counts {dict(every)}")
        a = int(kept.get("00", 0) + kept.get("11", 0))
        d = int(kept.get("01", 0) + kept.get("10", 0))
        agree = int(every.get("00", 0) + every.get("11", 0))
        shots = int(sum(every.values()))
        cells[basis] = (a, d, agree - a, shots - agree - d, shots)
    total = sum(c[4] for c in cells.values())
    kept_total = sum(c[0] + c[1] for c in cells.values())
    if kept_total == total or any(c[0] + c[1] == 0 for c in cells.values()):
        return math.nan, math.nan
    discarded = 1 - kept_total / total
    gain = fidelity_from_counts(kept_by_basis).value - fidelity_from_counts(all_by_basis).value
    value = gain / discarded
    terms = []
    for basis, (a, d, e, f, shots) in cells.items():
        s, kept = SIGNS[basis], a + d
        # Derivatives of the gain and of p by each count, the basis's shots held fixed.
        d_gain = [2 * d / kept**2 - 1 / shots, -2 * a / kept**2 + 1 / shots, -1 / shots, 1 / shots]
        d_p = [1 / total, 1 / total, 0.0, 0.0]
        g = [x * s / 4 / discarded + gain / discarded**2 * y for x, y in zip(d_gain, d_p)]
        n = (a, d, e, f)
        terms.append(math.fsum(c * x * x for c, x in zip(n, g)))
        terms.append(-math.fsum(c * x for c, x in zip(n, g)) ** 2 / shots)
    return float(value), math.sqrt(math.fsum(terms))


def _fidelity(correlators: dict[str, Correlator], method: str) -> Fidelity:
    value = bell_fidelity(correlators["XX"].value, correlators["YY"].value, correlators["ZZ"].value)
    error = math.sqrt(sum(c.variance for c in correlators.values())) / 4
    return Fidelity(value, error, correlators, method)


def _check_bases(by_basis: Mapping) -> None:
    if set(by_basis) != set(BASES):
        raise ValueError(f"counts are needed for exactly the bases {BASES}; got {sorted(by_basis)}")


def _for(basis: str) -> str:
    return f" for basis {basis}" if basis else ""
