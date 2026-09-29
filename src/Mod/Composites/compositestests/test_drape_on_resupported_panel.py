# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Draping on a re-supported panel keeps the layup quality.

Regression for the fuselage's frame rings on their real skin: the ring's
seat is consumed and the panel re-drapes on the remainder — a boolean-cut
face whose boundary includes the seat's trim — and that re-drape fired
hundreds of ``BOUNDARY-LINK-BORN-OFF-EDGE`` traps (boundary links stopping
up to 1210 mm short of the part edge, mean 271 mm) while the coverage
diagnostic reported a flat 1.0 and the shear blew the 25 deg gate (measured
38.9 deg on the fwd skin's remainder, nextdrape diagnostics 2026-09-30).
The re-drape must meet the same quality gates as the first drape: this
test pins them.
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


def z_profile_points():
    """A Z-section with a foot: base flange, web, top flange (open)."""
    return [
        FreeCAD.Vector(0.0, 0.0, 0.0),
        FreeCAD.Vector(20.0, 0.0, 0.0),
        FreeCAD.Vector(20.0, 10.0, 0.0),
        FreeCAD.Vector(0.0, 10.0, 0.0),
    ]


class TestDrapeOnResupportedPanel(StiffenerCompositeFixture, unittest.TestCase):
    """The panel's re-drape after a ring's seat cut meets the quality gates."""

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

    def test_redrape_on_remainder_keeps_layup_quality(self):
        """After the ring's seat cut, the panel's re-drape meets the gates."""
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

        # The panel re-draped on the remainder: its diagnostics must meet
        # the layup quality gates the first drape meets.
        raw = panel.DrapeDiagnostics
        self.assertIsNotNone(raw, "the panel re-drape produced no diagnostics")
        diag = json.loads(raw)
        self.assertEqual(diag.get("status"), "valid")
        self.assertGreaterEqual(
            float(diag.get("coverage_ratio", 0.0)),
            self.COVERAGE_GATE,
            "the re-drape's coverage fell below the gate",
        )
        self.assertLessEqual(
            float(diag.get("max_shear_deg", 0.0)),
            self.SHEAR_GATE_DEG,
            "the re-drape's shear exceeded the gate",
        )
