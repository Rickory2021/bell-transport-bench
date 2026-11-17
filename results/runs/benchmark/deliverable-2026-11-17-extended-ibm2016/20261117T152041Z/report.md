# 2016-inspired, the protected case beside its alternatives

An optional study, kept apart from the nine cases (docs/CHALLENGE.md, What is fixed and what we choose): on the 2016-inspired graph, the deliverable's protected case, case 3, beside the circuits that differ from it by one step, so each comparison shows what one change buys. The rungs, each a builder call along the baseline's path [0, 3, 4]: the organisers' baseline; the move chain, which moves the pair with two CX gates a hop instead of a SWAP's three; ghz_measure, the textbook GHZ transport, which reads the interior qubits in X and owes a Z on the first port for each 1; ghz_uncompute, which empties the interior with gates instead; ghz_measure again with no readout error on the interior qubits it reads, an override only this run takes, which shows whether readout error alone decides between the two GHZ transports; each of the two empty transports followed by a vacancy read at the end, where only ghz_uncompute's last gate makes the read catch a bit flip on the first port; and the move-chain benchmark's case 3, the move chain with an XX check on the pair's own path, which reads a qubit mid-circuit and runs with the mid-circuit measurement error of 0.01 it was reported with. The graph has no spare path, so no rung adds an XX check to the vacancy read. Every run takes the deliverable's noise profile, shots and base seed, so the runs it shares with the deliverable repeat its numbers exactly; the runs it shares with the move-chain benchmark, which takes 20,000 shots, agree with them within their errors.

| Run | F | Standard error | F raw | Acceptance | Two-qubit gates | Total shots |
|---|---|---|---|---|---|---|
| baseline-ibm2016 | 0.9766 | 0.0003 | 0.9766 | 1.0000 | 7 | 300000 |
| move-chain-ibm2016 | 0.9814 | 0.0003 | 0.9814 | 1.0000 | 3 | 300000 |
| ghz-measure-ibm2016 | 0.9790 | 0.0003 | 0.9790 | 1.0000 | 2 | 300000 |
| ghz-measure-ibm2016-readout-0 | 0.9828 | 0.0003 | 0.9828 | 1.0000 | 2 | 300000 |
| ghz-uncompute-ibm2016 | 0.9818 | 0.0003 | 0.9818 | 1.0000 | 3 | 300000 |
| move-chain-vacancy-ibm2016 | 0.9832 | 0.0003 | 0.9816 | 0.9938 | 3 | 300000 |
| ghz-uncompute-vacancy-ibm2016 | 0.9842 | 0.0003 | 0.9816 | 0.9928 | 3 | 300000 |
| move-chain-path-xx-ibm2016 | 0.9797 | 0.0003 | 0.9682 | 0.9697 | 5 | 300000 |

One row per run, its noisy simulation; every run's ideal simulation passed the self-test, F = 1 with every shot kept. Total shots are the raw shots of the three bases together.

Every row, with the derived metrics, is in comparison.csv. F's standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
