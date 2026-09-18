# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Sample a shell's drape frame on its own support faces.

Reports, per sample point, what each layer answers:

* ``lookup_uv``  — nextdrape's texture coordinate at the point (or None);
* ``lookup_lcs`` — nextdrape's fabric frame at the point (or None);
* ``get_drape_lcs`` — the shell's per-element frame (or None).

A point on the draped surface must yield a frame from ``lookup_lcs`` (its
lookup extrapolates from the nearest quad).  A None there is a bug, not a
coverage explanation.  No flat-lattice indices are involved anywhere.

Usage:
    FreeCADCmd -c "import runpy; runpy.run_path(\\
        'src/Mod/Composites/compositestests/inspect_drape_frame.py', \\
        run_name='__main__')"
    with env DRAPE_FRAME_ARGS, e.g.
    DRAPE_FRAME_ARGS="--source qi_panel"
    DRAPE_FRAME_ARGS="--source flat --angle 30"
"""

import argparse
import importlib
import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import FreeCAD
import Part

_X = FreeCAD.Vector(1.0, 0.0, 0.0)
_Y = FreeCAD.Vector(0.0, 1.0, 0.0)


def _sample(shell, label):
    backend = getattr(shell.Proxy, "_backend", None)
    print()
    print("=" * 78)
    print(f"{label}: {shell.Name}  (backend={type(backend).__name__ if backend else None})")
    print("=" * 78)
    if backend is None:
        print("  no drape backend")
        return
    print(f"  diagnostics: {backend.diagnostics()}")
    engine = getattr(backend, "_engine", None)
    if engine is None:
        print("  no engine")
        return

    box = shell.Support.Shape.BoundBox
    print("  lookup_uv over the panel plane (x across, y down):")
    for iy in range(8, 0, -1):
        y = box.YMin + (box.YMax - box.YMin) * iy / 8.0
        row = []
        for ix in range(1, 8):
            x = box.XMin + (box.XMax - box.XMin) * ix / 8.0
            uv = engine.lookup_uv([x, y, box.ZMin])
            row.append("  .   " if uv is None else f"{uv[0]:6.1f}")
        print(f"    y={y:6.1f} " + " ".join(row))

    for fidx, face in enumerate(shell.Support.Shape.Faces, 1):
        u0, u1, v0, v1 = face.ParameterRange
        for frac in (0.25, 0.5, 0.75):
            point = face.valueAt(
                u0 + (u1 - u0) * frac, v0 + (v1 - v0) * frac
            )
            xyz = [point.x, point.y, point.z]
            uv = engine.lookup_uv(xyz)
            frame = engine.lookup_lcs(xyz)
            plc = shell.Proxy.get_drape_lcs([point, point + _X, point + _Y])
            warp = None
            if plc is not None:
                warp = tuple(round(c, 4) for c in plc.Rotation.multVec(_X))
            print(f"  Face{fidx} frac={frac} point="
                  f"{tuple(round(c, 3) for c in point)}")
            print(f"      lookup_uv  : {uv}")
            print(f"      lookup_lcs : {None if frame is None else tuple(tuple(round(c, 4) for c in v) for v in frame)}")
            print(f"      get_drape_lcs warp: {warp}")


def build_flat(angle_deg, side=100.0):
    from Composites.features.CompositeShell import CompositeShellFP
    from Composites.features.HomogeneousLamina import HomogeneousLaminaFP
    from Composites.features.Laminate import LaminateFP
    from Composites.features.Rosette import RosetteFP

    doc = FreeCAD.newDocument("InspectDrapeFrame")
    support = doc.addObject("Part::Feature", "Plate")
    support.Shape = Part.makePlane(side, side)
    laminate = doc.addObject("Part::FeaturePython", "Laminate")
    LaminateFP(laminate)
    ply = doc.addObject("Part::FeaturePython", "Ply")
    HomogeneousLaminaFP(ply)
    ply.Angle = 0.0
    ply.Thickness = 0.5
    ply.Material = {
        "Name": "Carbon", "Density": "1750.0 kg/m^3",
        "PoissonRatioXY": "0.27", "PoissonRatioXZ": "0.27",
        "PoissonRatioYZ": "0.45", "ShearModulusXY": "5000 MPa",
        "ShearModulusXZ": "5000 MPa", "ShearModulusYZ": "3500 MPa",
        "YoungsModulusX": "135 GPa", "YoungsModulusY": "9.5 GPa",
        "YoungsModulusZ": "9.5 GPa",
    }
    laminate.Layers = [ply]
    shell = doc.addObject("Part::FeaturePython", "Shell")
    CompositeShellFP(shell, support)
    shell.Laminate = laminate
    rosette = doc.addObject("Part::FeaturePython", "Rosette")
    RosetteFP(rosette, support=(support, ["Face1"]))
    rosette.Angle = angle_deg
    shell.Rosette = rosette
    doc.recompute()
    return doc, shell


def build_qi_panel():
    module = importlib.import_module(
        "Composites.compositeexamples.examples.quasi_iso_stiffener_panel"
    )
    case = module.build(run_solver=False)
    return case["doc"], case["panel_shell"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("flat", "qi_panel"), default="flat")
    parser.add_argument("--angle", type=float, default=30.0)
    args = parser.parse_args(shlex.split(os.environ.get("DRAPE_FRAME_ARGS", "")))

    if args.source == "qi_panel":
        doc, shell = build_qi_panel()
    else:
        doc, shell = build_flat(args.angle)
    try:
        _sample(shell, f"panel shell ({args.source})")
    finally:
        FreeCAD.closeDocument(doc.Name)


if __name__ == "__main__":
    main()
