# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for MouldAnalysisFP, PartPlaneFP, and MouldFP."""

import os
import tempfile

import FreeCAD
import Part

from .test_base import TestFreeCADFP


class TestMouldAnalysis(TestFreeCADFP):
    """Tests for MouldAnalysisFP and PartPlaneFP features (Layer 3)."""

    def _make_source(self, name, shape):
        source = self.doc.addObject("Part::Feature", name)
        source.Shape = shape
        self.doc.recompute()
        return source

    def _make_mould_analysis(self, source, name="MouldAnalysis"):
        from Composites.features.MouldAnalysis import MouldAnalysisFP

        obj = self.doc.addObject("Part::FeaturePython", name)
        MouldAnalysisFP(obj, source)
        self.doc.recompute()
        return obj

    def _make_part_plane(self, source, name="PartPlane"):
        from Composites.features.PartPlane import PartPlaneFP

        obj = self.doc.addObject("Part::FeaturePython", name)
        PartPlaneFP(obj, source)
        self.doc.recompute()
        return obj

    def _make_loft_shape(self):
        base = Part.makePolygon(
            [
                FreeCAD.Vector(-12.0, -10.0, 0.0),
                FreeCAD.Vector(12.0, -10.0, 0.0),
                FreeCAD.Vector(12.0, 10.0, 0.0),
                FreeCAD.Vector(-12.0, 10.0, 0.0),
                FreeCAD.Vector(-12.0, -10.0, 0.0),
            ]
        )
        top = Part.makePolygon(
            [
                FreeCAD.Vector(-8.0, -6.0, 25.0),
                FreeCAD.Vector(8.0, -6.0, 25.0),
                FreeCAD.Vector(8.0, 6.0, 25.0),
                FreeCAD.Vector(-8.0, 6.0, 25.0),
                FreeCAD.Vector(-8.0, -6.0, 25.0),
            ]
        )
        return Part.makeLoft([Part.Wire(base), Part.Wire(top)], solid=True)

    def assert_non_null_shape(self, obj):
        self.assertIsNotNone(obj.Shape)
        self.assertFalse(obj.Shape.isNull())

    def assert_analysis_ready(self, analysis):
        self.assertNotEqual(analysis.AnalysisStatus, "Waiting for source")
        self.assertNotEqual(analysis.PartingSurfaceStatus, "Waiting for source")
        self.assertNotEqual(analysis.MouldHalvesStatus, "Waiting for source")
        self.assertNotEqual(analysis.ValidationStatus, "Waiting for source")
        self.assert_non_null_shape(analysis.PartingSurface)
        self.assert_non_null_shape(analysis.MouldHalfA)
        self.assert_non_null_shape(analysis.MouldHalfB)
        self.assertTrue(analysis.AnalysisSummary)

    def test_mould_analysis_on_cylinder(self):
        source = self._make_source("CylinderSource", Part.makeCylinder(10.0, 20.0))
        analysis = self._make_mould_analysis(source)

        self.assert_analysis_ready(analysis)
        self.assertGreaterEqual(analysis.UndercutCount, 0)
        self.assertGreaterEqual(analysis.DraftViolationCount, 0)

    def test_mould_analysis_on_box(self):
        source = self._make_source("BoxSource", Part.makeBox(20.0, 15.0, 10.0))
        analysis = self._make_mould_analysis(source, name="MouldAnalysisBox")

        self.assert_analysis_ready(analysis)
        self.assertEqual(analysis.AnalysisStatus, "Ready")
        self.assertEqual(analysis.ValidationStatus, "Pass")
        self.assertNotEqual(tuple(analysis.BestDrawDirection), (0.0, 0.0, 0.0))

    def test_part_plane_on_cylinder(self):
        source = self._make_source("CylinderSource", Part.makeCylinder(10.0, 20.0))
        part_plane = self._make_part_plane(source)

        self.assert_non_null_shape(part_plane)
        self.assertEqual(part_plane.Shape.ShapeType, "Compound")

    def test_mould_workflow_round_trip(self):
        source = self._make_source("WorkflowSource", Part.makeBox(20.0, 10.0, 12.0))
        analysis = self._make_mould_analysis(source, name="WorkflowAnalysis")
        part_plane = self._make_part_plane(source, name="WorkflowPartPlane")

        self.assert_analysis_ready(analysis)
        self.assert_non_null_shape(part_plane)

        filepath = os.path.join(tempfile.gettempdir(), "mould_workflow_round_trip.FCStd")
        try:
            self._save_document(filepath)
            reopened = FreeCAD.openDocument(filepath)
            try:
                reopened_analysis = reopened.getObject(analysis.Name)
                reopened_part_plane = reopened.getObject(part_plane.Name)
                self.assertIsNotNone(reopened_analysis)
                self.assertIsNotNone(reopened_part_plane)
                self.assertFalse(reopened_part_plane.Shape.isNull())
                self.assertNotEqual(reopened_analysis.AnalysisStatus, "Waiting for source")
            finally:
                try:
                    reopened.close()
                except Exception:
                    pass
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_mould_analysis_on_lofted_source(self):
        source = self._make_source("LoftSource", self._make_loft_shape())
        analysis = self._make_mould_analysis(source, name="MouldAnalysisLoft")

        self.assert_analysis_ready(analysis)
        # This tapered loft (wider base, narrower top) is truthfully un-releasable
        # under a planar parting at the bbox midpoint: the mould opening at the
        # parting plane is narrower than the base, so the base cannot withdraw
        # through it. With withdrawal clearance wired into the verdict, the
        # analysis reports Fail (not the historical Ready/Warning false
        # confidence). The parting surface is still produced.
        self.assertEqual(analysis.AnalysisStatus, "Fail")
        self.assertEqual(analysis.ValidationStatus, "Fail")
        self.assertTrue(analysis.PartingSurfaceSummary)

    # ── Layer 3: error paths + correctness ──────────────────────────────

    def test_mould_analysis_null_source_is_waiting(self):
        # A MouldAnalysis with no Source must not raise; it pins to the
        # documented 'Waiting for source' state.
        from Composites.features.MouldAnalysis import MouldAnalysisFP
        obj = self.doc.addObject("Part::FeaturePython", "MouldAnalysisNull")
        MouldAnalysisFP(obj, None)
        self.doc.recompute()
        self.assertEqual(obj.AnalysisStatus, "Waiting for source")
        self.assertEqual(obj.ValidationStatus, "Waiting for source")
        self.assertEqual(tuple(obj.BestDrawDirection), (0.0, 0.0, 1.0))

    def test_mould_analysis_empty_shape_is_fail(self):
        # An empty Part.Shape is a real failure (not 'Waiting') — the source
        # exists but has no geometry. Pin the actual behavior.
        source = self.doc.addObject("Part::Feature", "EmptySource")
        source.Shape = Part.Shape()
        self.doc.recompute()
        analysis = self._make_mould_analysis(source, name="MouldAnalysisEmpty")
        self.assertNotEqual(analysis.AnalysisStatus, "Ready")
        self.assertTrue(analysis.AnalysisSummary)

    def test_preferred_draw_direction_is_respected_when_valid(self):
        # The draw direction is user-specified, not auto-ranked. Setting
        # PreferredDrawDirection must drive the parting surface normal to
        # that direction (the parting plane is perpendicular to it) — the
        # contract the name always claimed but the auto-ranking path never
        # delivered.
        from Composites.features.MouldAnalysis import MouldAnalysisFP
        source = self._make_source("BoxForPref", Part.makeBox(20.0, 15.0, 10.0))
        obj = self.doc.addObject("Part::FeaturePython", "MouldAnalysisPref")
        MouldAnalysisFP(obj, source)
        obj.PreferredDrawDirection = FreeCAD.Vector(0, 1, 0)
        self.doc.recompute()
        self.assertGreaterEqual(obj.DrawDirectionScore, 0.0)
        self.assertNotEqual(obj.AnalysisStatus, "Waiting for source")
        best = obj.BestDrawDirection
        self.assertAlmostEqual(best.x, 0.0, places=6)
        self.assertAlmostEqual(best.y, 1.0, places=6)
        self.assertAlmostEqual(best.z, 0.0, places=6)
        normal = obj.PartingSurfaceNormal
        self.assertAlmostEqual(normal.x, 0.0, places=6)
        self.assertAlmostEqual(normal.y, 1.0, places=6)
        self.assertAlmostEqual(normal.z, 0.0, places=6)

    def test_parting_surface_normal_is_axis_aligned(self):
        # On a box the parting surface normal must be a unit axis vector
        # (the dominant axis of the chosen draw direction).
        source = self._make_source("BoxForParting", Part.makeBox(20.0, 20.0, 2.0))
        analysis = self._make_mould_analysis(source, name="MouldAnalysisParting")
        n = analysis.PartingSurfaceNormal
        # Exactly one component is ~±1, the others ~0
        comps = sorted([abs(n.x), abs(n.y), abs(n.z)], reverse=True)
        self.assertAlmostEqual(comps[0], 1.0, places=6)
        self.assertAlmostEqual(comps[1] + comps[2], 0.0, places=6)

    def test_mould_halves_persist_across_reload(self):
        # Extended round-trip: the analysis result (not just the shape) must
        # survive save/reload — AnalysisStatus, BestDrawDirection, and the
        # mould-half shapes.
        source = self._make_source("ReloadSource", Part.makeBox(20.0, 10.0, 12.0))
        analysis = self._make_mould_analysis(source, name="ReloadAnalysis")
        best_before = tuple(analysis.BestDrawDirection)
        status_before = analysis.AnalysisStatus

        filepath = os.path.join(tempfile.gettempdir(), "mould_reload.FCStd")
        try:
            self._save_document(filepath)
            reopened = FreeCAD.openDocument(filepath)
            try:
                ra = reopened.getObject(analysis.Name)
                self.assertIsNotNone(ra)
                self.assertEqual(ra.AnalysisStatus, status_before)
                self.assertEqual(tuple(ra.BestDrawDirection), best_before)
                self.assertFalse(ra.MouldHalfA.Shape.isNull())
                self.assertFalse(ra.MouldHalfB.Shape.isNull())
            finally:
                try:
                    reopened.close()
                except Exception:
                    pass
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_part_plane_on_box(self):
        # PartPlane should produce a non-null compound on a simple box too
        # (the existing test only covers a cylinder).
        source = self._make_source("BoxForPP", Part.makeBox(20.0, 15.0, 10.0))
        part_plane = self._make_part_plane(source, name="PartPlaneBox")
        self.assert_non_null_shape(part_plane)

    def test_part_plane_null_source_does_not_crash(self):
        # PartPlaneFP.execute has no null-source guard (it calls
        # make_parting_surface3(fp.Source.Shape) directly). Pin the actual
        # behavior — it must not abort the recompute; it may produce a null
        # shape or raise a caught exception.
        from Composites.features.PartPlane import PartPlaneFP
        obj = self.doc.addObject("Part::FeaturePython", "PartPlaneNull")
        PartPlaneFP(obj, None)
        # Recompute must not raise — whatever happens is contained.
        try:
            self.doc.recompute()
        except Exception as exc:
            self.fail(f"PartPlane recompute raised on null source: {exc}")
