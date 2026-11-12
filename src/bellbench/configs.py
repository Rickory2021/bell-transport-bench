# src/bellbench/configs.py
"""Find and load the config files in config/ by name.

A processor file is config/processor/bp.data.processor.<name>.yaml; its shape is
checked by config/bp.schema.processor.yaml through `make bp-validate`, and what
spans fields by tests/test_config.py. This module only reads files.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROCESSOR_DIR = ROOT / "config" / "processor"


def processor_path(name: str) -> Path:
    """The processor file for `name`; raises FileNotFoundError naming the known processors."""
    path = PROCESSOR_DIR / f"bp.data.processor.{name}.yaml"
    if not path.is_file():
        known = ", ".join(processor_names()) or "none"
        raise FileNotFoundError(f"no processor file named {name!r} in {PROCESSOR_DIR}; known: {known}")
    return path


def processor_names() -> list[str]:
    """The names of every processor file, sorted."""
    return sorted(p.name.split(".")[-2] for p in PROCESSOR_DIR.glob("bp.data.processor.*.yaml"))


def load_processor(name: str) -> dict:
    """The processor file for `name`, as loaded YAML."""
    with open(processor_path(name), encoding="utf-8") as f:
        return yaml.safe_load(f)
