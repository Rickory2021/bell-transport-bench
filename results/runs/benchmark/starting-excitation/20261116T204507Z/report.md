# Starting excitation sweep on the move-chain benchmark's runs

An optional study, kept apart from the nine cases (docs/CHALLENGE.md, What is fixed and what we choose): how the move-chain benchmark's runs fare if each qubit may start a shot in |1> rather than |0>. The move chain's two-CX move is a SWAP without its third CX, so it assumes the qubit it moves onto starts in |0>, and the XX check on a spare path trusts its spare qubits to start in |0>; the organisers' baseline swaps the pair out and back, which returns an excited qubit on its path to where it started. Each of the move-chain benchmark's nine runs, the baseline, the move chain alone and the move chain with its XX check on each graph, runs under boston-2026 with the starting excitation, the chance that each qubit starts a shot in |1>, at 0, 0.005, 0.01 and 0.02, each run named by its value in e notation after exc; the check on ibm2016 keeps case 3's mid-circuit measurement error of 0.01. A run at 0 differs from the move-chain benchmark's run of the same circuit only in its seeds. Each value is one point of a sweep, not a claimed property of any device, and each run derives its own seeds, so neighbouring points also differ by shot noise: read each difference against its standard errors. 20,000 shots per basis and base seed 20261116, as in the core.

| Run | F | Standard error | F raw | Acceptance | Two-qubit gates | Total shots |
|---|---|---|---|---|---|---|
| baseline-ibm2016-exc-0 | 0.9758 | 0.0008 | 0.9758 | 1.0000 | 7 | 60000 |
| baseline-ibm2016-exc-5e-3 | 0.9668 | 0.0009 | 0.9668 | 1.0000 | 7 | 60000 |
| baseline-ibm2016-exc-1e-2 | 0.9577 | 0.0010 | 0.9577 | 1.0000 | 7 | 60000 |
| baseline-ibm2016-exc-2e-2 | 0.9395 | 0.0012 | 0.9395 | 1.0000 | 7 | 60000 |
| baseline-contemporary-exc-0 | 0.9621 | 0.0010 | 0.9621 | 1.0000 | 19 | 60000 |
| baseline-contemporary-exc-5e-3 | 0.9526 | 0.0011 | 0.9526 | 1.0000 | 19 | 60000 |
| baseline-contemporary-exc-1e-2 | 0.9406 | 0.0012 | 0.9406 | 1.0000 | 19 | 60000 |
| baseline-contemporary-exc-2e-2 | 0.9238 | 0.0013 | 0.9238 | 1.0000 | 19 | 60000 |
| baseline-hyperbolic-exc-0 | 0.9683 | 0.0009 | 0.9683 | 1.0000 | 13 | 60000 |
| baseline-hyperbolic-exc-5e-3 | 0.9590 | 0.0010 | 0.9590 | 1.0000 | 13 | 60000 |
| baseline-hyperbolic-exc-1e-2 | 0.9486 | 0.0011 | 0.9486 | 1.0000 | 13 | 60000 |
| baseline-hyperbolic-exc-2e-2 | 0.9295 | 0.0013 | 0.9295 | 1.0000 | 13 | 60000 |
| move-ibm2016-exc-0 | 0.9811 | 0.0007 | 0.9811 | 1.0000 | 3 | 60000 |
| move-ibm2016-exc-5e-3 | 0.9661 | 0.0009 | 0.9661 | 1.0000 | 3 | 60000 |
| move-ibm2016-exc-1e-2 | 0.9526 | 0.0011 | 0.9526 | 1.0000 | 3 | 60000 |
| move-ibm2016-exc-2e-2 | 0.9215 | 0.0014 | 0.9215 | 1.0000 | 3 | 60000 |
| move-contemporary-exc-0 | 0.9747 | 0.0008 | 0.9747 | 1.0000 | 7 | 60000 |
| move-contemporary-exc-5e-3 | 0.9505 | 0.0011 | 0.9505 | 1.0000 | 7 | 60000 |
| move-contemporary-exc-1e-2 | 0.9265 | 0.0013 | 0.9265 | 1.0000 | 7 | 60000 |
| move-contemporary-exc-2e-2 | 0.8839 | 0.0016 | 0.8839 | 1.0000 | 7 | 60000 |
| move-hyperbolic-exc-0 | 0.9794 | 0.0007 | 0.9794 | 1.0000 | 5 | 60000 |
| move-hyperbolic-exc-5e-3 | 0.9585 | 0.0010 | 0.9585 | 1.0000 | 5 | 60000 |
| move-hyperbolic-exc-1e-2 | 0.9417 | 0.0012 | 0.9417 | 1.0000 | 5 | 60000 |
| move-hyperbolic-exc-2e-2 | 0.9018 | 0.0015 | 0.9018 | 1.0000 | 5 | 60000 |
| path-xx-ibm2016-exc-0 | 0.9802 | 0.0007 | 0.9700 | 0.9707 | 5 | 60000 |
| path-xx-ibm2016-exc-5e-3 | 0.9753 | 0.0008 | 0.9553 | 0.9599 | 5 | 60000 |
| path-xx-ibm2016-exc-1e-2 | 0.9682 | 0.0009 | 0.9383 | 0.9495 | 5 | 60000 |
| path-xx-ibm2016-exc-2e-2 | 0.9603 | 0.0010 | 0.9177 | 0.9367 | 5 | 60000 |
| spare-xx-contemporary-exc-0 | 0.9794 | 0.0007 | 0.9691 | 0.9740 | 11 | 60000 |
| spare-xx-contemporary-exc-5e-3 | 0.9504 | 0.0011 | 0.9361 | 0.9655 | 11 | 60000 |
| spare-xx-contemporary-exc-1e-2 | 0.9229 | 0.0014 | 0.9050 | 0.9557 | 11 | 60000 |
| spare-xx-contemporary-exc-2e-2 | 0.8737 | 0.0017 | 0.8489 | 0.9386 | 11 | 60000 |
| spare-xx-hyperbolic-exc-0 | 0.9806 | 0.0007 | 0.9742 | 0.9827 | 8 | 60000 |
| spare-xx-hyperbolic-exc-5e-3 | 0.9633 | 0.0010 | 0.9513 | 0.9723 | 8 | 60000 |
| spare-xx-hyperbolic-exc-1e-2 | 0.9436 | 0.0012 | 0.9279 | 0.9638 | 8 | 60000 |
| spare-xx-hyperbolic-exc-2e-2 | 0.9089 | 0.0015 | 0.8845 | 0.9449 | 8 | 60000 |

One row per run, its noisy simulation; every run's ideal simulation passed the self-test, F = 1 with every shot kept. Total shots are the raw shots of the three bases together.

Every row, with the derived metrics, is in comparison.csv. F's standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
