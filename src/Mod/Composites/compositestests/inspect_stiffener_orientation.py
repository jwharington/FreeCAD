# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Region map and per-transfer orientation dump for the stiffened panel.

``docs/handoff-2026-09-16.md`` §8.6 step 3 asks for a committed
diagnostic that dumps, per transfer rosette, the master frame, the
attachment frame, both support normals, the shared-edge tangent, and the
residual's slope in ``Angle`` — so a fix is designed from the measured
geometry of each joint rather than guessed.  §8.7 rule 3 asks for the
region map first: what objects exist, what surface each covers, what
seeds each, and which pairs must agree.

This tool prints both, for the joint the tests build (flat panel + Z
stiffener, ``TestStiffenerJointStack._make_joint``):

1. **Region map** — every composite shell of the joint: the faces of its
   support with their world normals, its rosette (angle, support
   sub-element, LCS frame in world axes), and the seed its drape actually
   takes (the rosette frame, or the centre-of-mass fallback when the
   frame's origin is not on the support).
2. **Global orientation** — the pairwise undirected-line offset between
   the shells' warp axes, and each warp's azimuth about global Z.  The
   joint's master / foot / attachment surfaces are required to agree
   here.
3. **Per transfer** — master and attachment frames, both support normals
   at the shared edge, the shared-edge tangent, the per-sample residual,
   and the residual's slope in ``Angle`` (measured, not assumed — the
   ``_solve`` docstring's "two free probes" claim is the defect §8.4).

Usage:
    FreeCADCmd -c "import runpy; runpy.run_path(\\
        'src/Mod/Composites/compositestests/inspect_stiffener_orientation.py', \\
        run_name='__main__')" > /tmp/stiffener-orientation.txt
    with env STIFF_ORIENT_ARGS, e.g.
    STIFF_ORIENT_ARGS="--source qi_example"
    STIFF_ORIENT_ARGS="--panel-angle 30 --stiffener-angle 30"
"""

import argparse
import importlib
import math
import os
import shlex
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import FreeCAD
import Part

_X_AXIS = FreeCAD.Vector(1.0, 0.0, 0.0)
_Z_AXIS = FreeCAD.Vector(0.0, 0.0, 1.0)

# Mirror of NextDrapeBackend._ON_SURFACE_TOL: the frame seed is only
# trusted when the LCS origin lies this close to the support.
_ON_SURFACE_TOL = 1e-4


def _vec(v):
    return f"({v.x:+.5f}, {v.y:+.5f}, {v.z:+.5f})"


def _line_offset_deg(a, b):
    """Undirected angle between two lines: parallel and anti-parallel agree."""
    if a.Length < 1e-12 or b.Length < 1e-12:
        return float("nan")
    cos = abs(a.dot(b)) / (a.Length * b.Length)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def _azimuth_deg(v):
    """Azimuth of a world vector about global Z, in (-180, 180]."""
    if v.Length < 1e-12:
        return float("nan")
    return math.degrees(math.atan2(v.y, v.x))


def _is_rosette(obj):
    from Composites.features.SeamCompositeLaminate import SeamCompositeLaminateFP

    return SeamCompositeLaminateFP._is_rosette(obj)


def _is_composite_shell(obj):
    from Composites.features.CompositeShell import is_composite_shell

    return is_composite_shell(obj)


def _is_transfer(obj):
    return (
        _is_rosette(obj)
        and getattr(obj, "MasterShell", None) is not None
        and hasattr(obj, "AttachmentShell")
    )


def _frame(rosette):
    """(base, X, Z) of a rosette's LCS in world axes, or (None, None, None)."""
    lcs = getattr(rosette, "LocalCoordinateSystem", None)
    if lcs is None:
        return None, None, None
    rotation = lcs.Placement.Rotation
    return (
        FreeCAD.Vector(lcs.Placement.Base),
        rotation.multVec(_X_AXIS),
        rotation.multVec(_Z_AXIS),
    )


