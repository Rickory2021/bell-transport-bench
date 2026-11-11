# scripts/flatten-sync/lib/prune.py
"""Conditional prune: drop files from a group based on a value in a probe file.

A condition modifier (see modifiers.yaml) names:

    group  root-relative directory pattern, one fnmatch pattern per segment
           ("opportunities/pipeline/*/*"); each matching directory is a group
    probe  file inside each group that holds the deciding value
    path   expression into the probe's YAML ("history[*].stage"); the last
           non-null value it reaches decides
    when   value -> {keep: [...]}; a listed value prunes every group member
           except the keep entries (exact group-relative paths, or "dir/"
           prefixes); an unlisted value keeps the whole group

Failures keep content: a probe that is missing, empty, or not valid YAML
keeps its group and warns. A config error never gets this far;
lib/modifiers.py rejects it at load time.

The "last non-null value" rule mirrors _derive_current_stage in
scripts/blueprint-render/fn/collect/extract_pipeline.py. Keep them in step.
"""

import re
import warnings
from collections import Counter, defaultdict
from fnmatch import fnmatchcase
from pathlib import Path

import yaml

_STEP = re.compile(r"^([A-Za-z0-9_-]+)(\[\*\])?$")

NO_VALUE = "(no value)"


# -- Path expressions -------------------------------------------------------------


def parse_path(expr: str) -> list[tuple[str, bool]]:
    """Parse "a.b[*].c" into [(key, flatten_list), ...].

    Raises:
        ValueError: on an empty expression or a malformed step.
    """
    steps = []
    for part in expr.split("."):
        match = _STEP.match(part)
        if not match:
            raise ValueError(f"invalid path step '{part}' in '{expr}'")
        steps.append((match.group(1), match.group(2) is not None))
    return steps


def extract_value(data, steps: list[tuple[str, bool]]) -> str | None:
    """Follow steps into parsed YAML; return the last non-null value as a string.

    A missing key or a non-mapping on the way drops that branch. Values are
    compared as strings (YAML 1.1 reads "no" as False; str() keeps the
    comparison consistent with the when keys, which are stringified the
    same way).
    """
    values = [data]
    for key, flatten in steps:
        reached = []
        for value in values:
            if not isinstance(value, dict) or key not in value:
                continue
            child = value[key]
            if flatten:
                if isinstance(child, list):
                    reached.extend(child)
            else:
                reached.append(child)
        values = reached
    for value in reversed(values):
        if value is not None:
            return str(value)
    return None


# -- Groups and keep entries -------------------------------------------------------


def split_group(rel_path: str, group_segments: list[str]) -> tuple[str, str] | None:
    """Return (group_dir, member_path) for a root-relative file path, or None.

    Matching is per segment, so "*" never crosses "/". A file must sit below
    the group directory: a file at exactly the group's depth is not a member.
    """
    parts = rel_path.split("/")
    depth = len(group_segments)
    if len(parts) <= depth:
        return None
    for part, pattern in zip(parts, group_segments):
        if not fnmatchcase(part, pattern):
            return None
    return "/".join(parts[:depth]), "/".join(parts[depth:])


def keep_match(member: str, keep: list[str]) -> str | None:
    """Return the keep entry that covers member, or None."""
    for entry in keep:
        if entry.endswith("/"):
            if member.startswith(entry):
                return entry
        elif member == entry:
            return entry
    return None


# -- Session ------------------------------------------------------------------------


class _ModStats:
    def __init__(self):
        self.groups_by_value = defaultdict(set)  # value -> {group_dir}
        self.unreadable = set()
        self.keep_hits = defaultdict(set)  # (value, entry) -> {group_dir}


