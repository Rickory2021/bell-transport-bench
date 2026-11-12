# tests/test_figures.py
"""The processor figure draws from the processor files, and any processor file draws."""

import matplotlib.pyplot as plt

from bellbench.configs import load_processor
from bellbench.figures import CORE_PROCESSORS, caption, draw_processor, processor_figure, processor_graph


def test_figure_has_a_panel_per_core_model():
    fig = processor_figure()
    assert len(fig.axes) == len(CORE_PROCESSORS)
    plt.close(fig)


def test_captions_count_from_the_files():
    expected = {
        "ibm2016": "5 qubits, 4 edges, ports 2 hops apart",
        "contemporary": "9 qubits, 12 edges, ports 4 hops apart",
        "hyperbolic": "13 qubits, 24 edges, ports 3 hops apart",
    }
    for name, line in expected.items():
        proc = load_processor(name)
        assert caption(proc, processor_graph(proc)).splitlines()[1] == line


def test_a_file_without_positions_still_draws():
    proc = load_processor("ibm2016")
    proc["qubits"] = [{"id": q["id"]} for q in proc["qubits"]]
    fig, ax = plt.subplots()
    draw_processor(ax, proc, used_edges=[(0, 3), (3, 4)])
    assert ax.get_title().startswith(proc["label"])
    plt.close(fig)
