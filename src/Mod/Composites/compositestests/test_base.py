# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Base test class and utilities for FreeCAD integration tests."""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

import FreeCAD
import Part

# Minimal FreeCADGui mock for tests that need GUI access.
# Features themselves no longer require FreeCADGui at import time.
# This mock provides stubs for common GUI operations used in tests.
_freeCADGui_mock = MagicMock()
_freeCADGui_mock.addCommand = lambda *args, **kwargs: None
_freeCADGui_mock.addWorkbench = lambda *args, **kwargs: None
_freeCADGui_mock.Selection = MagicMock()
_freeCADGui_mock.Selection.getSelectionEx = MagicMock(return_value=[])
_freeCADGui_mock.Selection.clearSelection = MagicMock()
sys.modules['FreeCADGui'] = _freeCADGui_mock

# Import Composites (now works without heavy mocking)
if "CompositesWB" not in sys.modules:
    import Composites as _composites_wb
    sys.modules["CompositesWB"] = _composites_wb

import Composites as CompositesWB


class TestFreeCADFP(unittest.TestCase):
    """Base test class for FreeCAD FeaturePython objects."""
    
    # Set to True to save .FCStd files for each test
    save_fcstd = True

    def setUp(self):
        self.doc_name = f"TestDoc_{self.id().replace('.', '_')}"
        self.doc = FreeCAD.newDocument(self.doc_name)
        # Generate filename based on test name
        test_name = f"{self.__class__.__name__}_{self._testMethodName}.FCStd"
        self.fcstd_path = os.path.join(tempfile.gettempdir(), test_name)

    def tearDown(self):
        # Save document before closing if enabled
        if self.save_fcstd and hasattr(self, 'doc') and self.doc is not None:
            try:
                self.doc.saveAs(self.fcstd_path)
                print(f"Saved: {self.fcstd_path}")
            except Exception as e:
                print(f"Error saving {self.fcstd_path}: {e}")
        
        # Close document
        if hasattr(self, 'doc') and self.doc is not None:
            try:
                if self.doc.Name in FreeCAD.listDocuments():
                    FreeCAD.closeDocument(self.doc.Name)
            except Exception:
                pass
            self.doc = None

    def _save_document(self, filepath):
        self.doc.saveAs(filepath)

    def _load_document(self, filepath):
        return FreeCAD.openDocument(filepath)

    def _create_shell(self, name="Shell", support_shape=None):
        from Composites.features.CompositeShell import CompositeShellFP
        support = self.doc.addObject("Part::Feature", "Support")
        support.Shape = support_shape or Part.makeCylinder(10.0, 20.0)
        shell = self.doc.addObject("Part::FeaturePython", name)
        CompositeShellFP(shell, support)
        self.doc.recompute()
        return shell

    def _create_laminate(self, name="Laminate"):
        from Composites.features.Laminate import LaminateFP
        laminate = self.doc.addObject("Part::FeaturePython", name)
        LaminateFP(laminate)
        self.doc.recompute()
        return laminate

    def _create_box(self, name="Box"):
        """Create a simple box."""
        obj = self.doc.addObject("Part::Box", name)
        obj.Length = 10.0
        obj.Width = 10.0
        obj.Height = 10.0
        self.doc.recompute()
        return obj