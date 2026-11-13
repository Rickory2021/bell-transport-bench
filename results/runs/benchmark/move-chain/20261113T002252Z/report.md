# Move chain with an XX check, the nine cases

The challenge's nine cases (docs/CHALLENGE.md, The nine core cases) with one protection strategy filled in, under boston-2026 as in the core benchmark, so the three graphs differ only in connectivity. Cases 1, 2, 4, 5, 7 and 8 are the organisers' baseline, the reference, exactly as the core benchmark runs it. Cases 3, 6 and 9 are the protection: move_chain carries the pair to the ports with two CX gates a hop instead of a SWAP's three, then bus_xx reads the ports' XX parity through a bus of extra qubits and postselection discards each shot where it reads -1. The check catches a phase flip on one port and is blind to a bit flip, to the same flip on both ports and to an error on the bus. On the contemporary and hyperbolic graphs the bus sits on a spare path that shares no qubit with the pair and reads only at the end; ibm2016 has no spare path, so there the bus sits on the pair's own path, reads each qubit as vacant before reusing it, and needs the mid-circuit measurement channel, set to 0.01 as one point of the range it is to be swept over. The move chain also runs without the check, filling no case, so the table separates what the cheaper transport buys from what the check buys. Every run takes 20,000 shots per basis, as in the core; protected runs are not yet given more shots in proportion to their acceptance.

| Case | Processor | Simulation | F | Standard error | Acceptance | Two-qubit gates | SWAPs |
|---|---|---|---|---|---|---|---|
| 1 | ibm2016 | ideal | 1.0000 | 0.0000 | 1.0000 | 7 | 2 |
| 2 | ibm2016 | noisy | 0.9770 | 0.0008 | 1.0000 | 7 | 2 |
| 3 | ibm2016 | noisy | 0.9786 | 0.0007 | 0.9700 | 5 | 0 |
| 4 | contemporary | ideal | 1.0000 | 0.0000 | 1.0000 | 19 | 6 |
| 5 | contemporary | noisy | 0.9614 | 0.0010 | 1.0000 | 19 | 6 |
| 6 | contemporary | noisy | 0.9793 | 0.0007 | 0.9750 | 11 | 0 |
| 7 | hyperbolic | ideal | 1.0000 | 0.0000 | 1.0000 | 13 | 4 |
| 8 | hyperbolic | noisy | 0.9681 | 0.0009 | 1.0000 | 13 | 4 |
| 9 | hyperbolic | noisy | 0.9812 | 0.0007 | 0.9828 | 8 | 0 |

Cases not listed have no run yet.

Every row, with the derived metrics, is in comparison.csv. Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
