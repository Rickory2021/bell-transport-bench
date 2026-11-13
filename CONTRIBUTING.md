<!-- CONTRIBUTING.md -->
# Contributing

Git conventions for bell-transport-bench. Five people commit here during a one-week hackathon, so the rules aim at two things: nobody breaks `main`, and every result in the submission traces to a commit.

## Branch strategy

`main` is not protected, and the hackathon is too short for required pull request reviews, so these rules rely on care instead of enforcement.

- **`main` must always run.** Before you push to it, the checks under [Before pushing to `main`](#before-pushing-to-main) pass. Everyone branches from `main`, so a broken `main` stops the whole team.
- Pull before you start, so your commits land on top of everyone else's: `git switch main && git pull --rebase`.
- Tell the group before you commit to `main`, and say what changed, so nobody is surprised by their next pull.
- When unsure, branch. Experimental work, large changes, and anything touching shared code in `src/bellbench/` or `config/` go on a branch: `git switch -c <type>/<short-description>` (for example `feat/noise-schema`). Merge it into `main` when it is ready, or open a pull request if you want a second pair of eyes: `gh pr create --fill --base main`.
- If something breaks, stop and tell the group. Do not stack fixes on a broken `main`; undo the commit that broke it with `git revert <commit>`. **Never force-push `main`.**

Keep branches short-lived (a day or less), and rebase on `main` before merging if `main` moved: `git fetch origin && git rebase origin/main`, then `git push --force-with-lease` if you had already pushed the branch.

**A branch that holds committed results is never rebased or squashed.** Each run records the commit it was made from, and a rebase or a squash gives those commits new ids that no branch reaches, so the records would cite commits that no longer exist. Merge such a branch with a merge commit, `git merge --no-ff <branch>`, or the merge-commit option on GitHub.

## Staging and committing

Stage from the repo root, one file per line:

```bash
git add <path/to/file>
git commit -m "<type>(<scope>): <short summary>"
```

Do not use `git add .`, `git add -A`, or `git add <directory>/`. Export output, local configs and scratch notebooks are gitignored, but new untracked files slip in when staging by directory. A new results folder holds many files; stage them by name, from git's own list of the untracked files in that folder:

```bash
git ls-files --others --exclude-standard -- results/runs/benchmark/<name>/<stamp> | while read -r f; do git add -- "$f"; done
```

## Commit messages

Format: `<type>(<scope>): <short summary>`

The summary says what changed, not why, in under 72 characters. Use the body (after a blank line) for the why when it is not obvious, and for results: when a commit changes a benchmark number, the body says which cases moved and by how much.

**A message cites no internal record,** such as a decision, an audit finding or a working session: the repo is public and those records are not in it. Say in plain words what changed, why, and whether any number or output file moved.

**Types:**

| Type | Use for |
|------|---------|
| `feat` | New behaviour: a transport, a check, a noise channel, a renderer |
| `fix` | A bug: wrong results, crashes, broken configs |
| `refactor` | Restructuring with **identical results**, shown as [Commit chunking](#commit-chunking) says |
| `perf` | Faster with identical results |
| `test` | Tests only |
| `data` | `bp.data`, `bp.enum` and `bp.invoke` files: processor files, noise profiles, circuit files, benchmark files, and committed results |
| `docs` | README, CONTRIBUTING, docs/DESIGN.md, notebook narrative |
| `chore` | Scripts, Makefile, pyproject, lockfile, gitignore |

**Scopes:**

| Scope | Covers |
|-------|--------|
| `bench` | `src/bellbench/` |
| `config` | `config/` (bp schemas, data, enums, invokes) |
| `notebooks` | `notebooks/` |
| `docs` | `docs/` |
| `scripts` | `scripts/` |
| `tests` | `tests/` |
| `root` | Root-level files |

When a commit spans directories, use the primary one, or `root` for a cross-cutting change.

## Commit chunking

One commit per logical change you can describe in one sentence.

- **Never mix a refactor with a behaviour change.** A refactor commit must leave every benchmark number identical, so a reviewer can trust it without rerunning the science. Show it by making the benchmarks before and after the change and comparing `comparison.csv` and each run's `simulations.csv`; `make run RUN=<folder>` rebuilds one run from its record and reports any difference. Change behaviour in the next commit.
- A noise profile and the schema change it needs go together; an unrelated notebook edit does not.
- **A generated notebook goes in the same commit as the change that produced it,** so the notebook and the code never disagree.
- **Results come in the commit after their change.** A run or benchmark made while `src/` or `config/` has uncommitted changes lands in `workspace/`, which is never committed. Commit the change first, make the results from the clean tree, and commit them next, in a `data` commit whose body gives the headline numbers.

## Before pushing to `main`

```bash
make test
make bp-validate
```

Both must pass. If your change moves results, commit it, remake each benchmark it affects (`make benchmark`, then `make benchmark NAME=<n>` for each of `move-chain`, `biased-noise`, `mid-circuit-sweep` and `starting-excitation`), and commit the new folders in the next commit, as [Commit chunking](#commit-chunking) says.

The folders of the repo and what each holds are in the README's [Layout](README.md#layout) and [File naming](README.md#file-naming).
