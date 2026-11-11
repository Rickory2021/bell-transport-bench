<!-- CONTRIBUTING.md -->
# Contributing

Git conventions for bell-transport-bench. Five people commit here during a one-week hackathon, so the rules aim at two things: nobody breaks `main`, and every result in the submission traces to a commit.

## Branch strategy

`main` always runs: `make test` passes and the core benchmark reproduces. Nobody pushes to it directly.

1. Branch from an up-to-date `main`: `git switch main && git pull && git switch -c <type>/<short-description>` (for example `feat/noise-schema`, `fix/vacancy-check`).
2. Commit on the branch, following the rules below.
3. Push the branch and open a pull request: `gh pr create --fill --base main`.
4. The repo owner merges with squash merge, so `main` gets one commit per pull request, titled in the commit format below.
5. Delete the branch after merge: `gh pr merge --squash --delete-branch` does both.

Keep branches short-lived (a day or less). Rebase on `main` before opening the pull request if `main` moved: `git fetch origin && git rebase origin/main`, then `git push --force-with-lease`.

## Staging and committing

Stage from the repo root, one file per line:

```bash
git add <path/to/file>
git commit -m "<type>(<scope>): <short summary>"
```

Do not use `git add .`, `git add -A`, or `git add <directory>/`. Export output, local configs and scratch notebooks are gitignored, but new untracked files slip in when staging by directory.

## Commit messages

Format: `<type>(<scope>): <short summary>`

The summary says what changed, not why, in under 72 characters. Use the body (after a blank line) for the why when it is not obvious, and for results: when a commit changes a benchmark number, the body says which cases moved and by how much.

**Types:**

| Type | Use for |
|------|---------|
| `feat` | New behaviour: a transport, a check, a noise channel, a renderer |
| `fix` | A bug: wrong results, crashes, broken configs |
| `refactor` | Restructuring with **identical results** (proved by a parity check) |
| `perf` | Faster with identical results |
| `test` | Tests only |
| `data` | `bp.data`, `bp.enum` and `bp.invoke` files: processor models, noise profiles, run configs |
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

- **Never mix a refactor with a behaviour change.** A refactor commit must leave every benchmark number identical, so a reviewer can trust it without rerunning the science. Change behaviour in the next commit.
- A noise profile and the schema change it needs go together; an unrelated notebook edit does not.
- Generated files (the submission notebook, result tables) go in the same commit as the change that produced them, so the numbers and the code never disagree.

## Before opening a pull request

```bash
make test
make bp-validate
```

Both must pass. If the pull request changes results, rerun the core benchmark and commit the regenerated outputs with it.