def _support_label(rosette):
    """The rosette support as '<object>.<subelements>' (what frames it)."""
    support = getattr(rosette, "Support", None)
    if not support:
        return "<none>"
    obj, subs = support
    name = getattr(obj, "Name", repr(obj))
    return f"{name}.{list(subs) if subs else []}"


def _normal_at(shape, point):
    """The world normal of the face of *shape* nearest *point*."""
    vertex = Part.Vertex(point)
    best = None
    for face in shape.Faces:
        try:
            dist, _pts, _info = face.distToShape(vertex)
        except Exception:
            continue
        if best is None or dist < best[0]:
            u, v = face.Surface.parameter(point)
            best = (dist, face.normalAt(u, v))
    return best


def _faces(shape):
    """[(centre, normal)] per face of *shape* — the surface a shell covers."""
    out = []
    for face in shape.Faces:
        u0, u1, v0, v1 = face.ParameterRange
        u, v = (u0 + u1) / 2.0, (v0 + v1) / 2.0
        out.append((face.valueAt(u, v), face.normalAt(u, v)))
    return out


def dump_region_map(shells):
    """§8.7 rule 3: what exists, what it covers, and what seeds it."""
    from Composites.util.geometry_util import live_support_shape

    print("=" * 78)
    print("REGION MAP")
    print("=" * 78)
    for label, shell in shells:
        shape = live_support_shape(shell)
        box = shape.BoundBox
        print(f"\n{label}: {shell.Name}  ({shell.TypeId})")
        print(f"  support   : {getattr(shell.Support, 'Name', shell.Support)}")
        print(
            f"  bbox      : X[{box.XMin:.2f},{box.XMax:.2f}] "
            f"Y[{box.YMin:.2f},{box.YMax:.2f}] "
            f"Z[{box.ZMin:.2f},{box.ZMax:.2f}]  faces={len(shape.Faces)}"
        )
        for centre, normal in _faces(shape):
            print(f"  face      : centre={_vec(centre)} normal={_vec(normal)}")

        rosette = getattr(shell, "Rosette", None)
        if rosette is None:
            from Composites.features.CompositeShell import is_isotropic_shell

            if is_isotropic_shell(shell):
                print("  rosette   : <none> orientation-free (QI): no rosette, "
                      "no drape")
            else:
                print("  rosette   : <none> (centre-of-mass seed, warp = world X)")
            continue
        base, warp, normal = _frame(rosette)
        print(
            f"  rosette   : {rosette.Name} "
            f"({type(rosette.Proxy).__name__}) Angle={float(rosette.Angle):+.4f}"
        )
        print(f"  seed ref  : {_support_label(rosette)}")
        if base is None:
            print("  LCS       : <unplaced>")
            continue
        print(f"  LCS base  : {_vec(base)}")
        print(f"  LCS warp  : {_vec(warp)}  azimuth={_azimuth_deg(warp):+8.3f} deg")
        print(f"  LCS Z     : {_vec(normal)}")

        # The seed the drape actually takes: the rosette frame only when its
        # origin is ON the support, else the COM fallback at world X.
        dist, _pts, _info = shape.distToShape(Part.Vertex(base))
        on_surface = dist <= _ON_SURFACE_TOL
        taken = warp if on_surface else _X_AXIS
        print(
            f"  seed      : {'frame' if on_surface else 'COM FALLBACK'} "
            f"(base-to-support {dist:.3e} mm) warp={_vec(taken)} "
            f"azimuth={_azimuth_deg(taken):+8.3f} deg"
        )


