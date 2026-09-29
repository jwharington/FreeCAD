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
    """A plain ruled loft spanning exactly the frame section.

    No boolean ``common`` treatment: that was a workaround so the seat's
    rows (interior sections of a wider sleeve) would be offsettable, and it
    left the support face in a state the Boolean engine cannot split at all
    (measured: cutting it with the stiffener's faces returns nothing; the
    same cut on this plain loft returns the expected pieces).  Spanning
    exactly the frame section puts both rows on the face's *own* boundary
    sections, which a plain loft sections and offsets correctly.
    """
    outboard = ellipse_wire(cut_offset, height, width)
    inboard = ellipse_wire(cut_offset + FRAME_SECTION, height, width)
    return Part.makeLoft([outboard, inboard], False, True).Faces[0]


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

    # The feet-cut: cutting the stiffener's seat (foot sweep) out of the
    # support.  Timed and counted with its RESULT, so "is this slow" and
    # "does it produce a remainder" are both answered by data — log-message
    # counting cannot answer either (only Section announces itself; Cut /
    # Common / Fuse print nothing that distinguishes them here).
    original_remainders = stiffener_tools._support_remainders

    def support_remainders(support, stiffener):
        started = time.perf_counter()
        pieces = original_remainders(support, stiffener)
        _record(
            "_support_remainders (feet cut)",
            (f"support_faces={len(support.Faces)}", f"pieces={len(pieces)}"),
            time.perf_counter() - started,
        )
        return pieces

    stiffener_tools._support_remainders = support_remainders

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


def _dump_direct_quantities(doc, name):
    """Print what a contact-point measurement reads, at two Angle values.

    Written because a direct single-point residual came back flat in Angle
    (slope -0.0012 rad/deg against an expected 0.0175) and the cause has to
    come from the numbers, not from theory: this shows whether the LCS warp
    rotates, whether the two surface normals resolve, and what each side's
    signed angle does.
    """
    from Composites.features.TransferRosette import TransferRosetteFP
    from Composites.util.geometry_util import live_support_shape

    transfer = doc.getObject(name)
    if transfer is None:
        print(f"DIAG {name}: object not found", flush=True)
        return
    proxy = transfer.Proxy
    for angle in (0.0, 20.0):
        transfer.Angle = angle
        proxy.execute(transfer)
        lcs = transfer.LocalCoordinateSystem
        rotation = lcs.Placement.Rotation
        warp = rotation.multVec(FreeCAD.Vector(1.0, 0.0, 0.0))
        axis = FreeCAD.Vector(0.0, 0.0, 1.0)
        rotated = rotation.multVec(axis)
        point = lcs.Placement.Base
        master = transfer.MasterShell
        master_shape = live_support_shape(master)
        attachment_shape = live_support_shape(transfer.AttachmentShell)
        master_normal = TransferRosetteFP._surface_normal(master_shape, point)
        attachment_normal = TransferRosetteFP._surface_normal(
            attachment_shape, point
        )
        master_rotation = TransferRosetteFP._master_frame(master)
        master_warp = master_rotation.multVec(FreeCAD.Vector(1.0, 0.0, 0.0))
        # A fixed reference tangent, so the two angles are directly comparable.
        tangent = FreeCAD.Vector(1.0, 0.0, 0.0)
        print(
            f"DIAG {name} angle={angle:5.1f} "
            f"point=({point.x:.2f},{point.y:.2f},{point.z:.2f}) "
            f"lcs_warp=({warp.x:+.3f},{warp.y:+.3f},{warp.z:+.3f}) "
            f"lcs_z=({rotated.x:+.3f},{rotated.y:+.3f},{rotated.z:+.3f}) "
            f"master_warp=({master_warp.x:+.3f},{master_warp.y:+.3f},"
            f"{master_warp.z:+.3f})",
            flush=True,
        )
        for label, normal in (
            ("master", master_normal),
            ("attach", attachment_normal),
        ):
            if normal is None:
                print(f"DIAG   n_{label}=None", flush=True)
                continue
            print(
                f"DIAG   n_{label}=({normal.x:+.3f},{normal.y:+.3f},"
                f"{normal.z:+.3f})",
                flush=True,
            )
        if master_normal is not None:
            phi_m = TransferRosetteFP._axis_angle_about(
                master_rotation, tangent, master_normal
            )
            phi_a = TransferRosetteFP._axis_angle_about(
                rotation, tangent, master_normal
            )
            surface_u = TransferRosetteFP._surface_tangent(
                master_shape, point, master_normal
            )
            if surface_u is None:
                print("DIAG   surface_u=None", flush=True)
            else:
                u_m = TransferRosetteFP._axis_angle_about(
                    master_rotation, surface_u, master_normal
                )
                u_a = TransferRosetteFP._axis_angle_about(
                    rotation, surface_u, master_normal
                )
                print(
                    f"DIAG   surface_u=({surface_u.x:+.3f},"
                    f"{surface_u.y:+.3f},{surface_u.z:+.3f}) "
                    f"u_phi_m={u_m:+.6f} u_phi_a={u_a:+.6f} "
                    f"u_residual={u_a - u_m:+.6f} rad",
                    flush=True,
                )
            print(
                f"DIAG   phi_m={phi_m:+.6f} phi_a={phi_a:+.6f} "
                f"residual={phi_a - phi_m:+.6f} rad",
                flush=True,
            )


