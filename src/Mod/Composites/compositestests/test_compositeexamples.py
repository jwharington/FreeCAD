# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com
"""Smoke tests for the compositeexamples framework.

Uses real FreeCAD objects — no mocks — consistent with the Composites
testing philosophy.
"""

import os
import sys
import tempfile
import unittest

import FreeCAD  # noqa: E402

# ---------------------------------------------------------------------------
# Ensure repo root is on sys.path so package imports work.
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from Composites.compositeexamples import registry, runner  # noqa: E402
from Composites.compositeexamples.examples import (  # noqa: E402
    _shell_example_common,
    tubular_shell,
)


class TestCompositeExamplesBase(unittest.TestCase):
    """Base class with automatic .FCStd file generation."""

    save_fcstd = True

    def tearDown(self):
        """Save .FCStd file after each test and close document."""
        try:
            if self.save_fcstd:
                docs = FreeCAD.listDocuments()
                if docs:
                    doc_name = list(docs.keys())[0]
                    filepath = os.path.join(
                        tempfile.gettempdir(),
                        f"{self.__class__.__name__}_{self._testMethodName}.FCStd",
                    )
                    doc = docs[doc_name]
                    doc.saveAs(filepath)
                    print(f"Saved: {filepath}")
            for doc_name in list(FreeCAD.listDocuments()):
                try:
                    FreeCAD.closeDocument(doc_name)
                except Exception:
                    pass
        except Exception as exc:
            print(f"Teardown error in {self._testMethodName}: {exc}")


class TestCompositeExamplesRegistry(TestCompositeExamplesBase):
    def test_list_examples_is_sorted(self):
        examples = registry.list_examples()
        self.assertEqual(examples, sorted(examples))
        self.assertIn("ud_plate_basic", examples)
        self.assertIn("quasi_iso_laminate_plate", examples)
        self.assertIn("tubular_shell", examples)
        self.assertIn("cylindrical_panel_segment", examples)
        self.assertIn("conical_panel_segment", examples)

    def test_get_example_module_unknown_raises(self):
        with self.assertRaises(ValueError) as ctx:
            registry.get_example_module("does_not_exist")

        msg = str(ctx.exception)
        self.assertIn("Unknown example 'does_not_exist'", msg)
        self.assertIn("Available examples", msg)


class TestCompositeExamplesRunner(TestCompositeExamplesBase):
    """Test runner plumbing with real FreeCAD geometry."""

    def test_run_calls_example_build(self):
        """runner.run delegates to the example's build function."""
        result = runner.run("ud_plate_basic", run_solver=False, doc=None)
        self._saved_doc = result.get("doc")

        self.assertIn("laminate", result)
        self.assertIsNotNone(result["laminate"])

    def test_run_forwards_run_solver_flag(self):
        """run_solver=True still succeeds (geometry only, no solver)."""
        result = runner.run("ud_plate_basic", run_solver=True, doc=None)
        self._saved_doc = result.get("doc")

        self.assertIn("laminate", result)
        self.assertIsNotNone(result["laminate"])


class TestFailurePostprocess(TestCompositeExamplesBase):
    def test_evaluate_failure_criteria_returns_hotspots(self):
        import types

        result_obj = types.SimpleNamespace(
            TypeId="Fem::FemResultMechanical",
            Name="ResultMechanical",
            PropertiesList=["StressXX", "StressYY", "StressXY"],
            StressXX={1: 100.0, 2: 250.0},
            StressYY={1: 10.0, 2: 25.0},
            StressXY={1: 5.0, 2: 12.0},
        )
        analysis = types.SimpleNamespace(Group=[result_obj])

        report = _shell_example_common.evaluate_failure_criteria(analysis)

        self.assertTrue(report["available"])
        self.assertGreater(report["max_failure_index"], 0.0)
        self.assertTrue(report["hotspots"])
        self.assertEqual(report["hotspots"][0]["element_id"], 2)


class TestCompositeExamplesSmoke(TestCompositeExamplesBase):
    """End-to-end smoke tests using real FreeCAD geometry."""

    def test_tubular_shell_builds(self):
        """tubular_shell builds successfully with real FreeCAD objects."""
        result = tubular_shell.build(doc=None, run_solver=False)
        self._saved_doc = result.get("doc")
        self.assertIn("laminate", result)
        self.assertIsNotNone(result["laminate"])

    def test_all_examples_build(self):
        """Every example builds successfully with run_solver=False."""
        for example_id in registry.list_examples():
            with self.subTest(example=example_id):
                result = runner.run(example_id, run_solver=False, doc=None)
                self._saved_doc = result.get("doc")
                self.assertIn("laminate", result)
                self.assertIsNotNone(result["laminate"])


if __name__ == "__main__":
    unittest.main(verbosity=2)