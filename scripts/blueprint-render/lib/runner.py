# scripts/blueprint-render/lib/runner.py
"""Map execution engine for the bp system.

Reads a process file and an invoke file, resolves imports and
variables, walks the map section, calls fn modules, assembles
the template context, and dispatches to the renderer.

Three stages per the tech spec:
  1. Validate (reuses lib/validate.py, runs before this module)
  2. Map (this module: resolve vars, call fns, build context)
  3. Render (dispatch to renderer specified in emit)

Profile resolution follows the flatten-sync pattern:
  <n>.blueprint-render.config.yaml (personal, gitignored)
  <n>.blueprint-render.config.example.yaml (committed)
  Run refuses the example (placeholder identity data).

Import reference syntax: profile:personal.header_name
  - "profile:" scheme prefix marks a profile value reference
  - "personal" is the import name (from the import list)
  - "header_name" is the field in the loaded profile

${} interpolation: ${var_name} in string values is replaced
with the resolved var value after all profile references are
resolved. Single pass, unresolved tokens error.
"""

import glob as glob_mod
import importlib.util
import re
import sys
from pathlib import Path

from lib.config import load_yaml

# Regex for ${var_name} interpolation tokens
_INTERP_RE = re.compile(r"\$\{([^}]+)\}")


class RunError(Exception):
    """Raised when the runner encounters a fatal error."""
    pass


# -- Profile resolution --------------------------------------------------------


def _resolve_profile_path(name, profiles_dir):
    """Resolve a profile name to its vars config file.

    Resolution order:
      1. <name>.vars.config.yaml (personal)
      2. <name>.vars.config.example.yaml (committed)

    Returns (path, is_example) tuple.
    Raises FileNotFoundError if neither exists.
    """
    personal = profiles_dir / f"{name}.vars.config.yaml"
    if personal.exists():
        return personal, False

    example = profiles_dir / f"{name}.vars.config.example.yaml"
    if example.exists():
        return example, True

    raise FileNotFoundError(
        f"Profile '{name}' not found. Looked for:\n"
        f"  {personal}\n  {example}"
    )


def _load_profile(name, profiles_dir):
    """Load a profile vars config.

    Returns the full dict (all keys are var values, no stripping).
    Raises RunError if only the example profile exists.
    """
    path, is_example = _resolve_profile_path(name, profiles_dir)

    if is_example:
        raise RunError(
            f"No personal vars config found for '{name}'.\n"
            f"Copy the example and fill in real values:\n"
            f"  cp {path} {path.parent / path.name.replace('.example', '')}\n"
            f"Placeholder identity data must not render into deliverables."
        )

    return load_yaml(path)


# -- Import and var resolution -------------------------------------------------


def resolve_imports(invoke_data, tool_dir):
    """Load all imported profiles and return a dict of {name: values}.

    Args:
        invoke_data: parsed invoke file contents.
        tool_dir: path to scripts/blueprint-render/ (contains profiles/).

    Returns:
        dict of import_name -> {field: value} for each imported profile.
    """
    imports = invoke_data.get("import", [])
    profiles_dir = tool_dir / "profiles"
    loaded = {}

    for entry in imports:
        profile_name = entry["profile"]
        import_name = entry.get("as", profile_name)
        loaded[import_name] = _load_profile(profile_name, profiles_dir)

    return loaded


def resolve_profile_refs(invoke_vars, imports):
    """Resolve profile: scheme references in invoke var values.

    Walks all var values. String values starting with "profile:" are
    resolved: strip the scheme prefix, split on "." to get
    (import_name, field), look up in loaded imports.

    Args:
        invoke_vars: dict of var_name -> value (import key already stripped).
        imports: dict of import_name -> {field: value}.

    Returns:
        New dict with profile references replaced by resolved values.

    Raises:
        RunError on unresolvable references.
    """
    resolved = {}
    for key, value in invoke_vars.items():
        resolved[key] = _resolve_value(value, imports)
    return resolved


