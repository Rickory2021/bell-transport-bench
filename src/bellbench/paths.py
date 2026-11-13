# src/bellbench/paths.py
"""Paths between a processor's ports: which path a transport takes, which spare path a check uses, and the
graph features that explain the results.

A transport moves the Bell pair along a path of couplers from the first port to
the second, and a check may work on a spare path, one between the same ports
that shares no qubit with the pair's (docs/DESIGN.md, section 7, the path
selector and the check placement). This module owns how both are chosen, so
every builder chooses them the same way:

- `smallest_shortest_path`: the default path, the lexicographically smallest of
  the shortest ones, so the choice never depends on networkx's order.
- `port_path`: a processor's graph and a checked path between its ports, the
  default or one given.
- `spare_path`: the smallest shortest port-to-port path whose interior avoids
  the pair's path and any qubits already taken.

`graph_metrics` reports the three features docs/DESIGN.md, section 3 explains
the results by: the port distance, the number of qubit-disjoint paths between
the ports, and the degree of the hubs and of each qubit on the pair's path.

The coupling graph itself is configs.py's (`processor_graph`); this module only
reads it.
"""

from collections.abc import Sequence

import networkx as nx

from bellbench import configs


def smallest_shortest_path(graph: nx.Graph, a: int, b: int) -> list[int]:
    """The lexicographically smallest of the shortest paths from `a` to `b`, so the choice never depends on networkx."""
    return min(nx.all_shortest_paths(graph, a, b))


def port_path(processor: str, path: Sequence[int] | None = None) -> tuple[nx.Graph, list[int]]:
    """The processor's graph and a checked path from its first port to its second along its couplers.

    By default the path is the lexicographically smallest shortest path; a
    given one must run port to port, along couplers, visiting no qubit twice.
    """
    proc = configs.load_processor(processor)
    graph = configs.processor_graph(proc)
    a, b = proc["ports"]
    path = list(path) if path is not None else smallest_shortest_path(graph, a, b)
    if len(path) < 2 or path[0] != a or path[-1] != b:
        raise ValueError(f"path {path} must run from the first port {a} to the second port {b}")
    for u, v in zip(path, path[1:]):
        if not graph.has_edge(u, v):
            raise ValueError(f"path {path}: qubits {u} and {v} are not a coupler of {processor!r}")
    if len(set(path)) != len(path):
        raise ValueError(f"path {path} visits a qubit twice")
    return graph, path


def spare_path(graph: nx.Graph, path: Sequence[int], avoid: Sequence[int] = ()) -> list[int]:
    """The lexicographically smallest shortest path between the ends of `path` whose interior shares no qubit with
    `path` or `avoid`, and has at least one qubit, since a check works on the interior.

    Raises a ValueError when no such path exists, as on a graph with one
    qubit-disjoint path between its ports.
    """
    a, b = path[0], path[-1]
    taken = (set(path) | set(avoid)) - {a, b}
    spare = graph.subgraph(set(graph.nodes) - taken).copy()
    if spare.has_edge(a, b):
        spare.remove_edge(a, b)
    if not nx.has_path(spare, a, b):
        raise ValueError(f"no path between the ports {a} and {b} avoids the qubits {sorted(taken)}")
    return smallest_shortest_path(spare, a, b)


def graph_metrics(processor: str) -> dict:
    """The features docs/DESIGN.md, section 3 explains a processor model's results by, as plain numbers.

    - `port_distance`: the fewest hops between the ports.
    - `disjoint_paths`: how many paths between the ports share no qubit.
    - `max_degree` and `hubs`: the most edges at any qubit, and the qubits that
      have that many.
    - `path` and `path_degrees`: the default path between the ports and the
      degree of each qubit on it.
    """
    graph, path = port_path(processor)
    a, b = path[0], path[-1]
    degree = dict(graph.degree)
    top = max(degree.values())
    return {
        "port_distance": len(path) - 1,
        "disjoint_paths": len(list(nx.node_disjoint_paths(graph, a, b))),
        "max_degree": top,
        "hubs": sorted(q for q, d in degree.items() if d == top),
        "path": path,
        "path_degrees": [degree[q] for q in path],
    }
