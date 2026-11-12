# src/bellbench/fidelity.py
"""The one Bell fidelity function, F = [1 + <XX> - <YY> + <ZZ>] / 4, and its correlators.

Every fidelity the benchmark reports comes through `bell_fidelity`, from three
correlators (docs/CHALLENGE.md, Verifying the pair):

- `fidelity_from_counts` estimates them from the port register's counts, one
  basis per circuit, and gives F with its standard error. Every result reports
  this measured F (D-50).
- `fidelity_from_density` computes them exactly from the ports' density
  matrix. Only the cross-check that reproduces the organisers' recorded numbers
  uses it (D-50).

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
    """Exact F from the two ports' density matrix; only the organisers' cross-check uses it (D-50)."""
    rho = DensityMatrix(rho)
    if rho.num_qubits != 2:
        raise ValueError(f"the ports' density matrix is over 2 qubits; got {rho.num_qubits}")
    correlators = {basis: Correlator(float(np.real(rho.expectation_value(Pauli(basis)))), None) for basis in BASES}
    return _fidelity(correlators, "exact, from the density matrix")


def _fidelity(correlators: dict[str, Correlator], method: str) -> Fidelity:
    value = bell_fidelity(correlators["XX"].value, correlators["YY"].value, correlators["ZZ"].value)
    error = math.sqrt(sum(c.variance for c in correlators.values())) / 4
    return Fidelity(value, error, correlators, method)


def _check_bases(by_basis: Mapping) -> None:
    if set(by_basis) != set(BASES):
        raise ValueError(f"counts are needed for exactly the bases {BASES}; got {sorted(by_basis)}")


def _for(basis: str) -> str:
    return f" for basis {basis}" if basis else ""