def _resolve_value(value, imports):
    """Recursively resolve profile: references in a value."""
    if isinstance(value, str) and value.startswith("profile:"):
        ref = value[len("profile:"):]
        parts = ref.split(".", 1)
        if len(parts) != 2:
            raise RunError(
                f"Invalid profile reference: '{value}'. "
                f"Expected profile:<import_name>.<field>"
            )
        import_name, field = parts
        if import_name not in imports:
            raise RunError(
                f"Profile reference '{value}' uses import "
                f"'{import_name}' which is not declared in the "
                f"import list."
            )
        profile = imports[import_name]
        if field not in profile:
            raise RunError(
                f"Profile reference '{value}' references field "
                f"'{field}' which does not exist in profile "
                f"'{import_name}'."
            )
        return profile[field]

    if isinstance(value, dict):
        return {k: _resolve_value(v, imports) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(v, imports) for v in value]
    return value


def interpolate_vars(invoke_vars):
    """Replace ${var_name} tokens in string values.

    Single pass. Errors on unresolved tokens. Handles nested
    structures (dicts, lists).

    Args:
        invoke_vars: dict of var_name -> resolved value.

    Returns:
        New dict with interpolated string values.

    Raises:
        RunError if a ${} token references a non-existent var.
    """
    result = {}
    for key, value in invoke_vars.items():
        result[key] = _interpolate_value(value, invoke_vars)
    return result


def _interpolate_value(value, all_vars):
    """Recursively interpolate ${} tokens in a value."""
    if isinstance(value, str):
        def replacer(match):
            var_name = match.group(1)
            if var_name not in all_vars:
                raise RunError(
                    f"Interpolation token '${{{var_name}}}' "
                    f"references unknown var '{var_name}'."
                )
            resolved = all_vars[var_name]
            if not isinstance(resolved, str):
                raise RunError(
                    f"Interpolation token '${{{var_name}}}' "
                    f"resolved to {type(resolved).__name__}, not string."
                )
            return resolved
        return _INTERP_RE.sub(replacer, value)

    if isinstance(value, dict):
        return {k: _interpolate_value(v, all_vars) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_value(v, all_vars) for v in value]
    return value


# -- Map execution -------------------------------------------------------------


def _set_nested(d, dotted_key, value):
    """Set a value in a nested dict using a dotted key.

    'header.name' sets d["header"]["name"].
    """
    parts = dotted_key.split(".")
    current = d
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _load_data_param(path_spec, root):
    """Load a {data: path} param value.

    If the path contains glob characters, loads all matching files
    into a list. Otherwise loads a single file.
    """
    if any(c in path_spec for c in ("*", "?", "[")):
        pattern = str(root / path_spec)
        paths = sorted(glob_mod.glob(pattern, recursive=True))
        return [load_yaml(p) for p in paths]
    else:
        abs_path = root / path_spec
        return load_yaml(abs_path)


def _load_data_with_paths(path_spec, root):
    """Load a {data_with_paths: path} param value.

    Like _load_data_param but returns [{_source: rel, _data: dict}]
    so the fn module can use source paths for key derivation or
    directory-based grouping (e.g. project tier from parent dir).

    Always glob-based (single-file does not need path metadata).
    """
    pattern = str(root / path_spec)
    paths = sorted(glob_mod.glob(pattern, recursive=True))
    result = []
    for p in paths:
        rel = str(Path(p).relative_to(root))
        result.append({"_source": rel, "_data": load_yaml(p)})
    return result


def _load_enum_keys(rel_path, root):
    """Load a bp.enum file and return its values keys as a list.

    Preserves insertion order from the YAML source, which for
    ordered enums (like lifecycle stages) represents the
    canonical progression.

    Args:
        rel_path: root-relative path to the bp.enum file.
        root: repo root Path.

    Returns:
        list of key strings from the enum's values map.
    """
    abs_path = root / rel_path
    if not abs_path.exists():
        raise RunError(
            f"enum file not found: {rel_path} "
            f"(resolved to {abs_path})"
        )
    data = load_yaml(abs_path)
    if not isinstance(data, dict) or "values" not in data:
        raise RunError(
            f"Not a valid bp.enum file (missing 'values' map): "
            f"{rel_path}"
        )
    return list(data["values"].keys())


