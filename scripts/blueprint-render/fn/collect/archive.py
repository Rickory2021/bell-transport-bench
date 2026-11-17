# scripts/blueprint-render/fn/collect/archive.py
"""Pack text files into one zip archive, base64-encoded, with a manifest of each file's SHA-256.

A rendered artifact can then carry files whole, such as a notebook that unpacks
them, while its manifest lets a reader check each file against its source.

Input:
    data.files: [{_source, _text}] from a {text: ...} tag.
    vars: an optional selection (under, whole, partial, names), as fn/collect/_select.py says.

Output:
    {"payload": base64 text of the zip,
     "files": [{"path": rel_path, "sha256": hex digest of its UTF-8 bytes}], in path order,
     "count": the number of files}

The same files always give the same zip: entries in path order, each with a
fixed timestamp, Unix permissions 0644 and deflate level 9. Deflate's output
can still differ between zlib builds, so compare two payloads by what they
unpack to, never by their encoded text.
"""

import base64
import hashlib
import io
import zipfile

from fn.collect._select import select

FIXED_TIME = (1980, 1, 1, 0, 0, 0)  # the earliest a zip records; the files' own times would change every render


def run(data, vars):
    files = sorted(select(data["files"], vars or {}), key=lambda e: e["_source"])
    if not files:
        raise ValueError("archive: no file to pack")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for entry in files:
            info = zipfile.ZipInfo(entry["_source"], date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # Unix, so the permissions below mean the same everywhere
            info.external_attr = 0o100644 << 16
            archive.writestr(info, entry["_text"].encode("utf-8"), compresslevel=9)
    manifest = [{"path": e["_source"], "sha256": hashlib.sha256(e["_text"].encode("utf-8")).hexdigest()} for e in files]
    return {"payload": base64.b64encode(buffer.getvalue()).decode("ascii"), "files": manifest, "count": len(files)}
