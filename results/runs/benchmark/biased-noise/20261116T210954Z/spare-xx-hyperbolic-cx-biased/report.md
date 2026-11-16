# Run move-chain-spare-xx-hyperbolic under pauli-cx-biased

- **Circuit file:** `config/circuit/bp.data.circuit.move-chain-spare-xx-hyperbolic.yaml`
- **Noise profile:** `config/noise/bp.data.noise.pauli-cx-biased.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 20000 per basis per simulation
- **Commit:** `971ed0677f32b31eaef564da153df7d155388193`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (0.9999 to 1.0000) |
| noisy | 0.9789 | 0.0008 | 0.9127 | 0.8961 (0.8936 to 0.8985) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 0 (0) | 8 | 8 | 6 | not scheduled | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
