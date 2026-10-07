# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""The bulkhead fixture — one construction for the tests and the examples.

Every bulkhead test and every bulkhead example is decided on the same support:
the doubly curved, open-ended skin fixed as the fixture by §6 of the design
record.  It lives here, and both sides import it, for two reasons.

* One construction, so what a demo shows is the geometry the suite measured.
  A copy-pasted fixture eventually drifts from its original, and the demo then
  demonstrates something no test checks.
* What the shape actually *does* here is measured, not assumed.  The ellipses
  have MajorRadius = height/2 and MinorRadius = width/2, so `height` must be the
  larger value (`Part.Ellipse` refuses the opposite), and the two chains are
  lofted separately and kept as a compound, with the section at x = 300 shared:
  that join is the band seam a flange has to be able to cross, and whether a
  cut follows it can only be answered by building this and asking it.
"""

import Part

import FreeCAD
from FreeCAD import Vector

# (station_x, height, width) per elliptical section.  The chains share the
# section at x = 300, so the bands meet there.
FORWARD_SECTIONS = [(100.0, 200.0, 100.0), (200.0, 220.0, 120.0), (300.0, 240.0, 140.0)]
AFT_SECTIONS = [(300.0, 240.0, 140.0), (420.0, 210.0, 120.0), (540.0, 160.0, 90.0)]

PLANE_SIDE = 900.0


def ellipse_section(station_x, height, width):
    """One elliptical section in the station plane, major axis vertical."""
    point = Vector(station_x, 0.0, 0.0)
    ellipse = Part.Ellipse(point, height / 2.0, width / 2.0)
    ellipse.rotate(FreeCAD.Placement(
        point, FreeCAD.Rotation(Vector(1, 0, 0), Vector(0, 0, 1))))
    return ellipse.toShape()


def lofted_bands(chains, sewn=False):
    """A skin lofted through each chain of elliptical sections.

    Taken as the loft's lateral faces with the caps dropped — a cap's carrier
    is perpendicular to the loft axis, so a cut normal to that axis would
    section the caps too and count closed wires where the skin has none.

    `sewn=True` builds `Part.makeShell`, which **does not stitch**: a sewn skin
    then holds one edge along the join between the two bands, while an unsewn
    one holds two coincident copies, one per band.  Both spellings are kept
    because a rule stated in terms of "faces sharing an edge" reads them
    differently, and this module's own first draft got that wrong by assuming a
    shell stitched.
    """
    faces = []
    for chain in chains:
        solid = Part.makeLoft(
            [ellipse_section(*section_) for section_ in chain], True, False)
        faces.extend(face for face in solid.Faces
                     if isinstance(face.Surface, Part.BSplineSurface))
    return (Part.makeShell(faces) if sewn else Part.makeCompound(faces))


def station_plane(x, normal=Vector(1, 0, 0), side=PLANE_SIDE):
    """A cutting plane through `x`, large enough to cut clear through the skin.

    Placed by its centre, not by a corner: `makePlane` builds the face in the
    local frame of the rotation that maps z onto `normal`, and for an
    x-directed normal that frame's second axis runs along **minus** global y, so
    a corner-placed plane lands shifted a full side along y and never meets the
    part.  A plane that misses reads exactly like an intersection that failed,
    which is how this misplacement was once misdiagnosed as an OCCT bug.
    """
    rotation = FreeCAD.Rotation(Vector(0, 0, 1), normal)
    corner = rotation.multVec(Vector(side / 2.0, side / 2.0, 0.0))
    plane = Part.makePlane(side, side)
    plane.Placement = FreeCAD.Placement(Vector(x, 0.0, 0.0) - corner, rotation)
    return plane


def bulkhead_fixture(sewn=False):
    """The fixture skin: forward band + aft band, joined at x = 300."""
    return lofted_bands([FORWARD_SECTIONS, AFT_SECTIONS], sewn=sewn)
