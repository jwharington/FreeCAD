# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Run a single test case (or a whole module) with stage-level output.

Complements ``run-tests.sh`` (module-level, log discarded on success):
this keeps the FreeCAD console output — including the drape [PROFILER]
stages — so a slow test can be decomposed.

Usage:
    FreeCADCmd -c "exec(open('.../compositestests/run_one.py').read())"
    with env COMPOSITES_TEST_ID set, e.g.
    COMPOSITES_TEST_ID=compositestests.test_stiffener_composite_shell.\\
TestStiffenerJointStack.test_combined_laminate_wiring
"""

import os
import sys
import unittest

test_id = os.environ.get("COMPOSITES_TEST_ID", "")
if not test_id:
    print("set COMPOSITES_TEST_ID=<dotted test id>", file=sys.stderr)
    sys.exit(2)

suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
