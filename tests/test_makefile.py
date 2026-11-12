# tests/test_makefile.py
"""The root Makefile's defaults hold even when the environment sets a variable of the same name.

WSL exports NAME as the machine's hostname, so a default written with ?= would
send `make benchmark` to a benchmark file named after the machine. A value
given on the command line still overrides the default.
"""

import os
import shutil
import subprocess

import pytest

from bellbench import configs

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")


def _dry_run(*args: str, env: dict[str, str]) -> str:
    """The commands `make -n` would run from the repo root, with `env` added to the environment."""
    return subprocess.run(
        ["make", "-n", *args], cwd=configs.ROOT, env={**os.environ, **env},
        capture_output=True, text=True, check=True,
    ).stdout


@pytest.mark.parametrize("target, variable, expected", [
    ("benchmark", "NAME", "bellbench.run benchmark core"),
    ("project-export-dry-run", "PROFILE", "PROFILE=default"),
])
def test_an_environment_variable_does_not_replace_a_default(target, variable, expected):
    assert expected in _dry_run(target, env={variable: "elsewhere"})


def test_the_command_line_still_overrides_a_default():
    assert "bellbench.run benchmark other" in _dry_run("benchmark", "NAME=other", env={"NAME": "elsewhere"})
