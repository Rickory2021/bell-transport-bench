# src/bellbench/configs.py
"""Find, load and hash the config files in config/ by kind and name.

Each kind of config file lives in its own folder under config/ and is named
bp.data.<kind>.<name>.yaml: a processor file in config/processor/, a noise
profile in config/noise/ and a circuit file in config/circuit/ (KINDS). Every
load checks the file before it returns it: `check_config` validates it against
its schema, config/bp.schema.<kind>.yaml, and runs `check_processor` on a
processor file, and the load then checks that the file's name field matches its
file name. A file that fails raises a ValueError naming the file and the field,
so a bad file fails before any model is built (docs/DESIGN.md, section 2).
src/bellbench/circuits.py adds the checks a circuit file's gates need. This
module only reads files.

`content_hash` identifies a config file by its parsed content, so a run can
record which version of each file it used and a rerun can refuse one that
changed (docs/DESIGN.md, section 5). Editing a comment or the formatting leaves
the hash unchanged. `load_recorded` loads a file and records it as
`{path, hash}`, hashing the very content it returns, so the record describes
what the caller builds from. `name_from_record` turns a record back into a
name, and `check_unchanged` refuses a file whose content changed since then.

`processor_graph` is the one builder of a processor's coupling graph, which
NoiseControl, the figures and the tests share.
"""

import hashlib
import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path

import networkx as nx
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

ROOT = Path(__file__).resolve().parents[2]

# Each kind of config file, and what an error message calls one; its files live in config/<kind>/.
KINDS = {"processor": "processor file", "noise": "noise profile", "circuit": "circuit file"}


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
    """The `kind` file for `name`, as loaded and checked YAML."""
    return _read(kind, name)[1]


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
    """`sha256:` and the hash of the file's parsed YAML, as `hash_data` gives it.

    Comments and formatting do not change it; any value does.
    """
    with open(path, encoding="utf-8") as f:
        return hash_data(yaml.safe_load(f))


def hash_data(data) -> str:
    """`sha256:` and the hash of parsed YAML, written as JSON with sorted keys; dates hash as their ISO text."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def repo_path(path: Path) -> str:
    """`path` relative to the repo root, with forward slashes, as runs record it."""
    return Path(path).resolve().relative_to(ROOT).as_posix()


def load_recorded(kind: str, name: str) -> tuple[dict, dict]:
    """The `kind` file for `name` as loaded and checked YAML, and its `{path, hash}` record of that same content."""
    path, data = _read(kind, name)
    return data, {"path": repo_path(path), "hash": hash_data(data)}


def name_from_record(record: Mapping, kind: str) -> str:
    """The config name a `{path, hash}` record points to; raises when the path is not a `kind` file's."""
    if not isinstance(record, Mapping) or set(record) != {"path", "hash"}:
        raise ValueError(f"the {kind} record has the keys path and hash; got {record!r}")
    path = ROOT / record["path"]
    prefix = f"bp.data.{kind}."
    if not (path.name.startswith(prefix) and path.name.endswith(".yaml")):
        raise ValueError(f"the {kind} record's path {record['path']!r} is not a {prefix}*.yaml file")
    if not path.is_file():
        raise FileNotFoundError(f"the {kind} file {record['path']} recorded by the run no longer exists")
    name = path.name[len(prefix) : -len(".yaml")]
    if repo_path(config_path(kind, name)) != record["path"]:
        raise ValueError(f"the {kind} record's path {record['path']!r} is not where {kind} files live")
    return name


def check_unchanged(recorded: Mapping, current: Mapping) -> None:
    """Raise a ValueError when a file's `current` record has another hash than the one `recorded`."""
    if current["hash"] != recorded["hash"]:
        raise ValueError(
            f"{recorded['path']} changed since it was recorded: recorded {recorded['hash']}, now {current['hash']}; "
            "a rerun needs the file the run used"
        )


# -- Checks ---------------------------------------------------------------------


def check_config(kind: str, data, where: str) -> None:
    """Raise a ValueError naming `where` and the field when `data` is not a valid `kind` file."""
    error = best_match(_validator(ROOT / "config" / f"bp.schema.{kind}.yaml").iter_errors(data))
    if error is not None:
        raise ValueError(f"{where}: {error.json_path}: {error.message}")
    if kind == "processor":
        try:
            check_processor(data)
        except ValueError as e:
            raise ValueError(f"{where}: {e}") from None


def check_processor(proc: dict) -> None:
    """Raise a ValueError naming the field when a schema-valid processor file is not a usable graph.

    Its ids run 0 to n - 1 in order, each once; its two ports are different
    qubits of the graph; each edge joins two different listed qubits and appears
    once in either direction; positions are given for every qubit or for none;
    and the graph is connected.
    """
    ids = [q["id"] for q in proc["qubits"]]
    if ids != list(range(len(ids))):
        raise ValueError(f"qubits: ids must run 0 to n - 1 in order, each once; got {ids}")
    known = set(ids)
    a, b = proc["ports"]
    if a == b:
        raise ValueError(f"ports: the two ports must be different qubits; got {proc['ports']}")
    for p in (a, b):
        if p not in known:
            raise ValueError(f"ports: port {p} is not a qubit of the graph")
    seen = set()
    for i, (u, v) in enumerate(proc["edges"]):
        if u == v:
            raise ValueError(f"edges[{i}]: a self-loop on qubit {u}")
        for q in (u, v):
            if q not in known:
                raise ValueError(f"edges[{i}]: qubit {q} is not listed in qubits")
        if frozenset((u, v)) in seen:
            raise ValueError(f"edges[{i}]: the coupler ({u}, {v}) is listed twice")
        seen.add(frozenset((u, v)))
    if sum("position" in q for q in proc["qubits"]) not in (0, len(ids)):
        raise ValueError("qubits: give a position for every qubit or for none")
    if not nx.is_connected(processor_graph(proc)):
        raise ValueError("edges: the graph is not connected, so some qubits cannot be reached")


# -- The processor graph -----------------------------------------------------------


def processor_graph(proc: dict) -> nx.Graph:
    """The processor's coupling graph, with qubits as nodes named by id."""
    graph = nx.Graph()
    graph.add_nodes_from(q["id"] for q in proc["qubits"])
    graph.add_edges_from(tuple(e) for e in proc["edges"])
    return graph


def _read(kind: str, name: str) -> tuple[Path, dict]:
    """The `kind` file for `name`, and its content once `check_config` passes it."""
    path = config_path(kind, name)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    where = repo_path(path)
    check_config(kind, data, where)
    if data["name"] != name:
        raise ValueError(f"{where}: $.name: {data['name']!r} does not match the file's name {name!r}")
    return path, data


@cache
def _validator(schema_path: Path) -> Draft202012Validator:
    with open(schema_path, encoding="utf-8") as f:
        return Draft202012Validator(yaml.safe_load(f))
