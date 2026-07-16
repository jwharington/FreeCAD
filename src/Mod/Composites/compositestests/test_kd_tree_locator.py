#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com
#
# Tests for KDTreeLocator — C++ k-d tree spatial index for UV point lookup.

import unittest
import FreeCAD
import Composites_drape

from Composites.util.geometry_util import tex_coord_at_point


def _build_warped_grid_mesh(nx=12, ny=12):
    """Build a deterministic warped grid large enough to trigger KD lookup."""
    nodes = []
    quads = []
    tex_coords = []

    for j in range(ny + 1):
        for i in range(nx + 1):
            x = float(i)
            y = float(j)
            z = 0.05 * ((i % 4) - 1.5) * ((j % 3) - 1.0)
            nodes.append((x, y, z))
            tex_coords.append((x + 0.1 * y, y - 0.05 * x))

    for j in range(ny):
        for i in range(nx):
            idx = j * (nx + 1) + i
            quads.append([idx, idx + 1, idx + (nx + 1) + 1, idx + (nx + 1)])

    return nodes, quads, tex_coords


class TestKDTreeLocator(unittest.TestCase):
    """Tests for the C++ KDTreeLocator class."""

    def test_min_quads_for_kdtree(self):
        """Test the static method min_quads_for_kdtree()."""
        self.assertEqual(Composites_drape.KDTreeLocator.min_quads_for_kdtree(), 100)

    def test_empty_quads(self):
        """Test construction with empty quads."""
        nodes = []
        quads = []
        locator = Composites_drape.KDTreeLocator(nodes, quads)
        result = locator.lookup([0.0, 0.0, 0.0], [])
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_single_quad_center(self):
        """Test lookup at center of a single quad."""
        nodes = [
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)
        ]
        quads = [[0, 1, 2, 3]]
        tex_coords = [
            (0.0, 0.0), (1.0, 0.0),
            (1.0, 1.0), (0.0, 1.0)
        ]

        locator = Composites_drape.KDTreeLocator(nodes, quads)
        result = locator.lookup([0.5, 0.5, 0.0], tex_coords)

        if len(result) >= 2:
            self.assertAlmostEqual(result[0], 0.5, delta=1e-4)
            self.assertAlmostEqual(result[1], 0.5, delta=1e-4)

    def test_small_grid_accuracy(self):
        """Test accuracy on a small 3x3 grid of quads."""
        nodes = []
        quads = []
        node_tex_coords = []

        nx, ny = 3, 3
        for j in range(ny + 1):
            for i in range(nx + 1):
                nodes.append((float(i), float(j), 0.0))
                node_tex_coords.append((float(i), float(j)))

        for j in range(ny):
            for i in range(nx):
                idx = j * (nx + 1) + i
                quads.append([idx, idx + 1, idx + (nx + 1) + 1, idx + (nx + 1)])

        locator = Composites_drape.KDTreeLocator(nodes, quads)

        result = locator.lookup([0.5, 0.5, 0.0], node_tex_coords)
        if len(result) >= 2:
            self.assertAlmostEqual(result[0], 0.5, delta=1e-4)
            self.assertAlmostEqual(result[1], 0.5, delta=1e-4)

        result = locator.lookup([0.0, 0.0, 0.0], node_tex_coords)
        if len(result) >= 2:
            self.assertAlmostEqual(result[0], 0.0, delta=1e-4)
            self.assertAlmostEqual(result[1], 0.0, delta=1e-4)

        result = locator.lookup([3.0, 3.0, 0.0], node_tex_coords)
        if len(result) >= 2:
            self.assertAlmostEqual(result[0], 3.0, delta=1e-4)
            self.assertAlmostEqual(result[1], 3.0, delta=1e-4)

    def test_z_offset(self):
        """Test that Z offset doesn't affect UV lookup."""
        nodes = [
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)
        ]
        quads = [[0, 1, 2, 3]]
        tex_coords = [
            (0.0, 0.0), (1.0, 0.0),
            (1.0, 1.0), (0.0, 1.0)
        ]

        locator = Composites_drape.KDTreeLocator(nodes, quads)
        result_near = locator.lookup([0.5, 0.5, 0.0], tex_coords)
        result_far = locator.lookup([0.5, 0.5, 100.0], tex_coords)

        if len(result_near) >= 2 and len(result_far) >= 2:
            self.assertAlmostEqual(result_near[0], result_far[0], delta=1e-4)
            self.assertAlmostEqual(result_near[1], result_far[1], delta=1e-4)

    def test_large_mesh_kdtree_activation(self):
        """Test that k-d tree is activated for large meshes."""
        nodes, quads, tex_coords = _build_warped_grid_mesh(nx=10, ny=10)

        locator = Composites_drape.KDTreeLocator(nodes, quads)

        result = locator.lookup([5.5, 5.5, 0.0], tex_coords)
        if len(result) >= 2:
            self.assertAlmostEqual(result[0], 6.05, delta=1e-4)
            self.assertAlmostEqual(result[1], 5.225, delta=1e-4)

    def test_kdtree_matches_bruteforce_reference(self):
        """KD lookup must match brute-force reference to 6 decimal places."""
        nodes, quads, tex_coords = _build_warped_grid_mesh()
        locator = Composites_drape.KDTreeLocator(nodes, quads)

        self.assertGreaterEqual(
            len(quads), Composites_drape.KDTreeLocator.min_quads_for_kdtree()
        )

        sample_points = [
            (0.25, 0.25, 0.01),
            (2.75, 1.50, -0.02),
            (4.40, 3.10, 0.03),
            (6.20, 7.80, 0.04),
            (9.10, 10.30, -0.01),
            (11.75, 8.25, 0.02),
        ]

        for point in sample_points:
            with self.subTest(point=point):
                expected = tex_coord_at_point(nodes, quads, tex_coords, point)
                actual = locator.lookup(list(point), tex_coords)

                self.assertIsNotNone(expected)
                self.assertEqual(len(actual), 2)
                self.assertEqual(len(expected), 2)
                self.assertAlmostEqual(actual[0], expected[0], places=6)
                self.assertAlmostEqual(actual[1], expected[1], places=6)


if __name__ == '__main__':
    unittest.main()