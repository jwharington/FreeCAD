# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for CompositeShellFP."""

import os
import tempfile
import unittest

from .test_base import TestFreeCADFP


class TestCompositeShellFP(TestFreeCADFP):
    """Tests for CompositeShellFP."""

    def test_basic_creation(self):
        shell = self._create_shell()
        self.assertIsNotNone(shell)
        self.assertFalse(shell.Shape.isNull())

    def test_save_load_document(self):
        shell = self._create_shell()
        filepath = os.path.join(tempfile.gettempdir(), "test_shell.FCStd")
        self._save_document(filepath)
        loaded_doc = self._load_document(filepath)
        try:
            loaded_shell = loaded_doc.getObject(shell.Name)
            self.assertIsNotNone(loaded_shell)
            self.assertFalse(loaded_shell.Shape.isNull())
        finally:
            try:
                loaded_doc.close()
            except Exception:
                pass
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_laminate_property(self):
        shell = self._create_shell()
        laminate = self._create_laminate()
        shell.Laminate = laminate
        self.assertIs(shell.Laminate, laminate)
    def test_live_support_shape_tracks_moved_support(self):
        """Known-issue #6: geometry queries must read the live support, not
        the shell's cached Shape snapshot."""
        import FreeCAD
        import Part

        from Composites.features.CompositeShell import CompositeShellFP
        from Composites.util.geometry_util import live_support_shape

        support = self.doc.addObject("Part::Feature", "Support")
        support.Shape = Part.makePlane(100.0, 100.0)
        shell = self.doc.addObject("Part::FeaturePython", "Shell")
        CompositeShellFP(shell, support)
        self.doc.recompute()
        self.assertEqual(
            live_support_shape(shell).BoundBox.ZMax,
            support.Shape.BoundBox.ZMax,
        )

        # Move the support WITHOUT recomputing: the shell's own Shape is
        # still the pre-move snapshot, but the live query must track.
        support.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0.0, 0.0, 40.0), FreeCAD.Rotation()
        )
        self.assertLess(shell.Shape.BoundBox.ZMax, 39.0)
        self.assertGreater(live_support_shape(shell).BoundBox.ZMax, 39.0)

        # After a recompute the snapshot catches up.
        self.doc.recompute()
        self.assertGreater(shell.Shape.BoundBox.ZMax, 39.0)
