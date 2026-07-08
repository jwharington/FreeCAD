# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Comprehensive tests for SeamShellFP."""

import os
import tempfile
import unittest

from test_base import TestFreeCADFP


class TestSeamShellFP(TestFreeCADFP):
    """Comprehensive tests for SeamShellFP."""

    def test_seam_shell_creation(self):
        """Test basic seam shell creation with two shells."""
        from Composites.features.Seam import SeamShellFP
        shell1 = self._create_shell("Shell1")
        shell2 = self._create_shell("Shell2")
        seam = self.doc.addObject("Part::FeaturePython", "Seam")
        SeamShellFP(seam, shell1, shell2, lap_side="A+B")
        self.doc.recompute()
        self.assertFalse(seam.Shape.isNull())

    def test_seam_helper_visibility(self):
        """Test that seam creates helper objects."""
        from Composites.features.Seam import SeamShellFP
        shell1 = self._create_shell("Shell1")
        shell2 = self._create_shell("Shell2")
        seam = self.doc.addObject("Part::FeaturePython", "Seam")
        SeamShellFP(seam, shell1, shell2, lap_side="A+B")
        self.doc.recompute()
        support_name = f"{seam.Name}_SeamSupport"
        laminate_name = f"{seam.Name}_VirtualLaminate"
        support = self.doc.getObject(support_name)
        laminate = self.doc.getObject(laminate_name)
        self.assertIsNotNone(support)
        self.assertIsNotNone(laminate)

    def test_seam_save_load(self):
        """Test saving and loading a seam shell."""
        from Composites.features.Seam import SeamShellFP
        shell1 = self._create_shell("Shell1")
        shell2 = self._create_shell("Shell2")
        seam = self.doc.addObject("Part::FeaturePython", "Seam")
        SeamShellFP(seam, shell1, shell2, lap_side="A+B")
        self.doc.recompute()
        filepath = os.path.join(tempfile.gettempdir(), "test_seam.FCStd")
        self._save_document(filepath)
        loaded_doc = self._load_document(filepath)
        try:
            loaded_seam = loaded_doc.getObject(seam.Name)
            self.assertIsNotNone(loaded_seam)
            self.assertFalse(loaded_seam.Shape.isNull())
        finally:
            try:
                loaded_doc.close()
            except Exception:
                pass
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_lap_side_b_plus_a(self):
        """Test seam with B+A lap side ordering."""
        from Composites.features.Seam import SeamShellFP
        shell1 = self._create_shell("Shell1")
        shell2 = self._create_shell("Shell2")
        seam = self.doc.addObject("Part::FeaturePython", "Seam")
        SeamShellFP(seam, shell1, shell2, lap_side="B+A")
        self.doc.recompute()
        self.assertFalse(seam.Shape.isNull())
        self.assertEqual(seam.LapSide, "B+A")

    def test_seam_with_different_overlaps(self):
        """Test seam with varying overlap lengths."""
        from Composites.features.Seam import SeamShellFP
        shell1 = self._create_shell("Shell1")
        shell2 = self._create_shell("Shell2")
        seam = self.doc.addObject("Part::FeaturePython", "Seam")
        SeamShellFP(seam, shell1, shell2, lap_side="A+B", overlap=5.0)
        self.doc.recompute()
        self.assertFalse(seam.Shape.isNull())

    def test_seam_validation_error(self):
        """Test that invalid inputs raise errors."""
        from Composites.features.Seam import SeamShellFP
        shell1 = self._create_shell("Shell1")
        shell2 = self._create_shell("Shell2")
        seam = self.doc.addObject("Part::FeaturePython", "Seam")
        # Try with invalid lap side
        try:
            SeamShellFP(seam, shell1, shell2, lap_side="INVALID")
            self.fail("Expected ValueError for invalid lap side")
        except ValueError:
            pass  # Expected

    def test_seam_shell_recompute(self):
        """Test that seam shell recomputes correctly."""
        from Composites.features.Seam import SeamShellFP
        shell1 = self._create_shell("Shell1")
        shell2 = self._create_shell("Shell2")
        seam = self.doc.addObject("Part::FeaturePython", "Seam")
        SeamShellFP(seam, shell1, shell2, lap_side="A+B")
        self.doc.recompute()
        # Force recompute
        self.doc.recompute()
        self.assertFalse(seam.Shape.isNull())

    def test_seam_shell_parent_child_relationship(self):
        """Test that seam maintains relationship with parent shells."""
        from Composites.features.Seam import SeamShellFP
        shell1 = self._create_shell("Shell1")
        shell2 = self._create_shell("Shell2")
        seam = self.doc.addObject("Part::FeaturePython", "Seam")
        SeamShellFP(seam, shell1, shell2, lap_side="A+B")
        self.doc.recompute()
        # Check that seam has references to shells
        self.assertIn(shell1.Name, str(seam))
        self.assertIn(shell2.Name, str(seam))