def _resolve_params(params, resolved_vars, root):
    """Resolve all params in a map entry's fn call.

    Each param value is tagged:
      {var: name} -> look up in resolved vars (an absent var raises)
      {var: name, optional: true} -> look up; None when the invoke
          omits the var. optional defaults to false.
      {data: path} -> load bp.data file(s)
      {data_with_paths: path} -> load files with source path metadata
      {enum_keys: path} -> load bp.enum file, return values keys as list
      {literal: value} -> inline value from the process file

    Returns:
        data_params: dict of param_name -> loaded data
        var_params: dict of param_name -> resolved var value
            (includes literal and enum_keys values)
    """
    data_params = {}
    var_params = {}

    for param_name, tag in params.items():
        if not isinstance(tag, dict):
            raise RunError(
                f"Param '{param_name}' must be a resolution tag "
                f"({{var: ...}}, {{data: ...}}, {{data_with_paths: ...}}, "
                f"{{enum_keys: ...}}, or {{literal: ...}}), "
                f"got {type(tag).__name__}"
            )
        if "var" in tag:
            var_name = tag["var"]
            optional = tag.get("optional", False)
            if not isinstance(optional, bool):
                raise RunError(
                    f"Param '{param_name}': 'optional' must be true or "
                    f"false, got {type(optional).__name__}"
                )
            if var_name not in resolved_vars and optional:
                var_params[param_name] = None
                continue
            if var_name not in resolved_vars:
                raise RunError(
                    f"Param '{param_name}' references var "
                    f"'{var_name}' which is not in the resolved vars."
                )
            var_params[param_name] = resolved_vars[var_name]
        elif "data" in tag:
            data_params[param_name] = _load_data_param(tag["data"], root)
        elif "data_with_paths" in tag:
            data_params[param_name] = _load_data_with_paths(
                tag["data_with_paths"], root
            )
        elif "enum_keys" in tag:
            var_params[param_name] = _load_enum_keys(
                tag["enum_keys"], root
            )
        elif "literal" in tag:
            var_params[param_name] = tag["literal"]
        else:
            raise RunError(
                f"Param '{param_name}' has unknown resolution tag: "
                f"{list(tag.keys())}"
            )

    return data_params, var_params


# -- Emit metadata resolution --------------------------------------------------


def _resolve_metadata(raw_metadata, invoke_vars, output_path):
    """Resolve metadata values from the emit.metadata section.

    Each value is either:
      - A {var: name} tag: look up in resolved invoke vars.
      - A bare string: used as a literal.

    If 'title' is not present, defaults to the output filename stem.

    Args:
        raw_metadata: dict from emit_entry.get("metadata", {}).
        invoke_vars: fully resolved invoke vars (post-interpolation).
        output_path: Path to the output file (for title default).

    Returns:
        Flat dict of resolved metadata fields.

    Raises:
        RunError on unresolvable var references.
    """
    resolved = {}

    for key, value in raw_metadata.items():
        if isinstance(value, dict) and "var" in value:
            var_name = value["var"]
            if var_name not in invoke_vars:
                raise RunError(
                    f"Metadata '{key}' references var "
                    f"'{var_name}' which is not in the resolved vars."
                )
            resolved[key] = invoke_vars[var_name]
        elif isinstance(value, str):
            resolved[key] = value
        else:
            raise RunError(
                f"Metadata '{key}' must be a string literal or "
                f"{{var: name}} tag, got {type(value).__name__}"
            )

    # Default title to output filename stem
    if "title" not in resolved:
        resolved["title"] = output_path.stem

    return resolved


# -- Map fn module loading -----------------------------------------------------


