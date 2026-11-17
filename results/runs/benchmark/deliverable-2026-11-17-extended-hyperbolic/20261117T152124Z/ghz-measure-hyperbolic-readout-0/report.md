# Run ghz-measure-hyperbolic under boston-2026

- **Circuit file:** `config/circuit/bp.data.circuit.ghz-measure-hyperbolic.yaml`
- **Noise profile:** `config/noise/bp.data.noise.boston-2026.yaml`, scale 1
- **Overrides:** 4 (flagged: per-qubit values differ from the profile)
- **Shots:** 100000 per basis per simulation
- **Commit:** `fdc6caf822ae65dd815aff4ee2f32b8280462421`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (1.0000 to 1.0000) |
| noisy | 0.9817 | 0.0003 | 0.9817 | 1.0000 (1.0000 to 1.0000) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 0 (0) | 3 | 11 | 4 | 2.432 µs | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
