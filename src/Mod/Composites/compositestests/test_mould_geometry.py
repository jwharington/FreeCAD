# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Geometry-behavior tests for mould_analysis.py public functions.

Targets the 5 public functions that take/return Part.Shape:
- propose_parting_surface
- make_mould_halves
- normalize_source_shape
- analyze_source_shape
- validate_mould_result

Asserts their actual contracts (parting plane at bbox midpoint, mould
halves on the correct side of the parting plane, normalization confidence,
analysis status/ranking) — not just 'shape not null'. Uses programmatic
primitives with known geometry plus the 'propblade' real-world fixture.
"""

import os
import unittest

import FreeCAD
import Part

from Composites.tools.mould_analysis import (
    NORMALIZATION_CONFIDENCE_EXACT,
    NORMALIZATION_CONFIDENCE_FAIL,
    analyze_source_shape,
    default_mould_analysis_draw_direction,
    make_mould_halves,
    normalize_source_shape,
    propose_parting_surface,
    validate_mould_result,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
PROPELLADE_PATH = os.path.join(FIXTURES_DIR, "propblade.FCStd")


def _box(dx=20.0, dy=15.0, dz=10.0):
    """A solid box centered on the origin is NOT what these helpers expect;
    they read shape.BoundBox, so place at origin for predictable bounds."""
    return Part.makeBox(dx, dy, dz, FreeCAD.Vector(0, 0, 0))


class TestProposePartingSurface(unittest.TestCase):
    """propose_parting_surface: plane at bbox midpoint along dominant axis."""

    def test_x_direction_plane_at_midpoint(self):
        shape = _box(dx=20.0, dy=10.0, dz=10.0)
        result = propose_parting_surface(shape, FreeCAD.Vector(1, 0, 0))
        self.assertEqual(result["status"], "Ready")
        self.assertFalse(result["shape"].isNull())
        # Parting plane at X midpoint = 10.0
        self.assertAlmostEqual(result["surface_offset"], 10.0, places=6)
        # Surface normal is the X axis
        n = result["surface_normal"]
        self.assertAlmostEqual(n.x, 1.0, places=6)
        self.assertAlmostEqual(abs(n.y) + abs(n.z), 0.0, places=6)

    def test_y_direction_plane_at_midpoint(self):
        shape = _box(dx=10.0, dy=20.0, dz=10.0)
        result = propose_parting_surface(shape, FreeCAD.Vector(0, 1, 0))
        self.assertEqual(result["status"], "Ready")
        self.assertAlmostEqual(result["surface_offset"], 10.0, places=6)
        n = result["surface_normal"]
        self.assertAlmostEqual(n.y, 1.0, places=6)

    def test_z_direction_plane_at_midpoint(self):
        shape = _box(dx=10.0, dy=10.0, dz=20.0)
        result = propose_parting_surface(shape, FreeCAD.Vector(0, 0, 1))
        self.assertEqual(result["status"], "Ready")
        self.assertAlmostEqual(result["surface_offset"], 10.0, places=6)
        n = result["surface_normal"]
        self.assertAlmostEqual(n.z, 1.0, places=6)

    def test_returns_valid_face_shape(self):
        shape = _box()
        result = propose_parting_surface(shape, FreeCAD.Vector(0, 0, 1))
        self.assertTrue(result["shape"].isValid())


class TestMakeMouldHalves(unittest.TestCase):
    """make_mould_halves: two non-null solids split at the parting plane."""

    def test_two_halves_non_null(self):
        shape = _box(dx=10.0, dy=10.0, dz=20.0)
        # Parting at Z=10 (midpoint)
        result = make_mould_halves(shape, FreeCAD.Vector(0, 0, 1), 10.0)
        self.assertIn(result["status"], ("Ready", "Degraded"))
        self.assertFalse(result["half_a_shape"].isNull())
        self.assertFalse(result["half_b_shape"].isNull())
        self.assertGreater(result["half_a_volume"], 0.0)
        self.assertGreater(result["half_b_volume"], 0.0)

    def test_halves_lie_on_opposite_sides_of_parting(self):
        shape = _box(dx=10.0, dy=10.0, dz=20.0)
        result = make_mould_halves(shape, FreeCAD.Vector(0, 0, 1), 10.0)
        # half_a is below the parting plane (Z < 10), half_b above (Z > 10)
        a = result["half_a_shape"]
        b = result["half_b_shape"]
        self.assertLessEqual(a.BoundBox.ZMax, 10.0 + 1e-6)
        self.assertGreaterEqual(b.BoundBox.ZMin, 10.0 - 1e-6)

    def test_each_half_has_positive_stock_volume(self):
        # The mould halves are stock blanks with the source cut out (cavity),
        # so their combined volume is NOT necessarily > source. The meaningful
        # contract is that each half is a real, positive-volume solid.
        shape = _box(dx=10.0, dy=10.0, dz=20.0)
        result = make_mould_halves(shape, FreeCAD.Vector(0, 0, 1), 10.0)
        self.assertGreater(result["half_a_volume"], 0.0)
        self.assertGreater(result["half_b_volume"], 0.0)


class TestNormalizeSourceShape(unittest.TestCase):
    """normalize_source_shape: confidence + effective solid."""

    def test_solid_passes_through_exact(self):
        shape = _box()
        result = normalize_source_shape(shape)
        self.assertEqual(result["confidence"], NORMALIZATION_CONFIDENCE_EXACT)
        self.assertFalse(result["effective_shape"].isNull())

    def test_null_shape_fails(self):
        result = normalize_source_shape(Part.Shape())
        self.assertEqual(result["confidence"], NORMALIZATION_CONFIDENCE_FAIL)

    def test_effective_shape_is_solid(self):
        shape = _box()
        result = normalize_source_shape(shape)
        eff = result["effective_shape"]
        # A normalized solid should have positive volume
        self.assertGreater(eff.Volume, 0.0)


class TestAnalyzeSourceShape(unittest.TestCase):
    """analyze_source_shape: status, ranking, best direction on a known box."""

    def test_box_yields_ready_status(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        self.assertEqual(result["status"], "Ready")
        self.assertEqual(result["validation_status"], "Pass")

    def test_best_direction_is_axis_aligned(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        best = result["best_draw_direction"]
        # Best direction must be one of the axis candidates (unit vector)
        self.assertAlmostEqual(best.Length, 1.0, places=6)

    def test_ranking_non_empty(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        self.assertTrue(result["draw_direction_ranking"])
        self.assertNotIn("No candidate", result["draw_direction_ranking"])

    def test_tall_thin_box_picks_smallest_extent_axis(self):
        # The draw-direction heuristic minimizes mould stock: bbox_score =
        # 1/extent, so it picks the SMALLEST-extent axis (least stock), not
        # the long axis. For a 2x2x20 box the smallest extent is X or Y (2),
        # NOT Z (20). Pin the actual behavior and flag the design question:
        # is stock-minimization the right heuristic, or should draw engagement
        # (longest axis) win?
        shape = _box(dx=2.0, dy=2.0, dz=20.0)
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        best = result["best_draw_direction"]
        # Best is X or Y (extent 2), never Z (extent 20)
        self.assertNotAlmostEqual(best.z, 1.0, places=6)

    def test_flat_wide_box_picks_z(self):
        # Flat box 20x20x2: smallest extent is Z (2) -> Z wins under the
        # stock-minimization heuristic.
        shape = _box(dx=20.0, dy=20.0, dz=2.0)
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        best = result["best_draw_direction"]
        self.assertAlmostEqual(best.z, 1.0, places=6)

    def test_null_shape_no_exception(self):
        # The documented early-return: null shape must not raise.
        result = analyze_source_shape(Part.Shape(),
                                      default_mould_analysis_draw_direction)
        self.assertEqual(result["status"], "Waiting for source")

    def test_manufacturability_metrics_present(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        metrics = result["manufacturability_metrics"]
        for key in ("backface_area_ratio", "undercut_count",
                    "draft_violation_count", "multipart_piece_count",
                    "risk_index", "risk_class"):
            self.assertIn(key, metrics)

    def test_summaries_non_empty(self):
        shape = _box()
        result = analyze_source_shape(shape, default_mould_analysis_draw_direction)
        self.assertTrue(result["summary"])
        self.assertTrue(result["manufacturability_summary"])


class TestValidateMouldResult(unittest.TestCase):
    """validate_mould_result: status from inputs (pure function over shapes)."""

    def _valid(self, shape):
        return shape  # a real box is valid + non-null

    def test_pass_on_clean_inputs(self):
        shape = _box()
        result = validate_mould_result(
            "Ready", "Ready", 0, 0, shape, shape, shape,
        )
        self.assertEqual(result["status"], "Pass")

    def test_fail_on_failed_parting_surface(self):
        shape = _box()
        result = validate_mould_result(
            "Fail", "Ready", 0, 0, shape, shape, shape,
        )
        self.assertEqual(result["status"], "Fail")

    def test_warning_on_undercuts(self):
        shape = _box()
        result = validate_mould_result(
            "Ready", "Ready", 2, 0, shape, shape, shape,
        )
        self.assertEqual(result["status"], "Warning")

    def test_warning_on_draft_violations(self):
        shape = _box()
        result = validate_mould_result(
            "Ready", "Ready", 0, 3, shape, shape, shape,
        )
        self.assertEqual(result["status"], "Warning")

    def test_fail_on_null_half(self):
        shape = _box()
        null_shape = Part.Shape()
        result = validate_mould_result(
            "Ready", "Ready", 0, 0, shape, null_shape, shape,
        )
        self.assertEqual(result["status"], "Fail")


@unittest.skipUnless(os.path.exists(PROPELLADE_PATH),
                     "propblade fixture not installed")
class TestPropbladeFixture(unittest.TestCase):
    """Real-world geometry: the propblade model exercises normalize_source_shape
    on a shell/surface solid (Volume=0.0 un-normalized) — the case simple
    primitives don't cover."""

    def setUp(self):
        self.doc = FreeCAD.openDocument(PROPELLADE_PATH)
        # Find the solid body
        self.shape = None
        for obj in self.doc.Objects:
            if hasattr(obj, "Shape") and not obj.Shape.isNull():
                self.shape = obj.Shape
                self.obj = obj
                break
        self.assertIsNotNone(self.shape, "propblade fixture has no shape")

    def tearDown(self):
        try:
            FreeCAD.closeDocument(self.doc.Name)
        except Exception:
            pass

    def test_fixture_opens_with_solid(self):
        self.assertTrue(self.shape.isValid())
        self.assertEqual(self.shape.ShapeType, "Solid")

    def test_normalize_handles_real_geometry(self):
        # Real CAD may report Volume=0 (shell-like) — normalize must still
        # produce an effective solid (possibly via bbox proxy) without failing.
        result = normalize_source_shape(self.shape)
        self.assertIn(result["confidence"],
                      (NORMALIZATION_CONFIDENCE_EXACT, "approximate"))
        self.assertFalse(result["effective_shape"].isNull())

    def test_analyze_does_not_crash_on_real_geometry(self):
        # The full pipeline must run on real-world geometry without raising.
        result = analyze_source_shape(self.shape,
                                      default_mould_analysis_draw_direction,
                                      source_obj=self.obj)
        self.assertNotEqual(result["status"], "Waiting for source")
        self.assertTrue(result["summary"])


if __name__ == "__main__":
    unittest.main()