def dump_global_orientation(shells):
    """The requirement: master / foot / attachment agree in global coords."""
    print()
    print("=" * 78)
    print("GLOBAL ORIENTATION (undirected warp line, degrees)")
    print("=" * 78)
    warps = []
    for label, shell in shells:
        rosette = getattr(shell, "Rosette", None)
        _base, warp, _normal = _frame(rosette) if rosette else (None, None, None)
        warps.append((label, warp))
        if warp is None:
            print(f"  {label:<10} <no frame — nothing to compare>")
        else:
            print(
                f"  {label:<10} warp={_vec(warp)} "
                f"azimuth={_azimuth_deg(warp):+8.3f} z={warp.z:+.5f}"
            )
    print()
    for i, (la, wa) in enumerate(warps):
        for lb, wb in warps[i + 1:]:
            if wa is None or wb is None:
                continue
            print(
                f"  offset {la} vs {lb}: "
                f"{_line_offset_deg(wa, wb):8.4f} deg"
            )


def _face_samples(face, count=3):
    """Sample points across a face's parametric range."""
    u0, u1, v0, v1 = face.ParameterRange
    pts = []
    for i in range(count):
        frac = (i + 0.5) / count
        u = u0 + (u1 - u0) * frac
        v = v0 + (v1 - v0) * 0.5
        pts.append(face.valueAt(u, v))
    return pts


def _median_quad_edge(backend):
    """Median lattice edge length of the drape solution (the real spacing).

    DrapePitch is the *requested* spacing; the actual quad size is what a
    nearest-quad lookup must be compared against, so derive the coverage
    gate from the solution itself.
    """
    import numpy as np

    try:
        r = backend._run_solve()
    except Exception:
        return None
    if not r.get("success"):
        return None
    pos = np.asarray(r["node_positions"])
    quads = r.get("quads", [])
    if not len(pos) or not quads:
        return None
    lens = []
    for q in quads:
        i0, i1, i2, i3 = [int(i) for i in q]
        for a, b in ((i0, i1), (i1, i2), (i2, i3), (i3, i0)):
            lens.append(float(np.linalg.norm(pos[a] - pos[b])))
    return float(np.median(lens))


def _face_samples(face, count=3):
    """Sample points across a face's parametric range."""
    u0, u1, v0, v1 = face.ParameterRange
    pts = []
    for i in range(count):
        frac = (i + 0.5) / count
        u = u0 + (u1 - u0) * frac
        v = v0 + (v1 - v0) * 0.5
        pts.append(face.valueAt(u, v))
    return pts


def dump_field(shells):
    """Sample the actual drape field on every support face.

    A shell's rosette frame is only the *seed*; the requirement is about the
    fibre direction each face actually carries, so query the backend's
    draped lattice (get_lcs_at_point) at several points per face and report
    the nearest-quad distance as a coverage precondition.
    """
    from Composites.util.geometry_util import live_support_shape

    print()
    print("=" * 78)
    print("DRAPE FIELD (sampled per support face via get_lcs_at_point)")
    print("=" * 78)
    for label, shell in shells:
        backend = getattr(shell.Proxy, "_backend", None)
        if backend is None:
            print(f"{label:<10} {shell.Name}: no drape backend (orientation-free)")
            continue
        shape = live_support_shape(shell)
        spacing = _median_quad_edge(backend)
        gate = (2.0 * spacing) if spacing else 6.0
        if spacing is not None:
            print(f"{label:<10} {shell.Name}: lattice spacing={spacing:.3f}mm "
                  f"coverage gate={gate:.3f}mm")
        for fidx, face in enumerate(shape.Faces, 1):
            for pidx, point in enumerate(_face_samples(face), 1):
                try:
                    plc = backend.get_lcs_at_point(
                        (point.x, point.y, point.z)
                    )
                except Exception as exc:  # pragma: no cover - diagnostic
                    print(f"{label:<10} {shell.Name} Face{fidx}.{pidx}: EXC {exc}")
                    continue
                if plc is None:
                    print(f"{label:<10} {shell.Name} Face{fidx}.{pidx} "
                          f"centre={_vec(point)}: NO FIELD")
                    continue
                warp = plc.Rotation.multVec(_X_AXIS)
                dist = (plc.Base - point).Length
                covered = dist <= gate
                print(f"{label:<10} {shell.Name} Face{fidx}.{pidx} "
                      f"at={_vec(point)} warp={_vec(warp)} "
                      f"azimuth={_azimuth_deg(warp):+8.3f} "
                      f"nearest_quad={dist:.3f}mm "
                      f"covered={'yes' if covered else 'NO'}")


