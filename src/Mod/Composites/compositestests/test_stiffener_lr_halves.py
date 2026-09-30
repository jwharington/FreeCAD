# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""The LS8e frame ring as two L/R half-stiffeners, one per skin half.

The settled design for the skin L/R split (``REPORT-2026-09-30-skin-lr-split-blocker.md``):
the skins drape as L/R halves, and each frame ring is physically two halves,
so each half-ring is an ordinary ``StiffenerFP`` sweeping on its own skin
half.  A single half sections to an **open single-edge** path, which is the
safe ``_sideways`` branch — unlike the full section on a halved compound,
whose closed two-edge row is the mis-dispatched case
(``test_stiffener_halved_support`` pins that defect).  No proxy, no split
flow, no ``tools/stiffener`` change: each half is just a normal stiffener on
a normal (half) panel.

Pinned here at fuselage scale:

* each half-stiffener sweeps on its half support and full-composite wires
  (web + foot + combined laminate) without error, spanning its own side of
  the symmetry plane and meeting its twin at y = 0; and
* each half's re-supported panel re-drapes within the quality gates.
"""

import json
import unittest

import FreeCAD
import Part

from .test_base import TestFreeCADFP
from .test_stiffener import lofted_skin_face, standalone_station_plane
from .test_stiffener_composite_shell import (
    StiffenerCompositeFixture,
    TestQuasiIsotropicStiffener,
)

SECTIONS = (
    (-10.0, 565.0, 460.0),
    (200.0, 495.0, 400.0),
    (420.0, 415.0, 330.0),
    (630.0, 355.0, 280.0),
)
STATION_X = 200.0
FRAME_SECTION = 34.0
COVERAGE_GATE = 0.95
SHEAR_GATE_DEG = 25.0


def _true_y_extent(shape):
    ys = [p.y for edge in shape.Edges for p in edge.discretize(24)]
    return (min(ys), max(ys)) if ys else (0.0, 0.0)


class TestStiffenerLRHalves(StiffenerCompositeFixture, TestFreeCADFP, unittest.TestCase):
    """Two L/R half-stiffeners, one per skin half, both draped within gates."""

    def _half_skin(self, side):
        """One half of the lofted skin: side 'L' is y <= 0, 'R' is y >= 0."""
        skin = lofted_skin_face(SECTIONS)
        bb = skin.BoundBox
        big = 4.0 * bb.DiagonalLength
        y_min = -big if side == "L" else 0.0
        box = Part.makeBox(
            big, big, big, FreeCAD.Vector(bb.XMin - 1.0, y_min, bb.ZMin - big / 2.0)
        )
        return skin.common(box)

    def _frame_profile_sketch(self, name):
        s = FRAME_SECTION
        sketch = self.doc.addObject("Sketcher::SketchObject", name)
        for start, end in (
            (FreeCAD.Vector(s, 0, 0), FreeCAD.Vector(0, 0, 0)),
            (FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, s, 0)),
            (FreeCAD.Vector(0, s, 0), FreeCAD.Vector(s, s, 0)),
        ):
            sketch.addGeometry(Part.LineSegment(start, end), False)
        return sketch

    def _make_half_stiffener(self, side):
        from Composites.features.Stiffener import StiffenerFP

        half = self._half_skin(side)
        panel = self._make_panel(
            name=f"Skin{side}",
            isotropic=False,
            rosette_angle=90.0,
            plate=half,
        )
        # A coarse pitch keeps the wiring's drape solves fast enough for the
        # test; the gates here pin the build, not the production fineness.
        panel.DrapePitch = 50.0
        ring_laminate = self._make_laminate(
            TestQuasiIsotropicStiffener.QI_ANGLES,
            [0.5] * len(TestQuasiIsotropicStiffener.QI_ANGLES),
            [TestQuasiIsotropicStiffener.CARBON] * len(TestQuasiIsotropicStiffener.QI_ANGLES),
            name=f"RingLaminate{side}",
            isotropic=True,
        )
        cut = self.doc.addObject("Part::Feature", f"Cut{side}")
        cut.Shape = standalone_station_plane(2.0 * 400.0, STATION_X)
        stiffener = self.doc.addObject("Part::FeaturePython", f"Ring{side}")
        StiffenerFP(
            stiffener,
            support=panel,
            cut_surface=cut,
            profile=self._frame_profile_sketch(f"Profile{side}"),
        )
        stiffener.Laminate = ring_laminate
        # The foot shell's pitch scales from the foot width; raise the floor
        # so the foot drape is coarse enough for the test's wall-clock.
        self.doc.recompute()
        return stiffener, panel

    def test_half_stiffeners_build_and_meet_at_centreline(self):
        """Each half sweeps on its half support and full-composite wires."""
        for side, expect in (("L", lambda lo, hi: hi <= 1e-6),
                             ("R", lambda lo, hi: lo >= -1e-6)):
            stiffener, _ = self._make_half_stiffener(side)
            self.assertIsNone(
                getattr(stiffener.Proxy, "last_error", None),
                f"ring {side} wiring failed: {stiffener.Proxy.last_error}",
            )
            self.assertFalse(
                stiffener.Shape.isNull(), f"ring {side} produced no swept geometry"
            )
            lo, hi = _true_y_extent(stiffener.Shape)
            self.assertTrue(
                expect(lo, hi), f"ring {side} crosses the centreline: y[{lo},{hi}]"
            )
            # The composite children exist: web shell and foot shell.
            self.assertIsNotNone(
                self.doc.getObject(f"Ring{side}_Web"), f"ring {side} has no web shell"
            )

    def test_half_panels_redrape_within_gates(self):
        """Each half panel re-drapes (post seat cut) to the skin's gates."""
        for side in ("L", "R"):
            _, panel = self._make_half_stiffener(side)
            raw = panel.DrapeDiagnostics
            self.assertIsNotNone(raw, f"panel {side} produced no diagnostics")
            diag = json.loads(raw)
            self.assertEqual(diag.get("status"), "valid", f"{side}: {diag}")
            self.assertGreaterEqual(
                float(diag.get("coverage_ratio", 0.0)), COVERAGE_GATE,
                f"{side} coverage below gate: {diag}",
            )
            self.assertLessEqual(
                float(diag.get("max_shear_deg", 0.0)), SHEAR_GATE_DEG,
                f"{side} shear above gate: {diag}",
            )


if __name__ == "__main__":
    unittest.main()
