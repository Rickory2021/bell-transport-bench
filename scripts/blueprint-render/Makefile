# scripts/blueprint-render/Makefile
#
# Portable Makefile for the blueprint-render tool.
# Travels with the blueprint-render/ directory.
#
# From repo root (via delegation):
#   make setup
#   make bp-validate
#   make bp-validate VERBOSE=true
#   make bp-validate FILE=config/bp.data.processor.ibm2016.yaml
#   make bp-validate KEY=project
#   make bp-test
#   make bp-run
#   make bp-run FILE=notebooks/bp.invoke.notebook.submission.yaml
#
# Standalone (from this directory):
#   make setup
#   make validate
#   make validate VERBOSE=true
#   make validate FILE=config/bp.data.processor.ibm2016.yaml
#   make validate KEY=project
#   make test
#   make run
#   make run FILE=notebooks/bp.invoke.notebook.submission.yaml

PROJECT_ROOT ?= $(shell git rev-parse --show-toplevel)
VERBOSE_FLAG := $(if $(VERBOSE),-v,)

.DEFAULT_GOAL := help

.PHONY: help setup validate test invoke pdftotext

help:
	@echo "blueprint-render"
	@echo ""
	@echo "  make setup                     Install system dependencies"
	@echo "  make validate                  Validate all bp files (failures only)"
	@echo "  make validate VERBOSE=true     Validate all bp files (verbose)"
	@echo "  make validate FILE=<path>      Validate one file (root-relative)"
	@echo "  make validate KEY=<key>        Validate all files for a key"
	@echo "  make test                      Run test suite"
	@echo "  make invoke                    Render all invokes"
	@echo "  make invoke FILE=<path>        Render one invoke (root-relative)"
	@echo "  make invoke FORCE=true         Re-render even if output exists"
	@echo "  make invoke OUTPUT=renderout   Render-out only (iteration mode)"
	@echo "  make invoke OUTPUT=adjacent    Adjacent bp.output only"
	@echo "  make pdftotext FILE=<path>     Extract text to .txt file and print"

setup:
	@echo "Installing system dependencies..."
	sudo apt install -y poppler-utils
	@echo "Done. Python deps are handled by uv run."

validate:
ifdef FILE
	uv run blueprint_render.py --root $(PROJECT_ROOT) validate $(VERBOSE_FLAG) --file $(FILE)
else ifdef KEY
	uv run blueprint_render.py --root $(PROJECT_ROOT) validate $(VERBOSE_FLAG) --key $(KEY)
else
	uv run blueprint_render.py --root $(PROJECT_ROOT) validate $(VERBOSE_FLAG)
endif

FORCE_FLAG := $(if $(FORCE),--force,)
OUTPUT_FLAG := $(if $(OUTPUT),--output $(OUTPUT),)

invoke:
ifdef FILE
	uv run blueprint_render.py --root $(PROJECT_ROOT) run $(FORCE_FLAG) $(OUTPUT_FLAG) --file $(FILE)
else
	uv run blueprint_render.py --root $(PROJECT_ROOT) run $(FORCE_FLAG) $(OUTPUT_FLAG)
endif

pdftotext:
ifndef FILE
	$(error FILE is required. Usage: make pdftotext FILE=<path-to-pdf>)
endif
	pdftotext $(PROJECT_ROOT)/$(FILE) $(PROJECT_ROOT)/$(basename $(FILE)).txt
	@sed -i 's/\x0c//g' $(PROJECT_ROOT)/$(basename $(FILE)).txt
	@cat $(PROJECT_ROOT)/$(basename $(FILE)).txt

test:
	uv run --group dev pytest tests/ -q
