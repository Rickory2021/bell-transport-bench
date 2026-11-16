# Core benchmark

The challenge's nine cases (docs/CHALLENGE.md, The nine core cases): the three processor models under one noise profile, boston-2026, so the comparison shows connectivity alone. Each run is the organisers' baseline transport on its graph. Cases 3, 6 and 9, the protected runs, stay open until a protected strategy is chosen for the core; the move-chain benchmark fills them with one candidate. 20,000 shots per basis gives F a standard error of about 0.001.

| Case | Processor | Simulation | F | Standard error | Acceptance | Two-qubit gates | SWAPs | Infidelity removed per rejection |
|---|---|---|---|---|---|---|---|---|
| 1 | ibm2016 | ideal | 1.0000 | 0.0000 | 1.0000 | 7 | 2 | n/a |
| 2 | ibm2016 | noisy | 0.9770 | 0.0008 | 1.0000 | 7 | 2 | n/a |
| 4 | contemporary | ideal | 1.0000 | 0.0000 | 1.0000 | 19 | 6 | n/a |
| 5 | contemporary | noisy | 0.9614 | 0.0010 | 1.0000 | 19 | 6 | n/a |
| 7 | hyperbolic | ideal | 1.0000 | 0.0000 | 1.0000 | 13 | 4 | n/a |
| 8 | hyperbolic | noisy | 0.9681 | 0.0009 | 1.0000 | 13 | 4 | n/a |

Cases not listed have no run yet. The infidelity removed per rejection is (F - F raw) / (1 - p) within the run, with its standard error by the delta method over each basis's kept and discarded counts, independent bases; it is n/a where no shot was discarded.

Every row, with the derived metrics, is in comparison.csv. F's standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
