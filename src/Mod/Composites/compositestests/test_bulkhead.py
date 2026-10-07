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

from Composites.compositestests.test_base import TestFreeCADFP
from Composites.compositestests.test_bulkhead_section import (
    AFT_SECTIONS,
    FORWARD_SECTIONS,
    lofted_bands,
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

        doc = bulkhead_section.build(doc=self.doc)
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

        doc = bulkhead_section.build_with_feature(doc=self.doc)
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

    def _make_panel(self, name="Skin", pitch=5.0):
        """The fixture skin as a Composite::Shell, pitch set before the solve."""
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
        panel.DrapePitch = pitch
        self.doc.recompute()
        return panel

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

    # The two cases below would drape the bulkhead through the FreeCAD
    # stack, and a drape of this section took 14.7 s (plate) / timed out
    # (panel) — minutes per test, which is a nextdrape defect, not a
    # fixture preference.  The exact geometry and setup are captured for
    # the draper at src/3rdParty/nextdrape/data/bulkhead-plate-drape
    # (BREP + setup.json); these cases stay skipped until the draper
    # fixes that, and re-run by deleting the skip.
    @unittest.skip(
        "nextdrape defect (bulkhead-plate-drape kit): plate drape took "
        "14.7 s, panel drape exceeded 100 s — no bulkhead may be draped "
        "until the draper handles this section in under a second")
    def test_wired_bulkhead_lays_up_through_the_stack_chain(self):
        """Plate and band shells exist, and the joint stack is wired.

        R3's routing: the band borrows the panel's solved drape (its
        DrapeSource), and the combined laminate is wired panel→band←plate
        with the footprint recorded as the joint's master-side support.
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
        self.assertTrue(scl.Layers, "no stack reached the joint")

    @unittest.skip(
        "nextdrape defect (bulkhead-plate-drape kit): same drape cost as "
        "the wired case above — the seam rule itself is unit-tested in "
        "test_bulkhead_section against the same geometry")
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
        for name in subs:
            edge = support.Shape.getElement(name)
            self.assertLessEqual(
                min(edge.distToShape(chain)[0] for chain in chains), 1e-6,
                f"{name} names an edge that lies on no section chain")


if __name__ == "__main__":
    unittest.main(verbosity=2)
