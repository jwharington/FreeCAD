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

from Composites.compositeexamples.fixture_bulkhead import (
    AFT_SECTIONS,
    FORWARD_SECTIONS,
    PLANE_SIDE,
    bulkhead_fixture,
    lofted_bands,
    station_plane,
)
from Composites.tools import bulkhead_section as section
from Composites.tools import stiffener


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
        self.support = bulkhead_fixture(sewn=True)

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
        band = section.band_of(self.support, station_plane(210.0), 34.0)
        self.assertTrue(band, "no band to take out of the support")
        self.assertGreater(band[0].Area, 0.0)

    def test_band_spans_both_bands_where_the_seam_crosses_it(self):
        """Where the cut crosses the band seam the band is a *compound*."""
        cutter = station_plane(300.0, Vector(1, 0.55, 0.35))
        band = section.band_of(self.support, cutter, 34.0)
        self.assertGreaterEqual(
            len(band), 2,
            "the band stops at the band seam, so a member built on it would "
            "carry one face across a fold between two surfaces")

    def test_band_and_plate_together_account_for_every_patch_of_the_support(self):
        """support area = (support − band) + band, exactly, on every probe cut.

        This is the one assertion that would have caught the first draft's two
        errors at once: `member_slab` handing the boolean a *compound* of slabs
        (whose common with a shell is a curve, so nothing is taken out and the
        sum falls short), and taking the plate and the band from *separate*
        overlapping slabs (which double-counts the patch they share, so the sum
        overshoots).  A member that double-counts a patch of fabric reads as
        locally doubled in the stack model, and the panel's own faces give up
        exactly what the band occupies, so equality here is what F4's
        exclusivity means in numbers.
        """
        total = sum(face.Area for face in self.support.Faces)
        for x, normal in ((210.0, Vector(1, 0, 0)), (420.0, Vector(1, 0, 0)),
                          (300.0, Vector(1, 0.55, 0.35))):
            cutter = station_plane(x, normal)
            for width in (34.0, 90.0):
                band = section.band_of(self.support, cutter, width)
                footprint = section.drape_cuts_of(self.support, cutter, width)
                with self.subTest(x=x, normal=tuple(normal), width=width):
                    self.assertGreater(len(band), 0, "nothing was taken out of the support")
                    accounted = sum(f.Area for f in band) + sum(f.Area for f in footprint)
                    self.assertAlmostEqual(
                        accounted, total, delta=1e-6 * total,
                        msg="band and footprint do not tile the support: overlap or gap")

    def test_section_closes_on_a_region_rather_than_a_chord(self):
        """The plate bounds real area, so the section is not its own chord.

        A chorded section keeps its perimeter and loses its area, which is the
        `make_stiffener` profile failure this module exists to avoid: rebuilding
        the boundary as straight runs between endpoints would still give one
        closed chain of positive length and *no* region inside it.
        """
        for x, normal in ((210.0, Vector(1, 0, 0)), (300.0, Vector(1, 0.55, 0.35))):
            cutter = station_plane(x, normal)
            plates = section.plate_of(self.support, cutter)
            with self.subTest(x=x, normal=tuple(normal)):
                self.assertTrue(plates, "the cut closed on nothing")
                for plate in plates:
                    self.assertGreater(
                        plate.Area, 1.0,
                        "zero-area section: the boundary is its own chord, not a region")

    def test_a_band_as_wide_as_the_local_chamber_still_meets_the_support(self):
        """A 90 mm band on a 120 mm chamber is real material, not a miss.

        The slab is one-sided — it runs from `width` behind the cutting
        surface up to the surface itself — so a wide band leans far into the
        tube; an empty answer here would mean the prism missed the surface,
        not that a wide flange is impossible.
        """
        cutter = station_plane(210.0)
        band = section.band_of(self.support, cutter, 90.0)
        self.assertTrue(band, "a chamber-wide band found nothing to take out of")


if __name__ == "__main__":
    unittest.main(verbosity=2)
