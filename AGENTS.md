
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