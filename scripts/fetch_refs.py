# scripts/fetch_refs.py
"""Download local copies of the project's references.

Reads docs/bp.data.references.yaml and downloads every entry with a
`download` link into .references/ (gitignored). Copies are for reading
offline; they are never committed, because most sources may not be
redistributed in this public repo.

Usage:
    uv run python scripts/fetch_refs.py            # download what is missing
    uv run python scripts/fetch_refs.py --dry-run  # show the plan only
    uv run python scripts/fetch_refs.py --force    # download everything again
"""

import argparse
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "bp.data.references.yaml"
OUT = ROOT / ".references"
USER_AGENT = "bell-transport-bench refs-fetch"
TIMEOUT_S = 60


def load_references(path=DATA):
    """Return the reference entries, failing on a missing file or duplicate ids."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    refs = data.get("references") or []
    seen = set()
    for ref in refs:
        rid = ref.get("id")
        if rid in seen:
            raise ValueError(f"duplicate reference id: {rid}")
        seen.add(rid)
    return refs


def file_name(ref_id, url):
    """Local file name: the reference id plus the URL's extension (.pdf for arXiv PDFs)."""
    suffix = Path(urlparse(url).path).suffix
    if not suffix or "arxiv.org" in urlparse(url).netloc:
        suffix = ".pdf" if "/pdf/" in url else suffix or ".bin"
    return f"{ref_id}{suffix}"


def plan(refs):
    """One download per distinct URL, named after the first reference that uses it.

    Returns a list of (url, file_name, [ids sharing the URL]).
    """
    by_url = {}
    for ref in refs:
        url = ref.get("download")
        if not url:
            continue
        by_url.setdefault(url, []).append(ref["id"])
    return [(url, file_name(ids[0], url), ids) for url, ids in by_url.items()]


def download(url, dest):
    """Download url to dest atomically; return None on success or an error message."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            tmp.write_bytes(response.read())
        tmp.replace(dest)
        return None
    except Exception as exc:  # report and carry on with the other files
        tmp.unlink(missing_ok=True)
        return f"{type(exc).__name__}: {exc}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="show the plan, download nothing")
    parser.add_argument("--force", action="store_true", help="download files that already exist")
    args = parser.parse_args(argv)

    jobs = plan(load_references())
    if not args.dry_run:
        OUT.mkdir(exist_ok=True)
    failed = 0
    for url, name, ids in jobs:
        dest = OUT / name
        shared = f"  (also: {', '.join(ids[1:])})" if len(ids) > 1 else ""
        if dest.exists() and not args.force:
            print(f"skip  {name}{shared}")
            continue
        if args.dry_run:
            print(f"plan  {name}  <-  {url}{shared}")
            continue
        error = download(url, dest)
        if error:
            failed += 1
            print(f"FAIL  {name}  <-  {url}: {error}", file=sys.stderr)
        else:
            print(f"ok    {name}{shared}")
    print(f"{len(jobs)} downloads planned, {failed} failed; files in {OUT.relative_to(ROOT)}/")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
