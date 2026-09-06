# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Comprehensive scenario tests for AlignFibreRosette feature type."""

import math
import os
import tempfile

import FreeCAD
import Part

from .test_base import TestFreeCADFP


class TestAlignFibreRosetteScenarios(TestFreeCADFP):
    """Comprehensive scenario tests for AlignFibreRosette feature types."""

    def _make_laminate(self):
        from Composites.features.Laminate import LaminateFP
        laminate = self.doc.addObject("Part::FeaturePython", "Laminate")
        LaminateFP(laminate)
        self.doc.recompute()
        return laminate

    def _make_shell(self, support_shape, name="Shell"):
        from Composites.features.CompositeShell import CompositeShellFP
        support = self.doc.addObject("Part::Feature", "Support")
        support.Shape = support_shape
        laminate = self._make_laminate()
        shell = self.doc.addObject("Part::FeaturePython", name)
        CompositeShellFP(shell, support)
        shell.Laminate = laminate
        self.doc.recompute()
        return shell

    def _make_align_fibre_rosette(self, name="AlignFibreRosette", support=None, composite_shell=None, second_point=None):
        from Composites.features.AlignFibreRosette import AlignFibreRosetteFP
        align = self.doc.addObject("Part::FeaturePython", name)
        AlignFibreRosetteFP(align, support=support, composite_shell=composite_shell, second_point=second_point)
        return align

    def _make_point(self, name, position):
        obj = self.doc.addObject("Part::Feature", name)
        obj.Shape = Part.makeSphere(0.1, position)
        self.doc.recompute()
        return obj

    def _make_flat_plate(self, size=(100.0, 100.0, 1.0)):
        return Part.makeBox(*size)

    def _make_cylinder_shell(self, radius=50.0, height=100.0):
        return Part.makeCylinder(radius, height)

    def test_align_fibre_rosette_basic(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        align = self._make_align_fibre_rosette(support=(shell.Support, ["Face1"]), composite_shell=shell)
        self.doc.recompute()
        self.assertIsNotNone(align)

    def test_align_fibre_rosette_with_second_point(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        align = self._make_align_fibre_rosette(support=(shell.Support, ["Face1"]), composite_shell=shell)
        face = shell.Support.Shape.Face1
        p = face.valueAt(0.3, 0.3)
        pt = self._make_point("Pt", p)
        align.SecondPoint = (pt, ["Vertex1"])
        self.doc.recompute()
        self.assertIsNotNone(align.SecondPoint)

    def test_align_fibre_rosette_different_angles(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        for init_angle in [0.0, 45.0, -45.0]:
            align = self._make_align_fibre_rosette(support=(shell.Support, ["Face1"]), composite_shell=shell)
            align.Angle = init_angle
            self.doc.recompute()
            self.assertAlmostEqual(float(align.Angle), init_angle, places=6)

    def test_align_fibre_rosette_curved_support(self):
        cyl_shape = self._make_cylinder_shell()
        shell = self._make_shell(cyl_shape)
        align = self._make_align_fibre_rosette(support=(shell.Support, ["Face1"]), composite_shell=shell)
        self.doc.recompute()
        self.assertIsNotNone(align)

    def test_align_fibre_rosette_multiple_points(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        align = self._make_align_fibre_rosette(support=(shell.Support, ["Face1"]), composite_shell=shell)
        face = shell.Support.Shape.Face1
        p1 = face.valueAt(0.3, 0.3)
        pt1 = self._make_point("Pt1", p1)
        align.SecondPoint = (pt1, ["Vertex1"])
        self.doc.recompute()
        p2 = face.valueAt(0.7, 0.7)
        pt2 = self._make_point("Pt2", p2)
        align.SecondPoint = (pt2, ["Vertex1"])
        self.doc.recompute()
        self.assertIsNotNone(align.SecondPoint)

    def test_align_fibre_rosette_near_origin(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        align = self._make_align_fibre_rosette(support=(shell.Support, ["Face1"]), composite_shell=shell)
        face = shell.Support.Shape.Face1
        p = face.valueAt(0.1, 0.1)
        pt = self._make_point("Pt", p)
        align.SecondPoint = (pt, ["Vertex1"])
        self.doc.recompute()
        self.assertIsNotNone(align.SecondPoint)

    def test_align_fibre_rosette_far_from_origin(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        align = self._make_align_fibre_rosette(support=(shell.Support, ["Face1"]), composite_shell=shell)
        face = shell.Support.Shape.Face1
        p = face.valueAt(0.9, 0.9)
        pt = self._make_point("Pt", p)
        align.SecondPoint = (pt, ["Vertex1"])
        self.doc.recompute()
        self.assertIsNotNone(align.SecondPoint)

    def test_align_fibre_rosette_at_boundary(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        align = self._make_align_fibre_rosette(support=(shell.Support, ["Face1"]), composite_shell=shell)
        face = shell.Support.Shape.Face1
        p = face.valueAt(0.5, 0.0)
        pt = self._make_point("Pt", p)
        align.SecondPoint = (pt, ["Vertex1"])
        self.doc.recompute()
        self.assertIsNotNone(align.SecondPoint)

    def test_align_fibre_rosette_outside_range(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        align = self._make_align_fibre_rosette(support=(shell.Support, ["Face1"]), composite_shell=shell)
        face = shell.Support.Shape.Face1
        p = face.valueAt(1.5, 1.5)
        pt = self._make_point("Pt", p)
        align.SecondPoint = (pt, ["Vertex1"])
        self.doc.recompute()
        self.assertIsNotNone(align.SecondPoint)

    def test_align_fibre_rosette_solver_edge_aligned(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        align = self._make_align_fibre_rosette(support=(shell.Support, ["Face1"]), composite_shell=shell)
        face = shell.Support.Shape.Face1
        p = face.valueAt(0.5, 0.0)
        pt = self._make_point("Pt", p)
        align.SecondPoint = (pt, ["Vertex1"])
        self.doc.recompute()
        self.assertTrue(math.isfinite(float(align.Angle)))

    def test_align_fibre_rosette_solver_edge_perpendicular(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        align = self._make_align_fibre_rosette(support=(shell.Support, ["Face1"]), composite_shell=shell)
        face = shell.Support.Shape.Face1
        p = face.valueAt(0.0, 0.5)
        pt = self._make_point("Pt", p)
        align.SecondPoint = (pt, ["Vertex1"])
        self.doc.recompute()
        self.assertTrue(math.isfinite(float(align.Angle)))

    def test_align_fibre_rosette_solver_impossible(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        align = self._make_align_fibre_rosette(support=(shell.Support, ["Face1"]), composite_shell=shell)
        face = shell.Support.Shape.Face1
        p = face.valueAt(0.5, 0.5)
        pt = self._make_point("Pt", p)
        align.SecondPoint = (pt, ["Vertex1"])
        self.doc.recompute()
        self.assertTrue(math.isfinite(float(align.Angle)))
    def test_align_fibre_rosette_solves_to_the_picked_point(self):
        """With the align rosette seeding the drape, the angle is solved, not
        defaulted: a point at 45 degrees from the rosette origin must land the
        warp fibre on 45."""
        from Composites.features.CompositeShell import CompositeShellFP

        plate = self.doc.addObject("Part::Feature", "PlateSupport")
        plate.Shape = Part.makePlane(100.0, 100.0)
        align = self._make_align_fibre_rosette(support=(plate, ["Face1"]), composite_shell=None)
        shell = self.doc.addObject("Part::FeaturePython", "Shell")
        CompositeShellFP(
            shell, support=plate, laminate=self._make_laminate(), rosette=align
        )
        self.doc.recompute()

        align.CompositeShell = shell
        self.doc.recompute()
        point = self._make_point("Point1", FreeCAD.Vector(60.0, 60.0, 0.0))
        align.SecondPoint = (point, ["Vertex1"])
        self.doc.recompute()

        self.assertAlmostEqual(float(align.Angle), 45.0, delta=0.5)
        self.assertNotIn("Invalid", align.State)

    def test_unreachable_second_point_fails_loud(self):
        """A second point the solver cannot align to leaves the feature
        Invalid — never a silently kept or defaulted angle."""
        from Composites.features.CompositeShell import CompositeShellFP

        plate = self.doc.addObject("Part::Feature", "PlateSupport")
        plate.Shape = Part.makePlane(100.0, 100.0)
        align = self._make_align_fibre_rosette(support=(plate, ["Face1"]), composite_shell=None)
        shell = self.doc.addObject("Part::FeaturePython", "Shell")
        CompositeShellFP(
            shell, support=plate, laminate=self._make_laminate(), rosette=align
        )
        self.doc.recompute()

        align.CompositeShell = shell
        self.doc.recompute()
        # Break the drape: with an undrapeable support the draper is invalid
        # and the alignment cannot even be evaluated.
        shell.Support.Shape = Part.Compound()
        self.doc.recompute()
        point = self._make_point("Point2", FreeCAD.Vector(60.0, 60.0, 0.0))
        align.SecondPoint = (point, ["Vertex1"])
        self.doc.recompute()

        self.assertIn("Invalid", align.State)
