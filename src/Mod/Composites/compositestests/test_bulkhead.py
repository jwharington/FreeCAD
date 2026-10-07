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


if __name__ == "__main__":
    unittest.main(verbosity=2)
