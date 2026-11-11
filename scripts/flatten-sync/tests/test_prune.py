# scripts/flatten-sync/tests/test_prune.py
"""Tests for conditional prune evaluation (lib/prune.py)."""

import warnings
from pathlib import Path

import pytest
import yaml

from lib.prune import PruneSession, extract_value, keep_match, parse_path, split_group


GROUP = "opportunities/pipeline/*/*"
PROBE = "bp.data.lifecycle.yaml"
ASSESSMENT = "research/bp.data.opportunity-assessment.yaml"


def _condition(when=None):
    return {
        "group": GROUP,
        "probe": PROBE,
        "path": "history[*].stage",
        "when": when
        or {"rejected": {"keep": [PROBE, ASSESSMENT, "interview/"]}},
    }


def _lifecycle(*stages):
    return yaml.safe_dump({"history": [{"stage": s} for s in stages]})


def _role(root, name, probe_text, extra=("notes.md", "job-description.md")):
    """Create a role directory with a probe, an assessment, and extra files."""
    base = root / "opportunities" / "pipeline" / name
    base.mkdir(parents=True, exist_ok=True)
    if probe_text is not None:
        (base / PROBE).write_text(probe_text)
    for rel in (ASSESSMENT, *extra):
        f = base / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    return base


def _files(root):
    return sorted(p for p in root.rglob("*") if p.is_file())


def _rel(root, paths):
    return sorted(p.relative_to(root).as_posix() for p in paths)


def _apply(root, condition=None, name="cold", files=None):
    session = PruneSession(root)
    kept, pruned = session.apply(
        [(name, {"condition": condition or _condition()})],
        files if files is not None else _files(root),
    )
    return session, kept, pruned


# -- path expressions -----------------------------------------------------------


class TestExtractValue:
    def test_last_non_null_stage(self):
        """Same rule as blueprint-render's _derive_current_stage."""
        data = {"history": [{"stage": "applied"}, {"stage": "rejected"}, {"stage": None}]}
        assert extract_value(data, parse_path("history[*].stage")) == "rejected"

    @pytest.mark.parametrize("data", [{"history": []}, {"history": [{"stage": None}]}])
    def test_empty_or_all_null_yields_no_value(self, data):
        assert extract_value(data, parse_path("history[*].stage")) is None

    @pytest.mark.parametrize(
        "data",
        [{"other": []}, {"history": "text"}, {"history": [1, "a"]}, ["not", "a", "map"], None],
    )
    def test_missing_key_or_non_mapping_yields_no_value(self, data):
        assert extract_value(data, parse_path("history[*].stage")) is None

    def test_non_string_scalars_compared_as_strings(self):
        assert extract_value({"stage": 2026}, parse_path("stage")) == "2026"
        assert extract_value(yaml.safe_load("stage: no"), parse_path("stage")) == "False"

    @pytest.mark.parametrize("expr", ["", "a..b", "a[0]", "a.b c", "[*]"])
    def test_invalid_expression_raises(self, expr):
        with pytest.raises(ValueError):
            parse_path(expr)


# -- groups and keep ----------------------------------------------------------------


class TestSplitGroup:
    def test_star_does_not_cross_slash(self):
        assert split_group("a/x/y/z/f.md", ["a", "*", "*"]) == ("a/x/y", "z/f.md")
        assert split_group("a/x/y/f.md", ["a", "*"]) == ("a/x", "y/f.md")
        assert split_group("b/x/y/f.md", ["a", "*", "*"]) is None
        assert split_group("a/f.md", ["a", "*", "*"]) is None

    def test_file_at_group_depth_is_not_a_member(self, tmp_path):
        assert split_group("opportunities/pipeline/acme/README.md", GROUP.split("/")) is None
        readme = tmp_path / "opportunities" / "pipeline" / "acme" / "README.md"
        readme.parent.mkdir(parents=True)
        readme.write_text("x")
        _, kept, pruned = _apply(tmp_path, files=[readme])
        assert kept == [readme] and pruned == {}


class TestKeep:
    def test_exact_path_kept(self):
        assert keep_match(ASSESSMENT, [ASSESSMENT]) == ASSESSMENT
        assert keep_match("research/other.yaml", [ASSESSMENT]) is None

    def test_dir_prefix_keeps_nested_files(self):
        assert keep_match("interview/round-1/landscape/a.md", ["interview/"]) == "interview/"
        assert keep_match("interview-notes.md", ["interview/"]) is None


# -- session ---------------------------------------------------------------------


