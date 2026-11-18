# Makefile
#
# bell-transport-bench root Makefile.
# Delegates to scripts/flatten-sync/ for project export and watch, and to
# scripts/blueprint-render/ for bp file validation and rendering.

# Plain = rather than ?=, so an environment variable of the same name never
# replaces a default; a value on the command line still does. WSL, for one,
# exports NAME as the machine's hostname.
PROFILE = default
FLATTEN_DIR = scripts/flatten-sync
BLUEPRINT_DIR = scripts/blueprint-render

.DEFAULT_GOAL := help

# -- Help ----------------------------------------------------------------

.PHONY: help

help:
	@echo "bell-transport-bench"
	@echo ""
	@echo "  Setup:"
	@echo "    make setup                       Create the env (uv sync) and system deps"
	@echo ""
	@echo "  Benchmark:"
	@echo "    make test                        Run the bellbench test suite in parallel (the gate before a commit)"
	@echo "    make test-fast                   The same, skipping the tests marked slow, for use while editing"
	@echo "    make test-serial                 The whole suite in one process, for debugging"
	@echo "    make benchmark                   Make the core benchmark (results/ or workspace/)"
	@echo "    make benchmark NAME=<n>          Make another benchmark"
	@echo "    make run RUN=<path>              Rerun a run folder and compare: make exits 0 on a match, 2 for a"
	@echo "                                     difference or a refusal; the last line make prints names the"
	@echo "                                     rerun's own code (Error 1 a difference, Error 2 a refusal)"
	@echo "    make report RUN=<path>           Redraw a run folder's diagrams and report.md"
	@echo "    make workbench                   Render the tutorial and the workbench and copy them into workspace/"
	@echo "    make workbench FORCE=1           The same, replacing existing workspace copies"
	@echo "    make submission                  Render the submission notebook, notebooks/bp.output.submission.ipynb"
	@echo "    make submission-executed         Render it, then run it into notebooks/bp.output.submission.executed.ipynb"
	@echo "                                     (about six minutes), the copy with every output"
	@echo ""
	@echo "  Docs figures:"
	@echo "    make figures                     Draw docs/assets/processor-models.png from the processor files"
	@echo "    make diagram                     Render docs/assets/design-flow.png from DESIGN.md (needs Node)"
	@echo ""
	@echo "  References:"
	@echo "    make refs-fetch                  Download local copies into .references/ (gitignored)"
	@echo ""
	@echo "  Project sync:"
	@echo "    make project-export              Export to Claude Project (default profile)"
	@echo "    make project-export PROFILE=x    Export with named profile"
	@echo "    make project-export-dry-run      Preview without copying"
	@echo "    make project-watch               Watch Downloads, auto-place files"
	@echo ""
	@echo "  Blueprint render:"
	@echo "    make bp-validate                 Validate all bp files"
	@echo "    make bp-validate FILE=<path>     Validate one file (root-relative)"
	@echo "    make bp-invoke                   Render all invokes"
	@echo "    make bp-invoke FILE=<path>       Render one invoke (root-relative)"
	@echo "    make bp-test                     Run blueprint-render test suite"

# -- Setup ---------------------------------------------------------------

.PHONY: setup bp-setup

setup: bp-setup
	uv sync --group dev

bp-setup:
	$(MAKE) -C $(BLUEPRINT_DIR) setup

# -- Benchmark -----------------------------------------------------------

.PHONY: test test-fast test-serial benchmark run report workbench submission submission-executed

NAME = core

# make test spreads the suite over one worker per core (pytest-xdist); make test-serial runs it in one
# process, where a debugger and print output work as usual.
test:
	uv run --group dev pytest -q -n auto

test-fast:
	uv run --group dev pytest -q -n auto -m "not slow"

test-serial:
	uv run --group dev pytest -q

benchmark:
	uv run python -m bellbench.run benchmark $(NAME)

run:
	@test -n "$(RUN)" || { echo "usage: make run RUN=<run folder or its bp.data.result.yaml>"; exit 2; }
	uv run python -m bellbench.run rerun $(RUN)

