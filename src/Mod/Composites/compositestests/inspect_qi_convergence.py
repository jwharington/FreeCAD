# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Mesh-convergence sweep for the QI isotropic presentation (§7.6).

Runs the QI FEM variant of the quasi-isotropic plate at a series of gmsh
characteristic lengths and reports the average displacement across the
free (loaded) edge per density.  The draped variant is intentionally
excluded (user directive 2026-09-16).

Run headless (runpy keeps ``__file__`` valid inside FreeCADCmd):
    FreeCADCmd -c "import runpy; runpy.run_path(\
        'src/Mod/Composites/compositestests/inspect_qi_convergence.py', \
        run_name='__main__')"

Environment options: ``QI_CONV_SIZES`` (comma list of gmsh clmax), 
``QI_CONV_HTML`` (output chart path), ``QI_CONV_JSON`` (output data 
path), ``QI_CONV_PROFILE`` (per-edge dump).
"""

import json
import math
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import FreeCAD

from Composites.compositestests.test_quasi_iso_fem import (
    FORCE_N,
    PLATE_LENGTH,
    PLATE_WIDTH,
    TestQuasiIsoFemCrossValidation,
)
from Composites.mechanics.stack_model_type import StackModelType


def _equivalent_plate_cfg(laminate_fp):
    """Equivalent isotropic plate constants from the laminate model.

    Returns (E, nu, thickness) in MPa / dimensionless / mm.
    """
    model = laminate_fp.Proxy.get_model(laminate_fp)
    layer = model.get_layers(StackModelType.Smeared)[0]
    modulus = float(str(layer.material["YoungsModulus"]).split()[0])
    return modulus, float(layer.material["PoissonRatio"]), layer.thickness


def analytic_bar_displacement(E, thickness):
    """Uniaxial bar tip displacement: delta = F*L/(A*E).

    The plate is clamped on one short edge and pulled on the other; away
    from the clamp the membrane response is that of a bar of cross
    section width*thickness.
    """
    return FORCE_N * PLATE_LENGTH / (PLATE_WIDTH * thickness * E)


def _cload_total(solver_input):
    """Sum the *CLOAD magnitudes written to the solver input."""
    total = 0.0
    in_block = False
    for line in solver_input.splitlines():
        if line.startswith("*CLOAD"):
            in_block = True
            continue
        if in_block:
            if line.startswith("**"):
                continue
            if line.startswith("*"):
                break
            parts = line.split(",")
            if len(parts) >= 3:
                total += float(parts[2])
    return total


def _ground_truth(solver_inp):
    """Independent ground truth from the generated CalculiX artifacts.

    Parses the frd coordinate block and DISP block directly — no FreeCAD
    result plumbing in the loop.  Coordinates must come from the frd's
    own coordinate block: CalculiX writes a different node space there
    (shell data is expanded to 3-D, so ids/nodes do not match the inp).
    Returns max |u|, avg |u| over the free-edge (max-x) and clamp-edge
    (min-x) nodes, and the summed *CLOAD magnitude.
    """
    inp_path = Path(solver_inp)
    inp = inp_path.read_text()
    frd_lines = inp_path.with_suffix(".frd").read_text().splitlines()

    def _records_after(marker):
        """Map id -> value tuple from the first frd block after marker."""
        records = {}
        idx = 0
        while idx < len(frd_lines) and not frd_lines[idx].strip().startswith(marker):
            idx += 1
        idx += 1
        while idx < len(frd_lines):
            if frd_lines[idx].strip().startswith("-3"):
                break
            if frd_lines[idx].strip().startswith("-1"):
                line = frd_lines[idx]
                nid = int(line[3:13])
                records[nid] = tuple(
                    float(line[13 + 12 * k:25 + 12 * k]) for k in range(3)
                )
            idx += 1
        return records

    coords = _records_after("2C")
    disp = _records_after("-4  DISP")

    def mag(v):
        return sum(c * c for c in v) ** 0.5

    xs = [x for x, _, _ in coords.values()]
    free_x, clamp_x = max(xs), min(xs)
    free = [nid for nid, (x, _, _) in coords.items() if abs(x - free_x) <= 1e-9]
    clamp = [nid for nid, (x, _, _) in coords.items() if abs(x - clamp_x) <= 1e-9]

    def avg_over(ids):
        vals = [mag(disp[nid]) for nid in ids if nid in disp]
        return sum(vals) / len(vals) if vals else float("nan")

    cload = 0.0
    in_c = False
    for line in inp.splitlines():
        if line.startswith("*CLOAD"):
            in_c = True
            continue
        if in_c:
            if line.startswith("**"):
                continue
            if line.startswith("*"):
                break
            parts = line.split(",")
            if len(parts) >= 3:
                cload += float(parts[2])

    n_nan = sum(1 for v in disp.values() if any(math.isnan(c) for c in v))
    print(f"[gt] frd_coords={len(coords)} disp={len(disp)} "
          f"free={len(free)} clamp={len(clamp)} nan={n_nan} "
          f"free_x={free_x} clamp_x={clamp_x}", flush=True)
    return {
        "max_u": max(mag(v) for v in disp.values()),
        "fixed_avg": avg_over(clamp),
        "free_avg": avg_over(free),
        "clamp_avg": avg_over(clamp),
        "cload": cload,
    }


def profile_edges(result_obj, mesh_obj, tag):
    """Per-node displacement profile along the free and clamp edges.

    Coordinates come from the result object's own (compacted) mesh — the
    official triple NodeNumbers/DisplacementVectors/Mesh written by
    importCcxFrdResults.
    """
    disp = dict(zip(result_obj.NodeNumbers, result_obj.DisplacementVectors))
    nodes = result_obj.Mesh.FemMesh.Nodes
    xs = [v.x for v in nodes.values()]
    free_x, clamp_x = max(xs), min(xs)
    span = max(abs(free_x), abs(clamp_x), 1.0)
    for label, target in (("FREE", free_x), ("CLAMP", clamp_x)):
        print(f"[{tag}] {label} edge (x={target:.3f}):")
        print(f"{'node':>7} {'x':>10} {'y':>10} {'|u|':>14} {'ux':>14}")
        for nid, vec in sorted(nodes.items()):
            if abs(vec.x - target) <= 1e-6 * span:
                u = disp.get(nid)
                if u is None:
                    continue
                mag = (u.x**2 + u.y**2 + u.z**2) ** 0.5
                print(f"{nid:>7} {vec.x:>10.3f} {vec.y:>10.3f} "
                      f"{mag:>14.6e} {u.x:>14.6e}")


def run_sweep(sizes, html_path, profile=False):
    case = TestQuasiIsoFemCrossValidation("test_cross_validation_membrane")
    print(f"{'clmax':>8} {'nodes':>8} {'avg free edge':>15} {'max all':>15} "
          f"{'avg clamp':>15} {'CLOAD sum':>12} {'analytic':>12}", flush=True)
    results = []
    analytic = None
    for size in sizes:
        name = f"QIConv{int(size) if size else 0}"
        r = case._build_and_solve(
            isotropic=True, name=name, mesh_max_size=size
        )
        result_obj = next(
            obj for obj in r["analysis"].Group
            if obj.isDerivedFrom("Fem::FemResultObject")
        )
        # The result value lists are ordered by result.NodeNumbers and the
        # result mesh is compacted (importCcxFrdResults); indexing by mesh
        # node id (lengths[nid-1]) misassigns every node (handoff
        # 2026-09-16 lessons).
        disp = dict(zip(result_obj.NodeNumbers, result_obj.DisplacementLengths))
        mesh_nodes = result_obj.Mesh.FemMesh.Nodes
        max_x = max(v.x for v in mesh_nodes.values())
        min_x = min(v.x for v in mesh_nodes.values())
        span = max(abs(max_x), abs(min_x), 1.0)
        free_vals, clamp_vals = [], []
        for nid, vec in sorted(mesh_nodes.items()):
            if nid not in disp:
                continue
            if abs(vec.x - max_x) <= 1e-6 * span:
                free_vals.append(disp[nid])
            elif abs(vec.x - min_x) <= 1e-6 * span:
                clamp_vals.append(disp[nid])
        avg_free = sum(free_vals) / len(free_vals)
        avg_clamp = (sum(clamp_vals) / len(clamp_vals)) if clamp_vals else 0.0
        max_all = max(float(v) for v in disp.values())
        cload = _cload_total(r["solver_input"])
        gt = _ground_truth(r["solver_inp"])
        modulus, _, thickness = _equivalent_plate_cfg(r["laminate"])
        analytic = analytic_bar_displacement(modulus, thickness)
        print(f"{str(size):>8} {r['mesh_node_count']:>8} {avg_free:>15.8e} "
              f"{max_all:>15.8e} {avg_clamp:>15.3e} {cload:>12.4f} "
              f"{analytic:>12.8e} "
              f"| frd: free {gt['free_avg']:.8e} clamp {gt['clamp_avg']:.3e} "
              f"fixed {gt['fixed_avg']:.3e} max {gt['max_u']:.8e} "
              f"cload {gt['cload']:.4f} (E={modulus:.1f} MPa, "
              f"t={thickness:.3f} mm)", flush=True)
        results.append({
            "size": size, "nodes": r["mesh_node_count"],
            "avg_free": avg_free, "max_all": max_all,
            "frd_free": gt["free_avg"], "frd_max": gt["max_u"],
            "frd_clamp": gt["clamp_avg"], "avg_clamp": avg_clamp,
            "cload": cload,
            "analytic": analytic, "modulus": modulus,
            "thickness": thickness, "gt": gt,
        })
        if profile:
            profile_edges(result_obj, r["mesh_obj"], name)
        FreeCAD.closeDocument(name)

    _write_convergence_html(results, html_path, analytic)
    json_path = os.environ.get("QI_CONV_JSON", "")
    if json_path:
        Path(json_path).write_text(
            json.dumps(
                {
                    "analytic": analytic,
                    "runs": [
                        {k: v for k, v in r.items() if k != "gt"}
                        for r in results
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"wrote: {json_path}")
    print(f"wrote: {html_path}")
    return results


def _write_convergence_html(results, html_path, analytic):
    """Plotly convergence chart: linear axes, millimetres, analytic line."""
    nodes = [r["nodes"] for r in results]
    series = (
        ("avg free edge (frd ground truth)", [r["frd_free"] for r in results]),
        ("avg free edge (FreeCAD result)", [r["avg_free"] for r in results]),
        ("max |u| all nodes (frd)", [r["frd_max"] for r in results]),
        ("avg clamp edge (frd)", [r["frd_clamp"] for r in results]),
    )
    traces = [
        {"x": nodes, "y": values, "mode": "lines+markers",
         "type": "scatter", "name": label}
        for label, values in series
    ]
    analytic_y = [analytic] * len(nodes)
    traces.append({
        "x": nodes, "y": analytic_y, "mode": "lines", "type": "scatter",
        "name": f"analytic F*L/(A*E) = {analytic:.3e} mm",
        "line": {"dash": "dash", "color": "black"},
    })
    html = (
        "<html><head><meta charset='utf-8'>"
        "<script src='https://cdn.plot.ly/plotly-2.27.0.min.js'></script>"
        "</head><body><div id='c' style='width:1100px;height:700px'></div>"
        "<script>Plotly.newPlot('c'," + json.dumps(traces) + ","
        "{xaxis:{title:{text:'mesh nodes'},type:'linear'},"
        "yaxis:{title:{text:'displacement (mm)'},type:'linear'},"
        "title:{text:'QI isotropic presentation — mesh convergence "
        "(F=1000 N)'}});</script></body></html>"
    )
    Path(html_path).write_text(html, encoding="utf-8")


def main():
    # Options come from the environment (FreeCADCmd intercepts unknown CLI
    # flags before the script sees them).
    sizes_raw = os.environ.get("QI_CONV_SIZES", "0,30,15,7.5,4,2")
    sizes = [float(v) if float(v) > 0 else None
             for v in sizes_raw.split(",")]
    html_path = os.environ.get("QI_CONV_HTML", "/tmp/qi-convergence.html")
    profile = os.environ.get("QI_CONV_PROFILE", "") != ""
    run_sweep(sizes, html_path, profile)


if __name__ == "__main__":
    main()
