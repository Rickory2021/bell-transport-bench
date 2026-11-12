# tests/test_config.py
"""Checks on the processor and noise config files that a schema cannot make.

The schemas (config/bp.schema.processor.yaml and config/bp.schema.noise.yaml)
check each file's shape through `make bp-validate`. These tests check what spans
fields or files: each processor graph is well formed and matches the challenge's
counts, every reference id exists, every comment in a noise file matches the
schema description it copies, and every value in a snapshot noise profile equals
the median of the pinned snapshot it cites, so a profile cannot drift from its
source.
"""

import math
import statistics
import warnings
from pathlib import Path

import networkx as nx
import pytest
import yaml

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


def _graph(proc):
    g = nx.Graph()
    g.add_nodes_from(q["id"] for q in proc["qubits"])
    g.add_edges_from(tuple(e) for e in proc["edges"])
    return g


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
    proc = PROCESSORS[name]
    ids = [q["id"] for q in proc["qubits"]]
    assert ids == list(range(len(ids))), "qubit ids run 0 to n - 1, in order, each once"
    known = set(ids)
    a, b = proc["ports"]
    assert a != b, "the two ports must be different qubits"
    assert {a, b} <= known, "ports must be qubits of the graph"
    for u, v in proc["edges"]:
        assert u != v, f"self-loop on qubit {u}"
        assert {u, v} <= known, f"edge ({u}, {v}) names a qubit the file does not list"
    undirected = {frozenset(e) for e in proc["edges"]}
    assert len(undirected) == len(proc["edges"]), "an edge is listed twice"
    with_position = sum("position" in q for q in proc["qubits"])
    assert with_position in (0, len(ids)), "positions for every qubit or for none"
    assert nx.is_connected(_graph(proc)), "every qubit must be reachable"


def test_core_graphs_are_present():
    assert set(CORE_GRAPHS) <= set(PROCESSORS)


@pytest.mark.parametrize("name", sorted(CORE_GRAPHS))
def test_core_graph_matches_challenge(name):
    qubits, edges, hops, disjoint = CORE_GRAPHS[name]
    proc = PROCESSORS[name]
    g = _graph(proc)
    a, b = proc["ports"]
    assert g.number_of_nodes() == qubits
    assert g.number_of_edges() == edges
    assert nx.shortest_path_length(g, a, b) == hops
    assert nx.node_connectivity(g, a, b) == disjoint


def test_t_graph_matches_its_snapshot():
    """The 2016 model's graph is the coupling graph of the T-graph snapshot burlington-2020 comes from."""
    from qiskit_ibm_runtime.fake_provider import FakeBurlingtonV2

    snap = nx.Graph(tuple(e) for e in FakeBurlingtonV2().coupling_map.get_edges())
    assert nx.is_isomorphic(_graph(PROCESSORS["ibm2016"]), snap)


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


def test_borrowed_measure_duration_matches_its_source():
    """Burlington's measurement duration is borrowed; it must equal the snapshots it names."""
    prof = NOISE["burlington-2020"]
    (entry,) = [b for b in prof["borrowed"] if b["field"] == "measure.duration"]
    assert entry["value"] == prof["measure"]["duration"]
    for class_name in ("FakeOurenseV2", "FakeValenciaV2", "FakeVigoV2"):
        snap = _snapshot_medians(class_name)
        assert snap["calibrated"] == "2021-01-20"
        assert _close(snap["measure"], entry["value"]), class_name
