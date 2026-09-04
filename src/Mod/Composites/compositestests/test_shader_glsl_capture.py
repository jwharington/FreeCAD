#!/usr/bin/env python3
"""Diagnostic: capture Coin3D GLSL shader compile/link warnings.

Builds the conical panel, switches to a 3D view, forces renders so Coin
compiles/links the GLSL program, then reads back the Coin warnings Coin
emitted during the GL traversal. This is objective, machine-checkable
evidence of shader program status (no visual inspection).

Coin routes its warnings to the FreeCAD log. We truncate the log before
the render and classify the lines Coin wrote during it.

Output is printed as a JSON report and written to /tmp/shader_glsl_report.json.
"""
import json
import os

import FreeCAD
import FreeCADGui

LOG = "/tmp/freecad.log"


def _classify(line: str):
    low = line.lower()
    if "shader" in low or "glsl" in low or "program" in low or "uniform" in low or "parameter" in low:
        return "glsl"
    if "polygon" in low or "face" in low or "normalcache" in low or "too few points" in low:
        return "geometry"
    if "material" in low or "lazy" in low or "diffuse" in low or "index" in low:
        return "material"
    return "other"


def run():
    for d in list(FreeCAD.listDocuments()):
        FreeCAD.closeDocument(d)

    # Truncate the log so we only capture messages from this run.
    try:
        open(LOG, "w").close()
    except OSError:
        pass

    from Composites.compositeexamples.examples import conical_panel_segment
    result = conical_panel_segment.build(doc=None, run_solver=False)
    shell = result["feature_stack"]["shell"]
    vobj = shell.ViewObject
    gs = vobj.Proxy.grid_shader

    structural = {
        "ShaderActive": bool(vobj.Proxy.Active),
        "_attached": bool(getattr(gs, "_attached", False)),
        "_coin_geo": str(gs._coin_geo.getName()) if getattr(gs, "_coin_geo", None) else None,
        "grp_children": int(gs.grp.getNumChildren()) if gs and gs.grp else 0,
        "num_shader_objects": int(gs.shaderProgram.shaderObject.getNum()) if gs and gs.shaderProgram else 0,
    }

    # Switch to a 3D view and force renders so Coin compiles/links the program.
    view = None
    try:
        view = FreeCADGui.ActiveDocument.ActiveView
    except Exception:
        pass
    rendered = False
    if view is not None:
        try:
            view.viewIsometric()
        except Exception:
            pass
        for _ in range(3):
            try:
                view.fitAll()
                view.redraw()
                rendered = True
            except Exception:
                pass

    # Read back Coin messages emitted during the render.
    messages = []
    if os.path.exists(LOG):
        with open(LOG, "r", errors="replace") as f:
            for line in f:
                low = line.lower()
                if "coin" in low and ("warning" in low or "error" in low):
                    messages.append(line.strip())

    classified = {"glsl": [], "geometry": [], "material": [], "other": []}
    for m in messages:
        classified[_classify(m)].append(m)

    report = {
        "structural": structural,
        "render_forced": rendered,
        "coin_message_count": len(messages),
        "glsl_messages": classified["glsl"],
        "geometry_warnings": classified["geometry"],
        "material_warnings": classified["material"],
        "other": classified["other"],
    }
    with open("/tmp/shader_glsl_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("SHADER_GLSL_REPORT " + json.dumps(report, indent=2))


if __name__ == "__main__":
    run()
