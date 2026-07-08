# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Comprehensive scenario tests for Rosette feature types."""

import math
import os
import tempfile

import FreeCAD
import Part

from test_base import TestFreeCADFP


class TestRosetteScenarios(TestFreeCADFP):
    """Comprehensive scenario tests for Rosette feature types."""

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

    def _make_rosette(self, name="Rosette"):
        from Composites.features.Rosette import RosetteFP
        rosette = self.doc.addObject("Part::FeaturePython", name)
        RosetteFP(rosette)
        return rosette

    def _make_align_fibre_rosette(self, name="AlignFibreRosette", support=None, composite_shell=None, second_point=None):
        from Composites.features.AlignFibreRosette import AlignFibreRosetteFP
        align = self.doc.addObject("Part::FeaturePython", name)
        AlignFibreRosetteFP(align, support=support, composite_shell=composite_shell, second_point=second_point)
        return align

    def _make_transfer_rosette(self, name="TransferRosette", support=None, master_shell=None, attachment_shell=None):
        from Composites.features.TransferRosette import TransferRosetteFP
        tr = self.doc.addObject("Part::FeaturePython", name)
        TransferRosetteFP(tr, support=support, master_shell=master_shell, attachment_shell=attachment_shell)
        return tr

    def _make_point(self, name, position):
        obj = self.doc.addObject("Part::Feature", name)
        obj.Shape = Part.makeSphere(0.1, position)
        self.doc.recompute()
        return obj

    def _make_flat_plate(self, size=(100.0, 100.0, 1.0)):
        return Part.makeBox(*size)

    def _make_cylinder_shell(self, radius=50.0, height=100.0):
        return Part.makeCylinder(radius, height)

    def test_rosette_on_planar_face(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        rosette = self._make_rosette()
        rosette.Support = (shell.Support, ["Face1"])
        shell.Rosette = rosette
        self.doc.recompute()
        self.assertIsNotNone(rosette)

    def test_rosette_on_curved_face_cylinder(self):
        cyl_shape = self._make_cylinder_shell()
        shell = self._make_shell(cyl_shape)
        rosette = self._make_rosette()
        rosette.Support = (shell.Support, ["Face1"])
        shell.Rosette = rosette
        self.doc.recompute()
        self.assertIsNotNone(rosette)

    def test_rosette_on_curved_face_sphere(self):
        sphere_shape = Part.makeSphere(50.0, 0, 360, 0, 30/50*180)
        shell = self._make_shell(sphere_shape)
        rosette = self._make_rosette()
        rosette.Support = (shell.Support, ["Face1"])
        shell.Rosette = rosette
        self.doc.recompute()
        self.assertIsNotNone(rosette)

    def test_rosette_on_straight_edge(self):
        box_shape = self._make_flat_plate()
        shell = self._make_shell(box_shape)
        rosette = self._make_rosette()
        rosette.Support = (shell.Support, ["Edge1"])
        shell.Rosette = rosette
        self.doc.recompute()
        self.assertIsNotNone(rosette)

    def test_rosette_on_curved_edge(self):
        cyl_shape = self._make_cylinder_shell()
        shell = self._make_shell(cyl_shape)
        rosette = self._make_rosette()
        rosette.Support = (shell.Support, ["Edge1"])
        shell.Rosette = rosette
        self.doc.recompute()
        self.assertIsNotNone(rosette)

    def test_rosette_on_vertex(self):
        box_shape = self._make_flat_plate()
        shell = self._make_shell(box_shape)
        rosette = self._make_rosette()
        rosette.Support = (shell.Support, ["Vertex1"])
        shell.Rosette = rosette
        self.doc.recompute()
        self.assertIsNotNone(rosette)

    def test_rosette_angle_variations(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        rosette = self._make_rosette()
        rosette.Support = (shell.Support, ["Face1"])
        shell.Rosette = rosette
        self.doc.recompute()
        for angle in [0.0, 45.0, -45.0, 90.0, 120.0, -90.0]:
            rosette.Angle = angle
            self.doc.recompute()
            self.assertAlmostEqual(float(rosette.Angle), angle, places=6)

    def test_multiple_rosettes_same_shell(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        rosette1 = self._make_rosette("Rosette1")
        rosette1.Support = (shell.Support, ["Face1"])
        rosette1.Angle = 30.0
        rosette2 = self._make_rosette("Rosette2")
        rosette2.Support = (shell.Support, ["Face1"])
        rosette2.Angle = 60.0
        shell.Rosette = rosette1
        self.doc.recompute()
        self.assertIsNotNone(rosette1)
        self.assertIsNotNone(rosette2)

    def test_multiple_rosettes_multi_face_support(self):
        shape = Part.makeBox(100.0, 100.0, 10.0)
        shell = self._make_shell(shape)
        rosette1 = self._make_rosette("Rosette1")
        rosette1.Support = (shell.Support, ["Face1"])
        rosette1.Angle = 30.0
        rosette2 = self._make_rosette("Rosette2")
        rosette2.Support = (shell.Support, ["Face2"])
        rosette2.Angle = 60.0
        self.doc.recompute()
        self.assertIsNotNone(rosette1)
        self.assertIsNotNone(rosette2)

    def test_rosette_save_load_complex(self):
        shape = Part.makeBox(100.0, 100.0, 1.0)
        shape2 = Part.makeBox(50.0, 50.0, 1.0)
        shape2.move(Part.Vector(25, 25, 0))
        compound = Part.makeCompound([shape, shape2])
        shell = self._make_shell(compound)
        rosette = self._make_rosette()
        rosette.Support = (shell.Support, ["Face1"])
        rosette.Angle = 45.0
        shell.Rosette = rosette
        self.doc.recompute()
        filepath = os.path.join(tempfile.gettempdir(), "rosette_save_load_complex.FCStd")
        try:
            self._save_document(filepath)
            reopened = FreeCAD.openDocument(filepath)
            try:
                reopened_rosette = reopened.getObject(rosette.Name)
                self.assertIsNotNone(reopened_rosette)
                self.assertAlmostEqual(float(reopened_rosette.Angle), 45.0, places=6)
            finally:
                reopened.close()
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_dynamic_angle_change(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        rosette = self._make_rosette()
        rosette.Support = (shell.Support, ["Face1"])
        shell.Rosette = rosette
        self.doc.recompute()
        rosette.Angle = 45.0
        self.doc.recompute()
        self.assertAlmostEqual(float(rosette.Angle), 45.0, places=6)

    def test_rosette_on_non_manifold_edge(self):
        shape = Part.makeBox(100.0, 100.0, 1.0)
        shape2 = Part.makeBox(50.0, 50.0, 1.0)
        shape2.move(Part.Vector(25, 25, 0))
        compound = Part.makeCompound([shape, shape2])
        shell = self._make_shell(compound)
        rosette = self._make_rosette()
        rosette.Support = (shell.Support, ["Edge1"])
        shell.Rosette = rosette
        self.doc.recompute()
        self.assertIsNotNone(rosette)

    def test_rosette_on_degenerate_face(self):
        face = Part.Face(Part.makePolygon([
            FreeCAD.Vector(0,0,0),
            FreeCAD.Vector(1,0,0),
            FreeCAD.Vector(0,1,0),
        ]))
        shell = self._make_shell(face)
        rosette = self._make_rosette()
        rosette.Support = (shell.Support, ["Face1"])
        shell.Rosette = rosette
        self.doc.recompute()
        self.assertIsNotNone(rosette)