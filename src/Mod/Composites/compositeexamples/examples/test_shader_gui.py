#!/usr/bin/env python3
"""Build conical panel and dump shader state to /tmp/shader_state.json."""
import sys, json
sys.path.insert(0, '/home/jmw/opt/FreeCAD/build/pixi-debug/Mod/Composites')
from compositeexamples.examples.conical_panel_segment import build

result = build(run_solver=False)
shell = result['feature_stack']['shell']

state = {
    "DrapeValid": shell.DrapeValid,
    "QualityPass": shell.QualityPass,
    "DrapeQuality": shell.DrapeQuality,
}

# Try GUI access
try:
    vobj = shell.ViewObject
    state["DisplayMode"] = vobj.DisplayMode
    state["ShaderActive"] = vobj.Proxy.Active
    
    if vobj.Proxy.Active and hasattr(vobj.Proxy, 'grid_shader'):
        gs = vobj.Proxy.grid_shader
        state["HasShaderProgram"] = gs.shaderProgram is not None
        state["HasCoordBinding"] = gs.coord_binding is not None
        
        if hasattr(gs, 'root') and gs.root:
            nc = gs.root.getChildren().getLength()
            state["RootChildrenCount"] = nc
            children = []
            for i in range(min(nc, 15)):
                c = gs.root.getChild(i)
                if c:
                    children.append(c.getTypeId().getName())
            state["RootChildren"] = children
except Exception as e:
    state["GUIError"] = str(e)

with open('/tmp/shader_state.json', 'w') as f:
    json.dump(state, f, indent=2)

print(json.dumps(state, indent=2))
print("Written to /tmp/shader_state.json")
