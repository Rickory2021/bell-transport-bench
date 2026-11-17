# Run ghz-uncompute-vacancy-ibm2016 under boston-2026

- **Circuit file:** `config/circuit/bp.data.circuit.ghz-uncompute-vacancy-ibm2016.yaml`
- **Noise profile:** `config/noise/bp.data.noise.boston-2026.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 100000 per basis per simulation
- **Commit:** `2a3499b29add364b7ff860ec9e368e48459f7e8e`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (1.0000 to 1.0000) |
| noisy | 0.9842 | 0.0003 | 0.9816 | 0.9928 (0.9925 to 0.9931) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 0 (0) | 3 | 15 | 3 | 2.532 µs | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
