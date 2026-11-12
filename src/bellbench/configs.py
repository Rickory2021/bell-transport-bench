# src/bellbench/configs.py
"""Find, load and hash the config files in config/ by name.

A processor file is config/processor/bp.data.processor.<n>.yaml and a noise
profile config/noise/bp.data.noise.<n>.yaml. Their shapes are checked by the
schemas in config/ through `make bp-validate`, and what spans fields by
tests/test_config.py. This module only reads files.

`content_hash` identifies a config file by its parsed content, so a run can
record which version of each file it used and a rerun can refuse one that
changed (docs/DESIGN.md, section 5). Editing a comment or the formatting leaves
the hash unchanged.
"""

import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROCESSOR_DIR = ROOT / "config" / "processor"
NOISE_DIR = ROOT / "config" / "noise"


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


def noise_path(name: str) -> Path:
    """The noise profile for `name`; raises FileNotFoundError naming the known profiles."""
    path = NOISE_DIR / f"bp.data.noise.{name}.yaml"
    if not path.is_file():
        known = ", ".join(noise_names()) or "none"
        raise FileNotFoundError(f"no noise profile named {name!r} in {NOISE_DIR}; known: {known}")
    return path


def noise_names() -> list[str]:
    """The names of every noise profile, sorted."""
    return sorted(p.name.split(".")[-2] for p in NOISE_DIR.glob("bp.data.noise.*.yaml"))


def load_noise(name: str) -> dict:
    """The noise profile for `name`, as loaded YAML."""
    with open(noise_path(name), encoding="utf-8") as f:
        return yaml.safe_load(f)


def content_hash(path: Path) -> str:
    """`sha256:` and the hash of the file's parsed YAML, written as JSON with sorted keys.

    Comments and formatting do not change it; any value does. Dates hash as
    their ISO text.
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def repo_path(path: Path) -> str:
    """`path` relative to the repo root, with forward slashes, as runs record it."""
    return Path(path).resolve().relative_to(ROOT).as_posix()
