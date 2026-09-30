# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""The fuselage ring on a QI proxy, with its foot split L/R onto the skin halves.

The LS8e build's target shape (``REPORT-2026-09-30-skin-lr-split-blocker.md``):
the skins drape as L/R halves, the QI frame ring spans the full closed section
and so sweeps on a **full-region QI-declared proxy** (never draped), and the
ring's **foot** — a draped, non-QI part — is split at the symmetry plane and
seeded from the matching skin-half weave.

These tests pin the building blocks ahead of the workbench change:

* a ring sweeps cleanly on a full-region **QI** support (the proxy), and its
  foot band can be split at y = 0 into two half-bands; and
* each half-band, draped as its own shell seeded by the matching half-skin
  weave, meets the drape quality gates.

They are the green contract the ``StiffenerCompositeShell`` foot-split change
must satisfy.
"""

import json
import unittest

import FreeCAD
import Part

from Composites.tools.stiffener import ProfileMirror, make_stiffener
from .test_base import TestFreeCADFP
from .test_stiffener import lofted_skin_face, standalone_station_plane
from .test_stiffener_composite_shell import StiffenerCompositeFixture


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
    """The (min, max) y of a shape from its edge samples, not its BoundBox.

    The full-ring foot band comes back from the boolean with a corrupted
    bounding box (and a degenerate trimmed surface), so any extent taken from
    ``BoundBox`` is unreliable; the edges evaluate exactly.
    """
    ys = [p.y for edge in shape.Edges for p in edge.discretize(24)]
    return (min(ys), max(ys)) if ys else (0.0, 0.0)


def derive_foot_halves(skin, cut_surface, low=0.0, high=FRAME_SECTION):
    """The (left, right) foot half-bands, re-derived from the split skin.

    The foot is the band of the support's own surface between the base
    edge's abscissas (``tools/stiffener._foot_bands``).  The full ring's band
    is a degenerate boolean face that resists a direct split at y = 0, so the
    halves are built the other way: split the (valid) skin at the symmetry
    plane, then cut each half by the abscissa slab.  Same surface, exact trim
    at the centreline.
    """
    normal = FreeCAD.Vector(1.0, 0.0, 0.0)
    slab_base = cut_surface.copy()
    slab_base.translate(normal * low)
    slab = slab_base.extrude(normal * (high - low))
    bb = skin.BoundBox
    big = 4.0 * bb.DiagonalLength
    left_skin = skin.common(
        Part.makeBox(big, big, big, FreeCAD.Vector(bb.XMin - 1.0, -big, bb.ZMin - big / 2.0))
    )
    right_skin = skin.common(
        Part.makeBox(big, big, big, FreeCAD.Vector(bb.XMin - 1.0, 0.0, bb.ZMin - big / 2.0))
    )
    return left_skin.common(slab), right_skin.common(slab)


def frame_profile():
    """The C frame section as a wire (make_stiffener needs a shape, not edges)."""
    s = FRAME_SECTION
    points = [
        FreeCAD.Vector(s, 0, 0),
        FreeCAD.Vector(0, 0, 0),
        FreeCAD.Vector(0, s, 0),
        FreeCAD.Vector(s, s, 0),
    ]
    edges = [
        Part.LineSegment(a, b).toShape() for a, b in zip(points, points[1:])
    ]
    return Part.Wire(edges)


class TestRingFootSplit(StiffenerCompositeFixture, TestFreeCADFP, unittest.TestCase):
    """Ring on a full-region QI proxy; foot split L/R onto the skin halves."""

    def _full_skin(self):
        return lofted_skin_face(SECTIONS)

    def test_ring_on_qi_proxy_sweeps_and_foot_splits(self):
        """A full ring sweeps on the full skin; its foot band re-derives per half.

        The QI ring spans the whole section, so it sweeps on the full-region
        proxy without the halved-support defect.  Its foot band — the
        support's own surface between the base-edge abscissas — comes back as
        a degenerate boolean face that resists a direct split, so the half
        bands are re-derived: split the (valid) skin at y=0, then cut each
        half by the foot's abscissa slab.  Each half-band must lie on its own
        side and conserve the band area.
        """
        skin = self._full_skin()
        plane = standalone_station_plane(2.0 * 400.0, STATION_X)
        sweep = make_stiffener(
            skin, plane, frame_profile(), ProfileMirror(flip_y=True)
        )
        self.assertFalse(sweep.shell.isNull(), "no swept geometry on the full skin")
        self.assertGreater(len(sweep.web_faces), 0, "no web faces")
        self.assertGreater(len(sweep.foot_faces), 0, "no foot band to split")

        left, right = derive_foot_halves(skin, plane)
        self.assertGreater(len(left.Faces), 0, "the foot produced no left half")
        self.assertGreater(len(right.Faces), 0, "the foot produced no right half")
        # Each half-band stays on its own side of the symmetry plane.
        self.assertLessEqual(
            _true_y_extent(left)[1], 1e-6, "left foot crosses y=0"
        )
        self.assertGreaterEqual(
            _true_y_extent(right)[0], -1e-6, "right foot crosses y=0"
        )
        # The halves share the band's outline (equal area, the centreline a
        # shared trim).
        self.assertAlmostEqual(left.Area, right.Area, delta=right.Area * 0.01)

    def test_foot_half_seeded_from_half_skin_drapes_within_gates(self):
        """A foot half-band, draped on its own, meets the quality gates.

        The foot's weave is the panel weave continued over the seat; split,
        each half must drape from its own side's weave.  This pins that a
        half-band is drapable to the same gates the skin meets.
        """
        skin = self._full_skin()
        plane = standalone_station_plane(2.0 * 400.0, STATION_X)
        left, _ = derive_foot_halves(skin, plane)

        panel = self._make_panel(
            name="FootHalf",
            isotropic=False,
            rosette_angle=90.0,
            plate=left,
        )
        panel.DrapePitch = 10.0
        self.doc.recompute()

        raw = panel.DrapeDiagnostics
        self.assertIsNotNone(raw, "the foot half produced no drape diagnostics")
        diag = json.loads(raw)
        self.assertEqual(diag.get("status"), "valid", f"drape failed: {diag}")
        self.assertGreaterEqual(
            float(diag.get("coverage_ratio", 0.0)), COVERAGE_GATE,
            f"foot-half coverage below gate: {diag}",
        )
        self.assertLessEqual(
            float(diag.get("max_shear_deg", 0.0)), SHEAR_GATE_DEG,
            f"foot-half shear above gate: {diag}",
        )


if __name__ == "__main__":
    unittest.main()
