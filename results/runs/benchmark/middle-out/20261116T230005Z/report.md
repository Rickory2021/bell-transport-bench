# Middle-out study

An optional study, kept apart from the nine cases (docs/CHALLENGE.md, What is fixed and what we choose): do two variants of the reported strategy do better than it? The first, move_middle_out, makes the pair in the middle of the path and moves both halves outward at once, so it uses the same gates as move_chain in a shorter schedule. The second adds a ZZ check before the XX check on the hyperbolic graph, whose third qubit-disjoint path between the ports holds a second spare bus; the ZZ check catches a bit flip on one port, which the XX check misses, and runs first so that the XX check's parity covers the ZZ check's frame bit. The contemporary graph has only two qubit-disjoint paths, so it has no room for a second spare bus, and on ibm2016 move_middle_out writes the same circuit as move_chain, so neither graph runs that variant. Each new run sits beside the move-chain benchmark's run it varies, rerun here under the same circuit, profile and base seed, so with the same seeds and the same numbers. The ZZ and XX run's XX bus passes through the centre qubit, so its numbers are without the planned degree penalty (docs/DESIGN.md, section 4). Every run takes 20,000 shots per basis, as in the core.

| Run | F | Standard error | F raw | Acceptance | Two-qubit gates | Total shots |
|---|---|---|---|---|---|---|
| move-contemporary | 0.9756 | 0.0008 | 0.9756 | 1.0000 | 7 | 60000 |
| move-hyperbolic | 0.9788 | 0.0007 | 0.9788 | 1.0000 | 5 | 60000 |
| spare-xx-contemporary | 0.9793 | 0.0007 | 0.9697 | 0.9750 | 11 | 60000 |
| spare-xx-hyperbolic | 0.9812 | 0.0007 | 0.9745 | 0.9828 | 8 | 60000 |
| middle-out-contemporary | 0.9790 | 0.0007 | 0.9790 | 1.0000 | 7 | 60000 |
| middle-out-hyperbolic | 0.9783 | 0.0007 | 0.9783 | 1.0000 | 5 | 60000 |
| middle-out-xx-contemporary | 0.9790 | 0.0007 | 0.9697 | 0.9739 | 11 | 60000 |
| middle-out-xx-hyperbolic | 0.9819 | 0.0007 | 0.9748 | 0.9830 | 8 | 60000 |
| middle-out-zz-xx-hyperbolic | 0.9813 | 0.0007 | 0.9648 | 0.9629 | 12 | 60000 |

One row per run, its noisy simulation; every run's ideal simulation passed the self-test, F = 1 with every shot kept. Total shots are the raw shots of the three bases together.

Every row, with the derived metrics, is in comparison.csv. F's standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
