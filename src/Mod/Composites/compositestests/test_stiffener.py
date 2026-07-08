# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for StiffenerFP."""

import os
import tempfile
import unittest

import FreeCAD
import Part

from test_base import TestFreeCADFP


class TestStiffenerFP(TestFreeCADFP):
    """Tests for StiffenerFP."""

    def _make_support(self, name, shape):
        support = self.doc.addObject("Part::Feature", name)
        support.Shape = shape
        return support

    def _make_sketch(self, name, points):
        sketch = self.doc.addObject("Sketcher::SketchObject", name)
        for start, end in zip(points, points[1:]):
            sketch.addGeometry(Part.LineSegment(start, end), False)
        return sketch

    def _build_stiffener(
        self,
        support,
        plan_points,
        profile_points,
        *,
        mirror_x=False,
        mirror_y=False,
        direction=None,
        name="Stiffener",
    ):
        from Composites.features.Stiffener import StiffenerFP

        plan = self._make_sketch(f"{name}Plan", plan_points)
        profile = self._make_sketch(f"{name}Profile", profile_points)
        stiffener = self.doc.addObject("Part::FeaturePython", name)
        StiffenerFP(stiffener, support=support, plan=plan, profile=profile)
        stiffener.MirrorX = mirror_x
        stiffener.MirrorY = mirror_y
        if direction is not None:
            stiffener.Direction = direction
        self.doc.recompute()
        return stiffener, support, plan, profile

    def _plan_points(self):
        return [
            FreeCAD.Vector(10.0, 10.0, 0.0),
            FreeCAD.Vector(80.0, 10.0, 0.0),
        ]

    def _bent_plan_points(self):
        return [
            FreeCAD.Vector(10.0, 10.0, 0.0),
            FreeCAD.Vector(50.0, 10.0, 0.0),
            FreeCAD.Vector(50.0, 30.0, 0.0),
        ]

    def _rect_profile_points(self):
        return [
            FreeCAD.Vector(0.0, 0.0, 0.0),
            FreeCAD.Vector(0.0, 10.0, 0.0),
            FreeCAD.Vector(20.0, 10.0, 0.0),
            FreeCAD.Vector(20.0, 0.0, 0.0),
            FreeCAD.Vector(0.0, 0.0, 0.0),
        ]

    def _asymmetric_profile_points(self):
        return [
            FreeCAD.Vector(0.0, 0.0, 0.0),
            FreeCAD.Vector(0.0, 16.0, 0.0),
            FreeCAD.Vector(4.0, 16.0, 0.0),
            FreeCAD.Vector(4.0, 4.0, 0.0),
            FreeCAD.Vector(12.0, 4.0, 0.0),
            FreeCAD.Vector(12.0, 0.0, 0.0),
            FreeCAD.Vector(0.0, 0.0, 0.0),
        ]

    def assert_valid_stiffener(self, stiffener):
        self.assertIsNotNone(stiffener.Shape)
        self.assertFalse(stiffener.Shape.isNull())
        self.assertEqual(stiffener.Shape.ShapeType, "Compound")

    def test_basic_creation_on_planar_support(self):
        support = self._make_support("PlanarSupport", Part.makePlane(120.0, 60.0))
        stiffener, support, plan, profile = self._build_stiffener(
            support,
            self._plan_points(),
            self._asymmetric_profile_points(),
        )

        self.assert_valid_stiffener(stiffener)
        self.assertFalse(support.Visibility)
        self.assertFalse(plan.Visibility)
        self.assertFalse(profile.Visibility)

    @unittest.skip("Known issue: MirrorX on planar support produces null edges due to projection failure")
    @unittest.skip("Known issue: MirrorX on planar support produces null edges due to projection failure")
    def test_mirror_x_on_planar_support(self):
        support = self._make_support("PlanarSupport", Part.makePlane(120.0, 60.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            self._plan_points(),
            self._rect_profile_points(),
            mirror_x=True,
        )

        self.assert_valid_stiffener(stiffener)
        self.assertTrue(stiffener.MirrorX)
        self.assertFalse(stiffener.MirrorY)

    def test_mirror_y_on_planar_support(self):
        support = self._make_support("PlanarSupport", Part.makePlane(120.0, 60.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            self._plan_points(),
            self._rect_profile_points(),
            mirror_y=True,
        )

        self.assert_valid_stiffener(stiffener)
        self.assertFalse(stiffener.MirrorX)
        self.assertTrue(stiffener.MirrorY)

    def test_cylindrical_support_with_rect_profile(self):
        support = self._make_support("CylinderSupport", Part.makeCylinder(40.0, 120.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            self._plan_points(),
            self._rect_profile_points(),
        )

        self.assert_valid_stiffener(stiffener)

    def test_conical_support_with_oblique_direction(self):
        support = self._make_support("ConeSupport", Part.makeCone(45.0, 20.0, 120.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            self._plan_points(),
            self._rect_profile_points(),
            direction=FreeCAD.Vector(0.0, 1.0, 1.0),
        )

        self.assert_valid_stiffener(stiffener)
        self.assertEqual(stiffener.Direction, FreeCAD.Vector(0.0, 1.0, 1.0))

    @unittest.skip("Known issue: Shell support with bent plan produces null input shape during projection")
    def test_shell_support_with_bent_plan(self):
        support = self._create_shell("ShellSupport")
        stiffener, _, _, _ = self._build_stiffener(
            support,
            self._bent_plan_points(),
            self._rect_profile_points(),
        )

        self.assert_valid_stiffener(stiffener)

    def test_save_load_round_trip(self):
        support = self._make_support("SaveLoadSupport", Part.makePlane(120.0, 60.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            self._plan_points(),
            self._asymmetric_profile_points(),
        )

        filepath = os.path.join(tempfile.gettempdir(), "stiffener_round_trip.FCStd")
        try:
            self._save_document(filepath)
            loaded_doc = self._load_document(filepath)
            try:
                loaded_stiffener = loaded_doc.getObject(stiffener.Name)
                self.assertIsNotNone(loaded_stiffener)
                self.assertFalse(loaded_stiffener.Shape.isNull())
            finally:
                try:
                    loaded_doc.close()
                except Exception:
                    pass
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
