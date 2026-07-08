# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for SeamShellFP."""

import os
import tempfile
import unittest

from test_base import TestFreeCADFP


class TestSeamShellFP(TestFreeCADFP):
    """Tests for SeamShellFP."""

    def test_seam_shell_creation(self):
        from Composites.features.Seam import SeamShellFP
        shell1 = self._create_shell("Shell1")
        shell2 = self._create_shell("Shell2")
        seam = self.doc.addObject("Part::FeaturePython", "Seam")
        SeamShellFP(seam, shell1, shell2, lap_side="A+B")
        self.doc.recompute()
        self.assertFalse(seam.Shape.isNull())

    def test_seam_helper_visibility(self):
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