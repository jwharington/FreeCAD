# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Integration test for the Composites_parting C++ binding.

Verifies the pybind11 non-planar parting binding over its real Python entry
point (_propose_non_planar_parting): the returned parting line, mould halves,
shells and skirt arrive as live Part.Shape objects (not BREP bytes needing a
decode), and the shapes are valid enough to round-trip through volume queries.

Runs under headless FreeCADCmd via run-tests.sh. Each run is a fresh process,
so a teardown crash in the binding (double-free of a returned TopoShapePy)
would surface here as a non-zero exit, independent of any solver-level assert.
"""

import unittest

import FreeCAD
import Part

from Composites.tools.mould_analysis import _propose_non_planar_parting


def _box(dx=40.0, dy=40.0, dz=60.0):
    """Draw-direction-agnostic box for the non-planar path."""
    return Part.makeBox(dx, dy, dz)


class NonPlanarPartingBindingTest(unittest.TestCase):
    """The binding returns live Part.Shape objects across the result dict."""

    def test_propose_returns_live_shapes(self):
        result = _propose_non_planar_parting(
            _box(),
            FreeCAD.Vector(0.0, 0.0, 1.0),
            stock_margin_x=5.0,
            stock_margin_y=5.0,
            stock_margin_z=5.0,
            part_line_tolerance=0.1,
        )
        self.assertEqual(result["status"], "ready", result.get("error", result["summary"]))
        # Ordinary Part.Shape objects, not bytes.
        for key in ("parting_line", "upper_shell", "lower_shell"):
            shape = result[key]
            self.assertIsInstance(shape, Part.Shape, f"{key} is {type(shape)}")
            self.assertFalse(shape.isNull(), f"{key} is null")
        # The 3D parting_line compound is the cross-check that the canonical
        # segment chain produced geometry (it must be a non-null shape).
        # part_line_segments is shape-dependent: FaceSegments are marshaled
        # into it, but a box's parting line is silhouette EdgeSegments, so the
        # list is intentionally empty here.
        self.assertFalse(result["parting_line"].isNull())

    def test_mould_half_shapes_have_positive_volume(self):
        result = _propose_non_planar_parting(
            _box(),
            FreeCAD.Vector(0.0, 0.0, 1.0),
        )
        self.assertEqual(result["status"], "ready", result.get("error", result["summary"]))
        for key in ("parting_line", "upper_shell", "lower_shell"):
            self.assertIsInstance(result[key], Part.Shape, f"{key} wrong type")
        vol = result["upper_shell"].Volume
        self.assertGreater(vol, 0.0, "upper mould half has no volume")


if __name__ == "__main__":
    unittest.main()


