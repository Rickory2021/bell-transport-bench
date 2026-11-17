# Run ghz-uncompute-vacancy-spare-xx-contemporary under boston-2026

- **Circuit file:** `config/circuit/bp.data.circuit.ghz-uncompute-vacancy-spare-xx-contemporary.yaml`
- **Noise profile:** `config/noise/bp.data.noise.boston-2026.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 100000 per basis per simulation
- **Commit:** `b026fc902f6bed953022a2c0a5d424b0ef70c693`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (1.0000 to 1.0000) |
| noisy | 0.9827 | 0.0003 | 0.9690 | 0.9557 (0.9550 to 0.9564) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 0 (0) | 11 | 35 | 8 | 3.032 µs | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