def _trace_point_solves():
    """Print every point-measurement the solve makes: the Angle it is at and
    the residual it read.  A residual that is 1:1 by hand but flat inside
    the solve shows up here directly."""
    from Composites.features.TransferRosette import TransferRosetteFP

    original = TransferRosetteFP._point_angle_error
    seen = {"n": 0}

    def wrapper(self, fp, point):
        residual = original(self, fp, point)
        if seen["n"] < 24:
            seen["n"] += 1
            lcs = getattr(fp, "LocalCoordinateSystem", None)
            warp = FreeCAD.Vector(0, 0, 0)
            if lcs is not None:
                warp = lcs.Placement.Rotation.multVec(
                    FreeCAD.Vector(1.0, 0.0, 0.0)
                )
            print(
                f"TRACE {fp.Name} angle={float(fp.Angle):+8.4f} "
                f"warp=({warp.x:+.4f},{warp.y:+.4f},{warp.z:+.4f}) "
                f"residual={residual:+.6f} rad",
                flush=True,
            )
        return residual

    TransferRosetteFP._point_angle_error = wrapper


def _measure_cut_variants(doc, name):
    """Time the support cut with different tools, to isolate why the
    feet-cut returns nothing.

    The flow cuts the support face with the whole swept shell.  The foot
    faces of that shell are *coplanar* with the support (they are the base
    rows, laid on it), which is the classic degenerate Boolean case.  This
    separates the tools: foot faces alone, web faces alone, and both.
    """
    from Composites.util.geometry_util import live_support_shape

    stiffener = doc.getObject(name)
    if stiffener is None:
        print(f"CUTDIAG {name}: not found", flush=True)
        return
    panel = stiffener.Support
    support = live_support_shape(panel)
    face = max(support.Faces, key=lambda f: f.Area)

    def child_shape(suffix):
        child = doc.getObject(f"{name}{suffix}")
        if child is None:
            return None
        return live_support_shape(child)

    foot = child_shape("_Foot")
    web = child_shape("_Web")
    for label, shape in (
        ("foot only (coplanar)", foot),
        ("web only (transverse)", web),
        ("foot + web (the flow)", stiffener.Shape),
    ):
        if shape is None:
            print(f"CUTDIAG {name} {label}: no shape", flush=True)
            continue
        started = time.perf_counter()
        try:
            result = face.cut(shape)
            pieces = len(result.Faces)
            area = result.Area
            note = f"faces={pieces} area={area:.1f}"
        except Exception as exc:
            note = f"EXCEPTION {str(exc)[:60]}"
        print(
            f"CUTDIAG {name} {label}: {note} "
            f"({time.perf_counter() - started:.2f}s) "
            f"[support face area={face.Area:.1f}]",
            flush=True,
        )

    # generalFuse: the splitting algorithm, not a subtraction.  The map
    # tells us which pieces came from the support itself (map[0]); no
    # extrusion, no solids, nothing converted.
    tools = [shape for shape in (foot, web) if shape is not None]
    if tools:
        started = time.perf_counter()
        try:
            result, mapping = face.generalFuse(tools)
            own = list(mapping[0]) if mapping else []
            own_faces = [f for piece in own for f in piece.Faces]
            own_area = sum(f.Area for f in own_faces)
            print(
                f"CUTDIAG {name} generalFuse: own_pieces={len(own)} "
                f"own_faces={len(own_faces)} own_area={own_area:.1f} "
                f"total_faces={len(result.Faces)} "
                f"({time.perf_counter() - started:.2f}s) "
                f"[support area={face.Area:.1f}]",
                flush=True,
            )
        except Exception as exc:
            print(
                f"CUTDIAG {name} generalFuse: EXCEPTION {str(exc)[:60]}",
                flush=True,
            )


