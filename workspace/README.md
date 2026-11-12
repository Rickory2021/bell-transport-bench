<!-- workspace/README.md -->
# workspace

**Your scratch space: everything here except this README is gitignored, so nothing in it reaches the repo.**

- **`runs/`** holds a run made while `src/` or `config/` had uncommitted changes, in the same layout as `results/runs/`: `runs/<circuit>/<noise>/<stamp>/`.
- **`benchmarks/`** holds a benchmark made with uncommitted changes.

**To keep a result,** commit the change it came from and make the run again: a clean run lands in `results/`, and a result made from uncommitted code cannot be rebuilt (docs/DESIGN.md, section 5).
