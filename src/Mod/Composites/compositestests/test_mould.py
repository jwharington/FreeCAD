# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for MouldAnalysisFP, PartPlaneFP, and MouldFP."""

import os
import tempfile

import FreeCAD
import Part

from .test_base import TestFreeCADFP


class TestMouldAnalysis(TestFreeCADFP):
    """Tests for MouldAnalysisFP and PartPlaneFP features."""

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
        self.assertTrue(analysis.DrawDirectionRanking)
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
        self.assertTrue(analysis.PartingSurfaceSummary)
