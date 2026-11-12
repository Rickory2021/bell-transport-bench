# tests/test_config.py
"""Checks on the processor and noise config files that a schema cannot make.

The schemas (config/bp.schema.processor.yaml and config/bp.schema.noise.yaml)
check each file's shape through `make bp-validate`. These tests check what spans
fields or files: each processor graph is well formed and matches the challenge's
counts, every reference id exists, every comment in a noise file matches the
schema description it copies, and every value in a snapshot noise profile equals
the median of the pinned snapshot it cites, so a profile cannot drift from its
source. The last section checks that src/bellbench/configs.py finds each noise
profile by name.
"""

import copy
import math
import statistics
import warnings
from pathlib import Path

import networkx as nx
import pytest
import yaml

from bellbench.configs import check_processor, processor_graph

ROOT = Path(__file__).resolve().parents[1]
PROCESSOR_DIR = ROOT / "config" / "processor"
NOISE_DIR = ROOT / "config" / "noise"
NOISE_SCHEMA = ROOT / "config" / "bp.schema.noise.yaml"
REFERENCES = ROOT / "docs" / "bp.data.references.yaml"


def _load(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


PROCESSOR_FILES = {p.stem.split(".")[-1]: p for p in sorted(PROCESSOR_DIR.glob("bp.data.processor.*.yaml"))}
NOISE_FILES = {p.stem.split(".")[-1]: p for p in sorted(NOISE_DIR.glob("bp.data.noise.*.yaml"))}
PROCESSORS = {name: _load(p) for name, p in PROCESSOR_FILES.items()}
NOISE = {name: _load(p) for name, p in NOISE_FILES.items()}
SNAPSHOT_PROFILES = sorted(n for n, p in NOISE.items() if p["kind"] == "snapshot")

# The challenge's three graphs: (qubits, edges, hops between ports, port-disjoint paths).
CORE_GRAPHS = {
    "ibm2016": (5, 4, 2, 1),
    "contemporary": (9, 12, 4, 2),
    "hyperbolic": (13, 24, 3, 3),
}


# -- References ----------------------------------------------------------------


def _reference_ids():
    return {entry["id"] for entry in _load(REFERENCES)["references"]}


@pytest.mark.parametrize("path", [*PROCESSOR_FILES.values(), *NOISE_FILES.values()], ids=lambda p: p.name)
def test_reference_exists(path):
    assert _load(path)["reference"] in _reference_ids()


# -- Processor files -----------------------------------------------------------


@pytest.mark.parametrize("name", sorted(PROCESSORS))
def test_processor_name_matches_file(name):
    assert PROCESSORS[name]["name"] == name


@pytest.mark.parametrize("name", sorted(PROCESSORS))
def test_processor_graph_is_well_formed(name):
    check_processor(PROCESSORS[name])


def _broken(change):
    proc = copy.deepcopy(PROCESSORS["ibm2016"])
    change(proc)
    return proc


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda p: p["qubits"][4].update(id=5), r"qubits: ids must run 0 to n - 1"),
        (lambda p: p.update(ports=[0, 0]), r"ports: the two ports must be different"),
        (lambda p: p.update(ports=[0, 9]), r"ports: port 9 is not a qubit"),
        (lambda p: p["edges"].append([2, 2]), r"edges\[4\]: a self-loop on qubit 2"),
        (lambda p: p["edges"].append([2, 7]), r"edges\[4\]: qubit 7 is not listed"),
        (lambda p: p["edges"].append(list(reversed(p["edges"][0]))), r"edges\[4\]: the coupler .* is listed twice"),
        (lambda p: p["qubits"][0].pop("position"), r"qubits: give a position for every qubit or for none"),
        (lambda p: p.update(edges=p["edges"][:-1]), r"edges: the graph is not connected"),
    ],
)
def test_malformed_processor_raises_naming_the_field(change, message):
    with pytest.raises(ValueError, match=message):
        check_processor(_broken(change))


def _write(path, data):
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_loading_a_malformed_processor_file_raises_naming_the_file(config_copy):
    from bellbench import configs

    proc = _broken(lambda p: p["edges"].append(list(reversed(p["edges"][0]))))
    _write(configs.processor_path("ibm2016"), proc)
    with pytest.raises(ValueError, match=r"config/processor/bp\.data\.processor\.ibm2016\.yaml: edges\[4\]"):
        configs.load_processor("ibm2016")


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda p: p.pop("kind"), r"\$: 'kind' is a required property"),
        (lambda p: p.update(time_step="4e-9"), r"\$\.time_step"),
        (lambda p: p.update(time_step=0.0), r"\$\.time_step"),
        (lambda p: p.update(name="fez-2026"), r"\$\.name: 'fez-2026' does not match"),
    ],
)
def test_loading_a_malformed_noise_profile_raises_naming_the_field(config_copy, change, message):
    from bellbench import configs

    profile = copy.deepcopy(NOISE["fez-2025"])
    change(profile)
    _write(configs.noise_path("fez-2025"), profile)
    with pytest.raises(ValueError, match=r"config/noise/bp\.data\.noise\.fez-2025\.yaml: " + message):
        configs.load_noise("fez-2025")