report:
	@test -n "$(RUN)" || { echo "usage: make report RUN=<run folder or its bp.data.result.yaml>"; exit 2; }
	uv run python -m bellbench.run report $(RUN)

# The notebooks make workbench renders: each from notebooks/bp.invoke.<name>.yaml into
# notebooks/bp.output.<name>.ipynb, then copied to workspace/<name>.ipynb, where a teammate edits and runs it.
WORKBENCH_NOTEBOOKS = workbench tutorial

workbench: $(WORKBENCH_NOTEBOOKS:%=workbench-%)

workbench-%:
	$(MAKE) -C $(BLUEPRINT_DIR) invoke PROJECT_ROOT=$(CURDIR) FILE=notebooks/bp.invoke.$*.yaml FORCE=true OUTPUT=adjacent
	@mkdir -p workspace
	@if [ -e workspace/$*.ipynb ] && [ -z "$(FORCE)" ]; then \
		echo "workspace/$*.ipynb exists; make workbench FORCE=1 replaces it"; \
	else \
		cp notebooks/bp.output.$*.ipynb workspace/$*.ipynb && echo "wrote workspace/$*.ipynb"; \
	fi

# The submission notebook: rendered from notebooks/bp.invoke.submission.yaml into notebooks/bp.output.submission.ipynb,
# with the code and the chosen snapshots packed into it, and committed. It is never copied into workspace/.
submission:
	$(MAKE) -C $(BLUEPRINT_DIR) invoke PROJECT_ROOT=$(CURDIR) FILE=notebooks/bp.invoke.submission.yaml FORCE=true OUTPUT=adjacent

# The submission notebook as a reader sees it after Run all: rendered, run top to bottom in a fresh kernel, and
# normalized, so it differs from the last copy only where the notebook or its results do. Committed with the render.
submission-executed: submission
	uv run --group dev python scripts/execute_notebook.py notebooks/bp.output.submission.ipynb notebooks/bp.output.submission.executed.ipynb

# -- Docs figures --------------------------------------------------------
# make figures needs only the Python env. make diagram needs Node, because the
# Mermaid CLI renders through a headless browser; only whoever edits the
# diagram in docs/DESIGN.md runs it, and the PNG is committed for everyone else.

MERMAID_CLI = @mermaid-js/mermaid-cli@11.16.0

.PHONY: figures diagram

figures:
	uv run python -m bellbench.figures

diagram:
	@tmp=$$(mktemp --suffix=.mmd) && \
	awk '/^```mermaid/{f=1; next} /^```/{f=0} f' docs/DESIGN.md > $$tmp && \
	test -s $$tmp || { echo "no mermaid block in docs/DESIGN.md"; rm -f $$tmp; exit 1; } && \
	npx -y $(MERMAID_CLI) -i $$tmp -o docs/assets/design-flow.png -s 2 -b white && \
	rm -f $$tmp

# -- References ----------------------------------------------------------

.PHONY: refs-fetch

refs-fetch:
	uv run python scripts/fetch_refs.py

# -- Project sync --------------------------------------------------------

.PHONY: project-export project-export-dry-run project-watch

project-export:
	$(MAKE) -C $(FLATTEN_DIR) run PROFILE=$(PROFILE) PROJECT_ROOT=$(CURDIR)

project-export-dry-run:
	$(MAKE) -C $(FLATTEN_DIR) dry-run PROFILE=$(PROFILE) PROJECT_ROOT=$(CURDIR)

project-watch:
	$(MAKE) -C $(FLATTEN_DIR) watch PROFILE=$(PROFILE)

# -- Blueprint render ----------------------------------------------------

.PHONY: bp-validate bp-test bp-invoke

bp-validate:
	$(MAKE) -C $(BLUEPRINT_DIR) validate PROJECT_ROOT=$(CURDIR) $(if $(VERBOSE),VERBOSE=$(VERBOSE),) $(if $(FILE),FILE=$(FILE),) $(if $(KEY),KEY=$(KEY),)

bp-invoke:
	$(MAKE) -C $(BLUEPRINT_DIR) invoke PROJECT_ROOT=$(CURDIR) $(if $(FILE),FILE=$(FILE),)

bp-test:
	$(MAKE) -C $(BLUEPRINT_DIR) test
