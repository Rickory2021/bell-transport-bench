# Mid-circuit measurement error sweep on ibm2016

An optional study, kept apart from the nine cases (docs/CHALLENGE.md, What is fixed and what we choose): how the XX check on ibm2016 fares as its mid-circuit measurement error grows. ibm2016 has no spare path, so its check sits on the pair's own path, reads each bus qubit mid-circuit and reuses it, and the move-chain benchmark's case 3 sets the mid-circuit measurement error to 0.01, one assumed value. Here that circuit, move_chain with bus_xx on the pair's path, runs under boston-2026 at mid-circuit measurement errors 0, 0.001, 0.003, 0.01, 0.02 and 0.05, each run named by its value in e notation after mcm. Each value is one point of a sweep, not a claimed property of any device, and each run derives its own seeds, so neighbouring points also differ by shot noise: read each difference against its standard errors. The run at 0.01 has case 3's settings and seeds, so it gives case 3's numbers. The organisers' baseline and move_chain alone read nothing mid-circuit, so the error cannot reach them: each runs once, without the channel, as a fixed reference. Setting the check's F after postselection, with its acceptance, beside move_chain alone's F at each point shows at which errors, if any, the check pays for the shots it discards. 20,000 shots per basis and base seed 20261116, as in the core.

| Run | F | Standard error | F raw | Acceptance | Two-qubit gates | Total shots |
|---|---|---|---|---|---|---|
| baseline-ibm2016 | 0.9770 | 0.0008 | 0.9770 | 1.0000 | 7 | 60000 |
| move-ibm2016 | 0.9805 | 0.0007 | 0.9805 | 1.0000 | 3 | 60000 |
| path-xx-ibm2016-mcm-0 | 0.9796 | 0.0007 | 0.9685 | 0.9790 | 5 | 60000 |
| path-xx-ibm2016-mcm-1e-3 | 0.9801 | 0.0007 | 0.9689 | 0.9785 | 5 | 60000 |
| path-xx-ibm2016-mcm-3e-3 | 0.9794 | 0.0007 | 0.9680 | 0.9753 | 5 | 60000 |
| path-xx-ibm2016-mcm-1e-2 | 0.9786 | 0.0007 | 0.9668 | 0.9700 | 5 | 60000 |
| path-xx-ibm2016-mcm-2e-2 | 0.9810 | 0.0007 | 0.9701 | 0.9615 | 5 | 60000 |
| path-xx-ibm2016-mcm-5e-2 | 0.9810 | 0.0007 | 0.9710 | 0.9335 | 5 | 60000 |

One row per run, its noisy simulation; every run's ideal simulation passed the self-test, F = 1 with every shot kept. Total shots are the raw shots of the three bases together.

Every row, with the derived metrics, is in comparison.csv. F's standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
