# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""The bulkhead feature, from the fixture through a save/reopen round trip.

The section layer's facts are `test_bulkhead_section`'s business; this module
holds the feature on top of them: that a `BulkheadFP` computes a shape with a
plate core and a flange band, that it fails loudly when the cut closes on
nothing, and that what it computes survives the document being saved, closed
and reopened — R5's round-trip contract, which is where a feature's Python
proxy usually stops matching the feature that wrote it.

The fixture is the section test's, imported rather than copied: one support
shape is the fixture for every bulkhead test and every example, and two
constructions of it would eventually disagree.
"""

import os
import tempfile
import unittest

import FreeCAD

import numpy

from Composites.compositestests.test_base import TestFreeCADFP
from Composites.compositestests.test_bulkhead_section import (
    AFT_SECTIONS,
    FORWARD_SECTIONS,
    lofted_bands,
    split_fixture,
    station_plane,
)


def _fixture_support():
    return lofted_bands([FORWARD_SECTIONS, AFT_SECTIONS])


class TestBulkheadFeature:
    """Built per-test into a fresh document by :class:`TestBulkheadFP`."""

    def _make_support(self, name="Support"):
        support = self.doc.addObject("Part::Feature", name)
        support.Shape = _fixture_support()
        return support

    def _make_cutter(self, name="Cutter", x=210.0):
        cutter = self.doc.addObject("Part::Feature", name)
        cutter.Shape = station_plane(x)
        return cutter

    def _make_bulkhead(self, name="Bulkhead"):
        from Composites.features.Bulkhead import BulkheadFP

        bulkhead = self.doc.addObject("Part::FeaturePython", name)
        BulkheadFP(
            bulkhead,
            support=self._make_support(),
            cut_surface=self._make_cutter(),
        )
        self.doc.recompute()
        return bulkhead


class TestBulkheadGeometry(TestBulkheadFeature, TestFreeCADFP):
    """Level 1 — the member's own faces."""

    def test_bulkhead_has_plate_and_flange(self):
        """A bulkhead carries at least one plate core and one flange band."""
        bulkhead = self._make_bulkhead()
        faces = bulkhead.Shape.Faces
        self.assertGreaterEqual(
            len(faces), 2,
            "a bulkhead is a plate and a flange, not one face of either")

    def test_bulkhead_is_three_dimensional(self):
        """The plate lies in the cutting plane and the flange does not.

        If both lay in one plane the member would be flat — the plate with no
        flange, or the flange with no plate — and a laminate draped on it would
        carry a fold the stack model never sees.
        """
        bulkhead = self._make_bulkhead()
        normals = {
            tuple(round(value, 6) for value in face.normalAt(*face.Surface.parameter(
                face.CenterOfMass)))
            for face in bulkhead.Shape.Faces
        }
        self.assertGreater(
            len(normals), 1,
            "every face shares one normal: the member is flat, not plate+flange")


class TestBulkheadFailure(TestBulkheadFeature, TestFreeCADFP):
    """The loud-failure contract."""

    def test_cut_that_closes_on_nothing_fails_loudly(self):
        """A cutter past the end of the skin is an error, not an empty shape.

        Silence here would be the worst kind: the feature would keep its last
        good shape, show as up to date, and the FEM write-out would quietly
        carry a bulkhead the geometry no longer agrees with.
        """
        bulkhead = self.doc.addObject("Part::FeaturePython", "EmptyBulkhead")
        from Composites.features.Bulkhead import BulkheadFP

        BulkheadFP(
            bulkhead,
            support=self._make_support(),
            cut_surface=self._make_cutter(x=700.0),
        )
        self.doc.recompute()
        self.assertIn("Invalid", bulkhead.State,
                      "the failure must show on the feature, not only raise")
        self.assertTrue(bulkhead.Shape.isNull())


