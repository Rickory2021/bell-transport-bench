# tests/test_makefile.py
"""The root Makefile's defaults hold even when the environment sets a variable of the same name.

WSL exports NAME as the machine's hostname, so a default written with ?= would
send `make benchmark` to a benchmark file named after the machine. A value
given on the command line still overrides the default. The tests read each
variable through a target added with --eval, so no recipe or sub-make runs.
"""

import os
import shutil
import subprocess

import pytest

from bellbench import configs

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")

SHOW = "show-%: ; @echo $($*)"  # a target that prints the variable it names


def _make(*args: str, env: dict[str, str]) -> str:
    """What make prints for `args` from the repo root, with `env` added to the environment."""
    return subprocess.run(
        ["make", "-s", "--no-print-directory", *args], cwd=configs.ROOT, env={**os.environ, **env},
        capture_output=True, text=True, check=True,
    ).stdout.strip()


@pytest.mark.parametrize("variable, default", [("NAME", "core"), ("PROFILE", "default")])
def test_an_environment_variable_does_not_replace_a_default(variable, default):
    assert _make("--eval", SHOW, f"show-{variable}", env={variable: "elsewhere"}) == default


@pytest.mark.parametrize("variable", ["NAME", "PROFILE"])
def test_the_command_line_still_overrides_a_default(variable):
    assert _make("--eval", SHOW, f"show-{variable}", f"{variable}=other", env={variable: "elsewhere"}) == "other"


def test_make_benchmark_runs_the_core_benchmark_by_default():
    assert "bellbench.run benchmark core" in _make("-n", "benchmark", env={"NAME": "elsewhere"})
