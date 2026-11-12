# Core benchmark

The challenge's nine cases (docs/CHALLENGE.md, The nine core cases): the three processor models under one noise profile, boston-2026, so the comparison shows connectivity alone (D-65). Each run is the baseline transport on its graph. Cases 3, 6 and 9, the protected runs, stay open until a protected strategy is chosen. 20,000 shots per basis gives F a standard error of about 0.001.

| Case | Processor | Simulation | F | Standard error | Acceptance | Two-qubit gates | SWAPs |
|---|---|---|---|---|---|---|---|
| 1 | ibm2016 | ideal | 1.0000 | 0.0000 | 1.0000 | 7 | 2 |
| 2 | ibm2016 | noisy | 0.9770 | 0.0008 | 1.0000 | 7 | 2 |
| 4 | contemporary | ideal | 1.0000 | 0.0000 | 1.0000 | 19 | 6 |
| 5 | contemporary | noisy | 0.9614 | 0.0010 | 1.0000 | 19 | 6 |
| 7 | hyperbolic | ideal | 1.0000 | 0.0000 | 1.0000 | 13 | 4 |
| 8 | hyperbolic | noisy | 0.9681 | 0.0009 | 1.0000 | 13 | 4 |

Cases not listed have no run yet.

Every row, with the derived metrics, is in comparison.csv. Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
