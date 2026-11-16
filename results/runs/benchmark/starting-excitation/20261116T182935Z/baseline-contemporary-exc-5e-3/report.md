# Run baseline-contemporary under boston-2026

- **Circuit file:** `config/circuit/bp.data.circuit.baseline-contemporary.yaml`
- **Noise profile:** `config/noise/bp.data.noise.boston-2026.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 20000 per basis per simulation
- **Commit:** `8f580c14c880e3dbbd2e2be17991bee3d1c144ce`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (0.9999 to 1.0000) |
| noisy | 0.9526 | 0.0011 | 0.9526 | 1.0000 (0.9999 to 1.0000) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 6 (0) | 19 | 39 | 5 | 4.068 µs | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
