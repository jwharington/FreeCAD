# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""
Test entry point for FreeCAD FeaturePython integration tests.

Runs all test modules from the compositestests package.
"""

import os
import sys
import tempfile
import types
import unittest

# CRITICAL: Install FreeCADGui stub BEFORE importing any Composites modules
if "FreeCADGui" not in sys.modules:
    _stub = types.SimpleNamespace()
    _stub.addCommand = lambda *a, **k: None
    _stub.addWorkbench = lambda *a, **k: None
    sys.modules["FreeCADGui"] = _stub

# Import FreeCAD after mocking FreeCADGui
import FreeCAD
import Part

# Now import Composites
if "CompositesWB" not in sys.modules:
    import Composites as _composites_wb
    sys.modules["CompositesWB"] = _composites_wb

import Composites as CompositesWB

# Import base test class
from .test_base import TestFreeCADFP


class TestDocumentPersistence(TestFreeCADFP):
    """Tests for document save/load functionality."""

    def test_save_load_single_object(self):
        """Test saving and loading a single object."""
        box = self._create_box("Box1")
        filepath = os.path.join(tempfile.gettempdir(), "test_simple.FCStd")
        self._save_document(filepath)

        loaded_doc = self._load_document(filepath)
        try:
            loaded_box = loaded_doc.getObject("Box1")
            self.assertIsNotNone(loaded_box)
            self.assertEqual(loaded_box.TypeId, "Part::Box")
            self.assertEqual(loaded_box.Length, 10.0)
            self.assertEqual(loaded_box.Width, 10.0)
            self.assertEqual(loaded_box.Height, 10.0)
        finally:
            try:
                loaded_doc.close()
            except Exception:
                pass
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_save_load_multiple_objects(self):
        """Test saving and loading multiple objects."""
        box1 = self._create_box("Box1")
        box1.Length = 10.0
        box1.Width = 10.0
        box1.Height = 10.0

        box2 = self._create_box("Box2")
        box2.Length = 20.0
        box2.Width = 20.0
        box2.Height = 20.0

        self.doc.recompute()

        filepath = os.path.join(tempfile.gettempdir(), "test_multi.FCStd")
        self._save_document(filepath)

        loaded_doc = self._load_document(filepath)
        try:
            loaded_box1 = loaded_doc.getObject("Box1")
            loaded_box2 = loaded_doc.getObject("Box2")
            self.assertIsNotNone(loaded_box1)
            self.assertIsNotNone(loaded_box2)
            self.assertEqual(loaded_box1.Length, 10.0)
            self.assertEqual(loaded_box2.Length, 20.0)
        finally:
            try:
                loaded_doc.close()
            except Exception:
                pass
            if os.path.exists(filepath):
                os.remove(filepath)


class TestSimpleFeatures(TestFreeCADFP):
    """Tests for simple feature creation."""

    def test_create_and_save_box(self):
        """Test creating a box and saving it."""
        box = self._create_box("TestBox")
        filepath = os.path.join(tempfile.gettempdir(), "test_box.FCStd")
        self._save_document(filepath)

        loaded_doc = self._load_document(filepath)
        try:
            loaded_box = loaded_doc.getObject("TestBox")
            self.assertIsNotNone(loaded_box)
            self.assertEqual(loaded_box.TypeId, "Part::Box")
        finally:
            try:
                loaded_doc.close()
            except Exception:
                pass
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_create_and_save_cylinder(self):
        """Test creating a cylinder and saving it."""
        cyl = self.doc.addObject("Part::Cylinder", "TestCyl")
        cyl.Radius = 10.0
        cyl.Height = 20.0
        self.doc.recompute()
        filepath = os.path.join(tempfile.gettempdir(), "test_cyl.FCStd")
        self._save_document(filepath)

        loaded_doc = self._load_document(filepath)
        try:
            loaded_cyl = loaded_doc.getObject("TestCyl")
            self.assertIsNotNone(loaded_cyl)
            self.assertEqual(loaded_cyl.TypeId, "Part::Cylinder")
            self.assertEqual(loaded_cyl.Radius, 10.0)
        finally:
            try:
                loaded_doc.close()
            except Exception:
                pass
            if os.path.exists(filepath):
                os.remove(filepath)


# -----------------------------------------------------------------------------
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add our demonstration tests
    suite.addTests(loader.loadTestsFromTestCase(TestDocumentPersistence))
    suite.addTests(loader.loadTestsFromTestCase(TestSimpleFeatures))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)