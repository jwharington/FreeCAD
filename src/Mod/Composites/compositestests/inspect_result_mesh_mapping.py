# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Does the frd reader put an expanded CalculiX mesh back onto the model mesh?

A layered COMPOSITE *SHELL SECTION makes CalculiX write the expanded shells to
the .frd no matter what OUTPUT is set to, so importing that file built a result
mesh several times the model (289,239 nodes against 35,383 in the measured
wing).  Every GUI ray pick then pays for that geometry.

The reader now prefers the analysis's own mesh when the frd's node set is a
strict superset, filtering the result rows to the nodes that mesh holds.  This
re-imports a saved document's frd against its analysis and reports both node
counts, so the mapping is a measurement and a regression can be seen.

Usage:

    ~/.pi/agent/skills/freecad-dev/scripts/run-script.sh \\
        src/Mod/Composites/compositestests/inspect_result_mesh_mapping.py \\
        --document /tmp/wing_clean.FCStd \\
        --frd /tmp/fcfem_6lntjgmu/WingPipelineCost_FEMMesh.frd \\
        --analysis WingPipelineCost_Analysis
"""

from __future__ import annotations

import argparse
import sys
import time

import FreeCAD


def _drop_existing_results(doc):
    """Remove result objects, their meshes and their pipelines before re-import."""
    results = [o for o in doc.Objects if o.isDerivedFrom("Fem::FemResultObject")]
    meshes = [o.Mesh for o in results if getattr(o, "Mesh", None) is not None]
    pipelines = [o for o in doc.Objects if o.isDerivedFrom("Fem::FemPostPipeline")]
    for obj in results + meshes + pipelines:
        doc.removeObject(obj.Name)
    doc.recompute()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--document", required=True, help="saved .FCStd holding the analysis")
    parser.add_argument("--frd", required=True, help="the frd to re-import")
    parser.add_argument("--analysis", required=True, help="analysis object name")
    parser.add_argument("--results-type", default="static")
    args = parser.parse_args(argv)
    # FreeCADCmd's buffered stdout is lost when the process exits unless it is
    # flushed, and this script's whole value is the lines it prints.
    sys.stdout.reconfigure(line_buffering=True)

    doc = FreeCAD.openDocument(args.document)
    analysis = doc.getObject(args.analysis)
    if analysis is None:
        raise SystemExit(f"no analysis {args.analysis} in {args.document}")

    model_meshes = [
        o for o in analysis.Group
        if o.isDerivedFrom("Fem::FemMeshObject") and not o.isDerivedFrom("Fem::FemMeshObjectPython")
    ]
    for mesh in model_meshes:
        print(f"[model] {mesh.Name} nodes={mesh.FemMesh.NodeCount}")

    _drop_existing_results(doc)

    from feminout import importCcxFrdResults

    start = time.perf_counter()
    importCcxFrdResults.importFrd(args.frd, analysis, "CCX_", args.results_type)
    elapsed = time.perf_counter() - start
    doc.recompute()

    result_meshes = [
        o for o in doc.Objects
        if o.isDerivedFrom("Fem::FemResultObject") and getattr(o, "Mesh", None) is not None
    ]
    for res in result_meshes:
        mesh = res.Mesh
        print(f"[result] {res.Name}.Mesh = {mesh.Name} nodes={mesh.FemMesh.NodeCount} "
              f"result rows={len(res.NodeNumbers)}")
        lengths = [abs(v) for v in res.DisplacementLengths]
        print(f"[result] max |u| = {max(lengths):.6g} over {len(lengths)} rows")
    print(f"[result] import + recompute {elapsed:.1f} s")

    model_nodes = max((m.FemMesh.NodeCount for m in model_meshes), default=0)
    result_nodes = max((r.Mesh.FemMesh.NodeCount for r in result_meshes), default=0)
    if model_nodes and result_nodes == model_nodes:
        print("VERDICT: the result mesh is the model mesh, not the expanded frd")
        return 0
    if result_nodes:
        print(f"VERDICT: result mesh {result_nodes} vs model {model_nodes} - not mapped")
        return 1
    print("VERDICT: no result mesh was produced")
    return 1


if __name__ == "__main__":
    sys.exit(main())
