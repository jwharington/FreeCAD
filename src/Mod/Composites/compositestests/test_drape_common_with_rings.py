# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""The common drape survives the rings at fuselage scale.

Lap joint (owner decision 2026-09-30): the panel drapes once, before any
stiffener, and its weave runs continuously under the ring's foot.  This
was ``test_drape_on_resupported_panel``, which pinned the old
weave-exclusivity architecture — the panel re-draped on the seat
remainder after the ring's seat cut, and that re-drape had to meet the
same quality gates as the first drape.  That re-drape no longer happens
(it was the source of the multi-island seeding defect); the pin becomes:
wiring the ring leaves the panel's *common* drape in place, and that
common drape still meets the gates on the full fuselage-scale skin.
"""

import json
import unittest

import FreeCAD
import Part

from .test_stiffener import lofted_skin_face
from .test_stiffener_composite_shell import (
    StiffenerCompositeFixture,
    TestQuasiIsotropicStiffener,
)


class TestDrapeCommonWithRings(StiffenerCompositeFixture, unittest.TestCase):
    """Wiring the ring leaves the common drape in place, gates met."""

    # Fuselage-scale station: frame_0's ellipse, its section 34 mm aft.
    STATION_X = -10.0
    FRAME_SECTION = 34.0
    SHEAR_GATE_DEG = 25.0
    COVERAGE_GATE = 0.95

    def _make_sketch(self, name, strokes):
        sketch = self.doc.addObject("Sketcher::SketchObject", name)
        for start, end in strokes:
            sketch.addGeometry(Part.LineSegment(start, end), False)
        return sketch

    def _ring_cut_surface(self, name):
        """The station plane as a plain centred plane face."""
        side = 2.0 * 400.0
        rotation = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(1, 0, 0))
        face = Part.makePlane(side, side)
        corner = rotation.multVec(FreeCAD.Vector(side / 2.0, side / 2.0, 0.0))
        face.Placement = FreeCAD.Placement(
            FreeCAD.Vector(self.STATION_X, 0.0, 0.0) - corner, rotation
        )
        return self.doc.addObject("Part::Feature", name), face

    def _coverage(self, panel):
        raw = getattr(panel, "DrapeDiagnostics", None)
        if not raw:
            return None
        return json.loads(raw).get("coverage_ratio")

    def test_common_drape_survives_the_ring(self):
        """Wiring the ring neither re-drapes the panel nor breaks the gates."""
        from Composites.features.Stiffener import StiffenerFP

        sections = (
            (-10.0, 565.0, 460.0),
            (200.0, 495.0, 400.0),
            (420.0, 415.0, 330.0),
            (630.0, 355.0, 280.0),
        )
        panel = self._make_panel(
            name="SkinPanel",
            isotropic=False,
            rosette_angle=90.0,
            plate=lofted_skin_face(sections),
            pitch=25.0,
        )
        ring_laminate = self._make_laminate(
            TestQuasiIsotropicStiffener.QI_ANGLES,
            [0.5] * len(TestQuasiIsotropicStiffener.QI_ANGLES),
            [TestQuasiIsotropicStiffener.CARBON] * len(TestQuasiIsotropicStiffener.QI_ANGLES),
            name="RingLaminate",
            isotropic=True,
        )

        cut_object, face = self._ring_cut_surface("RingCutSurface")
        cut_object.Shape = face
        profile = self._make_sketch(
            "RingProfile",
            [
                (FreeCAD.Vector(self.FRAME_SECTION, 0.0, 0.0), FreeCAD.Vector(0.0, 0.0, 0.0)),
                (FreeCAD.Vector(0.0, 0.0, 0.0), FreeCAD.Vector(0.0, self.FRAME_SECTION, 0.0)),
                (
                    FreeCAD.Vector(0.0, self.FRAME_SECTION, 0.0),
                    FreeCAD.Vector(self.FRAME_SECTION, self.FRAME_SECTION, 0.0),
                ),
            ],
        )
        stiffener = self.doc.addObject("Part::FeaturePython", "FrameRing")
        StiffenerFP(
            stiffener, support=panel, cut_surface=cut_object, profile=profile
        )
        stiffener.Laminate = ring_laminate
        self.doc.recompute()

        self.assertIsNone(
            getattr(stiffener.Proxy, "last_error", None),
            f"ring wiring failed: {stiffener.Proxy.last_error}",
        )

        # The common drape: the panel's support was never re-pointed and
        # its solved coverage is exactly what the first drape measured.
        coverage_before = self._coverage(panel)
        self.assertIsNotNone(coverage_before, "the common drape is unmeasured")
        self.assertGreaterEqual(
            coverage_before,
            self.COVERAGE_GATE,
            "the common drape's coverage fell below the gate",
        )
        raw = panel.DrapeDiagnostics
        diag = json.loads(raw)
        self.assertEqual(diag.get("status"), "valid")
        self.assertLessEqual(
            float(diag.get("max_shear_deg", 0.0)),
            self.SHEAR_GATE_DEG,
            "the common drape's shear exceeded the gate",
        )