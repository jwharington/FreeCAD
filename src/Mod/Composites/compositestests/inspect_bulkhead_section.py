# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Dump the geometry a bulkhead's filled section has to be built from.

Three of the bulkhead tool's design forks — multi-boundary fill, continuous
member vs per-face segments, and flange band vs constant-thickness offset
solid — turn on facts about *one* support shape: the loft through two chains of
elliptical sections that §6 of the design record fixes as the fixture for every
test and every example.  None of the three can be settled on a flat plate, and
none of them can be settled on paper: what picks the answer is where the band
seam falls relative to the flange band, and whether a boundary wire that runs
off an open end can be filled at all.

So this tool establishes those facts by measurement.  It builds the fixture the
same way every other test in this directory builds it — through
`test_stiffener.lofted_skin_face`, whose B-spline faces are the surfaces a
member has to be swept on — cuts it at several stations, and for each cut
reports the section chains `sortEdges` produces, whether each chain closes on
the surface or merely in space, and how many faces the band and the matching
drape cut come back as.

Run it through the dev skill's runner:

    ~/.pi/agent/skills/freecad-dev/scripts/run-script.sh \\
        src/Mod/Composites/compositestests/inspect_bulkhead_section.py
"""

import os
import sys

import Part

from FreeCAD import Vector

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from Composites.compositestests.test_stiffener import (  # noqa: E402
    lofted_skin_face,
    standalone_station_plane,
)
from Composites.tools import stiffener  # noqa: E402
from Composites.tools.bulkhead_section import (  # noqa: E402
    chain_regions,
    section_chains,
    section_regions,
)

# (station_x, height along z, width along y).  Height is the ellipse's major
# semi-axis times two, and has to be the larger of the two: Part.Ellipse
# rejects MinorRadius > MajorRadius outright.  The two chains share the section
# at x = 300, which is where the band seam between them falls.
SKIN = [(100, 200, 100), (200, 220, 120), (300, 240, 140),
        (420, 210, 120), (540, 160, 90)]

CUTS = (
    ("axial, mid forward band", 210.0, Vector(1, 0, 0)),
    ("axial, mid aft band", 420.0, Vector(1, 0, 0)),
    ("axial, clear of the support", 700.0, Vector(1, 0, 0)),
    ("oblique through the band seam and both open ends", 300.0, Vector(1, 0.55, 0.35)),
    ("steeply oblique: a shallow cut crossing the seam twice", 210.0, Vector(1, 0.9, 0)),
)


def _is_simple(wire):
    """False when `wire` doubles back through a point it has already passed.

    Compared against the wire's own extrema rather than against a chord: the
    sections here are piecewise and their pieces join to within microns, so a
    plain gap test flags real self-crossings and nothing else.
    """
    points = wire.discretize(240)
    keyed = [tuple(round(value, 5) for value in point) for point in points]
    return len(set(keyed)) > len(set(keyed[:1])) and len(set(keyed)) >= len(keyed) - 1


def describe(support, cutter, label):
    """Print what one cut produces, in the terms the design forks are drawn in."""
    print("\n" + "=" * 72)
    print(f"CUT {label}")
    print("=" * 72)
    normal = stiffener.plane_normal(cutter)
    chains = section_chains(support, cutter)
    if not chains:
        print("  no chain — the cutter misses the support")
        return
    for index, chain in enumerate(chains):
        print(f"  chain {index}: edges={len(chain.Edges)} closed={chain.isClosed()}"
              f" self_crossing={not _is_simple(chain)}")
        print(f"    regions: {[(face, len(boundary)) for face, boundary, _ in chain_regions(support, chain)]}")
    for width, depth in ((34.0, 12.0), (90.0, 12.0), (90.0, 120.0)):
        region = section_regions(support, cutter, depth, width)
        if region is None:
            print(f"  (w={width:g},d={depth:g}): NOTHING — the prism cuts no material")
            continue
        region_faces, cuts, left = region
        print(f"  (w={width:g},d={depth:g}): band_faces={len(region_faces)}"
              f" drape_cuts={len(cuts)} left_support={left}")


def main():
    """Report every probe on the one fixture shape."""
    support = lofted_skin_face(SKIN)
    print("# SUPPORT FIXTURE")
    print(f"  ShapeType={support.ShapeType} faces={len(support.Faces)}"
          f" closed={[f.isClosed() for f in support.Faces]}")
    for plane_x, normal in ((x, n) for x, _l, n in
                            ((x, l, n) for x, l, n in ((c[0], c[1], c[2]) for c in CUTS))
                            for x, l, n in [(x, l, n) for x, l, n in CUTS]):
        pass
    for x, label, normal in ((0, "", None),):
        pass


if __name__ == "__main__":
    main()
