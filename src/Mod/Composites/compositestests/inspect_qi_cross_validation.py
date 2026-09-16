# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""QI-vs-draped membrane cross-validation (PRD §7.6).

Solves the same quasi-isotropic `[0/45/-45/90]s` flat plate twice at a
given mesh density — (a) the QI isotropic presentation and (b) the
conventional draped per-ply orthotropic export — under an in-plane
(membrane) load case, and reports the agreement.  This is the independent
check that breaks the self-reference of the QI-only bar comparison: the
draped export never consults the merged isotropic material, so agreement
confirms the homogeneous collapse.

The plate is flat deliberately: only an unsteered drape keeps variant (b)
on the same nominal layup as variant (a).  A curved mould would steer the
fibres and the two variants would no longer be the same stack.

Run headless (runpy keeps ``__file__`` valid inside FreeCADCmd):
    FreeCADCmd -c "import runpy; runpy.run_path(\\
        'src/Mod/Composites/compositestests/inspect_qi_cross_validation.py', \\
        run_name='__main__')"

Environment options: ``QI_XVAL_SIZES`` (comma list of gmsh clmax),
``QI_XVAL_JSON`` (output data path), ``QI_XVAL_HTML`` (output chart path).
"""

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import FreeCAD

from Composites.compositestests.test_quasi_iso_fem import (
    TestQuasiIsoFemCrossValidation,
)


def _install_identity_lcs():
    """Diagnostic: force the draped frame to a uniform (identity) frame.

    The backend derives the per-element frame from mesh triangle edges, so
    it changes with the mesh.  Replacing it with identity isolates how much
    of the QI-vs-draped gap is the frame versus the material representation.
    Runtime only — no file is modified, and nextdrape is untouched.
    """
    from Composites.features.CompositeShell import CompositeShellFP

    def identity_lcs(self, tris):
        pts = [t if hasattr(t, "x") else FreeCAD.Vector(*t) for t in tris]
        centroid = (pts[0] + pts[1] + pts[2]) / 3.0
        return FreeCAD.Placement(centroid, FreeCAD.Rotation())

    CompositeShellFP.get_drape_lcs = identity_lcs


def _max_axial(analysis):
    """Largest axial displacement (ux)."""
    result = next(
        obj for obj in analysis.Group
        if obj.isDerivedFrom("Fem::FemResultObject")
    )
    return max(float(v.x) for v in result.DisplacementVectors)


def _max_out_of_plane(analysis):
    """Largest |uz| — exposes bending the membrane load should not excite."""
    result = next(
        obj for obj in analysis.Group
        if obj.isDerivedFrom("Fem::FemResultObject")
    )
    return max(abs(float(v.z)) for v in result.DisplacementVectors)


def _solver_markers(solver_input):
    return {
        "orientation_block": "*ORIENTATION" in solver_input,
        "composite_orientation": "COMPOSITE,ORIENTATION=" in solver_input,
        "type_iso": "TYPE=ISO" in solver_input,
        "type_orthotropic": "TYPE=ORTHOTROPIC" in solver_input,
    }


def run_cross_validation(sizes, json_path, html_path):
    case = TestQuasiIsoFemCrossValidation("test_cross_validation_membrane")
    print(f"{'clmax':>8} {'nodes':>8} {'QI ux':>14} {'draped ux':>14} "
          f"{'dfree':>9} {'QI max ux':>14} {'draped max ux':>14} "
          f"{'dmax':>9}", flush=True)
    runs = []
    for size in sizes:
        tag = int(size) if size else 0
        qi_name = f"QIXvalQI{tag}"
        draped_name = f"QIXvalDraped{tag}"

        qi = case._build_and_solve(
            isotropic=True, name=qi_name, mesh_max_size=size
        )
        qi_max = _max_axial(qi["analysis"])
        qi_uz = _max_out_of_plane(qi["analysis"])
        qi_markers = _solver_markers(qi["solver_input"])

        # Same mesh as (a): keep (a)'s document open as the mesh template.
        draped = case._build_and_solve(
            isotropic=False, name=draped_name, mesh_template=qi["mesh_obj"]
        )
        draped_max = _max_axial(draped["analysis"])
        draped_uz = _max_out_of_plane(draped["analysis"])
        draped_markers = _solver_markers(draped["solver_input"])
        FreeCAD.closeDocument(draped_name)
        FreeCAD.closeDocument(qi_name)

        free_qi = qi["displacement"]
        free_draped = draped["displacement"]
        d_free = abs(free_qi - free_draped) / free_draped
        d_max = abs(qi_max - draped_max) / draped_max
        nodes = qi["mesh_node_count"]
        nodes_draped = draped["mesh_node_count"]
        # gmsh meshing is not bit-reproducible across the two separate
        # builds, so node counts can differ by a handful at fine densities;
        # report the mismatch rather than aborting on it.
        merge_note = ""
        if nodes != nodes_draped:
            merge_note = f" [mesh: draped={nodes_draped}]"

        print(f"{str(size):>8} {nodes:>8} {free_qi:>14.8e} "
              f"{free_draped:>14.8e} {d_free:>9.2%} {qi_max:>14.8e} "
              f"{draped_max:>14.8e} {d_max:>9.2%}{merge_note}", flush=True)
        print(f"         |uz|max QI={qi_uz:.6e} draped={draped_uz:.6e} "
              f"(draped uz/ux_free={draped_uz / free_draped:.4f})", flush=True)
        print(f"         QI markers:    {qi_markers}", flush=True)
        print(f"         draped markers: {draped_markers}", flush=True)

        runs.append({
            "size": size,
            "nodes": nodes,
            "nodes_draped": nodes_draped,            "free_qi": free_qi,
            "free_draped": free_draped,
            "d_free": d_free,
            "max_qi": qi_max,
            "max_draped": draped_max,
            "d_max": d_max,
            "uz_qi": qi_uz,
            "uz_draped": draped_uz,
            "qi_markers": qi_markers,
            "draped_markers": draped_markers,
        })

    _write_json(runs, json_path)
    _write_html(runs, html_path)
    return runs


def _write_json(runs, json_path):
    if not json_path:
        return
    Path(json_path).write_text(
        json.dumps({"runs": runs}, indent=2), encoding="utf-8"
    )
    print(f"wrote: {json_path}", flush=True)


def _write_html(runs, html_path):
    nodes = [r["nodes"] for r in runs]
    traces = [
        {"x": nodes, "y": [r["free_qi"] for r in runs],
         "mode": "lines+markers", "type": "scatter",
         "name": "avg ux (free edge) — QI isotropic (a)"},
        {"x": nodes, "y": [r["free_draped"] for r in runs],
         "mode": "lines+markers", "type": "scatter",
         "name": "avg ux (free edge) — draped per-ply (b)"},
        {"x": nodes, "y": [r["max_qi"] for r in runs],
         "mode": "lines+markers", "type": "scatter",
         "name": "max ux — QI isotropic (a)"},
        {"x": nodes, "y": [r["max_draped"] for r in runs],
         "mode": "lines+markers", "type": "scatter",
         "name": "max ux — draped per-ply (b)"},
    ]
    html = (
        "<html><head><meta charset='utf-8'>"
        "<script src='https://cdn.plot.ly/plotly-2.27.0.min.js'></script>"
        "</head><body><div id='c' style='width:1100px;height:700px'></div>"
        "<script>Plotly.newPlot('c'," + json.dumps(traces) + ","
        "{xaxis:{title:{text:'mesh nodes'},type:'linear'},"
        "yaxis:{title:{text:'displacement (mm)'},type:'linear'},"
        "title:{text:'QI isotropic (a) vs draped per-ply (b) — membrane "
        "cross-validation (F=1000 N)'}});</script></body></html>"
    )
    if html_path:
        Path(html_path).write_text(html, encoding="utf-8")
        print(f"wrote: {html_path}", flush=True)


def main():
    sizes_raw = os.environ.get("QI_XVAL_SIZES", "30,7.5,2,1")
    sizes = [float(v) if float(v) > 0 else None
             for v in sizes_raw.split(",")]
    if os.environ.get("QI_XVAL_IDENTITY", ""):
        _install_identity_lcs()
        print("[diag] draped frame forced to identity (runtime patch)",
              flush=True)
    json_path = os.environ.get("QI_XVAL_JSON", "")
    html_path = os.environ.get("QI_XVAL_HTML", "")
    run_cross_validation(sizes, json_path, html_path)


if __name__ == "__main__":
    main()
