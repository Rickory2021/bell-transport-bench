# Run baseline-hyperbolic under boston-2026

- **Circuit file:** `config/circuit/bp.data.circuit.baseline-hyperbolic.yaml`
- **Noise profile:** `config/noise/bp.data.noise.boston-2026.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 20000 per basis per simulation
- **Commit:** `276561cbf5f1a1a629a77539750cfa77e8255ec1`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (0.9999 to 1.0000) |
| noisy | 0.9590 | 0.0010 | 0.9590 | 1.0000 (0.9999 to 1.0000) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 4 (0) | 13 | 27 | 4 | 3.468 µs | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
