# Run move-chain-contemporary under pauli-cx-biased

- **Circuit file:** `config/circuit/bp.data.circuit.move-chain-contemporary.yaml`
- **Noise profile:** `config/noise/bp.data.noise.pauli-cx-biased.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 20000 per basis per simulation
- **Commit:** `276561cbf5f1a1a629a77539750cfa77e8255ec1`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (0.9999 to 1.0000) |
| noisy | 0.9070 | 0.0015 | 0.9070 | 1.0000 (0.9999 to 1.0000) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 0 (0) | 7 | 8 | 5 | not scheduled | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
