# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Mesh-convergence sweep for the QI isotropic presentation (§7.6).

Runs the QI FEM variant of the quasi-isotropic plate at a series of gmsh
characteristic lengths and reports the average displacement across the
free (loaded) edge per density.  The draped variant is intentionally
excluded (user directive 2026-09-16).

Run headless:
    FreeCADCmd src/Mod/Composites/compositestests/inspect_qi_convergence.py
"""

import math
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import FreeCAD

from Composites.compositestests.test_quasi_iso_fem import (
    TestQuasiIsoFemCrossValidation,
)


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
    """Convention-free ground truth from the generated CalculiX artifacts.

    Parses the inp (node coordinates, fixed node set, CLOAD block) and the
    frd (DISP records) directly — no FreeCAD result plumbing in the loop.
    Returns max |u|, avg |u| over the fixed nodes, and avg |u| over the
    free-edge (max-x) and clamp-edge (min-x) nodes.
    """
    import re

    inp_path = Path(solver_inp)
    stem = inp_path.stem
    inp = inp_path.read_text()
    frd = inp_path.with_suffix(".frd").read_text()

    nodes = {}
    for line in inp.splitlines():
        if line.startswith("*"):
            continue
        parts = line.split(",")
        if len(parts) == 4:
            try:
                nodes[int(parts[0])] = tuple(float(v) for v in parts[1:])
            except ValueError:
                continue

    m = re.search(rf"\*NSET,NSET={stem}_Fixed\n((?:\d+,\n)+)", inp)
    fixed = set(int(v) for v in re.findall(r"\d+", m.group(1))) if m else set()

    disp, in_disp = {}, False
    for line in frd.splitlines():
        if " -4  DISP" in line:
            in_disp = True
            continue
        if in_disp:
            if line.strip().startswith("-1"):
                nid = int(line[3:13])
                disp[nid] = tuple(float(line[13 + 12 * i:25 + 12 * i])
                                  for i in range(3))
            elif line.strip().startswith("-3"):
                in_disp = False

    def mag(v):
        return sum(c * c for c in v) ** 0.5

    xs = [x for x, _, _ in nodes.values()]
    free_x, clamp_x = max(xs), min(xs)
    free = [nid for nid, (x, _, _) in nodes.items() if abs(x - free_x) <= 1e-9]
    clamp = [nid for nid, (x, _, _) in nodes.items() if abs(x - clamp_x) <= 1e-9]
    fixed_present = [nid for nid in fixed if nid in disp]

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
    print(f"[gt] nodes={len(nodes)} disp={len(disp)} fixed={len(fixed)} "
          f"free={len(free)} clamp={len(clamp)} nan={n_nan} "
          f"free_x={free_x} clamp_x={clamp_x}")
    return {
        "max_u": max(mag(v) for v in disp.values()),
        "fixed_avg": avg_over(fixed_present),
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
          f"{'avg clamp':>15} {'CLOAD sum':>12}")
    results = []
    for size in sizes:
        name = f"QIConv{int(size) if size else 0}"
        r = case._build_and_solve(
            isotropic=True, name=name, mesh_max_size=size
        )
        result_obj = next(
            obj for obj in r["analysis"].Group
            if obj.isDerivedFrom("Fem::FemResultObject")
        )
        lengths = result_obj.DisplacementLengths
        mesh_nodes = r["mesh_obj"].FemMesh.Nodes
        max_x = max(v.x for v in mesh_nodes.values())
        min_x = min(v.x for v in mesh_nodes.values())
        span = max(abs(max_x), abs(min_x), 1.0)
        free_vals, clamp_vals = [], []
        for nid, vec in sorted(mesh_nodes.items()):
            if abs(vec.x - max_x) <= 1e-6 * span:
                free_vals.append(lengths[nid - 1])
            elif abs(vec.x - min_x) <= 1e-6 * span:
                clamp_vals.append(lengths[nid - 1])
        avg_free = sum(free_vals) / len(free_vals)
        avg_clamp = (sum(clamp_vals) / len(clamp_vals)) if clamp_vals else 0.0
        cload = _cload_total(r["solver_input"])
        gt = _ground_truth(r["solver_inp"])
        print(f"{str(size):>8} {r['mesh_node_count']:>8} {avg_free:>15.8e} "
              f"{max(lengths):>15.8e} {avg_clamp:>15.3e} {cload:>12.4f} "
              f"| frd: free {gt['free_avg']:.8e} clamp {gt['clamp_avg']:.3e} "
              f"fixed {gt['fixed_avg']:.3e} max {gt['max_u']:.8e} "
              f"cload {gt['cload']:.4f}")
        results.append({
            "size": size, "nodes": r["mesh_node_count"],
            "avg_free": avg_free, "max_all": max(lengths),
            "avg_clamp": avg_clamp, "cload": cload, "gt": gt,
        })
        if profile:
            profile_edges(result_obj, r["mesh_obj"], name)
        FreeCAD.closeDocument(name)

    traces = "".join(
        f"{{x:{[r['nodes'] for r in results]},"
        f"y:{[r[k] for r in results]},mode:'lines+markers',"
        f"name:'{label}',type:'scatter'}},"
        for k, label in (("avg_free", "avg free edge"),
                         ("max_all", "max all nodes"),
                         ("avg_clamp", "avg clamp edge"))
    )
    html = (
        "<html><head><script src='https://cdn.plot.ly/plotly-2.27.0.min.js'>"
        "</script></head><body><div id='c' style='width:1100px;height:700px'>"
        "</div><script>Plotly.newPlot('c',[" + traces.rstrip(',') + "],"
        "{xaxis:{type:'log',title:'mesh nodes'},"
        "yaxis:{type:'log',title:'displacement (mm)'},"
        "title:'QI presentation — mesh convergence'});</script>"
        "</body></html>"
    )
    with open(html_path, "w") as fh:
        fh.write(html)
    print(f"wrote: {html_path}")
    return results


def main():
    # Options come from the environment (FreeCADCmd intercepts unknown CLI
    # flags before the script sees them).
    sizes_raw = os.environ.get("QI_CONV_SIZES", "0,30,15,7.5,4,2")
    sizes = [float(v) if float(v) > 0 else None
             for v in sizes_raw.split(",")]
    html_path = os.environ.get("QI_CONV_HTML", "/tmp/qi-convergence.html")
    profile = os.environ.get("QI_CONV_PROFILE", "") != ""
    run_sweep(sizes, html_path, profile)


main()
