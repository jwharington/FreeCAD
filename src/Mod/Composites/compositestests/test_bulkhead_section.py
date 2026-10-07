# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""What a bulkhead's filled section has to be built from, on real geometry.

Three of the bulkhead tool's design questions turn on facts about one support
shape — the lofted, doubly curved, open-ended skin that §6 of
docs/handoff-2026-10-07-bulkhead-tool.md §6 fixes as the fixture for every
bulkhead test and every example — and none of them can be settled on a flat plate or settled on paper:

* does a bulkhead's section bound **one** region, or several disjoint ones?
  A self-crossing boundary bounds several, and nextdrape's hole test reads a
  self-crossing polygon's *chords* as hole boundaries, so "several" would have
  to be answered by construction rather than by a hole test;
* does the **band seam** fall inside the flange band, and does taking the band
  out of the support by boolean actually work, or come back empty?
* is a **stand-off comparable to the local chamber** a legitimate
  configuration?

Each assertion is written so that a *false* premise fails loudly.  An earlier
draft of `tools/bulkhead_section.py` encoded several of these as prose
assumptions instead of measurements, and they were wrong in ways only measuring
the fixture could show — including a fixture built with `Part.makeShell`, which
does not stitch, so it reported "no seam" for a seam that was there all along.

Run headlessly:

    ~/.pi/agent/skills/freecad-dev/scripts/run-tests.sh test_bulkhead_section
