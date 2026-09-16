# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""QI-vs-draped FEM export benchmark (PRD quasi_isotropic_laminate.md §8.6).

Times the CalculiX input *writing* (not the solve) for the QI isotropic
presentation against the conventional draped per-ply export across mesh
densities, and counts ``get_drape_lcs`` calls (which must be zero for a QI
shell).  Complements the soft §7.6 performance assertion with wall-clock
numbers.  Not a CI gate.

The scenario is the §7.6 flat plate; the PRD's "stiffener panel scenario"
still needs its multi-shell export wiring (handoff §0 item 1).

Run headless (runpy keeps ``__file__`` valid inside FreeCADCmd):
    FreeCADCmd -c "import runpy; runpy.run_path(\\
        'src/Mod/Composites/compositestests/inspect_qi_export_benchmark.py', \\
        run_name='__main__')"

Environment options: ``QI_BENCH_SIZES`` (comma list of gmsh clmax),
``QI_BENCH_JSON`` (output data path), ``QI_BENCH_HTML`` (output chart).
"""

import json
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import FreeCAD

from Composites.compositestests.test_quasi_iso_fem import (
    TestQuasiIsoFemCrossValidation,
)
from Composites.compositeexamples.examples._shell_example_common import (
    _write_ccx_input,
)


def _install_lcs_counter():
    """Count CompositeShell.get_drape_lcs calls (the per-element query)."""
    from Composites.features.CompositeShell import CompositeShellFP

    original = CompositeShellFP.get_drape_lcs
    counter = {"count": 0}

    def counted(self, tris):
        counter["count"] += 1
        return original(self, tris)

    CompositeShellFP.get_drape_lcs = counted
    return counter, original


def _time_export(case_result, counter):
    counter["count"] = 0
    start = time.perf_counter()
    inp, _fem = _write_ccx_input(
        case_result["analysis"],
        case_result["solver"],
        case_result["mesh_obj"],
    )
    elapsed = time.perf_counter() - start
    return elapsed, counter["count"], inp


def run_benchmark(sizes, json_path, html_path):
    case = TestQuasiIsoFemCrossValidation("test_cross_validation_membrane")
    counter, original = _install_lcs_counter()
    rows = []
    print(f"{'clmax':>8} {'nodes':>8} {'QI export (s)':>15} "
          f"{'draped (s)':>12} {'speedup':>9} {'QI calls':>9} "
          f"{'draped calls':>13}", flush=True)
    try:
        for size in sizes:
            tag = int(size) if size else 0
            qi_name = f"QIBenchQI{tag}"
            draped_name = f"QIBenchDraped{tag}"

            qi = case._build_and_solve(
                isotropic=True, name=qi_name, mesh_max_size=size, solve=False
            )
            draped = case._build_and_solve(
                isotropic=False, name=draped_name,
                mesh_template=qi["mesh_obj"], solve=False,
            )

            qi_s, qi_calls, _ = _time_export(qi, counter)
            draped_s, draped_calls, _ = _time_export(draped, counter)
            nodes = qi["mesh_node_count"]

            FreeCAD.closeDocument(draped_name)
            FreeCAD.closeDocument(qi_name)

            speedup = draped_s / qi_s if qi_s > 0 else float("nan")
            print(f"{str(size):>8} {nodes:>8} {qi_s:>15.6f} "
                  f"{draped_s:>12.6f} {speedup:>8.2f}x {qi_calls:>9} "
                  f"{draped_calls:>13}", flush=True)
            rows.append({
                "size": size, "nodes": nodes,
                "qi_export_s": qi_s, "draped_export_s": draped_s,
                "speedup": speedup,
                "qi_get_drape_lcs_calls": qi_calls,
                "draped_get_drape_lcs_calls": draped_calls,
            })
    finally:
        from Composites.features.CompositeShell import CompositeShellFP

        CompositeShellFP.get_drape_lcs = original

    if json_path:
        Path(json_path).write_text(
            json.dumps({"runs": rows}, indent=2), encoding="utf-8"
        )
        print(f"wrote: {json_path}", flush=True)
    if html_path:
        _write_html(rows, html_path)
        print(f"wrote: {html_path}", flush=True)
    return rows


def _write_html(rows, html_path):
    nodes = [r["nodes"] for r in rows]
    traces = [
        {"x": nodes, "y": [r["qi_export_s"] for r in rows],
         "mode": "lines+markers", "type": "scatter",
         "name": "QI isotropic export"},
        {"x": nodes, "y": [r["draped_export_s"] for r in rows],
         "mode": "lines+markers", "type": "scatter",
         "name": "draped per-ply export"},
    ]
    html = (
        "<html><head><meta charset='utf-8'>"
        "<script src='https://cdn.plot.ly/plotly-2.27.0.min.js'></script>"
        "</head><body><div id='c' style='width:1100px;height:700px'></div>"
        "<script>Plotly.newPlot('c'," + json.dumps(traces) + ","
        "{xaxis:{title:{text:'mesh nodes'},type:'log'},"
        "yaxis:{title:{text:'CalculiX input write (s)'},type:'log'},"
        "title:{text:'QI vs draped FEM export cost (§8.6)'}});"
        "</script></body></html>"
    )
    Path(html_path).write_text(html, encoding="utf-8")


def main():
    sizes_raw = os.environ.get("QI_BENCH_SIZES", "30,15,7.5,4,2")
    sizes = [float(v) if float(v) > 0 else None
             for v in sizes_raw.split(",")]
    run_benchmark(
        sizes,
        os.environ.get("QI_BENCH_JSON", ""),
        os.environ.get("QI_BENCH_HTML", ""),
    )


if __name__ == "__main__":
    main()
