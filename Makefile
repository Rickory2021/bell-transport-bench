# Makefile
#
# bell-transport-bench root Makefile.
# Delegates to scripts/flatten-sync/ for project export and watch, and to
# scripts/blueprint-render/ for bp file validation and rendering.

PROFILE ?= default
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
	@echo "    make test                        Run the bellbench test suite"
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

.PHONY: test

test:
	uv run --group dev pytest -q

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
