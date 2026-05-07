
The build environment is in ~/opt/FreeCAD/build/pixi-debug

To build FreeCAD:
    cd /home/jmw/opt/FreeCAD
    cmake --build build/pixi-debug --target FreeCAD -j8

Rebuild GUI resources when .ui files change

An MCP server for FreeCAD is available for when the user asks to see models in the GUI.

Build/runtime note learned:
    FreeCADCmd in build/pixi-debug imports Python modules from build/pixi-debug/Mod, not directly from src/Mod.
    A regular CMake build of target FreeCAD may not refresh every edited Python file under build/pixi-debug/Mod.
    If a Python-side FEM change is not reflected at runtime, copy the edited file(s) from src/Mod/... to build/pixi-debug/Mod/... before running focused tests.


