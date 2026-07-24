# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Pure-Python unit tests for mould_analysis.py helper functions.

Targets the deterministic normalization helpers in tools/mould_analysis.py
without constructing any Part geometry. Runs headless under FreeCADCmd
(the module imports FreeCAD/Part at load time, but the helpers under test
take plain dicts/scalars).
"""

import unittest

from Composites.tools.mould_analysis import (
    _extract_normalization_hints,
    _quantity_to_mm,
)


class TestQuantityToMm(unittest.TestCase):
    """_quantity_to_mm: FreeCAD Quantity / raw value extraction."""

    def test_none_returns_none(self):
        self.assertIsNone(_quantity_to_mm(None))

    def test_raw_float(self):
        self.assertEqual(_quantity_to_mm(12.5), 12.5)

    def test_raw_int(self):
        self.assertEqual(_quantity_to_mm(7), 7.0)

    def test_object_with_value_attribute(self):
        class Q:
            Value = 42.0
        self.assertEqual(_quantity_to_mm(Q()), 42.0)

    def test_unparseable_returns_none(self):
        self.assertIsNone(_quantity_to_mm("not a number"))


class TestExtractNormalizationHints(unittest.TestCase):
    """_extract_normalization_hints: thickness + laminate detection."""

    def test_none_source(self):
        hints = _extract_normalization_hints(None)
        self.assertEqual(hints["thickness_hint_state"], "missing")
        self.assertFalse(hints["has_laminate"])

    def test_valid_thickness(self):
        class Q:
            Value = 2.5
        class Source:
            Name = "src"
            Thickness = Q()
        hints = _extract_normalization_hints(Source())
        self.assertEqual(hints["thickness_hint_state"], "valid")
        self.assertAlmostEqual(hints["thickness_mm"], 2.5)
        self.assertEqual(hints["thickness_hint_source"], "Thickness")

    def test_non_positive_thickness_is_invalid(self):
        class Q:
            Value = 0.0
        class Source:
            Name = "src"
            Thickness = Q()
        hints = _extract_normalization_hints(Source())
        self.assertEqual(hints["thickness_hint_state"], "invalid_non_positive")

    def test_laminate_detected_via_attribute(self):
        class Lam:
            Proxy = type("P", (), {"Type": "Composite::Laminate"})()
        class Source:
            Name = "src"
            Laminate = Lam()
        hints = _extract_normalization_hints(Source())
        self.assertTrue(hints["has_laminate"])

    def test_falls_back_through_candidate_props(self):
        class Q:
            Value = 1.8
        class Source:
            Name = "src"
            ShellThickness = Q()  # later in the candidate list
        hints = _extract_normalization_hints(Source())
        self.assertEqual(hints["thickness_hint_state"], "valid")
        self.assertEqual(hints["thickness_hint_source"], "ShellThickness")


if __name__ == "__main__":
    unittest.main()