def _measure_curve_split(doc, name, station_x, height, width):
    """Split the support with the seat's BOUNDARY CURVES."""
    from Composites.util.geometry_util import live_support_shape

    print(f"CUTDIAG {name} curve-split: start", flush=True)
    stiffener = doc.getObject(name)
    if stiffener is None:
        print(f"CUTDIAG {name} curve-split: no stiffener", flush=True)
        return
    support = live_support_shape(stiffener.Support)
    face = max(support.Faces, key=lambda f: f.Area)
    foot = doc.getObject(f"{name}_Foot")
    if foot is None:
        print(f"CUTDIAG {name} curve-split: no foot child", flush=True)
        return
    foot_shape = live_support_shape(foot)
    edges = [edge for f in foot_shape.Faces for edge in f.Edges]
    print(
        f"CUTDIAG {name} curve-split: {len(edges)} boundary edges, "
        f"support area={face.Area:.1f}",
        flush=True,
    )

    for label, call in (
        ("generalFuse(curves)", "fuse"),
        ("cut(curves)", "cut"),
    ):
        print(f"CUTDIAG {name} curve-split: calling {label}", flush=True)
        started = time.perf_counter()
        try:
            if call == "fuse":
                _result, mapping = face.generalFuse(edges)
                own = list(mapping[0]) if mapping else []
                pieces = [f for piece in own for f in piece.Faces]
            else:
                pieces = list(face.cut(edges).Faces)
            areas = [f.Area for f in pieces]
            spans = ", ".join(
                f"[{p.BoundBox.XMin:.2f},{p.BoundBox.XMax:.2f}]"
                for p in pieces
            )
            print(
                f"CUTDIAG {name} {label}: pieces={len(pieces)} "
                f"areas={[round(a, 1) for a in areas]} spans={spans} "
                f"({time.perf_counter() - started:.2f}s)",
                flush=True,
            )
        except Exception as exc:
            print(
                f"CUTDIAG {name} {label}: EXCEPTION {str(exc)[:70]}",
                flush=True,
            )
    # The curves the MODEL derives: the seat's boundary rows are the
    # support's own sections with the station planes, so they lie on the
    # support exactly.  These are the ones that must be cuttable.
    plane = doc.getObject(f"{name}Plane")
    if plane is not None and plane.Shape.Faces:
        seat_face = plane.Shape.Faces[0]
        try:
            normal = seat_face.normalAt(0.0, 0.0)
        except Exception:
            normal = seat_face.Surface.Axis
        rows = []
        for offset in (0.0, FRAME_SECTION):
            moved = seat_face.copy()
            moved.translate(normal * offset)
            rows.extend(support.section(moved).Edges)
        print(
            f"CUTDIAG {name} curve-split: model rows={len(rows)} "
            f"(sectioned at 0 and {FRAME_SECTION})",
            flush=True,
        )
        for label, call in (
            ("generalFuse(rows)", "fuse"),
            ("cut(rows)", "cut"),
            ("generalFuse(rows, fuzzy 1e-3)", "fuse"),
            ("generalFuse(rows, fuzzy 1e-2)", "fuse"),
            ("cut(rows, tol 1e-3)", "cut"),
        ):
            started = time.perf_counter()
            try:
                if call == "fuse":
                    fuzzy = 0.0
                    if "fuzzy 1e-3" in label:
                        fuzzy = 1e-3
                    elif "fuzzy 1e-2" in label:
                        fuzzy = 1e-2
                    _result, mapping = face.generalFuse(rows, fuzzy)
                    own = list(mapping[0]) if mapping else []
                    pieces = [f for piece in own for f in piece.Faces]
                else:
                    tolerance = 1e-3 if "tol 1e-3" in label else 0.0
                    pieces = list(face.cut(rows, tolerance).Faces)
                spans = ", ".join(
                    f"[{p.BoundBox.XMin:.2f},{p.BoundBox.XMax:.2f}]"
                    for p in pieces
                )
                print(
                    f"CUTDIAG {name} {label}: pieces={len(pieces)} "
                    f"areas={[round(f.Area, 1) for f in pieces]} "
                    f"spans={spans} ({time.perf_counter() - started:.2f}s)",
                    flush=True,
                )
            except Exception as exc:
                print(
                    f"CUTDIAG {name} {label}: EXCEPTION {str(exc)[:70]}",
                    flush=True,
                )
    # FreeCAD's own Slice: generalFuse with each tool wrapped in a compound
    # (its "prevent contamination" hack) and the base's pieces taken from the
    # map.  This is the primitive path the module should use.
    try:
        from BOPTools import SplitAPI
    except Exception as exc:
        print(f"CUTDIAG {name} slice: import failed {exc}", flush=True)
        return
    row_compound = Part.makeCompound(rows) if rows else None
    # (a) Settle the raw-vs-processed area difference: print what each face
    # actually is, and cut both with the seat.
    from Composites.util.geometry_util import live_support_shape

    ring_support = live_support_shape(stiffener.Support)
    ring_face = max(ring_support.Faces, key=lambda f: f.Area)
    wide_out = ellipse_wire(station_x - SLEEVE_MARGIN, height, width)
    wide_in = ellipse_wire(
        station_x + FRAME_SECTION + SLEEVE_MARGIN, height, width
    )
    wide_face = Part.makeLoft([wide_out, wide_in], False, True).Faces[0]
    for label, candidate in (
        ("ring support (plain loft)", ring_face),
        ("wide plain loft (margins)", wide_face),
    ):
        box = candidate.BoundBox
        print(
            f"CUTDIAG {name} {label}: area={candidate.Area:.1f} "
            f"faces={len(candidate.Faces)} edges={len(candidate.Edges)} "
            f"span[{box.XMin:.2f},{box.XMax:.2f}]",
            flush=True,
        )
        started = time.perf_counter()
        try:
            result = SplitAPI.slice(candidate, [foot_shape], "Split")
            pieces = list(result.Faces)
            spans = ", ".join(
                f"[{p.BoundBox.XMin:.2f},{p.BoundBox.XMax:.2f}]"
                for p in pieces
            )
            print(
                f"CUTDIAG {name} {label} cut by seat: pieces={len(pieces)} "
                f"areas={[round(p.Area, 1) for p in pieces]} "
                f"spans={spans} ({time.perf_counter() - started:.2f}s)",
                flush=True,
            )
        except Exception as exc:
            print(
                f"CUTDIAG {name} {label} cut by seat: EXCEPTION "
                f"{str(exc)[:60]}",
                flush=True,
            )
    for label, tools in (
        ("slice(foot faces)", [foot_shape]),
        ("slice(model rows)", [row_compound] if row_compound else []),
    ):
        if not tools:
            continue
        started = time.perf_counter()
        try:
            result = SplitAPI.slice(face, tools, "Split")
            pieces = list(result.Faces)
            spans = ", ".join(
                f"[{p.BoundBox.XMin:.2f},{p.BoundBox.XMax:.2f}]"
                for p in pieces
            )
            print(
                f"CUTDIAG {name} {label}: pieces={len(pieces)} "
                f"areas={[round(p.Area, 1) for p in pieces]} spans={spans} "
                f"({time.perf_counter() - started:.2f}s)",
                flush=True,
            )
        except Exception as exc:
            print(
                f"CUTDIAG {name} {label}: EXCEPTION {str(exc)[:70]}",
                flush=True,
            )


