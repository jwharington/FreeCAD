# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Dump the closed-ring stiffener web faces for nextdrape reproduction.

The ring stiffener web shells drape at ~0.26 coverage in the
``closed_ring_composite_shell`` example (known defect: the web faces are
self-closing non-periodic B-splines), while nextdrape's ``web_band``
testshape — a *periodic* analytic cylinder — solves 1.0.  This tool
captures the *actual* failing geometry, without paying for the full
composite drape: it builds the ring support and the ring stiffeners
geometry-only (no Laminate ⇒ no solver run), then dumps the web faces
as BREP plus a seed/params JSON, byte-identical in topology to what the
production path sweeps.

Surface characterisation (type, degrees, periodicity, UV bounds,
domain-edge coincidence) is printed here and mirrored C++-side by
``drape_cli --shapefile`` so both sides agree on what the solver sees.

Usage:
    FreeCADCmd -c "exec(open('.../inspect_ring_stiffener_web.py').read())"
    with env WEB_DUMP_DIR (default /tmp/fc-drape-dump).
"""

import json
import os

from Composites.compositeexamples.examples.stiffener import (
    _make_shape_object,
    _make_sketch,
    _z_profile,
)

_DUMP_DIR = os.environ.get("WEB_DUMP_DIR", "/tmp/fc-drape-dump")


def _characterise(face, label):
    """Print the surface topology facts the seam-stop law keys on."""
    bb = face.BoundBox
    print(
        f"{label}: area={face.Area:.3f}mm2 "
        f"bbox=({bb.XLength:.1f},{bb.YLength:.1f},{bb.ZLength:.1f})")
    if hasattr(face, "Surface"):
        s = face.Surface
    else:
        # web_faces entries can be Shells; characterise the first face inside
        s = face.Faces[0].Surface
    u0, u1, v0, v1 = face.ParameterRange
    print(
        f"{label}: type={type(s).__name__} "
        f"degrees=({getattr(s, 'UDegree', '?')},{getattr(s, 'VDegree', '?')}) "
        f"URange=({u0:.6g},{u1:.6g}) VRange=({v0:.6g},{v1:.6g}) "
        f"UPeriodic={getattr(s, 'isUPeriodic', lambda: '?')()} "
        f"VPeriodic={getattr(s, 'isVPeriodic', lambda: '?')()} "
        f"UClosed={getattr(s, 'isUClosed', lambda: '?')()} "
        f"VClosed={getattr(s, 'isVClosed', lambda: '?')()}"
    )
    # Self-closure probe: do the u-domain end edges coincide in 3D?
    n = 5
    d_max = 0.0
    for i in range(n):
        v = v0 + (v1 - v0) * i / (n - 1)
        p0 = face.valueAt(u0, v)
        p1 = face.valueAt(u1, v)
        d_max = max(d_max, (p0 - p1).Length)
    print(f"{label}: u-domain-edge max gap = {d_max:.6g} mm")


def main():
    import importlib

    import FreeCAD
    import Part

    m = importlib.import_module(
        "Composites.compositeexamples.examples.closed_ring_composite_shell")

    doc = FreeCAD.newDocument("RingStiffenerWebDump")
    geom = m.GEOMETRY
    ring = Part.makeCylinder(
        geom["radius_mm"], geom["length_mm"],
        FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), geom["sweep_deg"])
    support = doc.addObject("Part::Feature", "ClosedRingSupport")
    support.Shape = [
        f for f in ring.Faces
        if abs(f.Area - 2.0 * 3.141592653589793 * geom["radius_mm"]
               * geom["length_mm"]) < 1.0e-6
    ][0]

    from Composites.features.Stiffener import StiffenerFP

    os.makedirs(_DUMP_DIR, exist_ok=True)
    for name, z_centre in (("RingStiffenerA", 40.0),
                           ("RingStiffenerB", geom["length_mm"] - 40.0)):
        side = 3.0 * geom["radius_mm"]
        cut = Part.makePlane(
            side, side,
            FreeCAD.Vector(-side / 2.0, -side / 2.0, z_centre),
            FreeCAD.Vector(0, 0, 1))
        cut_surface = _make_shape_object(doc, f"{name}CutSurface", cut)
        profile = _make_sketch(doc, f"{name}Profile", _z_profile())
        stiffener = doc.addObject("Part::FeaturePython", name)
        # Geometry-only: no Laminate ⇒ no composite wiring, no drape solve.
        StiffenerFP(stiffener, support=support,
                    cut_surface=cut_surface, profile=profile)
        doc.recompute()
        web_faces = list(stiffener.Proxy.web_faces)
        print(f"{name}: {len(web_faces)} web faces, "
              f"areas={[round(f.Area, 2) for f in web_faces]}")
        for i, f in enumerate(web_faces):
            targets = f.Faces if isinstance(f, Part.Shape) and len(f.Faces) else [f]
            for k, sub in enumerate(targets):
                _characterise(sub, f"{name}_WebFace{i}.{k}")
        web_shape = Part.makeCompound(
            [sub for f in web_faces
             for sub in (f.Faces if len(getattr(f, 'Faces', [])) else [f])])
        brep_path = os.path.join(_DUMP_DIR, f"{name}_Web.brep")
        web_shape.exportBrep(brep_path)
        bb = web_faces[0].BoundBox
        seed = {
            "point": [bb.Center.x, bb.Center.y, bb.Center.z],
            "warp_direction": [1.0, 0.0, 0.0],
        }
        with open(os.path.join(_DUMP_DIR, f"{name}_Web.json"), "w") as fh:
            json.dump({"seed": seed, "params": {"pitch": 2.5}}, fh, indent=2)
        print(f"{name}: dumped web compound → {brep_path} (seed at face centre)")
    FreeCAD.closeDocument(doc.Name)


main()