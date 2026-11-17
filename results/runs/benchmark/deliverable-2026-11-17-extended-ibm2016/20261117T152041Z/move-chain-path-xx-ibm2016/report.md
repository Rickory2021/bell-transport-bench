# Run move-chain-path-xx-ibm2016 under boston-2026

- **Circuit file:** `config/circuit/bp.data.circuit.move-chain-path-xx-ibm2016.yaml`
- **Noise profile:** `config/noise/bp.data.noise.boston-2026.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 100000 per basis per simulation
- **Commit:** `fdc6caf822ae65dd815aff4ee2f32b8280462421`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (1.0000 to 1.0000) |
| noisy | 0.9797 | 0.0003 | 0.9682 | 0.9697 (0.9690 to 0.9703) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 0 (0) | 5 | 23 | 3 | 4.932 µs | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
