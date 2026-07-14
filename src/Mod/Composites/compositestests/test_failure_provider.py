# SPDX-License-Identifier: LGPL-2.1-or-later

"""Tests for composite failure models.

Uses real NumPy arrays and model dicts — no mocks of FreeCAD behavior.
"""

import sys
import types
import unittest

import numpy as np

from Composites.fem.failure_models_composites import (  # noqa: E402
    calc_failure_hashin,
    calc_failure_tsai_wu,
    register_composite_failure_models,
)


class TestCompositeFailureModels(unittest.TestCase):
    """Monotonicity: doubling stresses should increase failure index."""

    def setUp(self):
        self.opts = {
            "XT": 1500.0,
            "XC": 1500.0,
            "YT": 50.0,
            "YC": 250.0,
            "ZT": 50.0,
            "ZC": 250.0,
            "S12": 80.0,
            "S13": 80.0,
            "S23": 40.0,
            "f12": 0.0,
            "f13": 0.0,
            "f23": 0.0,
        }

    def test_hashin_monotonic(self):
        s = np.array([0.2, 0.1, 0.0, 0.05, 0.0, 0.0])
        e = np.zeros(6)
        f1 = calc_failure_hashin(s, e, self.opts)
        f2 = calc_failure_hashin(2.0 * s, e, self.opts)
        self.assertGreater(f2, f1)

    def test_tsai_wu_monotonic(self):
        s = np.array([0.2, 0.1, 0.0, 0.0, 0.0, 0.0])
        e = np.zeros(6)
        f1 = calc_failure_tsai_wu(s, e, self.opts)
        f2 = calc_failure_tsai_wu(2.0 * s, e, self.opts)
        self.assertGreater(f2, f1)


class TestCompositeFailureRegistration(unittest.TestCase):
    def test_register_composite_failure_models(self):
        called = []

        def register_failure_model(name, fn, metadata=None):
            called.append((name, fn, metadata))

        fake_module = types.SimpleNamespace(register_failure_model=register_failure_model)
        sys.modules["femresult.failuremodels"] = fake_module

        try:
            ok = register_composite_failure_models()
        finally:
            del sys.modules["femresult.failuremodels"]

        self.assertTrue(ok)
        names = [c[0] for c in called]
        self.assertIn("tsai_wu", names)
        self.assertIn("hashin", names)
        self.assertIn("composites.tsai_wu", names)
        self.assertIn("composites.hashin", names)