# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Unit tests for Rosette feature types (RosetteFP, AlignFibreRosetteFP, TransferRosetteFP).

Each test produces an FCStd file in /tmp for inspection.
"""

import math
import os
import tempfile

import FreeCAD
import Part

from .test_base import TestFreeCADFP


class TestRosetteTypes(TestFreeCADFP):
    """Tests for the three Rosette feature types."""

    def _make_simple_shell(self, name="Shell", support_shape=None):
        """Create a CompositeShell with a simple cylinder support and laminate."""
        from Composites.features.CompositeShell import CompositeShellFP
        from Composites.features.Laminate import LaminateFP

        support = self.doc.addObject("Part::Feature", "Support")
        support.Shape = support_shape or Part.makeCylinder(10.0, 20.0)

        laminate = self.doc.addObject("Part::FeaturePython", "Laminate")
        LaminateFP(laminate)

        shell = self.doc.addObject("Part::FeaturePython", name)
        CompositeShellFP(shell, support)
        shell.Laminate = laminate
        self.doc.recompute()
        return shell

    def _make_point(self, name, position):
        """Create a simple point feature."""
        obj = self.doc.addObject("Part::Feature", name)
        obj.Shape = Part.makeSphere(0.1, position)
        self.doc.recompute()
        return obj

    # ==================== RosetteFP tests ====================

    def test_rosette_basic_creation(self):
        """Test basic creation of RosetteFP."""
        from Composites.features.Rosette import RosetteFP

        shell = self._make_simple_shell()
        rosette = self.doc.addObject("Part::FeaturePython", "Rosette")
        RosetteFP(rosette)
        rosette.Support = (shell.Support, ["Face1"])
        shell.Rosette = rosette
        self.doc.recompute()

        self.assertIsNotNone(rosette)
        self.assertEqual(rosette.Proxy.Type, "Composite::Rosette")
        self.assertAlmostEqual(float(rosette.Angle), 0.0, places=6)

    def test_rosette_save_load(self):
        """Test that RosetteFP can be saved and loaded."""
        from Composites.features.Rosette import RosetteFP

        shell = self._make_simple_shell()
        rosette = self.doc.addObject("Part::FeaturePython", "Rosette")
        RosetteFP(rosette)
        rosette.Support = (shell.Support, ["Face1"])
        rosette.Angle = 45.0
        shell.Rosette = rosette
        self.doc.recompute()

        filepath = os.path.join(tempfile.gettempdir(), "rossette_save_load.FCStd")
        try:
            self._save_document(filepath)
            reopened = FreeCAD.openDocument(filepath)
            try:
                reopened_rosette = reopened.getObject(rosette.Name)
                self.assertIsNotNone(reopened_rosette)
                self.assertAlmostEqual(float(reopened_rosette.Angle), 45.0, places=6)
            finally:
                try:
                    reopened.close()
                except Exception:
                    pass
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    # ==================== AlignFibreRosetteFP tests ====================

    def test_align_fibre_rosette_basic_creation(self):
        """Test basic creation of AlignFibreRosetteFP."""
        from Composites.features.AlignFibreRosette import AlignFibreRosetteFP

        shell = self._make_simple_shell()
        align = self.doc.addObject("Part::FeaturePython", "AlignFibreRosette")
        AlignFibreRosetteFP(align, support=(shell.Support, ["Face1"]), composite_shell=shell)
        self.doc.recompute()

        self.assertIsNotNone(align)
        self.assertEqual(align.Proxy.Type, "Composite::AlignFibreRosette")
        self.assertIsNone(align.SecondPoint)

    def test_align_fibre_rosette_with_second_point(self):
        """Test AlignFibreRosetteFP with a second point (no angle assertion)."""
        from Composites.features.AlignFibreRosette import AlignFibreRosetteFP

        shell = self._make_simple_shell()
        align = self.doc.addObject("Part::FeaturePython", "AlignFibreRosette")
        AlignFibreRosetteFP(align, support=(shell.Support, ["Face1"]), composite_shell=shell)

        # Create a second point inside the shell face
        face = shell.Support.Shape.Face1
        u0, u1, v0, v1 = face.ParameterRange
        um = (u0 + u1) / 2.0
        vm = (v0 + v1) / 2.0
        du = (u1 - u0) * 0.10
        dv = (v1 - v0) * 0.15
        p_second = face.valueAt(um + du, vm + dv)
        point_obj = self._make_point("SecondPoint", p_second)

        align.SecondPoint = (point_obj, ["Vertex1"])
        self.doc.recompute()

        # Just ensure the angle property exists and is numeric
        self.assertIsNotNone(align.Angle)
        angle_val = float(align.Angle)
        self.assertTrue(math.isfinite(angle_val))

    # ==================== TransferRosetteFP tests ====================

    def test_transfer_rosette_basic_creation(self):
        """Test basic creation of TransferRosetteFP."""
        from Composites.features.TransferRosette import TransferRosetteFP

        shell = self._make_simple_shell()
        tr = self.doc.addObject("Part::FeaturePython", "TransferRosette")
        TransferRosetteFP(tr, support=(shell.Support, ["Face1"]), attachment_shell=shell)
        self.doc.recompute()

        self.assertIsNotNone(tr)
        self.assertEqual(tr.Proxy.Type, "Composite::TransferRosette")

    def test_transfer_rosette_with_master(self):
        """Test TransferRosetteFP transferring angle from a master rosette."""
        from Composites.features.TransferRosette import TransferRosetteFP
        from Composites.features.Rosette import RosetteFP

        # Create master shell with rosette
        master_shell = self._make_simple_shell("MasterShell")
        master_rosette = self.doc.addObject("Part::FeaturePython", "MasterRosette")
        RosetteFP(master_rosette)
        master_rosette.Support = (master_shell.Support, ["Face1"])
        master_rosette.Angle = 30.0
        master_shell.Rosette = master_rosette
        self.doc.recompute()

        # Create attachment shell
        attachment_shell = self._make_simple_shell("AttachmentShell")

        # Create transfer rosette
        tr = self.doc.addObject("Part::FeaturePython", "TransferRosette")
        TransferRosetteFP(tr, support=(attachment_shell.Support, ["Face1"]), attachment_shell=attachment_shell)
        tr.MasterShell = master_shell
        self.doc.recompute()

        # The transfer rosette angle should be set and finite
        self.assertTrue(math.isfinite(float(tr.Angle)))