# src/bellbench/views/base.py
"""The parts a view is made of, and how a view shows itself.

A view is a list of parts in order: Markdown, HTML, LaTeX, an image or a
stepper. In a notebook each part is shown as an output of its own kind, so
Markdown and LaTeX render as the front end renders them and a table stays a
table; outside a notebook a view is its parts as text.

IPython is imported only inside `emit`, at the moment a notebook shows a view,
so the package loads and its views print without it. A figure is drawn on a
matplotlib Figure of its own, never through pyplot, so matplotlib's backend is
never switched (src/bellbench/run.py, write_views).
"""

import base64
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

import pandas as pd
from matplotlib.figure import Figure

TAG = re.compile(r"<[^>]+>")
SCRIPT = re.compile(r"<script>.*?</script>", flags=re.S)
IMAGE = re.compile(r'<img[^>]*src="data:image/png;base64,[^"]*"[^>]*>')


@dataclass(frozen=True)
class Part:
    """One output of a view: its kind and its content.

    `kind` is "markdown", "html", "latex", "png" (base64 text) or "stepper",
    whose content is HTML and whose `still` is the first frame as base64 PNG,
    for a viewer that cannot show HTML.
    """

    kind: str
    content: str
    still: str = ""

    def text(self) -> str:
        """The part as plain text, for a view shown outside a notebook."""
        if self.kind == "png":
            return "[figure]"
        if self.kind in ("html", "stepper"):
            return TAG.sub("", IMAGE.sub("[figure]", SCRIPT.sub("", self.content))).strip()
        return self.content


def markdown(text: str) -> Part:
    return Part("markdown", text)


def html(text: str) -> Part:
    return Part("html", text)


def latex(text: str) -> Part:
    return Part("latex", text)


def table(rows: list[dict]) -> Part:
    """A plain HTML table: no CSS, so it reads the same on GitHub as in Jupyter."""
    return html(pd.DataFrame(rows).to_html(index=False, border=0, na_rep=""))


def png(fig: Figure) -> str:
    """A figure as base64 PNG text."""
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=100, bbox_inches="tight", facecolor="white")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def image(fig: Figure) -> Part:
    return Part("png", png(fig))


def img(fig: Figure) -> str:
    """A figure as an HTML image, for a folded view."""
    return f'<img style="max-width:100%" src="data:image/png;base64,{png(fig)}">'


def fold(summary: str, inner_html: str) -> Part:
    """A debug view, folded: closed until clicked, so a view's output stays short.

    A script goes after the fold, not inside it: VS Code reads a script inside a closed fold as empty,
    so it would never run there.
    """
    scripts = "".join(SCRIPT.findall(inner_html))
    markup = SCRIPT.sub("", inner_html)
    return html(f"<details><summary><b>{escape(summary)}</b></summary>{markup}</details>{scripts}")


def emit(parts: Sequence[Part]) -> None:
    """Show each part as an output of its own kind in a notebook; print the parts as text where IPython is absent."""
    try:
        from IPython.display import HTML, Image, Markdown, Math, display
    except ImportError:
        print("\n".join(part.text() for part in parts))
        return
    for part in parts:
        if part.kind == "markdown":
            display(Markdown(part.content))
        elif part.kind == "latex":
            display(Math(part.content))
        elif part.kind == "png":
            display(Image(data=base64.b64decode(part.content), format="png"))
        elif part.kind == "stepper":
            display({"text/html": part.content, "image/png": part.still}, raw=True)
        else:
            display(HTML(part.content))


class View:
    """Parts in order, each shown as its own output in a notebook, and as text elsewhere."""

    def __init__(self, parts: Sequence[Part]):
        self.parts = list(parts)

    def _ipython_display_(self) -> None:
        emit(self.parts)

    def __repr__(self) -> str:
        return "\n".join(part.text() for part in self.parts)