class TestPruneSession:
    def test_uncovered_files_pruned_keep_files_kept(self, tmp_path):
        base = _role(tmp_path, "acme/eng", _lifecycle("applied", "rejected"),
                     extra=("notes.md", "deliverables/resume.yaml", "interview/r1/drill.md"))
        _, kept, pruned = _apply(tmp_path)
        prefix = "opportunities/pipeline/acme/eng/"
        assert _rel(tmp_path, kept) == sorted(
            prefix + p for p in (PROBE, ASSESSMENT, "interview/r1/drill.md")
        )
        assert pruned == {"cold": sorted(prefix + p for p in ("deliverables/resume.yaml", "notes.md"))}
        assert base.exists()

    def test_empty_keep_prunes_whole_group(self, tmp_path):
        _role(tmp_path, "acme/eng", _lifecycle("rejected"))
        _, kept, pruned = _apply(tmp_path, _condition({"rejected": {"keep": []}}))
        assert kept == []
        assert len(pruned["cold"]) == 4

    def test_probe_not_in_keep_is_pruned(self, tmp_path):
        _role(tmp_path, "acme/eng", _lifecycle("rejected"))
        _, kept, pruned = _apply(tmp_path, _condition({"rejected": {"keep": [ASSESSMENT]}}))
        assert "opportunities/pipeline/acme/eng/" + PROBE in pruned["cold"]

    def test_value_not_in_when_keeps_group(self, tmp_path):
        _role(tmp_path, "acme/eng", _lifecycle("applied"))
        _, kept, pruned = _apply(tmp_path)
        assert pruned == {} and len(kept) == 4

    def test_yaml_boolean_value_matches_boolean_when_key(self, tmp_path):
        _role(tmp_path, "acme/eng", "history:\n  - stage: no\n")
        when = yaml.safe_load("no:\n  keep: []\n")
        _, kept, pruned = _apply(tmp_path, _condition(when))
        assert kept == [] and len(pruned["cold"]) == 4

    @pytest.mark.parametrize(
        "probe_text, reason",
        [(None, "missing"), ("history: [unclosed\n", "invalid YAML"), ("  \n", "empty")],
    )
    def test_unreadable_probe_keeps_group_and_warns(self, tmp_path, probe_text, reason):
        _role(tmp_path, "acme/eng", probe_text)
        with pytest.warns(UserWarning, match=reason):
            _, kept, pruned = _apply(tmp_path)
        assert pruned == {}
        assert len(kept) == (3 if probe_text is None else 4)

    def test_every_group_unreadable_escalates(self, tmp_path):
        _role(tmp_path, "acme/eng", None)
        _role(tmp_path, "beta/ops", None)
        with pytest.warns(UserWarning):
            session, _, _ = _apply(tmp_path)
        with pytest.warns(UserWarning, match="no group resolved a value"):
            session.finish()

    def test_no_group_yields_value_escalates(self, tmp_path):
        """A renamed field parses fine but resolves nothing anywhere."""
        _role(tmp_path, "acme/eng", yaml.safe_dump({"events": [{"stage": "rejected"}]}))
        session, _, pruned = _apply(tmp_path)
        assert pruned == {}
        with pytest.warns(UserWarning, match="no group resolved a value"):
            session.finish()

    def test_tally_counts_groups_per_value(self, tmp_path):
        _role(tmp_path, "acme/eng", _lifecycle("rejected"))
        _role(tmp_path, "beta/ops", _lifecycle("rejected"))
        _role(tmp_path, "gamma/dev", _lifecycle("applied"))
        _role(tmp_path, "delta/qa", _lifecycle(None))
        session, _, _ = _apply(tmp_path, _condition({"rejected": {"keep": [PROBE, ASSESSMENT]}}))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            lines = session.finish()
        assert lines == [
            "cold: trimmed 2 groups (rejected 2); kept 2 ((no value) 1, applied 1); unreadable 0"
        ]

    def test_keep_entry_matching_nothing_anywhere_warns(self, tmp_path):
        _role(tmp_path, "acme/eng", _lifecycle("rejected"))
        typo = "research/bp.data.opportunity-assesment.yaml"
        session, _, pruned = _apply(tmp_path, _condition({"rejected": {"keep": [PROBE, typo]}}))
        with pytest.warns(UserWarning, match="assesment.yaml' matched nothing in 1 trimmed"):
            session.finish()

    def test_keep_entry_matching_in_one_group_does_not_warn(self, tmp_path):
        _role(tmp_path, "acme/eng", _lifecycle("rejected"),
              extra=("notes.md", "interview/r1/drill.md"))
        _role(tmp_path, "beta/ops", _lifecycle("rejected"))
        session, _, _ = _apply(tmp_path)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            session.finish()

    def test_keep_entry_matched_under_another_value_does_not_warn(self, tmp_path):
        """interview/ exists only in rejected roles; stale roles lacking it is normal."""
        _role(tmp_path, "acme/eng", _lifecycle("rejected"), extra=("interview/r1/drill.md",))
        _role(tmp_path, "beta/ops", _lifecycle("stale"))
        keep = {"keep": [PROBE, ASSESSMENT, "interview/"]}
        session, _, _ = _apply(tmp_path, _condition({"rejected": keep, "stale": keep}))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            session.finish()

    def test_probe_read_once_per_group(self, tmp_path, monkeypatch):
        _role(tmp_path, "acme/eng", _lifecycle("rejected"),
              extra=("a.md", "b.md", "c/d.md"))
        reads = []
        original = Path.read_text

        def spy(self, *args, **kwargs):
            if self.name == PROBE:
                reads.append(self)
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", spy)
        _apply(tmp_path)
        assert len(reads) == 1
