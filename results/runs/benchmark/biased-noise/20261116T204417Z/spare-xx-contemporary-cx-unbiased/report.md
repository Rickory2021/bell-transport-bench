# Run move-chain-spare-xx-contemporary under pauli-cx-unbiased

- **Circuit file:** `config/circuit/bp.data.circuit.move-chain-spare-xx-contemporary.yaml`
- **Noise profile:** `config/noise/bp.data.noise.pauli-cx-unbiased.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 20000 per basis per simulation
- **Commit:** `e5b712e7f2687b0401a04b777cfd055fcfe387e7`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (0.9999 to 1.0000) |
| noisy | 0.9454 | 0.0012 | 0.8784 | 0.9032 (0.9008 to 0.9056) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 0 (0) | 11 | 10 | 8 | not scheduled | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
