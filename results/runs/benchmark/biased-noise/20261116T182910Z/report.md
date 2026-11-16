# Biased-noise study

An optional study, kept apart from the core benchmark (docs/CHALLENGE.md, What is fixed and what we choose): if a processor's errors were mostly phase flips and its CX kept them so, would an XX check catch nearly every error on the pair? Each graph runs the organisers' baseline, move_chain alone, and move_chain with bus_xx, under three pauli profiles that differ only in the native two-qubit gate and the noise bias: pauli-cx-biased (CX, eta 100), pauli-cz-biased (CZ, eta 100) and pauli-cx-unbiased (CX, eta 0.5). On the contemporary and hyperbolic graphs bus_xx runs on a spare path and reads only at the end; ibm2016 has no spare path, so there it runs on the path, reads each qubit before reusing it, and needs the mid-circuit measurement channel, set to 0.01 as one point of the range it is to be swept over. The profiles have no readout error, decay or durations, so these numbers describe gate noise alone, on one finite model each. 20,000 shots per basis, as in the core.

| Run | F | Standard error | F raw | Acceptance | Two-qubit gates | Total shots |
|---|---|---|---|---|---|---|
| baseline-ibm2016-cx-biased | 0.9130 | 0.0014 | 0.9130 | 1.0000 | 7 | 60000 |
| baseline-contemporary-cx-biased | 0.8053 | 0.0020 | 0.8053 | 1.0000 | 19 | 60000 |
| baseline-hyperbolic-cx-biased | 0.8539 | 0.0018 | 0.8539 | 1.0000 | 13 | 60000 |
| move-ibm2016-cx-biased | 0.9576 | 0.0010 | 0.9576 | 1.0000 | 3 | 60000 |
| move-contemporary-cx-biased | 0.9070 | 0.0015 | 0.9070 | 1.0000 | 7 | 60000 |
| move-hyperbolic-cx-biased | 0.9292 | 0.0013 | 0.9292 | 1.0000 | 5 | 60000 |
| path-xx-ibm2016-cx-biased | 0.9795 | 0.0007 | 0.9371 | 0.9288 | 5 | 60000 |
| spare-xx-contemporary-cx-biased | 0.9747 | 0.0008 | 0.8909 | 0.8631 | 11 | 60000 |
| spare-xx-hyperbolic-cx-biased | 0.9789 | 0.0008 | 0.9127 | 0.8961 | 8 | 60000 |
| baseline-ibm2016-cz-biased | 0.9292 | 0.0013 | 0.9292 | 1.0000 | 7 | 60000 |
| baseline-contemporary-cz-biased | 0.8312 | 0.0019 | 0.8312 | 1.0000 | 19 | 60000 |
| baseline-hyperbolic-cz-biased | 0.8788 | 0.0017 | 0.8788 | 1.0000 | 13 | 60000 |
| move-ibm2016-cz-biased | 0.9543 | 0.0011 | 0.9543 | 1.0000 | 3 | 60000 |
| move-contemporary-cz-biased | 0.9012 | 0.0015 | 0.9012 | 1.0000 | 7 | 60000 |
| move-hyperbolic-cz-biased | 0.9272 | 0.0013 | 0.9272 | 1.0000 | 5 | 60000 |
| path-xx-ibm2016-cz-biased | 0.9696 | 0.0009 | 0.9359 | 0.9292 | 5 | 60000 |
| spare-xx-contemporary-cz-biased | 0.9255 | 0.0014 | 0.8695 | 0.9053 | 11 | 60000 |
| spare-xx-hyperbolic-cz-biased | 0.9448 | 0.0012 | 0.9024 | 0.9294 | 8 | 60000 |
| baseline-ibm2016-cx-unbiased | 0.9186 | 0.0014 | 0.9186 | 1.0000 | 7 | 60000 |
| baseline-contemporary-cx-unbiased | 0.8140 | 0.0020 | 0.8140 | 1.0000 | 19 | 60000 |
| baseline-hyperbolic-cx-unbiased | 0.8639 | 0.0018 | 0.8639 | 1.0000 | 13 | 60000 |
| move-ibm2016-cx-unbiased | 0.9567 | 0.0010 | 0.9567 | 1.0000 | 3 | 60000 |
| move-contemporary-cx-unbiased | 0.9130 | 0.0014 | 0.9130 | 1.0000 | 7 | 60000 |
| move-hyperbolic-cx-unbiased | 0.9325 | 0.0013 | 0.9325 | 1.0000 | 5 | 60000 |
| path-xx-ibm2016-cx-unbiased | 0.9650 | 0.0010 | 0.9323 | 0.9382 | 5 | 60000 |
| spare-xx-contemporary-cx-unbiased | 0.9454 | 0.0012 | 0.8784 | 0.9032 | 11 | 60000 |
| spare-xx-hyperbolic-cx-unbiased | 0.9543 | 0.0011 | 0.9037 | 0.9308 | 8 | 60000 |

One row per run, its noisy simulation; every run's ideal simulation passed the self-test, F = 1 with every shot kept. Total shots are the raw shots of the three bases together.

Every row, with the derived metrics, is in comparison.csv. F's standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
