# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Row-by-row trace of a ring sweep on a halved (L/R split) support.

Written for the LS8e skin L/R split job (handover
``HANDOVER-2026-09-30-skin-lr-split.md`` §4): with the fuselage skins cut
at the symmetry plane, the frame rings fail at ring 1 — a raw OCCT
``Offset on C0 curve`` is logged and the build raises ``no swept
geometry``, while direct calls on a plain compound of the halves produce
the clean closed two-arc row.  The handover's suspect is the chained
re-support (``StiffenerCompositeShell._resupport_panel``): with a halved
skin the remainder is a multi-piece shape, and a chained ring's sweep
then sections a gapped support.

This probe wraps the sweep stages of ``tools/stiffener.py`` **without
editing that file** (owner's instruction) and reports, per sweep:

* which support object drives the sweep (``fp.SupportBase`` name) and
  how many faces/pieces it has, with their areas and y-extents — the
  handover's "log fp.SupportBase.Name and the support's face count";
* every ``_sideways`` call: input row topology (edges, closure), which
  branch served it (translated / exact offset / sampled / creased), any
  OCCError a branch hit, and the output row topology;
* every locus handed to the loft (edges, closure), so the row whose
  topology breaks the loft is named.

Run against the design build:

    FUSELAGE_PROBE=1 FUSELAGE_RINGS=2 \\
        ~/.pi/agent/skills/freecad-dev/scripts/run-script.sh \\
        propeller/cad/FuselageV2.py

or standalone (a synthetic halved shell fixture)::

    ~/.pi/agent/skills/freecad-dev/scripts/run-script.sh \\
        src/Mod/Composites/compositestests/inspect_halved_support_sweep.py
"""

import functools
import traceback

import Part
from FreeCAD import Vector

from Composites.tools import stiffener as st


def describe_wire(wire) -> str:
    """One-line topology of a row wire: edges, closure, validity."""
    try:
        return (
            f"edges={len(wire.Edges)},closed={wire.isClosed()},"
            f"valid={wire.isValid()},len={wire.Length:.1f}"
        )
    except Exception as exc:
        return f"unreadable: {exc}"


def describe_support(shape) -> str:
    """One line per face of a support: area and y-extent (the L/R split)."""
    lines = [f"faces={len(shape.Faces)},area={shape.Area:.1f}"]
    for index, face in enumerate(shape.Faces, start=1):
        box = face.BoundBox
        lines.append(
            f"    face[{index}] area {face.Area:9.1f}  "
            f"y[{box.YMin:7.1f},{box.YMax:7.1f}]  "
            f"x[{box.XMin:7.1f},{box.XMax:7.1f}]  "
            f"z[{box.ZMin:7.1f},{box.ZMax:7.1f}]"
        )
    return "\n".join(lines)


def install_probe():
    """Wrap the sweep stages; returns nothing.  Idempotent."""
    if getattr(st, "_halved_probe_installed", False):
        return
    st._halved_probe_installed = True

    original_make_stiffener = st.make_stiffener
    original_sideways = st._sideways
    original_occt = st._occt_sideways
    original_sampled = st._sampled_sideways
    original_creased = st._creased_sideways
    original_loci = st._loci_over_plane

    @functools.wraps(original_make_stiffener)
    def probed_make_stiffener(support, cut_surface, profile, mirror=st.ProfileMirror()):
        print(
            f"[probe] make_stiffener: support\n{describe_support(support)}",
            flush=True,
        )
        return original_make_stiffener(support, cut_surface, profile, mirror)

    def probed_sideways(row, ordinate, normal):
        print(f"[probe] _sideways(ordinate={ordinate:g}) in: {describe_wire(row)}", flush=True)
        out = original_sideways(row, ordinate, normal)
        print(f"[probe] _sideways(ordinate={ordinate:g}) out: {describe_wire(out)}", flush=True)
        return out

    @functools.wraps(original_occt)
    def probed_occt(row, ordinate, normal):
        try:
            return original_occt(row, ordinate, normal)
        except Part.OCCError as error:
            print(f"[probe]   _occt_sideways raised OCCError: {error}", flush=True)
            raise

    @functools.wraps(original_sampled)
    def probed_sampled(row, ordinate, normal, per_edge=12):
        out = original_sampled(row, ordinate, normal, per_edge)
        print(f"[probe]   _sampled_sideways -> {describe_wire(out)}", flush=True)
        return out

    @functools.wraps(original_creased)
    def probed_creased(row, ordinate, normal):
        try:
            out = original_creased(row, ordinate, normal)
        except Part.OCCError as error:
            print(f"[probe]   _creased_sideways raised OCCError: {error}", flush=True)
            raise
        print(f"[probe]   _creased_sideways -> {describe_wire(out)}", flush=True)
        return out

    @functools.wraps(original_loci)
    def probed_loci(support, cut_surface, path, coords, normal):
        loci = original_loci(support, cut_surface, path, coords, normal)
        for key, locus in sorted(loci.items()):
            print(f"[probe] locus {key}: {describe_wire(locus)}", flush=True)
        return loci

    st.make_stiffener = probed_make_stiffener
    st._sideways = probed_sideways
    st._occt_sideways = probed_occt
    st._sampled_sideways = probed_sampled
    st._creased_sideways = probed_creased
    st._loci_over_plane = probed_loci


def probe_stiffener_execute(fp):
    """Report the support driving this stiffener's sweep (call pre-execute)."""
    base = getattr(fp, "SupportBase", None)
    support = getattr(fp, "Support", None)
    print(
        f"[probe] {fp.Name}: Support={getattr(support, 'Name', None)} "
        f"SupportBase={getattr(base, 'Name', None)}",
        flush=True,
    )
    shape = None
    if base is not None:
        shape = getattr(base, "Shape", None)
    elif support is not None:
        shape = getattr(support, "Shape", None)
    if shape is not None:
        print(f"[probe] {fp.Name}: sweep support\n{describe_support(shape)}", flush=True)


def main() -> int:
    """Standalone fixture: a halved cylindrical shell swept by a ring."""
    install_probe()
    shell = Part.makeCylinder(200.0, 500.0)
    face = shell.Faces[0]
    box = face.BoundBox
    big = 1000.0
    halves = []
    for y_min, y_max in ((box.YMin - 1.0, 0.0), (0.0, box.YMax + 1.0)):
        slab = Part.makeBox(big, y_max - y_min, big)
        slab.Placement.Base = Vector(box.XMin - 1.0, y_min, box.ZMin - 1.0)
        halves.extend(face.common(slab).Faces)
    support = Part.makeCompound(halves)
    print(f"[probe] fixture support\n{describe_support(support)}", flush=True)
    plane = Part.makePlane(800.0, 800.0, Vector(250.0, 0.0, 0.0), Vector(0.0, 0.0, 1.0))
    plane.rotate(Vector(250.0, 0.0, 0.0), Vector(0.0, 1.0, 0.0), 90.0)
    profile = [
        Part.LineSegment(Vector(34, 0, 0), Vector(0, 0, 0)).toShape(),
        Part.LineSegment(Vector(0, 0, 0), Vector(0, 34, 0)).toShape(),
        Part.LineSegment(Vector(0, 34, 0), Vector(34, 34, 0)).toShape(),
    ]
    try:
        sweep = st.make_stiffener(support, plane, profile, st.ProfileMirror(flip_y=True))
        print(f"[probe] sweep ok: shell faces={len(sweep.shell.Faces)}", flush=True)
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
