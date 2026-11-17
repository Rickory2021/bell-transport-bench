# Run move-chain-contemporary under boston-2026

- **Circuit file:** `config/circuit/bp.data.circuit.move-chain-contemporary.yaml`
- **Noise profile:** `config/noise/bp.data.noise.boston-2026.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 100000 per basis per simulation
- **Commit:** `2a3499b29add364b7ff860ec9e368e48459f7e8e`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (1.0000 to 1.0000) |
| noisy | 0.9749 | 0.0004 | 0.9749 | 1.0000 (1.0000 to 1.0000) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 0 (0) | 7 | 25 | 5 | 2.836 µs | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
