# Run move-chain-spare-xx-hyperbolic under pauli-cz-biased

- **Circuit file:** `config/circuit/bp.data.circuit.move-chain-spare-xx-hyperbolic.yaml`
- **Noise profile:** `config/noise/bp.data.noise.pauli-cz-biased.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 20000 per basis per simulation
- **Commit:** `971ed0677f32b31eaef564da153df7d155388193`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (0.9999 to 1.0000) |
| noisy | 0.9448 | 0.0012 | 0.9024 | 0.9294 (0.9273 to 0.9314) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 0 (0) | 8 | 12 | 6 | not scheduled | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