FEZ_PATH = "config/noise/bp.data.noise.fez-2025.yaml"
NOT_A_NOISE_FILE = r"is not a bp\.data\.noise\.\*\.yaml file"


def test_an_unknown_kind_of_config_file_raises_naming_the_known_ones():
    from bellbench import configs

    with pytest.raises(ValueError, match="no kind of config file named 'widget'; known: processor, noise"):
        configs.config_folder("widget")


@pytest.mark.parametrize(
    "record, message",
    [
        ({"path": FEZ_PATH}, "has the keys path and hash"),
        ({"path": FEZ_PATH, "hash": "sha256:0", "extra": 1}, "has the keys path and hash"),
        ({"path": "config/noise/fez-2025.yaml", "hash": "sha256:0"}, NOT_A_NOISE_FILE),
        ({"path": FEZ_PATH.replace(".yaml", ".yml"), "hash": "sha256:0"}, NOT_A_NOISE_FILE),
    ],
)
def test_a_malformed_file_record_is_refused(record, message):
    from bellbench import configs

    with pytest.raises(ValueError, match=message):
        configs.name_from_record(record, "noise")


@pytest.mark.parametrize(
    "file, name",
    [
        ("bp.data.noise.fez-2025.yaml", "fez-2025"),
        ("bp.data.noise..yaml", None),
        ("bp.data.circuit.fez-2025.yaml", None),
        ("bp.data.noise.fez-2025.yml", None),
    ],
)
def test_a_file_name_gives_back_its_name_and_nothing_else(file, name):
    from bellbench import configs

    assert configs.name_from_file("noise", file) == name
    if name is not None:
        assert configs.file_name("noise", name) == file


def test_core_graphs_are_present():
    assert set(CORE_GRAPHS) <= set(PROCESSORS)


@pytest.mark.parametrize("name", sorted(CORE_GRAPHS))
def test_core_graph_matches_challenge(name):
    qubits, edges, hops, disjoint = CORE_GRAPHS[name]
    proc = PROCESSORS[name]
    g = processor_graph(proc)
    a, b = proc["ports"]
    assert g.number_of_nodes() == qubits
    assert g.number_of_edges() == edges
    assert nx.shortest_path_length(g, a, b) == hops
    assert nx.node_connectivity(g, a, b) == disjoint


def test_t_graph_matches_its_snapshot():
    """The 2016 model's graph is the coupling graph of the T-graph snapshot burlington-2020 comes from."""
    from qiskit_ibm_runtime.fake_provider import FakeBurlingtonV2

    snap = nx.Graph(tuple(e) for e in FakeBurlingtonV2().coupling_map.get_edges())
    assert nx.is_isomorphic(processor_graph(PROCESSORS["ibm2016"]), snap)


# -- Noise profiles: comments --------------------------------------------------

# The value fields whose schema description is the comment on the line above them.
COMMENTED = (
    "time_step",
    "qubit.t1_relaxation_time",
    "qubit.t2_dephasing_time",
    "qubit.readout_error.reads_1_when_0",
    "qubit.readout_error.reads_0_when_1",
    "gates",
    "measure",
    "reset",
    "depolarising.after_gate",
    "depolarising.probability",
    "depolarising.gates",
)


def _schema_description(path):
    node = {"properties": _load(NOISE_SCHEMA)["properties"]}
    for key in path.split("."):
        node = node["properties"][key]
    return node["description"]


def _comment_above(text, path):
    """The comment on the line above the key at `path`, found by indentation, or None."""
    keys = path.split(".")
    lines = text.splitlines()
    depth = 0
    for i, line in enumerate(lines):
        indent = len(line) - len(line.lstrip(" "))
        if line.strip().startswith("#") or not line.strip():
            continue
        if indent < 2 * depth:
            return None
        if indent == 2 * depth and line.strip().startswith(keys[depth] + ":"):
            if depth == len(keys) - 1:
                above = lines[i - 1].strip()
                return above[2:] if above.startswith("# ") else None
            depth += 1
    return None


@pytest.mark.parametrize("name", sorted(NOISE))
def test_noise_comments_match_schema(name):
    """Each value field carries its schema description as the comment above it, word for word."""
    text = NOISE_FILES[name].read_text(encoding="utf-8")
    data = NOISE[name]

    def present(path):
        node = data
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                return False
            node = node[key]
        return True

    for path in (p for p in COMMENTED if present(p)):
        assert _comment_above(text, path) == _schema_description(path), f"{name}: comment above {path}"


# -- Noise profiles: values ----------------------------------------------------


@pytest.mark.parametrize("name", sorted(NOISE))
def test_noise_name_matches_file(name):
    assert NOISE[name]["name"] == name


