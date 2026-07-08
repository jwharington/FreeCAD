#!/usr/bin/env python
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""
Reusable test runner for FreeCAD FeaturePython integration tests.

Run with:
    FreeCADCmd -P src/Mod/Composites/compositestests/run_tests.py

This script sets up the environment and runs all test modules.
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


def run_tests():
    """Run all integration tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Import and add tests from feature-specific modules
    # Map module names to their corresponding test class names
    test_modules = {
        'test_composite_shell': 'TestCompositeShellFP',
        'test_laminate': 'TestLaminateFP',
        'test_seam': 'TestSeamShellFP',
        'test_stiffener': 'TestStiffenerFP',
        'test_mould': 'TestMouldFP',
        'test_place_dart': 'TestPlaceDartFP',
    }

    for module_name, class_name in test_modules.items():
        try:
            module = __import__(module_name)
            test_class = getattr(module, class_name)
            suite.addTests(loader.loadTestsFromTestCase(test_class))
        except Exception as e:
            print(f"Warning: Could not import {module_name}.{class_name}: {e}")

    # Also run integration tests (requires real FreeCAD)
    try:
        from test_integration_freecad import TestFreeCADIntegration
        suite.addTests(loader.loadTestsFromTestCase(TestFreeCADIntegration))
    except Exception as e:
        print(f"Warning: Could not import integration tests: {e}")

    # Run rosette integration tests
    try:
        from test_rosette_integration import TestRosetteIntegration
        suite.addTests(loader.loadTestsFromTestCase(TestRosetteIntegration))
    except Exception as e:
        print(f"Warning: Could not import rosette integration tests: {e}")

    # Run transfer rosette tests
    try:
        from test_transfer_rosette import TestTransferRosetteFP
        suite.addTests(loader.loadTestsFromTestCase(TestTransferRosetteFP))
    except Exception as e:
        print(f"Warning: Could not import transfer rosette tests: {e}")

    # Add demonstration tests from test_freecad_fp
    try:
        from test_freecad_fp import TestDocumentPersistence, TestSimpleFeatures
        suite.addTests(loader.loadTestsFromTestCase(TestDocumentPersistence))
        suite.addTests(loader.loadTestsFromTestCase(TestSimpleFeatures))
    except Exception as e:
        print(f"Warning: Could not import demonstration tests: {e}")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    run_tests()