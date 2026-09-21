import FreeCAD
from Composites.compositeexamples import runner

res = runner.run("seam_composite_laminate", run_solver=False)
doc = res["doc"]
for o in doc.Objects:
    if "TexturePlan" in o.Name or "Shell" in o.Name:
        dv = getattr(o, "DrapeValid", None)
        sh = getattr(o, "Shape", None)
        print(o.Name, o.TypeId, "State=", o.State, "DrapeValid=", dv,
              "edges=", len(sh.Edges) if sh and not sh.isNull() else "null")
