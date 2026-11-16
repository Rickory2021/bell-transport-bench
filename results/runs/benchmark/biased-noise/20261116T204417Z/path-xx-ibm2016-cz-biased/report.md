# Run move-chain-path-xx-ibm2016 under pauli-cz-biased

- **Circuit file:** `config/circuit/bp.data.circuit.move-chain-path-xx-ibm2016.yaml`
- **Noise profile:** `config/noise/bp.data.noise.pauli-cz-biased.yaml`, scale 1
- **Overrides:** 0
- **Shots:** 20000 per basis per simulation
- **Commit:** `e5b712e7f2687b0401a04b777cfd055fcfe387e7`

| Simulation | F | Standard error | F raw | Acceptance (95% Wilson interval) |
|---|---|---|---|---|
| ideal | 1.0000 | 0.0000 | 1.0000 | 1.0000 (0.9999 to 1.0000) |
| noisy | 0.9696 | 0.0009 | 0.9359 | 0.9292 (0.9271 to 0.9312) |

| SWAPs (router's) | Two-qubit gates | Depth | Qubits used | Scheduled duration | Pair on the ports |
|---|---|---|---|---|---|
| 0 (0) | 5 | 11 | 3 | not scheduled | yes |

Standard error method: binomial per basis: var(c) = (1 - c^2)/N, independent bases, SE(F) = sqrt(sum var)/4.
