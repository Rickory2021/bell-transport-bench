# scripts/flatten-sync/tests/test_flatten_for_project.py
"""End-to-end tests for the export command (cmd_run).

Each test builds a throwaway repo under tmp_path with its own modifiers.yaml
and profile, points the module-level config paths at them, and runs the
command. The tests pin observable behavior (output names, manifest content,
stale handling) so internal refactors of the walk orchestration stay safe.
"""

import argparse

import pytest
import yaml

import flatten_for_project as ffp


# -- helpers -------------------------------------------------------------------


MODIFIERS = """\
modifiers:
  build-output:
    silent: true
    dirs: [project-export-files]
    note: "Export output."
  tool-config:
    silent: true
    dirs: [profiles]
    files: [modifiers.yaml]
    note: "Tool configuration."
  tests:
    dirs: [tests]
    note: "Test suites."
"""


def _write(base, rel, content="x\n"):
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _setup_repo(root, monkeypatch, profile_yaml, modifiers_yaml=MODIFIERS):
    """Write config into the repo and point cmd_run at it."""
    _write(root, "modifiers.yaml", modifiers_yaml)
    _write(root, "profiles/default.flatten.config.example.yaml", profile_yaml)
    monkeypatch.setattr(ffp, "MODIFIERS_PATH", root / "modifiers.yaml")
    monkeypatch.setattr(ffp, "PROFILES_DIR", root / "profiles")


def _run(root, dry_run=False, clean=False, preserve=None):
    args = argparse.Namespace(
        profile="default",
        root=str(root),
        dry_run=dry_run,
        clean=clean,
        preserve=preserve or [],
    )
    ffp.cmd_run(args)
    return root / "project-export-files" / "default"


def _output_names(output):
    return sorted(p.name for p in output.iterdir() if p.is_file())


def _manifest(output):
    return yaml.safe_load((output / "_CONTEXT.yaml").read_text())


ROOT_PROFILE = """\
root:
  __path: .
  __modifier:
    exclude: [build-output, tool-config, tests]
"""


# -- C1-C5: characterization ---------------------------------------------------


class TestCmdRun:
    """Behavior of a full export run."""

    def test_exports_included_files_with_flat_names(self, tmp_path, monkeypatch):
        _setup_repo(tmp_path, monkeypatch, ROOT_PROFILE)
        _write(tmp_path, "README.md")
        _write(tmp_path, "src/app.py")
        _write(tmp_path, "tests/test_app.py")

        output = _run(tmp_path)

        assert _output_names(output) == ["README.md", "_CONTEXT.yaml", "src--app.py"]

    def test_manifest_matches_walk(self, tmp_path, monkeypatch):
        _setup_repo(tmp_path, monkeypatch, ROOT_PROFILE)
        _write(tmp_path, "README.md")
        _write(tmp_path, "src/app.py")
        _write(tmp_path, "tests/test_app.py")

        manifest = _manifest(_run(tmp_path))

        assert manifest["file_count"] == 2
        assert manifest["excluded_count"] == 1
        assert manifest["modifiers_applied"] == {
            "tests": {
                "files": 1,
                "note": "Test suites.",
                "excluded": ["tests/test_app.py"],
            }
        }

    def test_stale_removed_context_and_preserved_kept(self, tmp_path, monkeypatch):
        _setup_repo(tmp_path, monkeypatch, ROOT_PROFILE)
        _write(tmp_path, "README.md")
        app = _write(tmp_path, "src/app.py")
        output = _run(tmp_path)

        app.unlink()
        _write(output, "manual-notes.md")
        _run(tmp_path, preserve=["manual-*"])

        assert _output_names(output) == ["README.md", "_CONTEXT.yaml", "manual-notes.md"]

    def test_dry_run_writes_nothing(self, tmp_path, monkeypatch):
        _setup_repo(tmp_path, monkeypatch, ROOT_PROFILE)
        _write(tmp_path, "README.md")

        output = _run(tmp_path, dry_run=True)

        assert not output.exists()

    def test_child_node_modifiers_apply_only_under_child(self, tmp_path, monkeypatch):
        profile = """\
root:
  __path: .
  __modifier:
    exclude: [build-output, tool-config]
  lib:
    __path: lib
    __modifier:
      exclude: [tests]
"""
        _setup_repo(tmp_path, monkeypatch, profile)
        _write(tmp_path, "tests/test_root.py")
        _write(tmp_path, "lib/core.py")
        _write(tmp_path, "lib/tests/test_core.py")

        output = _run(tmp_path)

        assert _output_names(output) == [
            "_CONTEXT.yaml",
            "lib--core.py",
            "tests--test_root.py",
        ]
        assert _manifest(output)["modifiers_applied"]["tests"]["excluded"] == [
            "lib/tests/test_core.py"
        ]


# -- C6-C7: condition modifiers through a full run -------------------------------


COLD_MODIFIERS = MODIFIERS + """\
  cold:
    note: "Closed roles trimmed."
    condition:
      group: opportunities/pipeline/*/*
      probe: bp.data.lifecycle.yaml
      path: history[*].stage
      when:
        rejected:
          keep: [bp.data.lifecycle.yaml]
"""

COLD_PROFILE = """\
root:
  __path: .
  __modifier:
    exclude: [build-output, tool-config, cold]
"""

ROLE = "opportunities/pipeline/acme/eng"


def _lifecycle(stage):
    return yaml.safe_dump({"history": [{"stage": "applied"}, {"stage": stage}]})


class TestCmdRunConditionModifiers:
    """Pruned files leave the export and appear in the manifest."""

    def test_pruned_files_absent_and_listed_in_manifest(self, tmp_path, monkeypatch, capsys):
        _setup_repo(tmp_path, monkeypatch, COLD_PROFILE, COLD_MODIFIERS)
        _write(tmp_path, f"{ROLE}/bp.data.lifecycle.yaml", _lifecycle("rejected"))
        _write(tmp_path, f"{ROLE}/notes.md")

        output = _run(tmp_path)

        assert _output_names(output) == [
            "_CONTEXT.yaml",
            "opportunities--pipeline--acme--eng--bp.data.lifecycle.yaml",
        ]
        assert _manifest(output)["modifiers_applied"]["cold"] == {
            "files": 1,
            "note": "Closed roles trimmed.",
            "excluded": [f"{ROLE}/notes.md"],
        }
        assert "Prune:   cold: trimmed 1 groups (rejected 1)" in capsys.readouterr().out

    def test_file_pruned_on_rerun_removed_from_output(self, tmp_path, monkeypatch):
        _setup_repo(tmp_path, monkeypatch, COLD_PROFILE, COLD_MODIFIERS)
        lifecycle = _write(tmp_path, f"{ROLE}/bp.data.lifecycle.yaml", _lifecycle("applied"))
        _write(tmp_path, f"{ROLE}/notes.md")
        output = _run(tmp_path)
        assert "opportunities--pipeline--acme--eng--notes.md" in _output_names(output)

        lifecycle.write_text(_lifecycle("rejected"))
        _run(tmp_path)

        assert "opportunities--pipeline--acme--eng--notes.md" not in _output_names(output)
