# Run baseline-hyperbolic under pauli-cx-unbiased

- **Circuit file:** `config/circuit/bp.data.circuit.baseline-hyperbolic.yaml`
- **Noise profile:** `config/noise/bp.data.noise.pauli-cx-unbiased.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 20000 per basis per simulation
- **Commit:** `e5b712e7f2687b0401a04b777cfd055fcfe387e7`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (0.9999 to 1.0000) |
| noisy | 0.8639 | 0.0018 | 0.8639 | 1.0000 (0.9999 to 1.0000) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 4 (0) | 13 | 14 | 4 | not scheduled | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