class PruneSession:
    """Evaluates condition modifiers across one export run.

    One session spans every node, so a group split across nodes is probed
    once and counted once, and the end-of-run checks see every group.
    """

    def __init__(self, root: Path):
        self.root = root
        self._probes = {}  # (group_dir, probe, path) -> value | None
        self._stats = defaultdict(_ModStats)
        self._defs = {}

    def _probe(
        self, mod_name: str, condition: dict, group_dir: str
    ) -> tuple[str | None, str | None]:
        """Return (value, failure_reason) for a group's probe, read once per run."""
        key = (group_dir, condition["probe"], condition["path"])
        if key in self._probes:
            return self._probes[key]

        probe_path = self.root / group_dir / condition["probe"]
        value, reason = None, None
        try:
            text = probe_path.read_text()
        except FileNotFoundError:
            reason = "missing"
        except OSError as exc:
            reason = f"unreadable: {exc.__class__.__name__}"
        else:
            if not text.strip():
                reason = "empty"
            else:
                try:
                    data = yaml.safe_load(text)
                except yaml.YAMLError:
                    reason = "invalid YAML"
                else:
                    value = extract_value(data, parse_path(condition["path"]))

        if reason is not None:
            warnings.warn(
                f"{mod_name}: probe {group_dir}/{condition['probe']} is {reason}; "
                "keeping the whole group"
            )
        self._probes[key] = (value, reason)
        return self._probes[key]

    def apply(
        self,
        active: list[tuple[str, dict]],
        files: list[Path],
    ) -> tuple[list[Path], dict[str, list[str]]]:
        """Prune files with the active condition modifiers.

        Args:
            active: (mod_name, mod_def) for every condition modifier active
                at this node.
            files: absolute paths that survived the name-matching walk.

        Returns:
            (kept_files, pruned) where pruned maps mod_name to the
            root-relative paths it removed. The result is the union of every
            modifier's prune; a file is credited to the first modifier by
            sorted name that prunes it.
        """
        ordered = sorted(active, key=lambda item: item[0])
        for mod_name, mod_def in ordered:
            self._defs[mod_name] = mod_def

        kept, pruned = [], {}
        for path in files:
            rel = path.relative_to(self.root).as_posix()
            credited = None
            for mod_name, mod_def in ordered:
                if self._prunes(mod_name, mod_def["condition"], rel) and credited is None:
                    credited = mod_name
            if credited is None:
                kept.append(path)
            else:
                pruned.setdefault(credited, []).append(rel)
        return kept, pruned

    def _prunes(self, mod_name: str, condition: dict, rel: str) -> bool:
        split = split_group(rel, condition["group"].split("/"))
        if split is None:
            return False
        group_dir, member = split

        value, reason = self._probe(mod_name, condition, group_dir)
        stats = self._stats[mod_name]
        if reason is not None:
            stats.unreadable.add(group_dir)
            return False

        stats.groups_by_value[value if value is not None else NO_VALUE].add(group_dir)
        when = {str(k): v for k, v in condition["when"].items()}
        if value is None or value not in when:
            return False

        entry = keep_match(member, when[value]["keep"])
        if entry is not None:
            stats.keep_hits[(value, entry)].add(group_dir)
            return False
        return True

    def finish(self) -> list[str]:
        """Run the end-of-run checks and return one summary line per modifier.

        Warns when no group resolved a value (a broken path expression or a
        renamed field) and when a keep entry matched nothing in any group
        its value applied to (a probable typo).
        """
        lines = []
        for mod_name in sorted(self._stats):
            stats = self._stats[mod_name]
            when = {str(k): v for k, v in self._defs[mod_name]["condition"]["when"].items()}
            counts = Counter({v: len(g) for v, g in stats.groups_by_value.items()})

            resolved = sum(n for v, n in counts.items() if v != NO_VALUE)
            seen = sum(counts.values()) + len(stats.unreadable)
            if seen and resolved == 0:
                warnings.warn(
                    f"{mod_name}: no group resolved a value from "
                    f"'{self._defs[mod_name]['condition']['path']}'; "
                    "check condition.path and condition.probe"
                )

            # A keep entry is a probable typo when it matched nothing in any
            # group the modifier trimmed, under any value. Per-value checking
            # would flag optional entries (interview/) for values whose
            # groups happen to lack them.
            applied = set().union(*(stats.groups_by_value.get(v, set()) for v in when))
            if applied:
                hit = {entry for (_, entry), groups in stats.keep_hits.items() if groups}
                declared = sorted({k for entry in when.values() for k in entry["keep"]})
                for keep in declared:
                    if keep not in hit:
                        warnings.warn(
                            f"{mod_name}: keep entry '{keep}' matched nothing in "
                            f"{len(applied)} trimmed groups; check for a typo"
                        )

            trimmed = {v: n for v, n in counts.items() if v in when}
            kept = {v: n for v, n in counts.items() if v not in when}
            lines.append(
                f"{mod_name}: trimmed {sum(trimmed.values())} groups ({_fmt(trimmed)}); "
                f"kept {sum(kept.values())} ({_fmt(kept)}); "
                f"unreadable {len(stats.unreadable)}"
            )
        return lines


def _fmt(counts: dict) -> str:
    return ", ".join(f"{v} {n}" for v, n in sorted(counts.items())) or "none"
