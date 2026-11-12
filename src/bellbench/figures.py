# src/bellbench/figures.py
"""Draw the docs' processor figure from the processor files (`make figures`).

`draw_processor` draws one processor graph on a matplotlib axis: qubits as dots,
couplers as lines, each port ringed in red, and no qubit numbers. The run
folder's graph diagram reuses it, passing the edges a circuit used. The drawing
fits its range to whatever positions a file gives, and a file without positions
gets an automatic layout, so any processor file draws.

Run as a module, it writes docs/assets/processor-models.png: the three core
models side by side, each captioned with its qubits, edges and the hops between
its ports, at twice the base resolution on a white background.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402

from bellbench.configs import ROOT, load_processor  # noqa: E402

CORE_PROCESSORS = ("ibm2016", "contemporary", "hyperbolic")
COLORS = {"ibm2016": "#2151c7", "contemporary": "#137665", "hyperbolic": "#7139cc"}
DEFAULT_COLOR = "#4a5568"
EDGE_COLOR = "#9aa6b8"
PORT_COLOR = "#c62639"
FIGURE_PATH = ROOT / "docs" / "assets" / "processor-models.png"


def processor_graph(proc: dict) -> nx.Graph:
    """The processor's coupling graph, with qubits as nodes named by id."""
    graph = nx.Graph()
    graph.add_nodes_from(q["id"] for q in proc["qubits"])
    graph.add_edges_from(tuple(e) for e in proc["edges"])
    return graph


def processor_layout(proc: dict, graph: nx.Graph) -> dict:
    """Drawing coordinates per qubit id: the file's positions, or a fixed automatic layout."""
    if all("position" in q for q in proc["qubits"]):
        return {q["id"]: tuple(q["position"]) for q in proc["qubits"]}
    return nx.kamada_kawai_layout(graph)


def caption(proc: dict, graph: nx.Graph) -> str:
    """The model's label, then its qubits, edges and the hops between its ports."""
    a, b = proc["ports"]
    hops = nx.shortest_path_length(graph, a, b)
    return (
        f"{proc['label']}\n"
        f"{graph.number_of_nodes()} qubits, {graph.number_of_edges()} edges, ports {hops} hops apart"
    )


def draw_processor(ax, proc: dict, color: str = DEFAULT_COLOR, used_edges=None) -> None:
    """Draw one processor graph on `ax`; `used_edges`, if given, are drawn darker and thicker."""
    graph = processor_graph(proc)
    pos = processor_layout(proc, graph)
    used = {frozenset(e) for e in (used_edges or ())}
    for u, v in graph.edges():
        on = frozenset((u, v)) in used
        ax.plot(*zip(pos[u], pos[v]), color=color if on else EDGE_COLOR, lw=2.8 if on else 1.8, zorder=1)
    xs, ys = zip(*pos.values())
    ax.scatter(xs, ys, s=260, color=color, edgecolors="white", zorder=3)
    port_xs, port_ys = zip(*(pos[p] for p in proc["ports"]))
    ax.scatter(port_xs, port_ys, s=640, facecolors="none", edgecolors=PORT_COLOR, linewidths=2, zorder=2)
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    margin = 0.12 * span
    ax.set(xlim=(min(xs) - margin, max(xs) + margin), ylim=(min(ys) - margin, max(ys) + margin), aspect="equal")
    ax.axis("off")
    ax.set_title(caption(proc, graph), fontsize=10.5)


def processor_figure(names=CORE_PROCESSORS):
    """One panel per processor, side by side."""
    fig, axes = plt.subplots(1, len(names), figsize=(4 * len(names), 4.3), facecolor="white")
    for name, ax in zip(names, axes):
        draw_processor(ax, load_processor(name), COLORS.get(name, DEFAULT_COLOR))
    fig.subplots_adjust(top=0.84, bottom=0.02, left=0.01, right=0.99, wspace=0.05)
    for ax in axes:  # equal aspect shrinks some panels, so align the captions at one height
        ax.apply_aspect()
        box = ax.get_position()
        fig.text((box.x0 + box.x1) / 2, 0.97, ax.get_title(), ha="center", va="top", fontsize=10.5)
        ax.set_title("")
    return fig


def main(path: Path = FIGURE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig = processor_figure()
    fig.savefig(path, dpi=200, facecolor="white", metadata={"Software": None})
    plt.close(fig)
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
