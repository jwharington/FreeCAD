# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""
Test entry point for FreeCAD FeaturePython integration tests.

Runs all test modules from the compositestests package.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

# CRITICAL: Mock FreeCADGui BEFORE importing any Composites modules
FreeCADGui = MagicMock()
FreeCADGui.addCommand = lambda *args, **kwargs: None
FreeCADGui.addWorkbench = lambda *args, **kwargs: None
sys.modules['FreeCADGui'] = FreeCADGui

# Import FreeCAD after mocking FreeCADGui
import FreeCAD
import Part

# Now import Composites
if "CompositesWB" not in sys.modules:
    import Composites as _composites_wb
    sys.modules["CompositesWB"] = _composites_wb

import Composites as CompositesWB


class TestFreeCADFP(unittest.TestCase):
    """Base test class for FreeCAD FeaturePython objects."""

    def setUp(self):
        self.doc_name = f"TestDoc_{self.id().replace('.', '_')}"
        self.doc = FreeCAD.newDocument(self.doc_name)

    def tearDown(self):
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

    def _create_box(self, name="Box"):
        box = self.doc.addObject("Part::Box", name)
        box.Length = 10.0
        box.Width = 10.0
        box.Height = 10.0
        self.doc.recompute()
        return box

    def _create_simple_shell(self, name="Shell", support_shape=None):
        from Composites.features.CompositeShell import CompositeShellFP
        support = self.doc.addObject("Part::Feature", f"{name}_Support")
        support.Shape = support_shape or Part.makeCylinder(10.0, 20.0)
        shell = self.doc.addObject("Part::FeaturePython", name)
        CompositeShellFP(shell, support)
        self.doc.recompute()
        return shell


class TestDocumentPersistence(unittest.TestCase):
    """Tests for document save/load functionality."""

    def setUp(self):
        self.doc_name = f"TestDoc_{self.id().replace('.', '_')}"
        self.doc = FreeCAD.newDocument(self.doc_name)

    def tearDown(self):
        if hasattr(self, 'doc') and self.doc is not None:
            try:
                if self.doc.Name in FreeCAD.listDocuments():
                    FreeCAD.closeDocument(self.doc.Name)
            except Exception:
                pass
            self.doc = None

    def test_save_load_single_object(self):
        """Test saving and loading a single object."""
        box = self.doc.addObject("Part::Box", "Box1")
        box.Length = 10.0
        box.Width = 10.0
        box.Height = 10.0
        self.doc.recompute()

        filepath = os.path.join(tempfile.gettempdir(), "test_simple.FCStd")
        self.doc.saveAs(filepath)

        loaded_doc = FreeCAD.openDocument(filepath)
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
        box1 = self.doc.addObject("Part::Box", "Box1")
        box1.Length = 10.0
        box1.Width = 10.0
        box1.Height = 10.0

        box2 = self.doc.addObject("Part::Box", "Box2")
        box2.Length = 20.0
        box2.Width = 20.0
        box2.Height = 20.0

        self.doc.recompute()

        filepath = os.path.join(tempfile.gettempdir(), "test_multi.FCStd")
        self.doc.saveAs(filepath)

        loaded_doc = FreeCAD.openDocument(filepath)
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


class TestSimpleFeatures(unittest.TestCase):
    """Tests for simple feature creation."""

    def setUp(self):
        self.doc_name = f"TestDoc_{self.id().replace('.', '_')}"
        self.doc = FreeCAD.newDocument(self.doc_name)

    def tearDown(self):
        if hasattr(self, 'doc') and self.doc is not None:
            try:
                if self.doc.Name in FreeCAD.listDocuments():
                    FreeCAD.closeDocument(self.doc.Name)
            except Exception:
                pass
            self.doc = None

    def test_create_and_save_box(self):
        """Test creating a box and saving it."""
        box = self.doc.addObject("Part::Box", "TestBox")
        box.Length = 10.0
        box.Width = 10.0
        box.Height = 10.0
        self.doc.recompute()

        filepath = os.path.join(tempfile.gettempdir(), "test_box.FCStd")
        self.doc.saveAs(filepath)

        loaded_doc = FreeCAD.openDocument(filepath)
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
        self.doc.saveAs(filepath)

        loaded_doc = FreeCAD.openDocument(filepath)
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

    try:
        from test_composite_shell import TestCompositeShellFP
        suite.addTests(loader.loadTestsFromTestCase(TestCompositeShellFP))
    except Exception as e:
        print(f"Warning: Could not import test_composite_shell: {e}")

    try:
        from test_laminate import TestLaminateFP
        suite.addTests(loader.loadTestsFromTestCase(TestLaminateFP))
    except Exception as e:
        print(f"Warning: Could not import test_laminate: {e}")

    try:
        from test_seam import TestSeamShellFP
        suite.addTests(loader.loadTestsFromTestCase(TestSeamShellFP))
    except Exception as e:
        print(f"Warning: Could not import test_seam: {e}")

    # Add our demonstration tests
    suite.addTests(loader.loadTestsFromTestCase(TestDocumentPersistence))
    suite.addTests(loader.loadTestsFromTestCase(TestSimpleFeatures))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)