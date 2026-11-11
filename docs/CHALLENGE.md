<!-- docs/CHALLENGE.md -->
# The challenge

The task this repo answers, restated in our own words from the organisers' material: the quanTA (University of Saskatchewan) challenge deck presented by Steven Rayan at the UCF IBM Qiskit Fall Fest 2026, and the organisers' Bell-fidelity starter notebook. Sources and snapshot links are in `docs/bp.data.references.yaml` (`quanta-challenge-deck`, `bell-fidelity-starter`, `fallfest-site`). This file is the single statement of the requirements; other docs link here instead of restating them.

## Context

Qubits on real chips connect only to their neighbours. A circuit that needs two distant qubits to interact must be routed: extra operations, usually SWAPs, carry the interaction across the coupling graph, and under noise each one costs quality. quanTA studies how the geometry of a processor, including finite hyperbolic lattices with unusual patterns of connections and cycles, affects routing and error detection. Qiskit gives a common way to compare historical, contemporary and hypothetical processor models.

## Objective

On each of three processor models:

1. Create a verified Bell correlation, the state |Φ+⟩ = (|00⟩ + |11⟩)/√2, between two designated ports.
2. Establish an ideal baseline and a noisy baseline.
3. Test one justified error-detection or protection strategy.
4. Compare the resulting fidelity with the circuit cost and any discarded shots, and explain the differences between the three architectures.

## The three processor models

| Model | What the deck specifies | Ports as drawn |
|---|---|---|
| 2016-inspired reference | Five qubits, five-node reference graph, synthetic noise model | Top and bottom of a T-shaped graph, 2 hops apart |
| Contemporary IBM-style | A backend snapshot or fake backend, its native target and gate set, contemporary compilation as the baseline | Opposite ends of a schematic 9-node graph, 4 hops apart |
| Hyperbolic-inspired | A finite lattice-derived coupling graph, hypothetical qubit connectivity, a circuit-level model only | Top and bottom of a 13-node graph, 3 hops apart |

The deck gives drawings, not edge lists. Our transcriptions and how we use them are in `docs/DESIGN.md`, section 3.

## Verification

Measure the two port qubits in three bases and form the correlators ⟨XX⟩, ⟨YY⟩ and ⟨ZZ⟩:

- **ZZ:** measure directly.
- **XX:** apply H to both qubits, then measure.
- **YY:** apply S† then H to both qubits, then measure.

For each basis, ⟨BB⟩ = P(00) + P(11) − P(01) − P(10). The Bell fidelity is

F(Φ+) = [1 + ⟨XX⟩ − ⟨YY⟩ + ⟨ZZ⟩] / 4

Ideally ⟨XX⟩ = +1, ⟨YY⟩ = −1, ⟨ZZ⟩ = +1, so F = 1. Agreement in Z alone is not enough: a classical mixture of 00 and 11 also gives ⟨ZZ⟩ = +1.

## The nine core cases

| Model | Ideal baseline | Noisy baseline | Noisy + protection |
|---|---|---|---|
| 2016-inspired | Case 1 | Case 2 | Case 3 |
| Contemporary IBM-style | Case 4 | Case 5 | Case 6 |
| Hyperbolic-inspired | Case 7 | Case 8 | Case 9 |

For each model, compare the noisy baseline with the protected result and its added cost.

## Protection strategies the deck names

- **Parity or stabilizer checks:** extra measurements that reveal particular errors without measuring the encoded information.
- **Syndrome postselection:** keep only outcomes that pass a check. Any gain in conditional fidelity must be reported with the fraction of accepted shots.
- **Geometry-aware encodings:** for more advanced teams, adapt an encoding or check network to the available connections and measure its overhead.

## Rules

Common requirements:

- Use the common processor definitions, fixed output ports and noise assumptions.
- Complete the three-model comparison and test one justified protection method.
- Report reproducible results, including added operations and postselection yield.

Free choices and extensions:

- Choose the layout, routing method and protection strategy.
- Explore alternative noise models, larger circuits or geometry-aware encodings.
- Keep optional studies and real-hardware results separate from the common benchmark.

## Required measurements

| Measure | Report |
|---|---|
| Output quality | Bell fidelity with uncertainty |
| Circuit cost | Depth and number of two-qubit gates |
| Routing | SWAP overhead |
| Qubit use | Physical qubits, including ancillas |
| Postselection | Acceptance fraction and discarded shots |

## Suggested approaches by experience

| Level | Approach | Main comparison |
|---|---|---|
| Explorer | Bell preparation and a simple error-detection check | Ideal, noisy and protected results |
| Builder | Placement, routing or improved checks | Fidelity benefit versus extra operations |
| Research | Geometry-aware encoding or stabilizer network | Scaling and sensitivity to noise |

## Interpreting the comparison

- Relate changes in fidelity to the operations compilation introduced and to the assumed noise model.
- Judge whether a protection method pays for its extra gates, ancillas and discarded shots.
- Separate connectivity effects from differences in gate sets or noise. A result from one finite model does not establish a universal advantage.

## Submission

Materials:

1. A reproducible notebook: Qiskit code, assumptions and recorded results.
2. Graphs and circuits: the three coupling graphs with their ports, and the transpiled circuits.
3. A quantitative comparison: fidelity, circuit cost and yield across the core cases.
4. A scientific interpretation: what the results show and their limitations.
5. A hardware or software recommendation: one specific design choice for future cloud systems, supported by the results.

Delivery: email the submission to the organiser with a video presentation of at most 15 minutes. Groups of up to 5 members. Deadline: November 16, 2026.

## Judging rubric

| Criterion | Weight |
|---|---|
| Scientific correctness and reproducibility | 30% |
| Quality of the architecture comparison | 20% |
| Protection or error-detection strategy | 20% |
| Effective use of Qiskit | 15% |
| Evidence for the future-system recommendation | 10% |
| Clarity of presentation | 5% |