@pytest.mark.parametrize("name", SNAPSHOT_PROFILES)
def test_snapshot_profile_is_physical(name):
    q = NOISE[name]["qubit"]
    assert 0 < q["t2_dephasing_time"] <= 2 * q["t1_relaxation_time"], "T2 must not exceed 2 T1"
    assert q["readout_error"]["reads_1_when_0"] < 0.5 and q["readout_error"]["reads_0_when_1"] < 0.5
    two_qubit = [g for g in NOISE[name]["gates"].values() if g["qubits"] == 2]
    assert len(two_qubit) == 1, "one native two-qubit gate"


def _median(values):
    return float(statistics.median(values))


def _snapshot_medians(class_name):
    """The medians a snapshot profile must hold, recomputed from the snapshot itself."""
    from qiskit_ibm_runtime import fake_provider

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        backend = getattr(fake_provider, class_name)()
    target, props = backend.target, backend.properties()
    n = backend.num_qubits

    def gate(name):
        ps = [p for p in target[name].values() if p is not None]
        return _median([p.error for p in ps]), _median([p.duration for p in ps])

    def duration(name):
        if name not in target.operation_names:
            return None
        ds = [p.duration for p in target[name].values() if p is not None and p.duration is not None]
        return _median(ds) if ds else None

    return {
        "calibrated": str(props.last_update_date.date()),
        "dt": backend.dt,
        "t1": _median([q.t1 for q in target.qubit_properties]),
        "t2": _median([q.t2 for q in target.qubit_properties]),
        "p1_given_0": _median([props.qubit_property(q)["prob_meas1_prep0"][0] for q in range(n)]),
        "p0_given_1": _median([props.qubit_property(q)["prob_meas0_prep1"][0] for q in range(n)]),
        "gate": gate,
        "measure": duration("measure"),
        "reset": duration("reset"),
    }


def _close(a, b):
    return math.isclose(a, b, rel_tol=1e-12, abs_tol=0.0)


@pytest.mark.parametrize("name", SNAPSHOT_PROFILES)
def test_snapshot_profile_matches_snapshot(name):
    prof = NOISE[name]
    snap = _snapshot_medians(prof["snapshot"]["class"])
    assert prof["snapshot"]["calibrated"] == snap["calibrated"]
    assert prof["time_step"] == snap["dt"]
    q = prof["qubit"]
    assert _close(q["t1_relaxation_time"], snap["t1"]) and _close(q["t2_dephasing_time"], snap["t2"])
    assert _close(q["readout_error"]["reads_1_when_0"], snap["p1_given_0"])
    assert _close(q["readout_error"]["reads_0_when_1"], snap["p0_given_1"])
    for gate_name, g in prof["gates"].items():
        source_gate = g.get("from_snapshot_gate", gate_name)
        error, dur = snap["gate"](source_gate)
        assert _close(g["error_probability"], error), f"{gate_name} error"
        assert _close(g["duration"], dur), f"{gate_name} duration"
    borrowed = {b["field"] for b in prof.get("borrowed", [])}
    for timed in ("measure", "reset"):
        if timed in prof and f"{timed}.duration" not in borrowed:
            assert _close(prof[timed]["duration"], snap[timed]), f"{timed} duration"


def _snapshot_links(class_name, version):
    """The GitHub links to a fake backend's properties and configuration files at a package tag."""
    from qiskit_ibm_runtime import fake_provider

    backend = getattr(fake_provider, class_name)
    base = f"https://github.com/Qiskit/qiskit-ibm-runtime/blob/{version}/qiskit_ibm_runtime/fake_provider/backends/{Path(backend.dirname).name}"
    return f"{base}/{backend.props_filename}", f"{base}/{backend.conf_filename}"


@pytest.mark.parametrize("name", SNAPSHOT_PROFILES)
def test_snapshot_links_match_the_pin(name):
    """A snapshot profile links its own snapshot's files at the tag its package pin names."""
    snap = NOISE[name]["snapshot"]
    properties, configuration = _snapshot_links(snap["class"], snap["package"].split("==")[1])
    assert snap["properties"] == properties
    assert snap["configuration"] == configuration


def test_borrowed_measure_duration_matches_its_source():
    """Burlington's measurement duration is borrowed; it must equal the snapshots it names."""
    prof = NOISE["burlington-2020"]
    (entry,) = [b for b in prof["borrowed"] if b["field"] == "measure.duration"]
    assert entry["value"] == prof["measure"]["duration"]
    assert entry["url"] == _snapshot_links("FakeOurenseV2", prof["snapshot"]["package"].split("==")[1])[0]
    for class_name in ("FakeOurenseV2", "FakeValenciaV2", "FakeVigoV2"):
        snap = _snapshot_medians(class_name)
        assert snap["calibrated"] == "2021-01-20"
        assert _close(snap["measure"], entry["value"]), class_name


# -- Loading by name ------------------------------------------------------------


def test_noise_profiles_load_by_name():
    from bellbench import configs

    assert configs.noise_names() == sorted(NOISE)
    for name in NOISE:
        assert configs.load_noise(name) == NOISE[name]
        assert configs.noise_path(name) == NOISE_FILES[name]


def test_unknown_noise_profile_names_the_known_ones():
    from bellbench import configs

    with pytest.raises(FileNotFoundError, match="fez-2025"):
        configs.noise_path("no-such-profile")