def _measure_slice_forms(doc, name):
    """Compare the tool-list forms for SplitAPI.slice on the ring support.

    My module change passed the meeting faces as a list of separate tools and
    the flow fell back to the bare subtraction (2.5 s instead of 0.01 s),
    so slice raised.  The earlier probe passed ONE tool that was a compound
    of faces.  This pins which form actually works.
    """
    from Composites.util.geometry_util import live_support_shape

    stiffener = doc.getObject(name)
    foot = doc.getObject(f"{name}_Foot")
    if stiffener is None or foot is None:
        return
    support = live_support_shape(stiffener.Support)
    face = max(support.Faces, key=lambda f: f.Area)
    foot_faces = list(live_support_shape(foot).Faces)
    meeting = [
        f
        for f in face.Faces
        if True
    ]  # placeholder, replaced below
    meeting = []
    for candidate in live_support_shape(foot).Faces:
        meeting.append(candidate)

    from BOPTools import SplitAPI

    forms = (
        ("[compound(foot faces)]", [Part.makeCompound(foot_faces)]),
        ("foot faces as separate tools", foot_faces),
        ("[stiffener shell]", [stiffener.Shape]),
    )
    for label, tools in forms:
        started = time.perf_counter()
        try:
            result = SplitAPI.slice(face, tools, "Split")
            pieces = list(result.Faces)
            print(
                f"CUTDIAG {name} slice {label}: pieces={len(pieces)} "
                f"areas={[round(p.Area, 1) for p in pieces]} "
                f"({time.perf_counter() - started:.2f}s)",
                flush=True,
            )
        except Exception as exc:
            print(
                f"CUTDIAG {name} slice {label}: EXCEPTION "
                f"{type(exc).__name__} {str(exc)[:60]} "
                f"({time.perf_counter() - started:.2f}s)",
                flush=True,
            )


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
    if args.draped:
        from Composites.features import TransferRosette as _tr
        _tr.debug = True
        _trace_point_solves()

    doc = FreeCAD.newDocument("ring_boolean_cost")
    if args.draped:
        laminate = _make_draped_laminate(doc, "PanelLaminate")
    else:
        laminate = _make_qi_laminate(doc, "FrameQILaminate")
    started = time.perf_counter()
    for index in range(args.rings):
        name = f"Ring{index}"
        station_x = -80.0 * index
        # The seat's outboard plane is the station itself: the sleeve spans
        # exactly the frame section, so the rows are its boundary sections.
        cut_x = station_x
        sleeve = sleeve_shape(station_x, args.height, args.width, cut_x)
        panel = _make_panel(doc, name, sleeve, laminate)
        ring_started = time.perf_counter()
        _make_ring(doc, name, panel, laminate, station_x, cut_x)
        print(f"{name}: {time.perf_counter() - ring_started:.1f}s", flush=True)
    _report(args.rings, time.perf_counter() - started)
    for index in range(args.rings):
        _measure_curve_split(
            doc, f"Ring{index}", -80.0 * index, args.height, args.width
        )
        _measure_slice_forms(doc, f"Ring{index}")
        _measure_cut_variants(doc, f"Ring{index}")
    if args.draped:
        for index in range(args.rings):
            _dump_direct_quantities(doc, f"Ring{index}_PanelFootTransfer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
