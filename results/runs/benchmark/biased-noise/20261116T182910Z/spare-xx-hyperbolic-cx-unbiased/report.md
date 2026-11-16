# Run move-chain-spare-xx-hyperbolic under pauli-cx-unbiased

- **Circuit file:** `config/circuit/bp.data.circuit.move-chain-spare-xx-hyperbolic.yaml`
- **Noise profile:** `config/noise/bp.data.noise.pauli-cx-unbiased.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 20000 per basis per simulation
- **Commit:** `8f580c14c880e3dbbd2e2be17991bee3d1c144ce`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (0.9999 to 1.0000) |
| noisy | 0.9543 | 0.0011 | 0.9037 | 0.9308 (0.9288 to 0.9329) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 0 (0) | 8 | 8 | 6 | not scheduled | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
