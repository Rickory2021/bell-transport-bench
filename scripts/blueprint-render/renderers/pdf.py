# scripts/blueprint-render/renderers/pdf.py
"""PDF renderer using Jinja2 templates and WeasyPrint.

Renders an HTML template with the provided context dict,
then converts to PDF via WeasyPrint. base_url is set to the
template directory so relative CSS and font paths resolve.

FontConfiguration is used so @font-face declarations in CSS
work correctly under WeasyPrint.

PDF metadata (Author, Title, Producer, Creator) is set via
WeasyPrint's finisher callback when the emit entry includes a
metadata section. The runner resolves metadata values before
passing them here; this module applies them as-is. Only fields
explicitly declared in the process file are overridden; all
others keep WeasyPrint's defaults.
"""

from pathlib import Path

import jinja2
import pydyf
import weasyprint


def _build_finisher(metadata):
    """Return a WeasyPrint finisher that sets PDF metadata.

    Args:
        metadata: dict of resolved metadata fields.
            Supported keys: author, title, producer, creator.
            Empty strings and None values are skipped.

    Returns:
        A finisher function with signature (document, pdf),
        or None if no metadata to set.
    """
    # Filter to non-empty values
    fields = {k: v for k, v in metadata.items()
              if v is not None and v != ""}
    if not fields:
        return None

    # Map our keys to PDF info dict keys
    key_map = {
        "author": "Author",
        "title": "Title",
        "producer": "Producer",
        "creator": "Creator",
    }

    def finisher(document, pdf):
        for our_key, pdf_key in key_map.items():
            if our_key in fields:
                pdf.info[pdf_key] = pydyf.String(fields[our_key])

    return finisher


def render(context, template_path, output_path, root, **kwargs):
    """Render a PDF from an HTML template and context dict.

    Args:
        context: dict of template variables (from map stage).
        template_path: root-relative path to the Jinja2 HTML template.
        output_path: absolute path for the output PDF.
        root: repo root (Path).
        **kwargs:
            emit_entry: dict from the process emit section, may
                contain a resolved 'metadata' dict with 'author',
                'title', 'producer', and/or 'creator' keys.
    """
    abs_template = root / template_path
    template_dir = abs_template.parent

    # Jinja2: StrictUndefined fails loudly on missing variables
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_dir)),
        undefined=jinja2.StrictUndefined,
        autoescape=False,
    )
    template = env.get_template(abs_template.name)
    html_string = template.render(**context)

    # Resolve metadata finisher from emit entry
    emit_entry = kwargs.get("emit_entry") or {}
    metadata = emit_entry.get("metadata") or {}
    finisher = _build_finisher(metadata)

    # WeasyPrint: base_url resolves relative CSS/font paths
    font_config = weasyprint.text.fonts.FontConfiguration()
    html_doc = weasyprint.HTML(
        string=html_string,
        base_url=str(template_dir),
    )
    html_doc.write_pdf(
        str(output_path),
        font_config=font_config,
        finisher=finisher,
    )