class TestBulkheadRoundTrip(TestBulkheadFeature, TestFreeCADFP):
    """R5 — save, close, reopen."""

    def test_flipping_MirrorX_moves_the_foot_to_the_far_side(self):
        """The feature honours MirrorX, not only the tool layer.

        A property wired to nothing would still let every section test
        pass: this one only goes green if flipping the flag re-derives
        the feature's own shape.
        """
        plain = self._make_bulkhead("Plain")
        flipped = self._make_bulkhead("Flipped")
        flipped.MirrorX = True
        self.doc.recompute()
        self.assertFalse(flipped.Shape.isNull(), "flipping MirrorX killed it")
        self.assertNotEqual(
            [(face.Area, face.CenterOfMass) for face in plain.Shape.Faces],
            [(face.Area, face.CenterOfMass) for face in flipped.Shape.Faces],
            "MirrorX never reached the shape")

    def test_reopened_bulkhead_keeps_its_shape(self):
        """What reopenes must be what was saved, geometry for geometry."""
        bulkhead = self._make_bulkhead()
        before = [(face.Area, face.CenterOfMass) for face in bulkhead.Shape.Faces]

        handle, filepath = tempfile.mkstemp(suffix=".FCStd")
        os.close(handle)
        try:
            self._save_document(filepath)
            loaded = self._load_document(filepath)
            reopened = loaded.getObject(bulkhead.Name)
            self.assertIsNotNone(reopened, "the bulkhead did not survive the reopen")
            after = [(face.Area, face.CenterOfMass) for face in reopened.Shape.Faces]
            self.assertEqual(
                [(round(area, 6), round(v.x, 6), round(v.y, 6), round(v.z, 6))
                 for area, v in before],
                [(round(area, 6), round(v.x, 6), round(v.y, 6), round(v.z, 6))
                 for area, v in after])
        finally:
            os.remove(filepath)


class TestBulkheadOnSplitSupport(TestBulkheadFeature, TestFreeCADFP):
    """The deck has been cut L/R before the bulkhead is declared.

    The support is four unconnected pieces (both loft bands, left and
    right of the y = 0 plane); the section chain, the band and the
    footprint must all survive — the same situation a real bay has once
    the deck has been cut.
    """

    def _make_split_support(self, name="SplitSkin"):
        support = self.doc.addObject("Part::Feature", name)
        support.Shape = split_fixture(sewn=True)
        return support

    def _make_split_bulkhead(self, name="SplitBulkhead"):
        from Composites.features.Bulkhead import BulkheadFP

        bulkhead = self.doc.addObject("Part::FeaturePython", name)
        BulkheadFP(
            bulkhead,
            support=self._make_split_support(),
            cut_surface=self._make_cutter(),
        )
        self.doc.recompute()
        return bulkhead

    def test_bulkhead_spans_the_split_support(self):
        """Plate and band both exist across the separate pieces."""
        bulkhead = self._make_split_bulkhead()
        self.assertGreaterEqual(
            len(bulkhead.Shape.Faces), 2,
            "plate and flange must both survive the split deck")
        self.assertTrue(bulkhead.Shape.isValid(),
                        "the member must be a valid shape")
        # The member is still three-dimensional: the plate lies in the
        # cutting plane, the band on the skin.
        normals = {
            tuple(round(v, 6) for v in face.normalAt(
                *face.Surface.parameter(face.CenterOfMass)))
            for face in bulkhead.Shape.Faces
        }
        self.assertGreater(len(normals), 1,
                           "every face shares one normal after the split")

    def test_split_member_conserves_the_support(self):
        """Band + footprint = the split support, area-exact."""
        from Composites.tools import bulkhead_section as section

        support_shape = self._make_split_support().Shape
        cutter = station_plane(210.0)
        support_area = sum(f.Area for f in support_shape.Faces)
        band_area = sum(
            f.Area for f in section.band_of(support_shape, cutter, 34.0))
        remainder_area = sum(
            f.Area for f in section.drape_cuts_of(support_shape, cutter, 34.0))
        self.assertAlmostEqual(
            band_area + remainder_area, support_area, places=6,
            msg="band + footprint must equal the split support exactly")


class TestBulkheadExampleRuns(TestFreeCADFP):
    """The example must run headless, not merely exist beside the tests.

    A script nobody runs rots silently: this one reaches the same
    section-layer calls the suite asserts on, in both of its sections.
    Running it here keeps "verified by example" from meaning "looked at
    once, while it still worked".
    """

    def test_section_section_builds_every_named_object(self):
        """Section I: skins, plate, flange, footprint — and the mirrored pair."""
        from Composites.compositeexamples.examples import bulkhead_section

        doc = bulkhead_section.build(doc=self.doc)["doc"]
        names = ["Skin1", "Skin2", "Plate", "Flange", "Remainder",
                 "PlateM", "FlangeM", "SkinM"]
        for name in names:
            obj = doc.getObject(name)
            self.assertIsNotNone(obj, f"the example built no {name}")
            if obj is not None:
                self.assertFalse(obj.Shape.isNull(), f"{name} is empty")
                self.assertTrue(obj.Shape.isValid(), f"{name} is invalid")

    def test_feature_section_recomputes_the_feature_path(self):
        """Section II: the BulkheadFP must recompute, not sit Touched."""
        from Composites.compositeexamples.examples import bulkhead_section

        doc = bulkhead_section.build_with_feature(doc=self.doc)["doc"]
        member = doc.getObject("Bulkhead")
        self.assertIsNotNone(member, "no Bulkhead feature in section II")
        self.assertFalse(member.Shape.isNull(), "the feature computed nothing")
        self.assertTrue(member.Shape.isValid())
        self.assertGreater(
            len(member.Shape.Faces), 2,
            "plate and flange should both be in the feature's shape")