"""

import unittest

import Part

import FreeCAD
from FreeCAD import Vector

from Composites.tools import bulkhead_section as section
from Composites.tools import stiffener


def ellipse_section(station_x, height, width):
    """One elliptical section in the station plane, major axis vertical.

    `Part.Ellipse` rejects MinorRadius > MajorRadius outright, so `height` has to
    be the larger of the two — which is why the fixture's sections are written
    (height, width) and not the other way round.
    """
    point = Vector(station_x, 0.0, 0.0)
    ellipse = Part.Ellipse(point, height / 2.0, width / 2.0)
    ellipse.rotate(FreeCAD.Placement(
        point, FreeCAD.Rotation(Vector(1, 0, 0), Vector(0, 0, 1))))
    return ellipse.toShape()


def lofted_bands(chains, sewn=True):
    """The fixture: a skin lofted through each chain of elliptical sections.

    Taken as the loft's *lateral* faces, with the end caps dropped: a chain of
    three sections lofts into a solid of two lateral faces plus two caps, and a
    cap's support is perpendicular to the loft axis, so a cut plane normal to
    that axis would section the caps too and count closed wires where the
    surface has none.

    `sewn=False` builds the same faces as a compound, which is what
    `CompositeShellFP` keeps them as — `Part.makeShell` does not stitch, so the
    join between two bands is then two coincident copies rather than one shared
    edge, and a rule stated in terms of "faces sharing an edge" reads that
    differently.
    """
    faces = []
    for chain in chains:
        solid = Part.makeLoft(
            [ellipse_section(*section_) for section_ in chain], True, False)
        faces.extend(face for face in solid.Faces
                     if isinstance(face.Surface, Part.BSplineSurface))
    return Part.makeShell(faces) if sewn else Part.makeCompound(faces)


# The fixture's two chains of sections, as (station_x, height, width).  They
# share the section at x = 300, so the two bands meet there: that join is the
# band seam a flange band has to be able to cross.
FORWARD_SECTIONS = [(100.0, 200.0, 100.0), (200.0, 220.0, 120.0), (300.0, 240.0, 140.0)]
AFT_SECTIONS = [(300.0, 240.0, 140.0), (420.0, 210.0, 120.0), (540.0, 160.0, 90.0)]

PLANE_SIDE = 900.0


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


def _shape(chains):
    """How many chains, and how long each is — comparable, unlike Wires.

    Two `Part.Wire` objects compare by identity, so a test that wants to know
    whether two shapes are the *same shape* has to ask about the geometry.
    """
    return [(len(chain.Edges), round(chain.Length, 3)) for chain in chains]


def _travels_twice(wire, samples=240):
    """Whether `wire` passes back through a point it has already been through."""
    keyed = [tuple(round(value, 5) for value in point)
             for point in wire.discretize(samples)]
    return len(set(keyed)) < len(keyed) - 2


class SectionProbe(unittest.TestCase):
    """Shared fixture plumbing."""

    def setUp(self):
        self.support = lofted_bands([FORWARD_SECTIONS, AFT_SECTIONS])

    def chains_of(self, support, cutter):
        return stiffener.intersection_paths(support, cutter)

    def assertOneChain(self, cutter, label):
        chains = self.chains_of(self.support, cutter)
        self.assertEqual(
            len(chains), 1,
            f"{label}: expected one section chain, got {len(chains)}: "
            + ", ".join(f"{len(c.Edges)} edges" for c in chains))
        return chains


class TestSectionChains(SectionProbe):
    """How many chains a cut produces, and whether any of them doubles back."""

    def test_axial_cut_gives_one_chain_that_never_self_crosses(self):
        """An axial cut through a doubly curved band gives *one* chain.

        If this ever fails, the multi-boundary premise in §5.1 of the design
        record is back and the section polygonator has to split by connected
        region again — read that section before treating a fix here as safe.
        """
        for x in (210.0, 420.0):
            with self.subTest(x=x):
                chains = self.assertOneChain(station_plane(x), f"axial cut at x={x}")
                self.assertTrue(chains[0].isClosed(),
                                "an axial cut should close on the skin")
                self.assertFalse(
                    _travels_twice(chains[0]),
                    "the chain doubles back on itself, so its boundary bounds "
                    "more than one region and the hole test would read a "
                    "closing chord as a hole boundary")

    def test_cut_clear_of_the_support_produces_no_chain(self):
        """A plane past the end of the skin meets nothing, and has to say so."""
        self.assertEqual(self.chains_of(self.support, station_plane(700.0)), [])

    def test_oblique_cut_through_the_seam_still_gives_one_chain(self):
        """A steeply oblique cut crosses the band seam and stays one chain.

        The chain that comes back is not one of the skin's own curves: it is
        cut across both bands, so any member bounded by it has to be sewn from
        a shell rather than from a hand-built profile whose edges are each
        assumed to lie in one face's interior.
        """
        self.assertOneChain(station_plane(300.0, Vector(1, 0.55, 0.35)),
                            "oblique cut through the seam")

    def test_sewn_and_unsewn_supports_agree_on_the_chain_shape(self):
        """The seam's two representations must not change how many chains there are.

        A sewn skin holds the seam once; an unsewn one holds a copy per face.
        Counting section edges instead of de-duplicating them makes the same
        cut read differently on the two, and the fixture is built both ways.
        """
        unsewn = Part.makeCompound(self.support.Faces)
        for x in (210.0, 300.0, 420.0):
            with self.subTest(x=x):
                cutter = station_plane(x)
                self.assertEqual(
                    _shape(self.chains_of(self.support, cutter)),
                    _shape(self.chains_of(unsewn, cutter)),
                    f"x={x}: the seam's copies changed the chains")


class TestFlangeBand(SectionProbe):
    """Whether the flange band can be taken *out of* the support at all."""

    def test_band_exists_for_a_normal_flange_width(self):
        """A 34 mm band on a doubly curved band yields real material.

        An empty answer here is not "no flange", it is a bug: the prism either
        missed the surface or was built as a compound, and the common of a
        shell with a compound of faces is a *curve*, which has no faces to give
        — the first draft of `section_slab` did exactly that.
        """
        band = section.band_of(self.support, station_plane(210.0), 34.0, 12.0)
        self.assertTrue(band, "no band to take out of the support")
        self.assertGreater(band[0].Area, 0.0)

    def test_band_spans_both_bands_where_the_seam_crosses_it(self):
        """Where the cut crosses the band seam the band is a *compound*."""
        cutter = station_plane(300.0, Vector(1, 0.55, 0.35))
        band = section.band_of(self.support, cutter, 34.0, 12.0)
        self.assertGreaterEqual(
            len(band), 2,
            "the band stops at the band seam, so a member built on it would "
            "carry one face across a fold between two surfaces")

    def test_stand_off_as_far_as_the_local_chamber_still_meets_the_support(self):
        """`depth` measured from the support can exceed the local sagitta.

        A stand-off of 120 mm on this skin passes clean through both bands.
        That is a legitimate configuration rather than a degenerate one, and it
        is what decides where `depth` is measured from: measured *normally* to
        the support, a constant `depth` lies in the cutting plane, and a
        polygon bounded by a curve and its normal-offset comes back with
        nothing in it.
        """
        cutter = station_plane(210.0)
        self.assertTrue(section.band_of(self.support, cutter, 34.0, 12.0))
        self.assertTrue(section.band_of(self.support, cutter, 90.0, 120.0),
                        "a stand-off of the chamber's depth is a real shape")


if __name__ == "__main__":
    unittest.main(verbosity=2)
