# Run move-chain-spare-xx-contemporary under pauli-cx-biased

- **Circuit file:** `config/circuit/bp.data.circuit.move-chain-spare-xx-contemporary.yaml`
- **Noise profile:** `config/noise/bp.data.noise.pauli-cx-biased.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 20000 per basis per simulation
- **Commit:** `8f580c14c880e3dbbd2e2be17991bee3d1c144ce`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (0.9999 to 1.0000) |
| noisy | 0.9747 | 0.0008 | 0.8909 | 0.8631 (0.8604 to 0.8659) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 0 (0) | 11 | 10 | 8 | not scheduled | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
