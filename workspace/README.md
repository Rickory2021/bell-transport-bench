<!-- workspace/README.md -->
# workspace

**Your scratch space: everything here except this README is gitignored, so nothing in it reaches the repo.**

- **`circuits/`** holds trial circuits: circuit files saved with `save_circuit(..., trial=True)`, or a builder's `state.save(..., trial=True)`. A run loads one by its name, like a committed circuit, and no name is ever both. When a trial is worth keeping, `promote("<name>")` from `bellbench.circuits` moves it into `config/circuit/`, ready to commit. A benchmark names only committed circuits.
- **`runs/`** holds runs and benchmarks made while `src/` or `config/` had uncommitted changes, and runs of trial circuits, in the same layout as `results/runs/`: `runs/workbench/<circuit>/<noise>/<stamp>/` for a run made on its own, and `runs/benchmark/<name>/<stamp>/` for a benchmark, with its runs inside.
- **`workbench.ipynb`** is your copy of the workbench notebook, made by `make workbench`. Edit and run it here, never the generated one in `notebooks/`; `make workbench FORCE=1` replaces it with a fresh copy.

**To keep a result,** commit the change it came from, or promote the trial and commit it, and make the run again: a clean run lands in `results/`, and a result made from uncommitted code cannot be rebuilt (docs/DESIGN.md, section 5).
