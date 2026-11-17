# Vacancy-read study

An optional study, kept apart from the nine cases (docs/CHALLENGE.md, What is fixed and what we choose): does a GHZ-and-uncompute transport, followed by a vacancy read of the emptied path at the end, do better than the reported strategy? ghz_uncompute makes a GHZ state along the path, then empties the interior with gates controlled from the first port, so the vacancy read at the end catches a bit flip on that port, the qubit that has waited longest. On ibm2016 the vacancy read replaces case 3's XX check on the path, which reads a qubit mid-circuit and reuses it; on the contemporary and hyperbolic graphs the reported XX check on a spare path follows it. Each new run sits beside the move-chain benchmark's protected run on its graph, rerun here under the same circuit, profile and base seed, so with the same seeds and the same numbers. Case 3's run appears twice: at the mid-circuit measurement error of 0.01 it is reported with, and at 0, the Boston profile alone, under which every new run here needs no channel. The contemporary runs' XX bus passes through the five-edge qubit, so their numbers are without the planned degree penalty (docs/DESIGN.md, section 4). Every run takes 20,000 shots per basis, as in the core.

| Run | F | Standard error | F raw | Acceptance | Two-qubit gates | Total shots |
|---|---|---|---|---|---|---|
| path-xx-ibm2016 | 0.9786 | 0.0007 | 0.9668 | 0.9700 | 5 | 60000 |
| path-xx-ibm2016-mcm-0 | 0.9796 | 0.0007 | 0.9685 | 0.9790 | 5 | 60000 |
| spare-xx-contemporary | 0.9793 | 0.0007 | 0.9697 | 0.9750 | 11 | 60000 |
| spare-xx-hyperbolic | 0.9812 | 0.0007 | 0.9745 | 0.9828 | 8 | 60000 |
| ghz-vacancy-ibm2016 | 0.9844 | 0.0006 | 0.9818 | 0.9930 | 3 | 60000 |
| ghz-vacancy-xx-contemporary | 0.9826 | 0.0007 | 0.9695 | 0.9558 | 11 | 60000 |
| ghz-vacancy-xx-hyperbolic | 0.9837 | 0.0006 | 0.9741 | 0.9707 | 8 | 60000 |

One row per run, its noisy simulation; every run's ideal simulation passed the self-test, F = 1 with every shot kept. Total shots are the raw shots of the three bases together.

Every row, with the derived metrics, is in comparison.csv. F's standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
