## Debugging philosophy
- When debugging, do not fix symptoms — discover and address the root cause.
- A fix that silences an error without solving the underlying problem will surface again elsewhere. Always trace the error chain back to its origin.

## FreeCAD object model
- FreeCAD's `ViewObject.Proxy.Object.Proxy` often returns a *different Python object* than the FeaturePython object listed in `doc.Objects` — they share the same underlying C++ pointer but have different Python identities (different `id()`).
- Never rely on `getattr(vobj.Proxy.Object, "SomeProp", None)` to find a property set on the FP object in `doc.Objects`. They are different Python objects.
- Instead, access properties through stable channels: the FP object from `doc.getObject(name)`, or store references in the backend where they survive recompute cycles.
- Do not code fragile workarounds to object accessing — if `getattr(obj, "prop")` returns `None`, investigate why the wrong object is being referenced rather than reaching for a workaround.

## MCP usage
- When working on an example or demonstration, prefer to edit a Python file within the `examples/` directory of the source rather than writing raw Python into MCP tool calls.
- Generally retain MCP tool calls to short commands for debugging, triggering loads, and quick inspections — not for building multi-step examples.
- This keeps examples reproducible, version-controllable, and easier for the user to rerun independently.

## Source vs build paths
- **Master source**: `src/Mod/Composites/…` — edit here for all permanent changes.
- **Build output**: `build/pixi-debug/Mod/Composites/…` — this is what FreeCAD actually loads at runtime.
- The build directory is populated by CMake during the build step. Changes in `src/` are not visible to FreeCAD until the module is rebuilt (or, for pure-Python files, until FreeCAD's `.pyc` cache is purged).
- When running examples via MCP, use the **build** path (e.g. `build/pixi-debug/Mod/Composites/compositeexamples/examples/cylindrical_panel_segment.py`).
- When editing example scripts, edit the **source** copy (`src/Mod/Composites/compositeexamples/examples/…`) unless the user explicitly asks you to modify the build copy for quick testing.
- After editing Python files in `src/`, either rebuild the module or purge the `.pyc` cache in `build/pixi-debug/Mod/Composites/` before FreeCAD picks up the changes.

The build environment is in ~/opt/FreeCAD/build/pixi-debug

To build FreeCAD:
    cd /home/jmw/opt/FreeCAD
    cmake --build build/pixi-debug --target FreeCAD -j8

To install FreeCAD into the local build prefix:
    cd /home/jmw/opt/FreeCAD/build/pixi-debug
    cmake --build . --target install -j8

Rebuild GUI resources when .ui files change

An MCP server for FreeCAD is available for when the user asks to see models in the GUI.

If MCP is not responding, first confirm FreeCAD is running (the RPC server starts with FreeCAD):
    pgrep -af "/home/jmw/opt/FreeCAD/build/pixi-debug/install/bin/FreeCAD"
    pgrep -af "/home/jmw/opt/FreeCAD/build/pixi-debug/bin/FreeCAD"

You can also verify the RPC listener directly:
    ss -ltnp | grep 9875

If nothing is running/listening, start FreeCAD first:
    cd /home/jmw/opt/FreeCAD/build/pixi-debug/install/bin
    ./FreeCAD

Syncing edited Python files to the runtime trees:

    After editing Python files under src/Mod/, do NOT manually cp them.
    Instead use the dedicated CMake copy targets:

    # Sync Assembly Python files → build/pixi-debug/Mod/Assembly  (used by FreeCADCmd)
    cd /home/jmw/opt/FreeCAD/build/pixi-debug
    cmake --build . --target AssemblyTests

    # Sync Fem Python files → build/pixi-debug/Mod/Fem  (used by FreeCADCmd)
    cd /home/jmw/opt/FreeCAD/build/pixi-debug
    cmake --build . --target FemScriptsTarget

    # Sync everything to install/Mod/  (used by the GUI FreeCAD)
    cd /home/jmw/opt/FreeCAD/build/pixi-debug
    cmake --build . --target install -j8

    To update both runtime trees in one step (Python-only changes, fast):
    cd /home/jmw/opt/FreeCAD/build/pixi-debug
    cmake --build . --target AssemblyTests FemScriptsTarget install -j4

Build/runtime note:
    FreeCADCmd in build/pixi-debug imports Python modules from build/pixi-debug/Mod.
    FreeCAD GUI launched from build/pixi-debug/install/bin/FreeCAD imports Python modules from build/pixi-debug/install/Mod.
    Use the CMake targets above (not cp) to keep both trees in sync.
