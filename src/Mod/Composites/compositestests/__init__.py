# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com
"""Composites test package.

Registers all test modules with FreeCAD's test runner so that
``FreeCADCmd -t compositestests`` runs every Composites test.

Also supports ``FreeCADCmd -t compositestests.test_laminate`` to run
a single test file, or ``FreeCADCmd -t compositestests.test_laminate.TestLaminateFP``
for a specific test class.
"""

import importlib
import os
import pkgutil
import sys
import unittest

# Ensure sibling test modules (test_base, etc.) are importable when
# FreeCAD's test loader imports test files as top-level modules.
_this_dir = os.path.dirname(os.path.abspath(__file__))
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)


def load_tests(loader, tests, pattern):
    """Discover and return all test cases from sibling test modules.

    This is the standard ``load_tests`` protocol that FreeCAD's test runner
    (and unittest) use to discover tests in a package.
    """
    mod_root = __name__
    suite = unittest.TestSuite()

    for _, mod_name, is_pkg in pkgutil.iter_modules(__path__, f"{mod_root}."):
        if is_pkg or not mod_name.startswith("test_"):
            continue
        try:
            mod = importlib.import_module(mod_name)
            suite.addTests(loader.loadTestsFromModule(mod))
        except Exception as exc:
            print(f"Warning: could not load {mod_name}: {exc}")

    return suite