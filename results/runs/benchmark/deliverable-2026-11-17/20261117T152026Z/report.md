# GHZ disentangling with a vacancy read, the nine cases

The challenge's nine cases (docs/CHALLENGE.md, The nine core cases) as the submission reports them, under boston-2026 as in the core benchmark, so the three graphs differ only in connectivity. Cases 1, 2, 4, 5, 7 and 8 are the organisers' baseline, exactly as the core benchmark runs it. Cases 3, 6 and 9 are one protection strategy, the same builder steps on every graph: ghz_uncompute makes a GHZ state along the pair's path, then disentangles the path's interior qubits with gates controlled from the first port, leaving them in |0>; vacancy then reads them at the end of the circuit, and postselection discards each shot where any reads 1. The read catches a bit flip on the interior qubits and on the first port, the qubit that has waited longest, since the last gate copies it onto the path; it cannot see a phase flip. No qubit is read mid-circuit, so no case needs the mid-circuit measurement channel. The file runs only the runs that fill a case. Each graph's extended benchmark, deliverable-2026-11-17-extended-<processor>, runs the same protected case beside the alternatives under the same shots and seed, among them the transport without the read, so the submission separates what the transport buys from what the read buys. Every run takes 100,000 shots per basis, five times the core's 20,000, so F's standard error is about 0.0003 and a difference of 0.001 between two runs stands at more than two combined standard errors; the baseline cases therefore agree with the core's within their errors rather than repeating its numbers.

| Case | Processor | Simulation | F | Standard error | Acceptance | Two-qubit gates | SWAPs | Infidelity removed per rejection |
|---|---|---|---|---|---|---|---|---|
| 1 | ibm2016 | ideal | 1.0000 | 0.0000 | 1.0000 | 7 | 2 | n/a |
| 2 | ibm2016 | noisy | 0.9766 | 0.0003 | 1.0000 | 7 | 2 | n/a |
| 3 | ibm2016 | noisy | 0.9842 | 0.0003 | 0.9928 | 3 | 0 | 0.354 ± 0.014 |
| 4 | contemporary | ideal | 1.0000 | 0.0000 | 1.0000 | 19 | 6 | n/a |
| 5 | contemporary | noisy | 0.9600 | 0.0004 | 1.0000 | 19 | 6 | n/a |
| 6 | contemporary | noisy | 0.9817 | 0.0003 | 0.9774 | 7 | 0 | 0.322 ± 0.008 |
| 7 | hyperbolic | ideal | 1.0000 | 0.0000 | 1.0000 | 13 | 4 | n/a |
| 8 | hyperbolic | noisy | 0.9686 | 0.0004 | 1.0000 | 13 | 4 | n/a |
| 9 | hyperbolic | noisy | 0.9832 | 0.0003 | 0.9855 | 5 | 0 | 0.327 ± 0.010 |

Cases not listed have no run yet. The infidelity removed per rejection is (F - F raw) / (1 - p) within the run, with its standard error by the delta method over each basis's kept and discarded counts, independent bases; it is n/a where no shot was discarded.

Every row, with the derived metrics, is in comparison.csv. F's standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
