# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Boolean-cost report for a ring-frame build.

A closed full-composite ring stiffener on a *lofted* sleeve is expensive
(minutes per ring at fuselage scale).  This tool answers where that time
goes and whether work is being repeated, rather than guessing:

1. wall time per ring, and for the whole build;
2. per Python call site of the boolean entry points the composite flow
   uses (``TransferRosetteFP._shared_edge`` and the sweep's
   ``intersection_paths``): number of calls, number of *distinct*
   argument pairs, and total seconds — so a cache that would pay off
   shows up as ``calls >> distinct``;
3. the OCCT operation mix, which the caller reads from the tool's own
   stderr (OCCT prints ``Building the result of <Op> operation``) —
   count those lines to see how much of the total is ``Section`` vs
   ``Cut``/``Common``.

Usage:
    ~/.pi/agent/skills/freecad-dev/scripts/run-script.sh \\
        src/Mod/Composites/compositestests/inspect_ring_boolean_cost.py
    with env RING_BOOL_ARGS, e.g.
        RING_BOOL_ARGS="--rings 2 --radius 30"
"""

import os
import shlex
import sys
import time
import traceback

import FreeCAD
import Part

# ── the geometry (a lofted elliptical sleeve, i.e. the real ring case) ──

FRAME_SECTION = 8.0
SLEEVE_MARGIN = 6.0
BOX_SPAN = 90.0


def ellipse_wire(station_x, height, width):
    point = FreeCAD.Vector(station_x, 0.0, 0.0)
    ellipse = Part.Ellipse(point, height / 2.0, width / 2.0)
    rotation = FreeCAD.Rotation(
        FreeCAD.Vector(1.0, 0.0, 0.0), FreeCAD.Vector(0.0, 0.0, 1.0)
    )
    ellipse.rotate(FreeCAD.Placement(point, rotation))
    return ellipse.toShape()


def sleeve_shape(station_x, height, width, cut_offset):
    """A ruled elliptical sleeve spanning the frame section plus a margin
    at each end, passed through a boolean ``common`` against the frame
    slab.

    The boolean is what makes the ring's two row planes offsettable in
    this OCCT build; without it the sweep cannot run at all on a lofted
    face.  It is also part of the cost being measured.

    The station plane sits *inside* the outboard margin, so both row
    planes cut the face transversally.
    """
    outboard = ellipse_wire(station_x, height, width)
    inboard = ellipse_wire(
        station_x + 2.0 * SLEEVE_MARGIN + FRAME_SECTION, height, width
    )
    long_face = Part.makeLoft([outboard, inboard], False, True).Faces[0]
    slab = Part.makeBox(
        FRAME_SECTION,
        BOX_SPAN,
        BOX_SPAN,
        FreeCAD.Vector(cut_offset, -BOX_SPAN / 2.0, -BOX_SPAN / 2.0),
    )
    return long_face.common(slab)


# ── instrumentation ────────────────────────────────────────────────────

_CALLS = {}


def _record(label, arguments, elapsed):
    entry = _CALLS.setdefault(label, {"calls": 0, "seconds": 0.0, "keys": {}})
    entry["calls"] += 1
    entry["seconds"] += elapsed
    entry["keys"][arguments] = entry["keys"].get(arguments, 0) + 1


def _keys_for(*shapes):
    """Three candidate cache keys for the same shapes.

    Recorded side by side so the report shows calls versus distinct keys
    for each scheme: a scheme whose distinct count collapses to the number
    of real argument pairs is usable for memoisation; one that stays near
    the call count is not.
    """
    from Composites.util.geometry_util import shape_fingerprint, shape_stamp

    codes, fingerprints, stamps = [], [], []
    for shape in shapes:
        try:
            codes.append(shape.hashCode())
        except Exception:
            codes.append(None)
        try:
            fingerprints.append(shape_fingerprint(shape))
        except Exception:
            fingerprints.append(None)
        try:
            stamps.append(shape_stamp(shape))
        except Exception:
            stamps.append(None)
    return {
        "hashCode": tuple(codes),
        "fingerprint": tuple(fingerprints),
        "stamp": tuple(stamps),
    }


def _caller() -> str:
    """The nearest frame outside the composite feature modules — i.e. who
    asked for the section."""
    for frame in reversed(traceback.extract_stack()[:-2]):
        base = os.path.basename(frame.filename)
        if base in ("TransferRosette.py", "inspect_ring_boolean_cost.py"):
            continue
        return f"{base}:{frame.lineno} {frame.name}"
    return "?"


def _wrap_static(cls, name, label):
    """Count and time a staticmethod in place."""
    original = getattr(cls, name)

    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            _record(f"{label} <- {_caller()}", None, time.perf_counter() - started)

    setattr(cls, name, staticmethod(wrapper))


def _wrap_method(cls, name, label):
    """Count and time an instance method in place."""
    original = getattr(cls, name)

    def wrapper(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original(self, *args, **kwargs)
        finally:
            _record(f"{label}", None, time.perf_counter() - started)

    setattr(cls, name, wrapper)


def _instrument():
    """Wrap the Python boolean entry points with counters and timers."""
    from Composites.features.TransferRosette import TransferRosetteFP
    from Composites.features.SeamCompositeLaminate import (
        SeamCompositeLaminateFP,
    )
    from Composites.tools import stiffener as stiffener_tools

    original_edge = TransferRosetteFP._shared_edge

    def shared_edge(master, attachment):
        started = time.perf_counter()
        try:
            return original_edge(master, attachment)
        finally:
            elapsed = time.perf_counter() - started
            caller = _caller()
            for scheme, key in _keys_for(master, attachment).items():
                _record(
                    f"_shared_edge [{scheme}] <- {caller}",
                    key,
                    elapsed if scheme == "stamp" else 0.0,
                )

    TransferRosetteFP._shared_edge = staticmethod(shared_edge)

    # The rest of the solve's per-evaluation cost: the brute-force
    # nearest-face normal per sample, and the edge sampling itself.
    _wrap_static(TransferRosetteFP, "_surface_normal", "_surface_normal")
    _wrap_static(TransferRosetteFP, "_sample_edge", "_sample_edge")
    # The validation and its gate, so their own share is separable from
    # the sections they call (rows nest: _validate_wiring includes its
    # _shared_edge calls).
    _wrap_method(
        SeamCompositeLaminateFP, "_validate_wiring", "_validate_wiring"
    )
    _wrap_method(
        SeamCompositeLaminateFP, "_input_fingerprint", "_input_fingerprint"
    )

    original_paths = stiffener_tools.intersection_paths

    def intersection_paths(support, cut_surface):
        started = time.perf_counter()
        try:
            return original_paths(support, cut_surface)
        finally:
            _record(
                "tools.stiffener.intersection_paths",
                _keys_for(support, cut_surface)["stamp"],
                time.perf_counter() - started,
            )

    stiffener_tools.intersection_paths = intersection_paths


# ── the build ──────────────────────────────────────────────────────────

def _make_qi_laminate(doc, name):
    from Composites.features.HomogeneousLamina import HomogeneousLaminaFP
    from Composites.features.Laminate import LaminateFP

    carbon = {
        "Name": "Carbon",
        "Density": "1750.0 kg/m^3",
        "PoissonRatioXY": "0.27",
        "PoissonRatioXZ": "0.27",
        "PoissonRatioYZ": "0.45",
        "ShearModulusXY": "5000 MPa",
        "ShearModulusXZ": "5000 MPa",
        "ShearModulusYZ": "3500 MPa",
        "YoungsModulusX": "135 GPa",
        "YoungsModulusY": "9.5 GPa",
        "YoungsModulusZ": "9.5 GPa",
    }
    laminate = doc.addObject("Part::FeaturePython", name)
    LaminateFP(laminate)
    plies = []
    for index, angle in enumerate((0.0, 45.0, -45.0, 90.0)):
        ply = doc.addObject("Part::FeaturePython", f"{name}_Ply{index}")
        HomogeneousLaminaFP(ply)
        ply.Angle = angle
        ply.Thickness = 0.5
        ply.Material = carbon
        plies.append(ply)
    laminate.Layers = plies
    laminate.Symmetry = "Even"
    laminate.IsotropicEquivalent = True
    return laminate


def _make_draped_laminate(doc, name):
    """A non-isotropic laminate, so the panel is draped and its transfers
    (and therefore the rosette solve) actually run."""
    from Composites.features.HomogeneousLamina import HomogeneousLaminaFP
    from Composites.features.Laminate import LaminateFP

    carbon = {
        "Name": "Carbon",
        "Density": "1750.0 kg/m^3",
        "PoissonRatioXY": "0.27",
        "PoissonRatioXZ": "0.27",
        "PoissonRatioYZ": "0.45",
        "ShearModulusXY": "5000 MPa",
        "ShearModulusXZ": "5000 MPa",
        "ShearModulusYZ": "3500 MPa",
        "YoungsModulusX": "135 GPa",
        "YoungsModulusY": "9.5 GPa",
        "YoungsModulusZ": "9.5 GPa",
    }
    laminate = doc.addObject("Part::FeaturePython", name)
    LaminateFP(laminate)
    plies = []
    for index, angle in enumerate((30.0, -30.0)):
        ply = doc.addObject("Part::FeaturePython", f"{name}_Ply{index}")
        HomogeneousLaminaFP(ply)
        ply.Angle = angle
        ply.Thickness = 0.5
        ply.Material = carbon
        plies.append(ply)
    laminate.Layers = plies
    return laminate


def _make_panel(doc, name, sleeve, laminate):
    from Composites.features.CompositeShell import CompositeShellFP

    support = doc.addObject("Part::Feature", f"{name}_Support")
    support.Shape = sleeve
    panel = doc.addObject("Part::FeaturePython", f"{name}Panel")
    CompositeShellFP(panel, support, laminate)
    return panel


def _make_ring(doc, name, panel, laminate, station_x, cut_x):
    from Composites.features.Stiffener import StiffenerFP

    plane = doc.addObject("Part::Feature", f"{name}Plane")
    box = Part.makeBox(
        1.0,
        BOX_SPAN,
        BOX_SPAN,
        FreeCAD.Vector(cut_x - 1.0, -BOX_SPAN / 2.0, -BOX_SPAN / 2.0),
    )
    plane.Shape = [
        face
        for face in box.Faces
        if abs(face.BoundBox.XLength) < 1e-9
        and abs(face.BoundBox.XMin - cut_x) < 1e-9
    ][0]

    profile = doc.addObject("Sketcher::SketchObject", f"{name}Profile")
    points = [
        FreeCAD.Vector(0.0, 0.0, 0.0),
        FreeCAD.Vector(FRAME_SECTION, 0.0, 0.0),
        FreeCAD.Vector(FRAME_SECTION, FRAME_SECTION, 0.0),
        FreeCAD.Vector(0.0, FRAME_SECTION, 0.0),
        FreeCAD.Vector(0.0, 0.0, 0.0),
    ]
    for start, end in zip(points, points[1:]):
        profile.addGeometry(Part.LineSegment(start, end), False)

    stiffener = doc.addObject("Part::FeaturePython", name)
    StiffenerFP(stiffener, support=panel, cut_surface=plane, profile=profile)
    stiffener.Laminate = laminate
    doc.recompute()
    return stiffener


def _parse_args(argv):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rings", type=int, default=2)
    parser.add_argument("--height", type=float, default=48.0)
    parser.add_argument("--width", type=float, default=36.0)
    parser.add_argument(
        "--draped",
        action="store_true",
        help="give the sleeve a non-isotropic (draped) laminate so the "
        "stiffener transfers, and therefore the rosette solve, run",
    )
    return parser.parse_args(shlex.split(argv))


def _report(rings, wall):
    # flush: FreeCADCmd tears down without flushing Python's stdout buffer
    # when a script calls sys.exit(), so unflushed report output is lost.
    print(f"\nsection-cost report: {rings} ring(s) in {wall:.1f}s wall", flush=True)
    print(f"{'call site':<44}{'calls':>7}{'distinct':>10}{'seconds':>10}", flush=True)
    for label, entry in sorted(
        _CALLS.items(), key=lambda item: -item[1]["seconds"]
    ):
        print(
            f"{label:<44}{entry['calls']:>7}"
            f"{len(entry['keys']):>10}{entry['seconds']:>10.2f}",
            flush=True,
        )
        repeated = {
            key: count
            for key, count in entry["keys"].items()
            if count > 1
        }
        for key, count in sorted(repeated.items(), key=lambda i: -i[1])[:5]:
            print(f"    repeated {count}x  key={key}", flush=True)


def main(argv=""):
    args = _parse_args(argv or os.environ.get("RING_BOOL_ARGS", ""))
    _instrument()

    doc = FreeCAD.newDocument("ring_boolean_cost")
    if args.draped:
        laminate = _make_draped_laminate(doc, "PanelLaminate")
    else:
        laminate = _make_qi_laminate(doc, "FrameQILaminate")
    started = time.perf_counter()
    for index in range(args.rings):
        name = f"Ring{index}"
        station_x = -80.0 * index
        cut_x = station_x + SLEEVE_MARGIN
        sleeve = sleeve_shape(station_x, args.height, args.width, cut_x)
        panel = _make_panel(doc, name, sleeve, laminate)
        ring_started = time.perf_counter()
        _make_ring(doc, name, panel, laminate, station_x, cut_x)
        print(f"{name}: {time.perf_counter() - ring_started:.1f}s", flush=True)
    _report(args.rings, time.perf_counter() - started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
