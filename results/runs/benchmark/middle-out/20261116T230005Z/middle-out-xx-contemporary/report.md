# Run move-middle-out-spare-xx-contemporary under boston-2026

- **Circuit file:** `config/circuit/bp.data.circuit.move-middle-out-spare-xx-contemporary.yaml`
- **Noise profile:** `config/noise/bp.data.noise.boston-2026.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 20000 per basis per simulation
- **Commit:** `cf30bd18393fda708f50209b0cba5dafc9eeaeb7`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (0.9999 to 1.0000) |
| noisy | 0.9790 | 0.0007 | 0.9697 | 0.9739 (0.9726 to 0.9752) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 0 (0) | 11 | 24 | 8 | 2.800 µs | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
