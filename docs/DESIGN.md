<!-- docs/DESIGN.md -->
# Design

The design decisions behind bell-transport-bench, and why each was made. When a decision changes, rewrite its section and add a line to the change log at the bottom; never leave two versions of one decision standing.

## The problem

The task is stated once, in [`CHALLENGE.md`](CHALLENGE.md). Sources cited below by id are in [`bp.data.references.yaml`](bp.data.references.yaml).

## 1. Logic in Python, the notebook compiled from it

All benchmark logic lives in `src/bellbench/`. Notebooks import it and add narrative and plots only. The submission is one self-contained notebook, compiled by a blueprint-render renderer, that runs on Colab or any pinned environment. It is shaped like a paper: abstract, methods, results, limitations, recommendation. No separate paper is written.

**Why:** the submission is emailed with a video of at most 15 minutes, so one runnable file is the deliverable. Keeping logic out of notebooks keeps it testable and diffable for five people.

## 2. Typed configs

Processor models, noise profiles and run configs are `bp.data` and `bp.invoke` files validated by `bp.schema` files. Each assumption is a file with its source; each result traces to a config, a seed and pinned package versions.

**Why:** reproducibility is 30% of the grade, and the challenge requires stated assumptions.

## 3. Processor models follow the slides

| Model | Graph | Ports | Noise |
|---|---|---|---|
| 2016-inspired | T shape, 5 qubits (same graph as FakeLondonV2) | 2 hops apart, one path | Synthetic, from ibmqx4's 2018 published figures |
| Contemporary | Heron heavy-hex fake backend (FakeFez), no fractional gates | 4 hops apart, chosen for the most qubit-disjoint paths; the real count is reported | The fake backend's calibration snapshot |
| Hyperbolic-inspired | The slide's 13-node drawing as transcribed: 24 edges, degree-6 centre | 3 hops apart, three disjoint paths | The contemporary profile, plus a sensitivity profile with higher error on the hub |

The code also accepts custom topologies. The contemporary slide drawing (a 9-node graph with a degree-5 node) is a schematic, so a real backend stands in for it.

**Framing:** the 13-node graph is not a hyperbolic {p,q} patch (its curvature is flat or positive everywhere), so results are presented as effects of port distance, disjoint paths and degree in one finite model, never as a hyperbolic advantage. A true {7,3} patch may run as an optional study.

**Why:** the challenge says to use its definitions; our architecture research found the T graph matches IBM fake backends and the other two drawings are schematics. Sources: `quanta-challenge-deck`, `johnstun-2021-ibm-noise`, `pokharel-2018-dynamical-decoupling`, `kollar-2019-hyperbolic-cqed`, `rayan-2026-rethinking-circuits`, `chamberland-2020-heavy-hex`.

## 4. Noise model

The team's own model, built as selectable, composable profiles: channels attached per gate type, operation, qubit or edge, each value carrying its source.

| Tier | Channels |
|---|---|
| Core | Gate errors; decay during gates and while idle; asymmetric readout; decay during measurement; reset error; temperature and starting excitation |
| Optional sensitivity | Measurement-induced dephasing of neighbours; always-on ZZ; spectator errors during gates; coherent errors; drift by resampling; leftover excitation versus repetition delay |
| Not modelled (stated as limitations) | Cosmic-ray bursts; leakage; frequency crowding |

Every circuit is scheduled before noise is applied, so idle time, measurement and reset cost what they would on hardware. Biased-noise and replacement-gate profiles are optional and stated as assumptions. A same-noise run across all three graphs separates connectivity from noise.

**Why:** Qiskit Aer's `NoiseModel.from_backend` covers only gate error, readout flips and decay on explicit delays (our noise research). Without scheduling, measurement-heavy strategies look free. Sources: `qiskit-aer-noise-docs`, `replacement-type-gates`.

## 5. Protection as building blocks

Protection is built from composable blocks: transport, path selector, check type (vacancy, ZZ, XX, flagged), check placement (the pair's path or a spare disjoint path), check timing (terminal or mid-circuit) and analysis. A strategy is a run config, and the core strategy is chosen from benchmark results rather than in advance.

It is always called error detection with postselection, never fault tolerance or error correction.

**Why:** choosing the strategy before the benchmark exists gets the order backwards. The open question worth testing (our protection research found no prior work on it) is whether spare disjoint paths let a pair be checked without mid-circuit measurement. Sources: `smith-2026-error-detected-primitives`, `baumer-2024-long-range-entanglement`, `liao-2025-error-detected-entanglement`, `andersen-2019-parity-stabilization`, `chao-reichardt-2018-flag-qubits`, `siddhu-2025-distillation`.

## 6. Metrics and reporting

- **Headline per case:** (F after postselection, acceptance p) beside (F raw, 1) for the baseline.
- **Derived:** infidelity removed per unit of rejection; two-qubit gates per accepted pair. Break-even is where the first crosses zero in a noise sweep.
- **Recorded per case:** F raw and F postselected with uncertainty, p with a Wilson interval, raw and accepted shots per basis, and the uncertainty method. Shots scale with 1/p.
- **No readout mitigation** in the core benchmark. Aer runs use the standard `measure`.

**Why:** this is how the field reports postselected results (our protection research), and it keeps p well defined. Source: `smith-2026-error-detected-primitives`.

## 7. Repo and tooling

- Private GitHub repo; Python 3.12 with uv; exact pins: qiskit 2.6.2, qiskit-aer 0.18.2, qiskit-ibm-runtime 0.51.0.
- Feature branches merged into `main` by pull request (CONTRIBUTING.md).
- `scripts/` holds the generic engines of blueprint-render and flatten-sync from dev-forge, pruned of all dev-forge-specific code, profiles and tests before the first commit. The PDF renderer stays, unused.

**Why:** 3.12 is the overlap of what Qiskit, Aer, IBM Runtime and blueprint-render support, and what Colab runs. The scripts were pruned so nothing unrelated to this project enters its history.

## 8. Compilation

Circuits are written on physical qubits and compiled at optimisation level 1. From level 2 up, Qiskit's ElidePermutations pass deletes explicit SWAPs and relabels the outputs instead, so the pair would never physically reach the ports; every result records whether it did. Routing that relies on SABRE is run over several seeds, since the heuristic's results vary by seed.

**Why:** the benchmark measures the cost of moving the pair, so the compiler must not optimise the move away. Source: `fallfest-compilation-deck`.

## Change log

- 2026-11-11: initial decisions 1 to 7.
- 2026-11-11: research is folded into this file and the README, citing original sources; reports are not stored in the repo.
- 2026-11-11: the task moved to CHALLENGE.md; sources became `bp.data.references.yaml`; section 8 (compilation) added.
