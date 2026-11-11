# scripts/blueprint-render/blueprint_render.py
"""Blueprint render tool.

Validates, maps, and renders deliverables from structured
YAML source files and blueprint configurations.

Usage:
    blueprint_render.py validate                    # all bp files
    blueprint_render.py validate --file <path>      # one file
    blueprint_render.py validate --key <key>        # all files for a key
    blueprint_render.py run --file <path>            # render one invoke

Subcommands:
    validate    Check bp files against their schemas
    run         Build deliverables from invokes
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Bootstrap: add this script's directory to sys.path so lib/
# imports resolve regardless of where blueprint-render/ lives.
TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))

from lib.binding import discover, check_uniqueness
from lib.validate import run_all, run_file, run_key


def _resolve_root(args):
    """Resolve the repo root directory.

    Uses --root if provided, otherwise falls back to
    git rev-parse --show-toplevel.
    """
    if args.root:
        return Path(args.root).resolve()

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(result.stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: not in a git repo and --root not provided",
              file=sys.stderr)
        sys.exit(1)


def cmd_validate(args):
    """Run validation checks on bp files."""
    root = _resolve_root(args)

    # Discover all bp files
    registry = discover(root)

    # Count what we found
    total = sum(len(v) for v in registry.values())
    counts = {role: len(files) for role, files in registry.items() if files}
    count_parts = [f"{n} {r}" for r, n in sorted(counts.items())]
    print(f"Discovered {total} bp files: {', '.join(count_parts)}")
    print()

    # Check filename uniqueness (error tier, always runs)
    uniqueness_errors = check_uniqueness(registry)
    if uniqueness_errors:
        print("UNIQUENESS ERRORS:")
        for err in uniqueness_errors:
            print(f"  {err}")
        print()
        sys.exit(1)

    # Route to the appropriate validation scope
    if args.file:
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = root / file_path
        if not file_path.exists():
            print(f"Error: file not found: {args.file}",
                  file=sys.stderr)
            sys.exit(1)
        result = run_file(file_path, registry, root)

    elif args.key:
        result = run_key(args.key, registry, root)

    else:
        # Default: validate all
        result = run_all(registry, root)

    # Report
    use_color = sys.stdout.isatty()
    report = result.format_report(
        color=use_color, verbose=args.verbose
    )
    if report:
        print(report)
        print()
    print(result.format_summary(color=use_color))

    sys.exit(0 if result.passed else 1)


def cmd_run(args):
    """Build deliverables from invokes."""
    from lib.runner import run_invoke, RunError

    root = _resolve_root(args)
    emit_formats = None  # All formats declared in the process emit section

    # Discover once; validation and every run_invoke share it.
    registry = discover(root)

    # Validate before rendering: errors block, warnings print.
    # Prevents missing vars materializing as literal None in PDFs.
    result = run_all(registry, root)
    use_color = sys.stdout.isatty()
    report = result.format_report(color=use_color, verbose=False)
    if report:
        print(report)
        print()
    if not result.passed:
        print(result.format_summary(color=use_color))
        print("Run aborted: validation failed.", file=sys.stderr)
        sys.exit(1)

    # Collect invoke paths to render
    if args.file:
        invoke_path = Path(args.file)
        if not invoke_path.is_absolute():
            invoke_path = root / invoke_path
        if not invoke_path.exists():
            print(f"Error: file not found: {args.file}",
                  file=sys.stderr)
            sys.exit(1)
        invoke_paths = [invoke_path]
    else:
        # Default: all invokes
        invoke_paths = [path for path, _key, _qual in registry["invoke"]]
        if not invoke_paths:
            print("No bp.invoke files found.", file=sys.stderr)
            sys.exit(1)
        print(f"Running {len(invoke_paths)} invoke(s)...\n")

    # Color codes for render output
    if use_color:
        green = "\033[32m"
        cyan = "\033[36m"
        yellow = "\033[33m"
        red = "\033[31m"
        dim = "\033[2m"
        reset = "\033[0m"
    else:
        green = cyan = yellow = red = dim = reset = ""

    all_rendered = []
    all_skipped = []
    all_warnings = []
    all_noop = []
    failures = []

    for invoke_path in invoke_paths:
        rel = invoke_path.relative_to(root)
        try:
            rendered, skipped, warnings = run_invoke(
                invoke_path, root, TOOL_DIR, emit_formats,
                force=args.force,
                output_scope=args.output,
                registry=registry,
            )
            if not rendered and not skipped and not warnings:
                print(f"  {dim}NO-OP{reset}     {dim}{rel}{reset}")
                all_noop.append(rel)
                continue
            for path in rendered:
                try:
                    path_rel = path.relative_to(root)
                except ValueError:
                    path_rel = path
                print(f"  {green}RENDERED{reset}  {rel} -> {path_rel}")
            for path in skipped:
                try:
                    path_rel = path.relative_to(root)
                except ValueError:
                    path_rel = path
                print(f"  {cyan}SKIPPED{reset}   {path_rel}")
                print(f"            make bp-invoke FILE={rel} FORCE=true")
            for msg in warnings:
                print(f"  {yellow}WARNING{reset}   {rel}: {msg}")
            all_rendered.extend(rendered)
            all_skipped.extend(skipped)
            all_warnings.extend(warnings)
        except RunError as e:
            print(f"  {red}FAILED{reset}    {rel}: {e}")
            failures.append((rel, e))
        except Exception as e:
            import traceback
            print(f"  {red}FAILED{reset}    {rel}: {e}")
            traceback.print_exc()
            failures.append((rel, e))

    # Summary
    print()
    parts = []
    if all_rendered:
        parts.append(f"{green}{len(all_rendered)} rendered{reset}")
    if all_skipped:
        parts.append(f"{cyan}{len(all_skipped)} skipped{reset}")
    if all_noop:
        parts.append(f"{dim}{len(all_noop)} no-op{reset}")
    if all_warnings:
        parts.append(f"{yellow}{len(all_warnings)} warned{reset}")
    if failures:
        parts.append(f"{red}{len(failures)} failed{reset}")
    if parts:
        print(", ".join(parts))
    if failures:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Blueprint render tool."
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repo root (default: git rev-parse --show-toplevel)",
    )
    subparsers = parser.add_subparsers(dest="command")

    # -- validate --
    val_parser = subparsers.add_parser(
        "validate", help="Validate bp files"
    )
    val_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Show all results (default: failures only)",
    )
    scope = val_parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--file",
        default=None,
        help="Validate one file",
    )
    scope.add_argument(
        "--key",
        default=None,
        help="Validate all files for a binding key",
    )
    scope.add_argument(
        "--all",
        action="store_true",
        default=True,
        help="Validate all bp files (default)",
    )

    # -- run --
    run_parser = subparsers.add_parser(
        "run", help="Build deliverables from invokes"
    )
    run_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Re-render even if output file exists",
    )
    run_parser.add_argument(
        "--output",
        choices=["all", "adjacent", "renderout"],
        default="all",
        help="Output scope: all (default), adjacent (bp.output only), "
             "renderout (render-out only)",
    )
    run_scope = run_parser.add_mutually_exclusive_group()
    run_scope.add_argument(
        "--file",
        default=None,
        help="Render one invoke file",
    )
    run_scope.add_argument(
        "--all",
        action="store_true",
        default=True,
        help="Render all invokes (default)",
    )

    args = parser.parse_args()

    if args.command == "validate":
        cmd_validate(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
