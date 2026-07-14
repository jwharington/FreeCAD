# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Comprehensive scenario tests for TransferRosette feature types."""

import math
import os
import tempfile

import FreeCAD
import Part

from .test_base import TestFreeCADFP


class TestTransferRosetteScenarios(TestFreeCADFP):
    """Comprehensive scenario tests for TransferRosette feature types."""

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

    def test_transfer_rosette_basic(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        tr = self._make_transfer_rosette(support=(shell.Support, ["Face1"]), attachment_shell=shell)
        self.doc.recompute()
        self.assertIsNotNone(tr)

    def test_transfer_rosette_with_master(self):
        from Composites.features.Rosette import RosetteFP
        master_shell = self._make_shell(self._make_flat_plate())
        master_rosette = self._make_rosette()
        master_rosette.Support = (master_shell.Support, ["Face1"])
        master_shell.Rosette = master_rosette
        self.doc.recompute()
        tr = self._make_transfer_rosette(support=(master_shell.Support, ["Face1"]), master_shell=master_shell, attachment_shell=master_shell)
        self.doc.recompute()
        self.assertIsNotNone(tr)

    def test_transfer_rosette_curved_support(self):
        cyl_shape = self._make_cylinder_shell()
        shell = self._make_shell(cyl_shape)
        tr = self._make_transfer_rosette(support=(shell.Support, ["Face1"]), attachment_shell=shell)
        self.doc.recompute()
        self.assertIsNotNone(tr)

    def test_transfer_rosette_save_load(self):
        face_shape = self._make_flat_plate()
        shell = self._make_shell(face_shape)
        tr = self._make_transfer_rosette(support=(shell.Support, ["Face1"]), attachment_shell=shell)
        self.doc.recompute()
        filepath = os.path.join(tempfile.gettempdir(), "transfer_rosette_save_load.FCStd")
        try:
            self._save_document(filepath)
            reopened = FreeCAD.openDocument(filepath)
            try:
                reopened_tr = reopened.getObject(tr.Name)
                self.assertIsNotNone(reopened_tr)
            finally:
                FreeCAD.closeDocument(reopened.Name)
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_transfer_rosette_multiple_attachments(self):
        from Composites.features.Rosette import RosetteFP
        shell1 = self._make_shell(self._make_flat_plate(), "Shell1")
        shell2 = self._make_shell(self._make_flat_plate(), "Shell2")
        master_rosette = self._make_rosette("MasterRosette")
        master_rosette.Support = (shell1.Support, ["Face1"])
        shell1.Rosette = master_rosette
        self.doc.recompute()
        tr = self._make_transfer_rosette(support=(shell1.Support, ["Face1"]), master_shell=shell1, attachment_shell=shell2)
        self.doc.recompute()
        self.assertIsNotNone(tr)