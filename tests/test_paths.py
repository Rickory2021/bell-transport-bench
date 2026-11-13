# tests/test_paths.py
"""Paths between a processor's ports: the default path, the spare paths a check can use, and the graph metrics.

Covers src/bellbench/paths.py: the path selector and the check placement of
docs/DESIGN.md, section 7, and the features section 3 quotes, which these tests
pin to the values it states. A given path that does not run port to port along
couplers is refused through swap_chain in tests/test_circuits.py.
"""

import networkx as nx
import pytest

from bellbench import configs, paths
from bellbench.paths import graph_metrics, port_path, smallest_shortest_path, spare_path


@pytest.mark.parametrize("processor, path", [("ibm2016", [0, 3, 4]), ("contemporary", [0, 1, 2, 3, 7])])
def test_shortest_path_is_the_lexicographically_smallest(processor, path):
    proc = configs.load_processor(processor)
    assert smallest_shortest_path(configs.processor_graph(proc), *proc["ports"]) == path


# -- Spare paths --------------------------------------------------------------------


@pytest.mark.parametrize(
    "processor, spares",
    [("contemporary", [[0, 4, 5, 6, 7]]), ("hyperbolic", [[0, 3, 11, 12], [0, 2, 6, 10, 12]])],
)
def test_every_spare_path_in_turn_then_none(processor, spares):
    graph, path = port_path(processor)
    taken = []
    for expected in spares:
        spare = spare_path(graph, path, taken)
        assert spare == expected
        assert not set(spare[1:-1]) & (set(path) | set(taken)), "a spare shares no qubit with what is taken"
        taken += spare[1:-1]
    with pytest.raises(ValueError, match="no path between the ports"):
        spare_path(graph, path, taken)


def test_a_graph_with_one_disjoint_path_has_no_spare():
    graph, path = port_path("ibm2016")
    with pytest.raises(ValueError, match=r"no path between the ports 0 and 4 avoids the qubits \[3\]"):
        spare_path(graph, path)


def test_of_two_shortest_spares_the_lexicographically_smallest():
    graph = nx.Graph([(0, 1), (1, 3), (0, 4), (4, 3), (0, 2), (2, 3)])
    assert spare_path(graph, [0, 1, 3]) == [0, 2, 3]


def test_a_spare_path_has_an_interior_even_when_the_ports_are_neighbours():
    graph = nx.Graph([(0, 1), (0, 2), (2, 1)])
    assert spare_path(graph, [0, 1]) == [0, 2, 1]
    with pytest.raises(ValueError):
        spare_path(nx.Graph([(0, 1)]), [0, 1])


# -- Graph metrics --------------------------------------------------------------------


METRICS = {
    "ibm2016": dict(port_distance=2, disjoint_paths=1, max_degree=3, hubs=[0], path=[0, 3, 4], path_degrees=[3, 2, 1]),
    "contemporary": dict(
        port_distance=4, disjoint_paths=2, max_degree=5, hubs=[5], path=[0, 1, 2, 3, 7], path_degrees=[2, 3, 4, 2, 2]
    ),
    "hyperbolic": dict(
        port_distance=3, disjoint_paths=3, max_degree=6, hubs=[6], path=[0, 1, 9, 12], path_degrees=[3, 3, 3, 3]
    ),
}


@pytest.mark.parametrize("processor", METRICS)
def test_graph_metrics_match_what_design_states(processor):
    """docs/DESIGN.md, section 3: three disjoint paths on the hyperbolic-inspired model, two on the contemporary, one
    on the 2016-inspired; a centre qubit of degree six and a busiest contemporary qubit of degree five."""
    assert graph_metrics(processor) == METRICS[processor]


def test_disjoint_paths_share_no_qubit_not_merely_no_coupler(monkeypatch):
    """Two paths through one cut qubit share no coupler but are one qubit-disjoint path."""
    graph = nx.Graph([(0, 1), (0, 2), (1, 9), (2, 9), (9, 3), (9, 4), (3, 5), (4, 5)])
    monkeypatch.setattr(paths, "port_path", lambda processor: (graph, [0, 1, 9, 3, 5]))
    assert graph_metrics("cut")["disjoint_paths"] == 1


def test_graph_metrics_are_plain_numbers():
    for value in graph_metrics("hyperbolic").values():
        items = value if isinstance(value, list) else [value]
        assert all(type(v) is int for v in items)