def dump_transfer(rosette):
    """§8.6 step 3: everything a transfer fix must be designed from."""
    proxy = rosette.Proxy
    master = rosette.MasterShell
    attachment = rosette.AttachmentShell
    from Composites.util.geometry_util import live_support_shape

    print()
    print("-" * 78)
    print(f"TRANSFER {rosette.Name}  ({type(proxy).__name__})")
    print("-" * 78)
    print(f"  master      : {master.Name}")
    print(f"  attachment  : {attachment.Name}")
    print(f"  Angle       : {float(rosette.Angle):+.6f} deg")

    master_rotation = proxy._master_frame(master)
    master_warp = master_rotation.multVec(_X_AXIS)
    master_normal = master_rotation.multVec(_Z_AXIS)
    _base, att_warp, att_normal = _frame(rosette)
    print(f"  master frame: warp={_vec(master_warp)} "
          f"azimuth={_azimuth_deg(master_warp):+8.3f} Z={_vec(master_normal)}")
    print(f"  att frame   : warp={_vec(att_warp)} "
          f"azimuth={_azimuth_deg(att_warp):+8.3f} Z={_vec(att_normal)}")
    print(f"  frame offset: {_line_offset_deg(master_warp, att_warp):8.4f} deg")

    master_shape = live_support_shape(master)
    att_shape = live_support_shape(attachment)
    edge = proxy._shared_edge(master_shape, att_shape)
    if edge is None:
        print("  shared edge : <none>")
        return
    mid_param = edge.getParameterByLength(0.5 * edge.Length)
    mid = edge.valueAt(mid_param)
    tangent = FreeCAD.Vector(edge.tangentAt(mid_param))
    print(f"  shared edge : length={edge.Length:.3f} mid={_vec(mid)} "
          f"tangent={_vec(tangent)}")
    for label, shape in (("master", master_shape), ("attachment", att_shape)):
        found = _normal_at(shape, mid)
        if found is None:
            print(f"  {label:<10} normal at the shared edge: <not found>")
            continue
        dist, normal = found
        print(f"  {label:<10} normal at the shared edge: {_vec(normal)} "
              f"(face {dist:.2e} mm away)")

    samples = proxy._sample_edge(edge, 8)
    print("  per-sample residual (rad, folded into (-pi/2, pi/2]):")
    for point, tan in samples:
        phi_m = proxy._axis_angle(master_rotation, tan)
        phi_r = proxy._axis_angle(rosette.LocalCoordinateSystem.Placement.Rotation,
                                 tan)
        folded = (phi_r - phi_m + math.pi / 2.0) % math.pi - math.pi / 2.0
        print(f"    at {_vec(point)} tangent={_vec(tan)} "
              f"phi_master={math.degrees(phi_m):+8.3f} "
              f"phi_att={math.degrees(phi_r):+8.3f} "
              f"residual={math.degrees(folded):+8.3f} deg")

    # The slope, measured: perturb Angle and re-read the residual, exactly
    # as _solve's _residual does, with the recursion guard up.
    original = float(rosette.Angle)
    proxy._solving = True
    try:
        def residual_at(angle_deg):
            rosette.Angle = angle_deg
            proxy.execute(rosette)
            return proxy._edge_angle_error(rosette)

        step = 1.0
        r_minus = residual_at(original - step)
        r_plus = residual_at(original + step)
        slope = math.degrees((r_plus - r_minus) / (2.0 * step))
        print(f"  residual    : {math.degrees(residual_at(original)):+8.4f} deg "
              f"at Angle={original:+.4f}")
        print(f"  slope       : {slope:+8.4f} deg residual per deg Angle "
              f"(exact-linear solve assumes -1)")
    finally:
        rosette.Angle = original
        proxy.execute(rosette)
        proxy._solving = False


