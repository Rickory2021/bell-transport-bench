# src/bellbench/configs.py
"""Find, load and hash the config files in config/ by kind and name.

Each kind of config file lives in its own folder under config/ and is named
bp.data.<kind>.<name>.yaml: a processor file in config/processor/ and a noise
profile in config/noise/ (KINDS). Their shapes are checked by the schemas in
config/ through `make bp-validate`, and what spans fields by
tests/test_config.py. This module only reads files.

`content_hash` identifies a config file by its parsed content, so a run can
record which version of each file it used and a rerun can refuse one that
changed (docs/DESIGN.md, section 5). Editing a comment or the formatting leaves
the hash unchanged. `file_record` writes that record as `{path, hash}`, and
`name_from_record` checks one and turns it back into a name.

`processor_graph` is the one builder of a processor's coupling graph, which
NoiseControl, the figures and the tests share.
"""

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

import networkx as nx
import yaml

ROOT = Path(__file__).resolve().parents[2]

# Each kind of config file, and what an error message calls one; its files live in config/<kind>/.
KINDS = {"processor": "processor file", "noise": "noise profile"}


def config_path(kind: str, name: str) -> Path:
    """The `kind` file for `name`; raises FileNotFoundError naming the known ones."""
    folder = config_folder(kind)
    path = folder / file_name(kind, name)
    if not path.is_file():
        known = ", ".join(config_names(kind)) or "none"
        raise FileNotFoundError(f"no {KINDS[kind]} named {name!r} in {folder}; known: {known}")
    return path


def config_names(kind: str) -> list[str]:
    """The names of every `kind` file, sorted."""
    return sorted(p.name.split(".")[-2] for p in config_folder(kind).glob(file_name(kind, "*")))


def load_config(kind: str, name: str) -> dict:
    """The `kind` file for `name`, as loaded YAML."""
    with open(config_path(kind, name), encoding="utf-8") as f:
        return yaml.safe_load(f)


def config_folder(kind: str) -> Path:
    """The folder that holds every `kind` file, config/<kind>/."""
    if kind not in KINDS:
        raise ValueError(f"no kind of config file named {kind!r}; known: {', '.join(KINDS)}")
    return ROOT / "config" / kind


def file_name(kind: str, name: str) -> str:
    """A config file's name: bp.data.<kind>.<name>.yaml."""
    return f"bp.data.{kind}.{name}.yaml"


def processor_path(name: str) -> Path:
    """The processor file for `name`; raises FileNotFoundError naming the known processors."""
    return config_path("processor", name)


def processor_names() -> list[str]:
    """The names of every processor file, sorted."""
    return config_names("processor")


def load_processor(name: str) -> dict:
    """The processor file for `name`, as loaded YAML."""
    return load_config("processor", name)


def noise_path(name: str) -> Path:
    """The noise profile for `name`; raises FileNotFoundError naming the known profiles."""
    return config_path("noise", name)


def noise_names() -> list[str]:
    """The names of every noise profile, sorted."""
    return config_names("noise")


def load_noise(name: str) -> dict:
    """The noise profile for `name`, as loaded YAML."""
    return load_config("noise", name)


# -- Hashes and records -----------------------------------------------------------


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


def file_record(path: Path) -> dict:
    """A config file as a run records it: `{path, hash}`, the path repo-relative."""
    return {"path": repo_path(path), "hash": content_hash(path)}


def name_from_record(record: Mapping, kind: str) -> str:
    """The config name a `{path, hash}` record points to; raises when the file changed."""
    if not isinstance(record, Mapping) or set(record) != {"path", "hash"}:
        raise ValueError(f"the {kind} record has the keys path and hash; got {record!r}")
    path = ROOT / record["path"]
    prefix = f"bp.data.{kind}."
    if not (path.name.startswith(prefix) and path.name.endswith(".yaml")):
        raise ValueError(f"the {kind} record's path {record['path']!r} is not a {prefix}*.yaml file")
    if not path.is_file():
        raise FileNotFoundError(f"the {kind} file {record['path']} recorded by the run no longer exists")
    current = content_hash(path)
    if current != record["hash"]:
        raise ValueError(
            f"{record['path']} changed since it was recorded: recorded {record['hash']}, now {current}; "
            "a rerun needs the file the run used"
        )
    name = path.name[len(prefix) : -len(".yaml")]
    if repo_path(config_path(kind, name)) != record["path"]:
        raise ValueError(f"the {kind} record's path {record['path']!r} is not where {kind} files live")
    return name


# -- The processor graph -----------------------------------------------------------


def processor_graph(proc: dict) -> nx.Graph:
    """The processor's coupling graph, with qubits as nodes named by id."""
    graph = nx.Graph()
    graph.add_nodes_from(q["id"] for q in proc["qubits"])
    graph.add_edges_from(tuple(e) for e in proc["edges"])
    return graph