def _load_fn_module(fn_path, root):
    """Dynamically import a fn module by its root-relative path.

    The path is like: scripts/blueprint-render/fn/resume/group_skills
    Appends .py and uses importlib to load.
    """
    abs_path = root / f"{fn_path}.py"
    if not abs_path.exists():
        raise RunError(f"fn module not found: {fn_path} -> {abs_path}")

    module_name = fn_path.replace("/", ".").replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, abs_path)
    if spec is None or spec.loader is None:
        raise RunError(f"Could not load fn module: {abs_path}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "run"):
        raise RunError(
            f"fn module {fn_path} does not export a run() function."
        )
    return mod


def execute_map(process_map, resolved_vars, root):
    """Walk the process map and build the template context.

    Each map entry is either:
      - A var passthrough: {var: var_name}
      - An fn call: {fn: module_path, params: {param_name: tag}}

    Returns the assembled context dict (nested from dotted keys).
    """
    context = {}

    for dotted_key, entry in process_map.items():
        if isinstance(entry, dict) and "var" in entry:
            # Var passthrough
            var_name = entry["var"]
            value = resolved_vars.get(var_name)
            _set_nested(context, dotted_key, value)

        elif isinstance(entry, dict) and "fn" in entry:
            # Fn call
            fn_path = entry["fn"]
            params = entry.get("params", {})

            data_params, var_params = _resolve_params(
                params, resolved_vars, root
            )

            mod = _load_fn_module(fn_path, root)
            result = mod.run(data_params, var_params)
            _set_nested(context, dotted_key, result)

        else:
            raise RunError(
                f"Map entry ''{dotted_key}'' is not a var passthrough "
                f"or fn call: {entry}"
            )

    return context


# -- Renderer dispatch ---------------------------------------------------------


def _load_renderer(render_path, root):
    """Dynamically import a renderer module by root-relative path."""
    abs_path = root / render_path
    if not abs_path.exists():
        raise RunError(f"Renderer not found: {render_path} -> {abs_path}")

    module_name = render_path.replace("/", ".").replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, abs_path)
    if spec is None or spec.loader is None:
        raise RunError(f"Could not load renderer: {abs_path}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "render"):
        raise RunError(
            f"Renderer {render_path} does not export a render() function."
        )
    return mod


def _adjacent_output_path(invoke_path, emit_format):
    """Output path adjacent to the invoke, using bp.output naming.

    bp.invoke.resume.backend-developer.yaml -> bp.output.resume.backend-developer.pdf
    bp.invoke.resume.yaml -> bp.output.resume.pdf (no qualifier)
    """
    stem = invoke_path.stem  # bp.invoke.resume.backend-developer
    parts = stem.split(".")
    # Parts: [bp, invoke, key, qualifier...]
    # Replace "invoke" with "output", keep everything else
    parts[1] = "output"
    return invoke_path.parent / f"{'.'.join(parts)}.{emit_format}"


def _load_run_config(tool_dir):
    """Load the run config file.

    Resolution order:
      1. default.run.config.yaml (personal)
      2. default.run.config.example.yaml (committed)

    Returns the full config dict, or {} if no config found.
    """
    profiles_dir = tool_dir / "profiles"

    config_path = profiles_dir / "default.run.config.yaml"
    if not config_path.exists():
        config_path = profiles_dir / "default.run.config.example.yaml"
    if not config_path.exists():
        return {}

    return load_yaml(config_path) or {}


def _load_profile_output_config(tool_dir):
    """Load the output section from the run config.

    Returns (directory, stems_list) or (None, []) if no output config.
    stems_list entries: {invoke: root-relative path, stem: filename}.
    """
    data = _load_run_config(tool_dir)
    output = data.get("output")
    if output is None:
        # Named-copy output is optional; absence is not a degradation.
        return None, []
    if not isinstance(output, dict):
        print("Warning: run config 'output' is not a mapping; "
              "named copy skipped", file=sys.stderr)
        return None, []

    directory = output.get("directory")
    stems = output.get("stems", [])
    if not isinstance(stems, list):
        stems = []

    return directory, stems


def _render_to_profile_output(renderer, context, template_path,
                              raw_metadata, invoke_vars, invoke_path,
                              emit_format, root, tool_dir):
    """Render independently to the profile output directory.

    Instead of copying from adjacent, renders a fresh PDF to the
    profile output directory. Ensures render-out is always current
    regardless of the adjacent skip gate.

    Updates _RENDER.yaml manifest in the output directory.

    Returns (output_path, warning) tuple. output_path is the
    rendered path or None. warning is a message string or None.
    """
    directory, stems = _load_profile_output_config(tool_dir)
    if not directory or not stems:
        return None, None

    invoke_rel = str(invoke_path.relative_to(root))

    for entry in stems:
        if not isinstance(entry, dict):
            continue
        entry_invoke = entry.get("invoke", "")
        entry_stem = entry.get("stem")
        if entry_invoke == invoke_rel and entry_stem:
            # Resolve directory
            if directory.startswith("~"):
                out_dir = Path(directory).expanduser()
            else:
                out_dir = root / directory
            out_dir.mkdir(parents=True, exist_ok=True)

            filename = f"{entry_stem}.{emit_format}"
            dest = out_dir / filename

            # Resolve metadata with render-out stem as title default
            resolved_meta = _resolve_metadata(
                raw_metadata, invoke_vars, dest
            )
            render_emit_entry = {"metadata": resolved_meta}

            # Render independently
            renderer.render(
                context, template_path, dest, root,
                emit_entry=render_emit_entry,
            )

            # Update manifest
            _update_copy_manifest(out_dir, filename, invoke_rel)

            return dest, None

    # No matching stem entry. Silent skip: invokes without stem
    # entries (test fixtures, starter variants, or simply unconfigured)
    # do not produce render-out copies. Not a warning.
    return None, None


def _update_copy_manifest(out_dir, filename, invoke_rel):
    """Update _RENDER.yaml in the output directory.

    Maintains a list of rendered files with source invoke and
    timestamp. Replaces existing entries for the same filename.
    """
    import datetime

    import yaml

    manifest_path = out_dir / "_RENDER.yaml"

    # Load existing manifest
    entries = []
    if manifest_path.exists():
        with open(manifest_path) as f:
            loaded = yaml.safe_load(f)
        if isinstance(loaded, list):
            entries = loaded

    # Remove existing entry for this filename
    entries = [e for e in entries if e.get("file") != filename]

    # Add new entry
    entries.append({
        "file": filename,
        "source": invoke_rel,
        "rendered": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    })

    # Sort by filename for stable output
    entries.sort(key=lambda e: e.get("file", ""))

    # Write manifest
    with open(manifest_path, "w") as f:
        f.write("# _RENDER.yaml (auto-generated, do not edit)\n")
        f.write("# Tracks files produced by blueprint-render output config.\n\n")
        yaml.dump(entries, f, default_flow_style=False, sort_keys=False)


# -- pdftotext extraction ------------------------------------------------------


def _extract_pdftotext(pdf_path):
    """Extract text from a PDF and write a .txt file alongside it.

    Runs pdftotext, strips form feed characters from the output.
    Returns the .txt path, or None if pdftotext is not available.
    """
    import shutil
    import subprocess

    if shutil.which("pdftotext") is None:
        print("Warning: pdftotext not found; txt verification skipped",
              file=sys.stderr)
        return None

    txt_path = pdf_path.with_suffix(".txt")

    try:
        result = subprocess.run(
            ["pdftotext", str(pdf_path), str(txt_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"Warning: pdftotext failed for {pdf_path.name}: "
                  f"{result.stderr.strip()}", file=sys.stderr)
            return None

        # Strip form feed characters
        content = txt_path.read_text()
        txt_path.write_text(content.replace("\x0c", ""))

        return txt_path
    except (OSError, subprocess.SubprocessError) as e:
        print(f"Warning: pdftotext error for {pdf_path.name}: {e}",
              file=sys.stderr)
        return None


# -- Main run entry point -----------------------------------------------------


def run_invoke(invoke_path, root, tool_dir, emit_formats=None, force=False,
               output_scope="all", registry=None):
    """Execute a single invoke: resolve, map, render.

    Args:
        invoke_path: Path to the bp.invoke file.
        root: repo root Path.
        tool_dir: path to scripts/blueprint-render/.
        emit_formats: list of format keys to render, or None for all
            formats declared in the process emit section.
        force: if False, skip rendering when the output file already
            exists. If True, always re-render.
        output_scope: "all" (default, both adjacent and render-out),
            "adjacent" (bp.output only), or "renderout" (render-out only).
        registry: output of binding.discover(root), or None to
            discover here. Callers running many invokes pass one
            registry so the repo is walked once per run.

    Returns:
        Tuple of (rendered, skipped, warnings) where rendered and
        skipped are lists of output file paths, and warnings is a
        list of message strings. Rendered paths are newly produced
        files. Skipped paths are existing files that were not
        overwritten (force=False).

    Raises:
        RunError on any failure.
    """

    invoke_path = Path(invoke_path).resolve()

    # Discover the process file via binding key
    from lib.binding import parse_bp_filename, get_process_path, discover

    parsed = parse_bp_filename(invoke_path.name)
    if parsed is None:
        raise RunError(f"Not a valid bp filename: {invoke_path.name}")

    role, key, qualifier = parsed
    if role != "invoke":
        raise RunError(f"Expected bp.invoke file, got bp.{role}")

    if registry is None:
        registry = discover(root)
    process_path = get_process_path(registry, key)
    if process_path is None:
        raise RunError(f"No bp.process.{key} found for invoke {invoke_path.name}")

    # Load files
    invoke_data = load_yaml(invoke_path) or {}
    process_data = load_yaml(process_path)

    # Early exit: named-output invokes (index rollups) cannot
    # produce render-out copies. Skip the map stage entirely
    # to avoid wasted fn execution and I/O.
    output_config = process_data.get("output", "adjacent")
    output_is_named = (
        isinstance(output_config, dict) and "name" in output_config
    )
    if output_scope == "renderout" and output_is_named:
        return [], [], []

    # Stage 2: Map

    # Resolve imports
    imports = resolve_imports(invoke_data, tool_dir)

    # Extract var assignments (everything except import)
    invoke_vars = {k: v for k, v in invoke_data.items() if k != "import"}

    # Resolve profile: references
    invoke_vars = resolve_profile_refs(invoke_vars, imports)

    # Interpolate ${}
    invoke_vars = interpolate_vars(invoke_vars)

    # Execute the map
    context = execute_map(process_data["map"], invoke_vars, root)

    # Stage 3: Render
    rendered = []
    skipped = []
    warnings = []
    emit = process_data.get("emit", {})

    # Load run config for verify and output settings
    run_config = _load_run_config(tool_dir)
    do_pdftotext = (
        run_config.get("verify", {}).get("pdftotext", False)
    )

    if emit_formats is None:
        emit_formats = list(emit.keys())

    for fmt in emit_formats:
        if fmt not in emit:
            continue

        emit_entry = emit[fmt]
        template_path = emit_entry.get("template")
        render_path = emit_entry["render"]

        # Output routing: named overrides adjacent bp.output naming.
        # output_config and output_is_named computed before the map
        # stage (used for the renderout early exit).
        if output_is_named:
            output_path = invoke_path.parent / output_config["name"]
        else:
            output_path = _adjacent_output_path(invoke_path, fmt)

        # Resolve emit metadata (always: needed by both adjacent
        # and render-out renders)
        raw_metadata = emit_entry.get("metadata", {})
        if raw_metadata:
            resolved_meta = _resolve_metadata(
                raw_metadata, invoke_vars, output_path
            )
            emit_entry = {**emit_entry, "metadata": resolved_meta}
        elif fmt == "pdf":
            emit_entry = {
                **emit_entry,
                "metadata": {"title": output_path.stem},
            }

        # Always load renderer (needed by both adjacent and
        # render-out renders)
        renderer = _load_renderer(render_path, root)

        # Adjacent output (bp.output.* next to the invoke).
        # Gated by output_scope: skip when scope is "renderout".
        # Skip adjacent PDF renders when output exists.
        # WeasyPrint embeds non-deterministic metadata
        # (CreationDate, ModDate, trailer /ID) so even unchanged
        # content produces byte-different files, causing spurious
        # git diffs. Other formats (YAML) are deterministic and
        # always re-render.
        if output_scope in ("all", "adjacent"):
            if fmt == "pdf" and output_path.exists() and not force:
                skipped.append(output_path)
            else:
                renderer.render(
                    context, template_path, output_path, root,
                    emit_entry=emit_entry,
                )
                rendered.append(output_path)

        # Render-out: independent render to profile output directory.
        # Gated by output_scope: skip when scope is "adjacent".
        # Uses its own renderer.render() call instead of copying
        # from adjacent. Title default uses the render-out stem.
        if output_scope in ("all", "renderout") and not output_is_named:
            extra, warn = _render_to_profile_output(
                renderer, context, template_path,
                raw_metadata, invoke_vars,
                invoke_path, fmt, root, tool_dir,
            )
            if extra:
                rendered.append(extra)
                if fmt == "pdf" and do_pdftotext:
                    txt_path = _extract_pdftotext(extra)
                    if txt_path:
                        rendered.append(txt_path)
            if warn:
                warnings.append(warn)

    return rendered, skipped, warnings