def build_case(panel_angle, stiffener_angle, source):
    """The narrow case under test: a flat panel carrying a Z stiffener.

    ``fixture`` is the joint ``TestStiffenerJointStack._make_joint`` builds
    (the web rosette keeps whatever angle the flow auto-created, so the
    stiffener's fabric is independent of the panel's).  ``example`` is
    ``compositeexamples.stiffener_composite_shell``, which lays the SAME
    fabric at ``panel_angle`` on both sides.  ``qi_example`` is
    ``compositeexamples.quasi_iso_stiffener_panel``: one draped panel of
    uniform orientation carrying a quasi-isotropic stiffener, so the
    attachment side is orientation-free and only master/foot can disagree.
    In all three the joint surfaces must agree in global coordinates.
    """
    if source in ("example", "qi_example"):
        module = (
            "quasi_iso_stiffener_panel"
            if source == "qi_example"
            else "stiffener_composite_shell"
        )
        example = importlib.import_module(
            f"Composites.compositeexamples.examples.{module}"
        )

        case = example.build()
        doc = case["doc"]
        shells = [
            ("master", case["panel_shell"]),
            ("foot", case["foot_shell"]),
            ("attachment", case["web_shell"]),
        ]
        shells = [(label, s) for label, s in shells if s is not None]
        transfers = [obj for obj in doc.Objects if _is_transfer(obj)]
        return None, shells, transfers

    from Composites.compositestests.test_stiffener_composite_shell import (
        TestStiffenerJointStack,
    )

    case = TestStiffenerJointStack("test_composite_build_creates_web_and_foot_shells")
    case.save_fcstd = False
    case.setUp()
    panel, stiffener = case._make_joint(panel_angle=panel_angle)
    if stiffener_angle is not None:
        stiffener.Rosette.Angle = stiffener_angle
        case.doc.recompute()
    doc = case.doc
    web = doc.getObject(f"{stiffener.Name}_Web")
    foot = doc.getObject(f"{stiffener.Name}_Foot")

    shells = [("master", panel)]
    if foot is not None:
        shells.append(("foot", foot))
    if web is not None:
        shells.append(("attachment", web))
    transfers = [obj for obj in doc.Objects if _is_transfer(obj)]
    return case, shells, transfers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel-angle", type=float, default=30.0)
    parser.add_argument(
        "--source",
        choices=("fixture", "example", "qi_example"),
        default="fixture",
        help="fixture: the joint the tests build; example: the "
             "stiffener_composite_shell example (same fabric both sides); "
             "qi_example: quasi_iso_stiffener_panel (draped panel + QI "
             "stiffener)",
    )
    parser.add_argument(
        "--stiffener-angle",
        type=float,
        default=None,
        help="override the web rosette angle after the build (default: leave "
             "whatever the flow auto-created)",
    )
    args = parser.parse_args(shlex.split(os.environ.get("STIFF_ORIENT_ARGS", "")))

    case, shells, transfers = build_case(
        args.panel_angle, args.stiffener_angle, args.source
    )
    print(f"source = {args.source}; panel angle = {args.panel_angle} deg; "
          f"shells = {[s.Name for _l, s in shells]}; "
          f"transfers = {[t.Name for t in transfers]}")
    try:
        dump_region_map(shells)
        dump_global_orientation(shells)
        dump_field(shells)
        for transfer in transfers:
            dump_transfer(transfer)
    finally:
        if case is not None:
            case.tearDown()
        elif FreeCAD.ActiveDocument is not None:
            FreeCAD.closeDocument(FreeCAD.ActiveDocument.Name)


if __name__ == "__main__":
    main()
