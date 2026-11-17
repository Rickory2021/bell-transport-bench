# Contemporary, the protected case beside its alternatives

An optional study, kept apart from the nine cases (docs/CHALLENGE.md, What is fixed and what we choose): on the contemporary graph, the deliverable's protected case, case 6, beside the circuits that differ from it by one step, so each comparison shows what one change buys. The rungs, each a builder call along the baseline's path [0, 1, 2, 3, 7]: the organisers' baseline; the move chain, which moves the pair with two CX gates a hop instead of a SWAP's three; ghz_measure, the textbook GHZ transport, which reads the interior qubits in X and owes a Z on the first port for each 1; ghz_uncompute, which empties the interior with gates instead; each of the two empty transports followed by a vacancy read at the end, where only ghz_uncompute's last gate makes the read catch a bit flip on the first port; and two XX checks on a spare path that shares no qubit with the pair's: the move-chain benchmark's case 6, the move chain with the check, and ghz_uncompute with its vacancy read followed by the check, which trades discarded shots for F. Both XX buses on this graph pass through its five-edge qubit, so their numbers are without the planned degree penalty (docs/DESIGN.md, section 4). Every run takes the deliverable's noise profile, shots and base seed, so the runs it shares with the deliverable repeat its numbers exactly; the runs it shares with the move-chain benchmark, which takes 20,000 shots, agree with them within their errors.

| Run | F | Standard error | F raw | Acceptance | Two-qubit gates | Total shots |
|---|---|---|---|---|---|---|
| baseline-contemporary | 0.9600 | 0.0004 | 0.9600 | 1.0000 | 19 | 300000 |
| move-contemporary | 0.9749 | 0.0004 | 0.9749 | 1.0000 | 7 | 300000 |
| ghz-measure-contemporary | 0.9663 | 0.0004 | 0.9663 | 1.0000 | 4 | 300000 |
| ghz-contemporary | 0.9745 | 0.0004 | 0.9745 | 1.0000 | 7 | 300000 |
| move-vacancy-contemporary | 0.9795 | 0.0003 | 0.9748 | 0.9808 | 7 | 300000 |
| ghz-vacancy-contemporary | 0.9817 | 0.0003 | 0.9744 | 0.9774 | 7 | 300000 |
| spare-xx-contemporary | 0.9797 | 0.0003 | 0.9699 | 0.9747 | 11 | 300000 |
| ghz-vacancy-xx-contemporary | 0.9827 | 0.0003 | 0.9690 | 0.9557 | 11 | 300000 |

One row per run, its noisy simulation; every run's ideal simulation passed the self-test, F = 1 with every shot kept. Total shots are the raw shots of the three bases together.

Every row, with the derived metrics, is in comparison.csv. F's standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
