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

# Import Composites
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
        'test_stiffener': 'TestStiffenerFP',
        'test_mould': 'TestMouldFP',
        'test_place_dart': 'TestPlaceDartFP',
        'test_rosette_types': 'TestRosetteTypes',
        'test_rosette_scenarios': 'TestRosetteScenarios',
        'test_align_fibre_scenarios': 'TestAlignFibreRosetteScenarios',
        'test_transfer_rosette_scenarios': 'TestTransferRosetteScenarios',
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

    # Run seam extraction tests
    try:
        from test_seam_extraction import TestSeamShellFP, TestSeamExtractionShellFP
        suite.addTests(loader.loadTestsFromTestCase(TestSeamShellFP))
        suite.addTests(loader.loadTestsFromTestCase(TestSeamExtractionShellFP))
    except Exception as e:
        print(f"Warning: Could not import seam extraction tests: {e}")

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