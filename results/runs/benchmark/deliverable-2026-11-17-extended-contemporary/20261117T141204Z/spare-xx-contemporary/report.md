# Run move-chain-spare-xx-contemporary under boston-2026

- **Circuit file:** `config/circuit/bp.data.circuit.move-chain-spare-xx-contemporary.yaml`
- **Noise profile:** `config/noise/bp.data.noise.boston-2026.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 100000 per basis per simulation
- **Commit:** `2a3499b29add364b7ff860ec9e368e48459f7e8e`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (1.0000 to 1.0000) |
| noisy | 0.9797 | 0.0003 | 0.9699 | 0.9747 (0.9742 to 0.9753) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 0 (0) | 11 | 29 | 8 | 2.968 µs | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