class TestBulkheadWiring(TestBulkheadFeature, TestFreeCADFP):
    """Composite mode: laminate → drape → stack chain, through the shared flow.

    The wiring is what the bulkhead shares with the stiffener, so it is
    tested where the feature lives: a plate/band pair of draped shells,
    the band borrowing the panel's solved drape, and the joint stack
    assembled through the seam machinery — or a loud refusal, never a
    half-wired joint.
    """

    def _make_laminate(self, name):
        from Composites.compositestests.example_materials import make_glass
        from Composites.features.HomogeneousLamina import HomogeneousLaminaFP
        from Composites.features.Laminate import LaminateFP

        laminate = self.doc.addObject("Part::FeaturePython", name)
        LaminateFP(laminate)
        plies = []
        for k, angle in enumerate((0.0, 90.0)):
            ply = self.doc.addObject("Part::FeaturePython", f"{name}_Ply{k}")
            HomogeneousLaminaFP(ply)
            ply.Angle = angle
            ply.Thickness = 0.5
            ply.Material = make_glass()
            plies.append(ply)
        laminate.Layers = plies
        self.doc.recompute()
        return laminate

    def _make_wired_bulkhead(self, name, panel, cutter_x=210.0):
        from Composites.features.Bulkhead import BulkheadFP

        bulkhead = self.doc.addObject("Part::FeaturePython", name)
        BulkheadFP(bulkhead, support=panel,
                   cut_surface=self._make_cutter(f"{name}_Cutter", x=cutter_x))
        bulkhead.Laminate = self._make_laminate(f"{name}_Laminate")
        self.doc.recompute()
        return bulkhead

    def test_geometry_only_mode_builds_no_wiring_children(self):
        """Without a Laminate the bulkhead stays pure geometry."""
        bulkhead = self._make_bulkhead()
        self.assertTrue(bulkhead.Shape.isValid())
        for name in ("Bulkhead_Plate", "Bulkhead_Band",
                     "Bulkhead_CombinedLaminate"):
            self.assertIsNone(
                self.doc.getObject(name),
                f"{name} exists although no Laminate is linked")

    def test_composite_mode_without_panel_laminate_fails_loudly(self):
        """A member laminate wired onto a plain (unclothed) skin is refused.

        The refusal has to be visible on the feature: a silent pass here
        would be the handover's one unacceptable outcome — a stack that
        reads as wired but computes against nothing.
        """
        from Composites.compositestests.example_materials import make_glass
        from Composites.features.Bulkhead import BulkheadFP
        from Composites.features.HomogeneousLamina import HomogeneousLaminaFP
        from Composites.features.Laminate import LaminateFP

        support = self._make_support()
        cutter = self._make_cutter()
        laminate = self.doc.addObject("Part::FeaturePython", "MemberLam")
        LaminateFP(laminate)
        ply = self.doc.addObject("Part::FeaturePython", "MemberPly")
        HomogeneousLaminaFP(ply)
        ply.Angle = 0.0
        ply.Thickness = 0.5
        ply.Material = make_glass()
        laminate.Layers = [ply]
        self.doc.recompute()

        bulkhead = self.doc.addObject("Part::FeaturePython", "Wired")
        BulkheadFP(bulkhead, support=support, cut_surface=cutter)
        bulkhead.Laminate = laminate
        self.doc.recompute()

        self.assertIn("Invalid", bulkhead.State,
                      "wiring onto a plain skin must fail, not half-wire")
        self.assertIsNone(self.doc.getObject("Wired_Band"),
                          "no half-wired joint may survive the refusal")

    def _make_panel(self, name="Skin"):
        """The fixture skin as a Composite::Shell, at its own default pitch."""
        from Composites.features.CompositeShell import CompositeShellFP
        from Composites.features.Rosette import RosetteFP

        support = self._make_support(f"{name}_Support")
        panel = self.doc.addObject("Part::FeaturePython", name)
        CompositeShellFP(panel, support)
        panel.Laminate = self._make_laminate(f"{name}_Laminate")
        rosette = self.doc.addObject("Part::FeaturePython", f"{name}_Rosette")
        RosetteFP(rosette, support=(support, ["Face1"]))
        rosette.Angle = 0.0
        panel.Rosette = rosette
        self.doc.recompute()
        return panel

    def test_wired_bulkhead_lays_up_through_the_stack_chain(self):
        """Plate and band shells exist, and the joint stack is wired.

        R3's routing: the band borrows the panel's solved drape (its
        DrapeSource), and the combined laminate is wired panel→band←plate
        with the footprint recorded as the joint's master-side support.
        The joint is accepted because the plate reads its boundary the
        stiffener's way — from the band's own wall edge — so the shared
        curve is identical, not tolerance-matched.
        """
        panel = self._make_panel()
        bulkhead = self._make_wired_bulkhead("Bulkhead", panel)
        plate = self.doc.getObject("Bulkhead_Plate")
        band = self.doc.getObject("Bulkhead_Band")
        self.assertIsNotNone(plate, "no plate shell was built")
        self.assertIsNotNone(band, "no band shell was built")
        self.assertIs(band.DrapeSource, panel,
                      "the band must borrow the panel's solved drape")
        scl = self.doc.getObject("Bulkhead_CombinedLaminate")
        self.assertIsNotNone(scl, "no combined laminate on the joint")
        self.assertIs(scl.Master, panel)
        self.assertIs(scl.Attachment, plate)
        self.assertIs(scl.SeamRegion, band)
        remainder = self.doc.getObject("Bulkhead_RemainderSupport")
        self.assertIsNotNone(remainder, "the footprint was not recorded")
        # The combined stack is composed, not a Layers link list — the seam
        # laminate delivers it through get_model, which is the stiffener
        # suite's own oracle for the same object.
        model = scl.Proxy.get_model(scl)
        self.assertEqual(
            len(model.layers), 4,
            "no combined stack reached the joint: panel plies + plate plies")

    def test_trim_tool_trims_the_member_shells(self):
        """A TrimTool makes the member stop at the opening.

        The stiffener's trim polarity, applied to the bulkhead: the
        plate/band faces are cut by the tool before the feature's shape
        and shells are built, and the drape rides the uncut geometry
        (borrowed, never re-solved).
        """
        import Part

        panel = self._make_panel()
        plain = self._make_wired_bulkhead("Plain", panel)
        plate = self.doc.getObject("Plain_Plate")
        band = self.doc.getObject("Plain_Band")
        plate_area, band_area = plate.Shape.Area, band.Shape.Area

        tool = self.doc.addObject("Part::Feature", "Tool")
        tool.Shape = Part.makeBox(200.0, 300.0, 200.0,
                                  FreeCAD.Vector(120.0, -150.0, 40.0))
        trimmed = self.doc.addObject("Part::FeaturePython", "Trimmed")
        from Composites.features.Bulkhead import BulkheadFP
        BulkheadFP(trimmed, support=panel,
                   cut_surface=self._make_cutter("Trimmed_Cutter"))
        trimmed.Laminate = self._make_laminate("Trimmed_Lam")
        trimmed.TrimTool = tool
        self.doc.recompute()

        self.assertLess(
            self.doc.getObject("Trimmed_Plate").Shape.Area, plate_area,
            "the trim tool must remove plate shell before the shell is built")
        self.assertLess(
            self.doc.getObject("Trimmed_Band").Shape.Area, band_area,
            "the trim tool must remove band shell before the shell is built")
        self.assertNotIn("Invalid", trimmed.State)

    def test_untrimmed_plate_spans_a_bay_like_void(self):
        """Control: without a TrimTool the plate crosses the void region.

        Pins the boundary of the trim fix — the no-op the property used
        to be is now a deliberate default: with no tool, material
        occupies the region a bay box would remove.
        """
        import Part

        panel = self._make_panel()
        bulkhead = self._make_wired_bulkhead("Bulkhead", panel)
        void = Part.makeBox(80.0, 200.0, 120.0,
                            FreeCAD.Vector(170.0, -100.0, 60.0))
        plate = self.doc.getObject("Bulkhead_Plate")
        crossing = plate.Shape.common(void)
        self.assertGreater(
            crossing.Area, 1.0,
            "the untrimmed plate must cross the would-be opening")

    def test_trimmed_plate_stops_at_the_opening(self):
        """With a TrimTool no material bridges the void it declares."""
        import Part

        panel = self._make_panel()
        bulkhead = self._make_wired_bulkhead("Bulkhead", panel)
        tool = self.doc.addObject("Part::Feature", "Tool")
        tool.Shape = Part.makeBox(80.0, 200.0, 120.0,
                                  FreeCAD.Vector(170.0, -100.0, 60.0))
        bulkhead.TrimTool = tool
        self.doc.recompute()

        plate = self.doc.getObject("Bulkhead_Plate")
        crossing = plate.Shape.common(tool.Shape)
        self.assertLessEqual(
            crossing.Area, 1e-6,
            "the trimmed plate must not bridge the opening")

    def test_changing_the_trim_tool_updates_the_shape(self):
        """TrimTool is live: a change re-derives the member's shape."""
        import Part

        panel = self._make_panel()
        bulkhead = self._make_wired_bulkhead("Bulkhead", panel)
        untrimmed_area = bulkhead.Shape.Area

        tool = self.doc.addObject("Part::Feature", "Tool")
        tool.Shape = Part.makeBox(80.0, 200.0, 120.0,
                                  FreeCAD.Vector(170.0, -100.0, 60.0))
        bulkhead.TrimTool = tool
        self.doc.recompute()
        trimmed_area = bulkhead.Shape.Area
        self.assertLess(trimmed_area, untrimmed_area,
                        "setting a trim tool must remove material")

        bulkhead.TrimTool = None
        self.doc.recompute()
        self.assertAlmostEqual(
            bulkhead.Shape.Area, untrimmed_area, places=4,
            msg="clearing the trim tool must restore the full member")

    def test_trim_that_removes_the_member_fails_loudly(self):
        """A tool covering the whole member is an error, not an empty shell."""
        import Part

        panel = self._make_panel()
        bulkhead = self._make_wired_bulkhead("Bulkhead", panel)
        box = bulkhead.Shape.BoundBox
        tool = self.doc.addObject("Part::Feature", "CoverTool")
        tool.Shape = Part.makeBox(
            box.XLength + 20.0, box.YLength + 20.0, box.ZLength + 20.0,
            FreeCAD.Vector(box.XMin - 10.0, box.YMin - 10.0, box.ZMin - 10.0))
        bulkhead.TrimTool = tool
        self.doc.recompute()

        self.assertIn("Invalid", bulkhead.State,
                      "a whole-member trim must fail on the feature")
        self.assertIn("trim", str(bulkhead.Proxy.last_error),
                      "the refusal must name the trim that caused it")

    def test_band_seam_subs_land_on_the_section_chain(self):
        """The seam rule names only edges that lie on a section chain.

        A positional ``Edge1`` would be the stiffener's rule copied to a
        geometry it does not fit: on a band the first compound edge can
        belong to neither boundary, and the seed is picked once (cost #2).
        """
        panel = self._make_panel()
        bulkhead = self._make_wired_bulkhead("Bulkhead", panel)
        band = self.doc.getObject("Bulkhead_Band")
        self.assertIsNotNone(band, "no band shell to address")
        from Composites.features.StiffenerCompositeShell import (
            bulkhead_band_seam_subs,
        )
        from Composites.tools.bulkhead_section import section_chains

        support, subs = bulkhead_band_seam_subs(band, bulkhead)
        self.assertTrue(subs, "the seam rule named nothing")
        chains = section_chains(bulkhead.Support.Shape,
                                bulkhead.IntersectSurface.Shape)
        self.assertTrue(chains, "the fixture cutter must produce a chain")
        # Same medicine as the rule itself: coincident-curve extrema never
        # return, so the oracle measures point-to-point against a
        # discretised chain cloud (finer than the rule's own: 0.5 mm).
        cloud = numpy.array(
            [[p.x, p.y, p.z]
             for chain in chains
             for p in chain.discretize(Number=max(2, int(chain.Length / 0.5)))])
        for name in subs:
            edge = support.Shape.getElement(name)
            samples = numpy.array(
                [[p.x, p.y, p.z]
                 for p in edge.discretize(Number=max(2, int(edge.Length / 1.0)))])
            deltas = samples[:, numpy.newaxis, :] - cloud[numpy.newaxis, :, :]
            nearest = numpy.sqrt((deltas * deltas).sum(axis=-1)).min(axis=1)
            self.assertLessEqual(
                float(nearest.max()), 1.0,
                f"{name} names an edge that lies on no section chain")


if __name__ == "__main__":
    unittest.main(verbosity=2)
