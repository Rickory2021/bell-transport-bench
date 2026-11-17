# Run baseline-hyperbolic under boston-2026

- **Circuit file:** `config/circuit/bp.data.circuit.baseline-hyperbolic.yaml`
- **Noise profile:** `config/noise/bp.data.noise.boston-2026.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 100000 per basis per simulation
- **Commit:** `fdc6caf822ae65dd815aff4ee2f32b8280462421`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (1.0000 to 1.0000) |
| noisy | 0.9686 | 0.0004 | 0.9686 | 1.0000 (1.0000 to 1.0000) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 4 (0) | 13 | 27 | 4 | 3.468 µs | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
