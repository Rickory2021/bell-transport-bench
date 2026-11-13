# scripts/blueprint-render/lib/config.py
"""YAML loading, per-run caching, and PyYAML date normalization.

PyYAML silently coerces two date-like forms on load:
  - Unquoted YYYY-MM-DD  -> datetime.date object
  - Bare YYYY            -> int

A date object is never valid JSON, so normalize_dates() converts
it back to an ISO string at the load boundary, before any
validation runs. A bare year stays an int here: only a schema can
say whether 2026 is a year or a count, such as a run's shots or
seed. lib/validate.py's coerce_years() turns it into a string
where the schema asks for a string, and nowhere else.

Caching: one run reads the same files many times (every schema
per data file, every data source per invoke, every enum per
$ref). load_yaml memoizes parsed files in memory for the life of
the process, keyed by resolved path, size, and mtime, so a file
that changes on disk is re-read and nothing persists across runs.

Loader: PyYAML's C loader (libyaml) is used when the installed
wheel has it; the pure-Python SafeLoader is the fallback. Both
produce identical structures for the bp file set.
"""

import datetime
import os
from pathlib import Path

import yaml

try:
    from yaml import CSafeLoader as _Loader
except ImportError:  # pragma: no cover - depends on the installed wheel
    from yaml import SafeLoader as _Loader

# Per-process cache: resolved path -> (size, mtime_ns, data).
_CACHE = {}


def normalize_dates(obj):
    """Recursively normalize PyYAML date coercion.

    - datetime.date / datetime.datetime -> .isoformat() string
    - Everything else passes through unchanged, bare years included
      (see lib/validate.py, coerce_years).
    """
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: normalize_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_dates(v) for v in obj]
    return obj


def load_yaml(path):
    """Load a YAML file with date normalization applied, cached per run.

    Returns the normalized data structure. Returns an empty dict
    if the file is empty (yaml.safe_load returns None).

    The returned structure is shared with every other caller that
    loads the same unchanged file in this process. Callers read it
    and build new structures from it; they never mutate it.
    """
    path = Path(path)
    st = os.stat(path)
    key = str(path.resolve())
    cached = _CACHE.get(key)
    if cached is not None:
        size, mtime_ns, data = cached
        if size == st.st_size and mtime_ns == st.st_mtime_ns:
            return data

    with open(path) as f:
        data = yaml.load(f, Loader=_Loader)
    if data is None:
        data = {}
    else:
        data = normalize_dates(data)

    _CACHE[key] = (st.st_size, st.st_mtime_ns, data)
    return data


def clear_cache():
    """Drop every cached parse. For tests and long-lived callers."""
    _CACHE.clear()
