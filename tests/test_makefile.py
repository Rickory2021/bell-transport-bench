# tests/test_makefile.py
"""The root Makefile's defaults hold even when the environment sets a variable of the same name, and its run,
report and workbench recipes call what they say.

WSL exports NAME as the machine's hostname, so a default written with ?= would
send `make benchmark` to a benchmark file named after the machine. A value
given on the command line still overrides the default. The tests read each
variable through a target added with --eval, and each recipe through make -n,
which prints its commands; only a recipe's own usage check runs.
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


def _make_status(*args: str) -> subprocess.CompletedProcess:
    """make `args` from the repo root, without raising on a non-zero exit."""
    command = ["make", "-s", "--no-print-directory", *args]
    return subprocess.run(command, cwd=configs.ROOT, capture_output=True, text=True)


@pytest.mark.parametrize(
    "target, command", [("run", "bellbench.run rerun some/run"), ("report", "bellbench.run report some/run")]
)
def test_run_and_report_pass_their_path_to_the_command_line(target, command):
    assert command in _make("-n", target, "RUN=some/run", env={})


@pytest.mark.parametrize("target", ["run", "report"])
def test_run_and_report_without_a_path_print_their_usage_and_exit_2(target):
    done = _make_status(target)
    assert done.returncode == 2 and f"usage: make {target} RUN=" in done.stdout


def test_make_workbench_renders_the_notebook_and_copies_it_to_workspace():
    printed = _make("-n", "workbench", env={})
    assert "FILE=notebooks/bp.invoke.workbench.yaml" in printed
    assert "cp notebooks/bp.output.workbench.ipynb workspace/workbench.ipynb" in printed


def test_make_help_states_the_codes_make_run_exits_with():
    printed = _make("help", env={})
    assert "make exits 0 on a match, 2 for a" in printed and "Error 1 a difference, Error 2 a refusal" in printed
