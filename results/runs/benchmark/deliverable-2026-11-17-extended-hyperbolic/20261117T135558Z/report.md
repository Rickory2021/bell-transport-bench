# Hyperbolic-inspired, the protected case beside its alternatives

An optional study, kept apart from the nine cases (docs/CHALLENGE.md, What is fixed and what we choose): on the hyperbolic-inspired graph, the deliverable's protected case, case 9, beside the circuits that differ from it by one step, so each comparison shows what one change buys. The rungs, each a builder call along the baseline's path [0, 1, 9, 12]: the organisers' baseline; the move chain, which moves the pair with two CX gates a hop instead of a SWAP's three; ghz_measure, the textbook GHZ transport, which reads the interior qubits in X and owes a Z on the first port for each 1; ghz_uncompute, which empties the interior with gates instead; each of the two empty transports followed by a vacancy read at the end, where only ghz_uncompute's last gate makes the read catch a bit flip on the first port; and two XX checks on a spare path that shares no qubit with the pair's: the move-chain benchmark's case 9, the move chain with the check, and ghz_uncompute with its vacancy read followed by the check, which trades discarded shots for F. Every run takes the deliverable's noise profile, shots and base seed, so the runs it shares with the deliverable repeat its numbers exactly; the runs it shares with the move-chain benchmark, which takes 20,000 shots, agree with them within their errors.

| Run | F | Standard error | F raw | Acceptance | Two-qubit gates | Total shots |
|---|---|---|---|---|---|---|
| baseline-hyperbolic | 0.9686 | 0.0004 | 0.9686 | 1.0000 | 13 | 300000 |
| move-hyperbolic | 0.9788 | 0.0003 | 0.9788 | 1.0000 | 5 | 300000 |
| ghz-measure-hyperbolic | 0.9721 | 0.0004 | 0.9721 | 1.0000 | 3 | 300000 |
| ghz-hyperbolic | 0.9782 | 0.0003 | 0.9782 | 1.0000 | 5 | 300000 |
| move-vacancy-hyperbolic | 0.9813 | 0.0003 | 0.9784 | 0.9877 | 5 | 300000 |
| ghz-vacancy-hyperbolic | 0.9832 | 0.0003 | 0.9784 | 0.9855 | 5 | 300000 |
| spare-xx-hyperbolic | 0.9810 | 0.0003 | 0.9739 | 0.9828 | 8 | 300000 |
| ghz-vacancy-xx-hyperbolic | 0.9845 | 0.0003 | 0.9751 | 0.9706 | 8 | 300000 |

One row per run, its noisy simulation; every run's ideal simulation passed the self-test, F = 1 with every shot kept. Total shots are the raw shots of the three bases together.

Every row, with the derived metrics, is in comparison.csv. F's standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
