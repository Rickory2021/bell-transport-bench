<!-- README.md -->
# bell-transport-bench

A benchmark for creating a Bell pair between two distant qubits and protecting it with error detection, across different processor connectivities and noise models. Built for the quanTA "geometry-aware quantum cloud" challenge at the UCF IBM Qiskit Fall Fest 2026.

**The question:** given a coupling graph, two fixed ports and a noise model, how well can we create |Φ+⟩ between the ports, what does error detection buy, and what does it cost in gates, ancillas and discarded shots?

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Rickory2021/bell-transport-bench/blob/submission/notebooks/bp.output.submission.ipynb)

**The submission notebook opens in Colab with the badge above, at the `submission` tag.** It needs Python 3.12 or later, installs the pinned packages in its first cell, and carries the code and recorded runs it needs, so it runs with no copy of the repo. To read it with every output, without running anything, open its executed copy, `notebooks/bp.output.submission.executed.ipynb`, [on GitHub](https://github.com/Rickory2021/bell-transport-bench/blob/submission/notebooks/bp.output.submission.executed.ipynb) or [in Colab](https://colab.research.google.com/github/Rickory2021/bell-transport-bench/blob/submission/notebooks/bp.output.submission.executed.ipynb). The tutorial and workbench notebooks import `bellbench` from the repo, so they run only in a clone set up with `make setup`, not from a Colab link.

The full task is in [`docs/CHALLENGE.md`](docs/CHALLENGE.md): three processor models, nine core cases, and what to report. The design decisions and their reasons are in [`docs/DESIGN.md`](docs/DESIGN.md), and every source we rely on is in [`docs/bp.data.references.yaml`](docs/bp.data.references.yaml).

## Quick start

Requires [uv](https://docs.astral.sh/uv/), which installs Python 3.12 if it is missing. `make setup` also installs poppler-utils with `sudo apt` for blueprint-render's PDF output, so it needs a Debian or Ubuntu system, WSL included, and sudo. Elsewhere, run `uv sync --group dev` in its place: everything below works without the PDF tools.

```bash
make setup       # poppler-utils with sudo apt, then uv sync
make test
make refs-fetch  # optional: local copies of each reference that has a download link
```

## Running the benchmark

```bash
make workbench                              # your own copy of the workbench notebook, in workspace/
make benchmark                              # the core benchmark
make benchmark NAME=deliverable-2026-11-17  # the nine cases the submission reports
make benchmark NAME=deliverable-2026-11-17-extended-<processor>
                                            # one graph's protected case beside the circuits one step from it:
                                            # ibm2016, contemporary or hyperbolic
make benchmark NAME=move-chain              # the nine cases the submission reported before
make benchmark NAME=<study>                 # an optional study: biased-noise, mid-circuit-sweep,
                                            # starting-excitation, middle-out or vacancy-read
make run RUN=<run folder>                   # rebuild a run from its record and report any difference
make report RUN=<run folder>                # redraw a run folder's diagrams and report.md
make submission                             # render the submission notebook from the snapshots its invoke names
make submission-executed                    # render it, then run it into its executed copy, with every output
```

**A run or benchmark made from committed code lands in `results/runs/`.** One made while `src/` or `config/` has uncommitted changes lands in `workspace/runs/`, which is never committed, and so does a run of a trial circuit in `workspace/circuits/`; a benchmark that names a trial is refused. To keep a result, commit the change, or promote the trial and commit it, and make it again. What each benchmark answers, and where its folders land, is in [DESIGN.md, section 6](docs/DESIGN.md#6-benchmarks-and-results). `make help` lists every target.

## Layout

| Path | What lives there |
|------|------------------|
| `src/bellbench/` | All benchmark logic: processors, noise, transports, checks, measurement, the runner |
| `config/` | Typed configs: processor files, noise profiles, circuit files and benchmark files |
| `results/` | Runs and benchmarks made from committed code, each in a folder never edited afterwards |
| `workspace/` | Your workbench copy, trial circuits, and anything made with uncommitted changes or from a trial; only its README is committed |
| `notebooks/` | The tutorial, workbench and submission notebooks, generated from their templates; narrative and plots only |
| `docs/` | `CHALLENGE.md` (the task), `DESIGN.md` (decisions and reasons), and the references data |
| `scripts/` | blueprint-render (validates and renders typed YAML) and flatten-sync (exports the repo for Claude Projects) |
| `tests/` | pytest suite |

## How the repo works

**Logic lives in Python, narrative lives in notebooks.** Every function the benchmark runs sits in `src/bellbench/`. Notebooks import it and add explanation and plots, never logic. Notebooks are generated from their templates in `notebooks/` by blueprint-render, the workbench and the submission notebook; never edit a generated notebook by hand.

**Configs are typed data.** Processor files, noise profiles, circuit files and benchmark files are YAML files validated by schemas, so every assumption is a reviewable file with its source, and every result traces to a config, a seed and pinned package versions.

**Sources are data, not copies.** Every paper, slide deck and doc we rely on is an entry in `docs/bp.data.references.yaml`: its link, an archive snapshot where the original may disappear, a summary in our words, and each claim we take from it with where it appears and which file uses it. Nothing is copied into the repo. `make refs-fetch` downloads local copies into the gitignored `.references/` folder. Entries marked `checked: false` came from secondary accounts and must be confirmed against the original before they reach the submission.

### File naming

Files in the typed system carry their role in a `bp.` prefix:

| Prefix | Role |
|--------|------|
| `bp.schema.*` | Validates a data file (JSON Schema draft 2020-12, written in YAML) |
| `bp.data.*` | Structured data validated by a schema: the configs, and the circuit files, run records and run lists the code writes |
| `bp.enum.*` | A legal value set under a single `values:` key |
| `bp.process.*` | Configures a rendering pipeline (vars, map, emit, output) |
| `bp.invoke.*` | Configures one run of a process |
| `bp.output.*` | A rendered artifact, committed so results have history |

Run `make bp-validate` to check every typed file.

## Science rules

- **Error detection, never fault tolerance.** Parity checks with postselection detect errors and discard shots; they correct nothing.
- **Every postselected fidelity is reported with its acceptance fraction,** raw and accepted shots per basis, and how the uncertainty was computed.
- **Separate connectivity from noise.** Any architecture claim needs a run where all graphs share one noise model: the same profile, scale factor, overrides and conditional channels. A comparison that differs in any of them, such as a protected case that sets a mid-circuit measurement error the others do not, is stated as conditional on that difference.
- **Circuits are scheduled before noise is applied** under a snapshot profile, the kind with durations, so idle time, measurement and reset cost what they would on hardware. A depolarising or pauli profile has no durations, so its runs are not scheduled, and a result under one states that its noise is gate noise alone.
- **No readout mitigation in the core benchmark.**
- **One finite model is not a universal advantage.** Recommendations are stated as conditional on the model.

## Contributing

Branch and commit rules are in [`CONTRIBUTING.md`](CONTRIBUTING.md). Read them before your first commit.

## AI use

We used AI assistants, including Claude, for research summaries, design discussion, and drafting code and documentation. We also used them in a search over candidate circuits; the team chose the reported circuit and checked it with the benchmark. The team reviewed and ran everything in this repo and can explain it.
