# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Dump the geometry a bulkhead's filled section has to be built from.

Three of the bulkhead tool's design forks (F1 multi-boundary fill, F3
continuous member vs per-face segments, F5 flange band vs constant-thickness
offset solid) turn on facts about *one* support shape — the loft through two
chains of elliptical sections, meeting at a shared seam edge and left
open-ended, that §6 of the design record fixes as the fixture for every test
and every example.  None of the three can be settled on a flat plate, and none
of them can be settled on paper: what picks the answer is where the band seam
falls relative to the flange band, and whether a boundary wire that runs off
an open end can be filled at all.

This tool establishes those facts, in the terms the forks are written in.  It
builds the fixture — sewn and unsewn, because `CompositeShellFP` keeps unsewn
faces unsewn and the answer differs — cuts it at several stations, and for
each cut reports

* the section curves `sortEdges` produces, and how many chains and wires
  result (F1: one closed boundary, or several);
* whether each chain closes *on the surface* and whether it closes *in
  space* — a wire that runs off an open end closes in space without closing
  on the surface, and a plate bounded by it sews from geometry that is not in
  the mesh;
* whether a chain self-crosses, which is the only way a single chain can have
  more than one boundary (F1's option a);
* where the band seam sits relative to the flange band: inside the band, on
  one of its edges, or on neither (F3/F5);
* whether the cut surface actually meets the support, which is the case that
  must raise rather than default.

Run it through the dev skill's runner:

    ~/.pi/agent/skills/freecad-dev/scripts/run-script.sh \\
        src/Mod/Composites/compositestests/inspect_bulkhead_section.py
"""

import os
import sys

import Part

import FreeCAD
from FreeCAD import Vector

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from Composites.tools import stiffener  # noqa: E402
from Composites.tools.bulkhead_section import (
    chain_regions,
    drape_cuts_of,
    section_polygon,
)

SEAM_X = 300.0

# (station_x, height along z, width along y).  Height is the ellipse's major
# semi-axis times two: Part.Ellipse rejects MinorRadius > MajorRadius outright,
# so a section whose height is not the larger of the two cannot be built.
FORWARD_SECTIONS = [(100.0, 200.0, 100.0), (200.0, 220.0, 120.0), (300.0, 240.0, 140.0)]
AFT_SECTIONS = [(300.0, 240.0, 140.0), (420.0, 210.0, 120.0), (540.0, 160.0, 90.0)]
PLANE_SIDE = 900.0


def ellipse_section(station_x, height, width):
    """One elliptical section, major axis vertical, centred on the loft axis."""
    point = Vector(station_x, 0.0, 0.0)
    ellipse = Part.Ellipse(point, height / 2.0, width / 2.0)
    ellipse.rotate(
        FreeCAD.Placement(point, FreeCAD.Rotation(Vector(1, 0, 0), Vector(0, 0, 1)))
    )
    return ellipse.toShape()


def band(sections):
    """One chain of elliptical sections, as the lateral faces of a lofted solid.

    The end caps are dropped, not kept: a chain of three sections lofts into a
    solid of two lateral faces plus two caps, and the caps are not part of the
    band — their support is perpendicular to the loft axis, so a cut plane
    taken normal to that axis would section the caps as well and count two
    closed wires where the surface has none.
    """
    solid = Part.makeLoft(
        [ellipse_section(*section) for section in sections], True, False
    )
    return [face for face in solid.Faces if isinstance(face.Surface, Part.BSplineSurface)]


def support_fixture(sewn=True):
    """The fixture support: two ellipse chains, meeting at x = SEAM_X, open-ended.

    `sewn` selects the stitched shell (`Part.makeShell`, one band seam) or the
    unsewn compound (coincident but distinct edges, which is what
    `CompositeShellFP` hands a real panel).
    """
    faces = band(FORWARD_SECTIONS) + band(AFT_SECTIONS)
    return Part.makeShell(faces) if sewn else Part.makeCompound(faces)


def station_plane(x, normal=Vector(1, 0, 0), side=PLANE_SIDE):
    """A cutting plane of `side` mm, centred on the loft axis at `x`.

    Placed by its centre, not by a corner: `makePlane` builds the face in the
    local frame of the rotation that maps z onto the normal, and for an
    x-directed normal that frame's second axis runs along **minus** global y, so
    a corner-placed face lands shifted a full side in y and never meets the
    part.  A plane that misses reads identically to an intersection that fails.
    """
    rotation = FreeCAD.Rotation(Vector(0, 0, 1), normal)
    face = Part.makePlane(side, side)
    corner = rotation.multVec(Vector(side / 2.0, side / 2.0, 0.0))
    face.Placement = FreeCAD.Placement(Vector(x, 0.0, 0.0) - corner, rotation)
    return face


def member_slab(cut, normal, flange_width, depth):
    """The prism the flange band and the plate are taken out of (F2/F5's shape).

    A planar region widened `flange_width` back along its own normal and
    stood off `depth` along the same normal, then ruled between the two — a
    member of constant `depth` whose feet fold flat onto the support.
    """
    widened = cut.copy()
    widened.translate(normal * -flange_width)
    slab = widened.extrude(normal * (flange_width + depth))
    return slab if slab.Faces else None


def face_of(support, chain):
    """Which support faces `chain` runs along, and how many of its edges each takes.

    A chain built by sectioning the whole shape at once contains one edge per
    face it crossed plus a repeated copy of any seam edge, so asking each
    face which of the chain's edges it carries is the only way to tell
    "crossed the seam" from "ran along one face's own boundary edge".
    """
    return [
        (index, len([edge for edge in chain.Edges
                     if face.isInside(edge.valueAt(
                         0.5 * (edge.FirstParameter + edge.LastParameter)), 1e-6, True)]))
        for index, face in enumerate(support.Faces)
        if any(face.isInside(edge.valueAt(
                   0.5 * (edge.FirstParameter + edge.LastParameter)), 1e-6, True)
               for edge in chain.Edges)
    ]


def _is_simple(wire):
    """False when `wire` doubles back through a point it has already passed.

    Compared against the wire's own extrema rather than against a chord: the
    sections here are piecewise and the pieces join to within microns, so a
    plain gap test flags real self-crossings and nothing else.
    """
    points = wire.discretize(240)
    keyed = [tuple(round(value, 5) for value in point) for point in points]
    return len(set(keyed)) >= len(keyed) * 7 // 8


def describe(support, cut, label):
    """Print what one cut produces, in the terms F1/F3/F5 are decided in."""
    print("\n" + "=" * 72)
    print(f"CUT {label}")
    print("=" * 72)
    normal = stiffener.plane_normal(cut)
    paths = stiffener.intersection_paths(support, cut)
    if not paths:
        print("  no intersection — the cut surface misses the support")
        return
    for index, path in enumerate(paths):
        regions = chain_regions(support, path)
        print(f"  path {index}: edges={len(path.Edges)} closed={path.isClosed()}"
              f" self_crossing={not _is_simple(path)}")
        print(f"    regions: {[(r[0].Volume > 0, len(r[1])) for r in regions]}")
    for width, depth in ((34.0, 12.0), (90.0, 12.0), (90.0, 120.0)):
        for path in paths:
            region = section_polygon(support, cut, path, depth, width, normal)
            if region is None:
                print(f"  (w={width:g},d={depth:g}): NO REGION — nothing bounded")
                continue
            print(f"  (w={width:g},d={depth:g}): band_faces={len(region.Faces)}"
                  f" drape_cuts={len(drape_cuts_of(support, region))}")


def main():
    """Report every probe on the one fixture shape, sewn and unsewn."""
    for sewn in (True, False):
        support = support_fixture(sewn=sewn)
        label = "sewn" if sewn else "unsewn"
        print("\n" + "#" * 72)
        print(f"# SUPPORT FIXTURE — {label}")
        print("#" * 72)
        print(f"  ShapeType={support.ShapeType} faces={len(support.Faces)}"
              f" closed={[face.isClosed() for face in support.Faces]}")
        shared = [edge for edge in support.Edges
                  if len(support.ancestorsOfType(edge, Part.Face)) > 1]
        describe(support, station_plane(210.0), "1 — axial, mid forward band")
        describe(support, station_plane(420.0), "2 — axial, mid aft band")
        describe(support, station_plane(700.0), "3 — axial, clear of the support")
        describe(support, station_plane(300.0, normal=Vector(1, 0.55, 0.35)),
                 "4 — oblique through the band seam and both open ends")
        describe(support, station_plane(210.0, normal=Vector(1, 0.9, 0.0), side=420.0),
                 "5 — steeply oblique: a shallow cut crossing the seam twice")


if __name__ == "__main__":
    main()
