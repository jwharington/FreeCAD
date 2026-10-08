## Testing discipline
- NEVER relax, widen, or remove test thresholds/tolerances/assertions to make a failing test pass.
- A failing test exposes a real bug in the code or the algorithm. Fix the code. If the algorithm is genuinely incapable of meeting the threshold, fix the algorithm — do not lower the bar.
- If a test threshold seems unrealistic, investigate WHY the code fails first. Only after exhausting all legitimate fixes should you consider whether the threshold itself is wrong — and even then, ask the user before changing it.
- This applies to all test frameworks (googletest, pytest, doctest, etc.) and all project types.

## Debugging philosophy
- When debugging, do not fix symptoms — discover and address the root cause.
- A fix that silences an error without solving the underlying problem will surface again elsewhere. Always trace the error chain back to its origin.

## No retry-until-success
- Never re-run a flaky operation until it passes — not by hand, not in a shell
  loop, and not in a test harness.
- A flaky failure is a serious bug, not an inconvenience. Retrying masks it,
  wastes the wall-clock that would have exposed it, and ships a defect that
  surfaces later as a broken build, a corrupt document, or a wrong answer.
- Diagnose the nondeterminism instead. Find what varies between runs —
  unordered iteration over a set or object-keyed dict, parallel execution in a
  boolean, a stale recompute, a cache key that changes while the geometry does
  not — and fix that.
- A retry is acceptable only where an external boundary genuinely requires it,
  and then it is an explicit, documented property of that boundary. It is
  never a route past a red result.

## FreeCAD object model
- FreeCAD's `ViewObject.Proxy.Object.Proxy` often returns a *different Python object* than the FeaturePython object listed in `doc.Objects` — they share the same underlying C++ pointer but have different Python identities (different `id()`).
- Never rely on `getattr(vobj.Proxy.Object, "SomeProp", None)` to find a property set on the FP object in `doc.Objects`. They are different Python objects.
- Instead, access properties through stable channels: the FP object from `doc.getObject(name)`, or store references in the backend where they survive recompute cycles.
- Do not code fragile workarounds to object accessing — if `getattr(obj, "prop")` returns `None`, investigate why the wrong object is being referenced rather than reaching for a workaround.

## MCP usage
- When working on an example or demonstration, prefer to edit a Python file within the `examples/` directory of the source rather than writing raw Python into MCP tool calls.
- Generally retain MCP tool calls to short commands for debugging, triggering loads, and quick inspections — not for building multi-step examples.
- This keeps examples reproducible, version-controllable, and easier for the user to rerun independently.

## Run-time configuration: no environment variables
- **Never use environment variables to pass run-time options** to a script,
  tool, or test. Run-time options are command-line arguments (argparse) or
  function parameters, and nothing else.
- The one permitted use is a **one-time installation variable**: where a
  build tree, SDK, or licence lives — something set once per machine and
  never varied per run (e.g. `FREECAD_ROOT`). If a value changes what a run
  computes, it is not an installation variable.
- Why the rule exists: an option read from the environment is invisible in
  the log, so a run cannot be reproduced from the command line; it leaks
  into every other script and test in the same shell, which makes results
  order-dependent and makes one run silently inherit another's settings.
- Do not name options with an env-var-style prefix in a docstring, help
  text, or log line as a leftover of the old scheme — describe the flag
  (`--case lc03`), not a variable that no longer exists.
- A script that must be launched through a helper still takes a real argv;
  if the helper cannot deliver one, fix the helper rather than routing the
  options through the environment. See
  `~/.pi/agent/skills/freecad-dev/scripts/run-script.sh`.
- In tests, configure by calling the same parser the CLI uses, or by
  setting the module's configuration directly. Never `monkeypatch.setenv`
  an option.

## Imports: at the top of the module, never inline
- **All imports go at the top of the file.** No `import` statements inside
  functions, and never `__import__("SomeModule").Thing()`.
- Why the rule matters here: FreeCAD scripts run headless in long jobs, and an
  import buried in a function fails at the deepest point of a 20-minute run —
  after the geometry is built and the deck is written — instead of at load.
  It also hides a dependency: the header stops saying what the module needs,
  so linters, `pyflakes`, and anyone reading the diff cannot see it.
- Do not use `__import__()` to dodge that. It has the same failure point with
  no static visibility at all, and it is how an import becomes invisible.
- If an inline import is there to dodge a circular import, that is a layering
  problem: fix the layering (move the shared piece into a third module), do
  not paper over it with a deferred import.
- Legitimate exceptions, both at module scope: an optional dependency guarded
  by `try`/`except ImportError` at the top with a flag set there, and a
  documented deferred import that genuinely breaks a cycle. Neither belongs
  mid-function as a habit.

## Source vs build paths
- **Master source**: `src/Mod/Composites/…` — edit here for all permanent changes.
- **Build output**: `build/debug/Mod/Composites/…` — this is what FreeCAD actually loads at runtime.
- The build directory is `build/debug/` (not `build/pixi-debug`).
- Changes in `src/` are not visible to FreeCAD until the module is rebuilt (or, for pure-Python files, until FreeCAD's `.pyc` cache is purged).
- When running examples via MCP, use the **build** path (e.g. `build/debug/Mod/Composites/compositeexamples/examples/cylindrical_panel_segment.py`).
- When editing example scripts, edit the **source** copy (`src/Mod/Composites/compositeexamples/examples/…`) unless the user explicitly asks you to modify the build copy for quick testing.
- After editing Python files in `src/`, either rebuild the module or purge the `.pyc` cache in `build/debug/Mod/Composites/` before FreeCAD picks up the changes.

## FreeCAD development
- **ALWAYS** refer to the `freecad-dev` skill (`~/.pi/agent/skills/freecad-dev/SKILL.md`) for all FreeCAD operations — starting the app, building, syncing, running tests, debugging.
- The skill contains the canonical paths, helper scripts, and common failure modes. Do not guess or invent FreeCAD commands.
- Key helper: `~/.pi/agent/skills/freecad-dev/scripts/start-freecad-mcp.sh [--kill] [--nowait] [--status]`
- To build: `cd /home/jmw/opt/FreeCAD && cmake --build build/debug -j2`
- MCP port: 9875. Verify with `ss -tlnp | grep 9875`.
- Log file: `/tmp/freecad.log` — check here when FreeCAD crashes or MCP doesn't respond.

## Workbench modification policy
- **No changes to workbenches other than Composites and Fem.** This includes
  core modules: never touch `src/Mod/Part/**` (including `src/Mod/Part/Gui/**`),
  `src/Mod/PartDesign`, `src/Mod/Sketcher`, `src/Gui`, `src/App`, or any other
  workbench outside `src/Mod/Composites` and `src/Mod/Fem`.
- Changes found there are illegal and must be undone immediately
  (`git checkout -- <paths>`), regardless of how small or well-meant they are.
- If a fix seems to require touching another workbench or core module, stop and
  raise it with the user first: the answer is almost always a fix at the
  Composites/Fem layer, or an upstream report — not a local hack to core.
