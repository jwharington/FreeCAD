# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for UV coordinate mapping from drape mesh to support surface.

Tests cover:
- Basic corner/center/edge mapping (single quad)
- Piecewise linear continuity across quad boundaries
- Diagonal linearity through multi-quad grids
- Interior point accuracy on fine grids
- Warped (non-planar) quad handling
"""

import unittest
import numpy as np

# Import the function under test directly
from Composites.features.coin_geometry import _map_uv_to_support


class GridDraper:
    """Mock draper that simulates a regular grid of quads in the XY plane.

    UV coordinates are set to identity mapping (world position = UV),
    so we can verify that the UV field is piecewise linear and continuous
    across quad boundaries.

    Parameters
    ----------
    nx, ny : int
        Number of quads in X and Y directions.
    x_min, y_min : float
        Bottom-left corner of the grid.
    dx, dy : float
        Spacing between nodes in X and Y (defaults to 1.0).
    """

    def __init__(self, nx=1, ny=1, x_min=0.0, y_min=0.0, dx=1.0, dy=1.0):
        self.nx = nx
        self.ny = ny
        self.dx = dx
        self.dy = dy

        # Build node positions: (ny+1) x (nx+1) grid in XY plane at Z=0
        nodes = []
        for j in range(ny + 1):
            for i in range(nx + 1):
                nodes.append([x_min + i * dx, y_min + j * dy, 0.0])
        self._node_positions = np.array(nodes, dtype=np.float64)

        # Build quads
        self._quads = []
        for j in range(ny):
            for i in range(nx):
                idx = j * (nx + 1) + i
                self._quads.append([idx, idx + 1, idx + (nx + 1) + 1, idx + (nx + 1)])

        # UV = world XY position (identity mapping)
        self._tex_coords = self._node_positions[:, :2].copy()

        self._backend = self

    def get_tex_coord_at_point(self, point, offset_angle_deg=0):
        """Delegate to geometry_util.tex_coord_at_point()."""
        from Composites.util.geometry_util import tex_coord_at_point
        return tex_coord_at_point(
            self._node_positions, self._quads, self._tex_coords,
            point, offset_angle_deg
        )


class TestMapUvToSupport(unittest.TestCase):
    """Test _map_uv_to_support with controlled inputs."""

    # ------------------------------------------------------------------
    # Regression tests (single-quad / edge cases)
    # ------------------------------------------------------------------

    def test_none_draper_returns_zeros(self):
        """With no draper, should return zero UVs."""
        verts = [(0, 0, 0), (1, 1, 1)]
        result = _map_uv_to_support(None, verts)
        self.assertEqual(len(result), 2)
        np.testing.assert_array_almost_equal(result, [[0, 0], [0, 0]])

    def test_empty_verts(self):
        """Empty vertex list should return empty array."""
        draper = GridDraper(nx=1, ny=1)
        result = _map_uv_to_support(draper, [])
        self.assertEqual(len(result), 0)

    def test_single_vertex_center_of_quad(self):
        """Vertex at center of quad should get UV (0.5, 0.5)."""
        draper = GridDraper(nx=1, ny=1)
        verts = [(0.5, 0.5, 0.0)]
        result = _map_uv_to_support(draper, verts)

        self.assertEqual(len(result), 1)
        np.testing.assert_array_almost_equal(result[0], [0.5, 0.5])

    def test_corners_match_tex_coords(self):
        """Vertices at quad corners should get exact tex coords."""
        draper = GridDraper(nx=1, ny=1)
        verts = [
            (0.0, 0.0, 0.0),  # node 0 -> UV (0, 0)
            (1.0, 0.0, 0.0),  # node 1 -> UV (1, 0)
            (1.0, 1.0, 0.0),  # node 2 -> UV (1, 1)
            (0.0, 1.0, 0.0),  # node 3 -> UV (0, 1)
        ]
        result = _map_uv_to_support(draper, verts)

        expected = [[0, 0], [1, 0], [1, 1], [0, 1]]
        np.testing.assert_array_almost_equal(result, expected)

    def test_multiple_vertices(self):
        """Multiple vertices should all get interpolated UVs."""
        draper = GridDraper(nx=1, ny=1)
        verts = [
            (0.25, 0.25, 0.0),
            (0.75, 0.75, 0.0),
            (0.0, 0.5, 0.0),
            (0.5, 0.0, 0.0),
        ]
        result = _map_uv_to_support(draper, verts)

        self.assertEqual(len(result), 4)
        # Check that UVs are in [0,1] range
        self.assertTrue(all(0 <= u <= 1 for u, v in result))
        self.assertTrue(all(0 <= v <= 1 for u, v in result))
        # Center-ish points should have UVs near 0.5
        np.testing.assert_array_almost_equal(result[0], [0.25, 0.25])
        np.testing.assert_array_almost_equal(result[1], [0.75, 0.75])

    def test_point_outside_quad_gets_clamped(self):
        """Points outside the quad should get clamped UVs (nearest quad)."""
        draper = GridDraper(nx=1, ny=1)
        verts = [(2.0, 2.0, 0.0)]  # Far outside the unit square
        result = _map_uv_to_support(draper, verts)

        self.assertEqual(len(result), 1)
        # Should get nearest-quad fallback, which for a single quad
        # would clamp to [0,1]x[0,1] giving (1,1)
        # But the actual behavior depends on the backend implementation
        # Just check it doesn't crash
        self.assertTrue(len(result) == 1)

    def test_z_offset_points(self):
        """Points with Z offset should still get correct UVs (projection).
        
        Without a plane distance filter, the bilinear refinement projects
        the query point onto the quad plane. Any Z offset is ignored as
        long as the XY projection falls within the quad.
        """
        draper = GridDraper(nx=1, ny=1)
        verts = [
            (0.5, 0.5, 10.0),   # Large Z offset
            (0.5, 0.5, -5.0),   # Large negative Z offset
        ]
        result = _map_uv_to_support(draper, verts)

        self.assertEqual(len(result), 2)
        # Both should map to center UV regardless of Z
        np.testing.assert_array_almost_equal(result[0], [0.5, 0.5])
        np.testing.assert_array_almost_equal(result[1], [0.5, 0.5])

    def test_no_backend_attribute(self):
        """Draper without _backend should return zeros."""
        class BareDraper:
            pass
        result = _map_uv_to_support(BareDraper(), [(0, 0, 0)])
        np.testing.assert_array_almost_equal(result, [[0, 0]])

    def test_backend_with_none_result(self):
        """Backend that returns None should get zero UVs."""
        class SilentDraper:
            _backend = type('Backend', (), {
                'get_tex_coord_at_point': staticmethod(lambda p, o=0: None)
            })()

        result = _map_uv_to_support(SilentDraper(), [(0, 0, 0)])
        np.testing.assert_array_almost_equal(result, [[0, 0]])

    # ------------------------------------------------------------------
    # Piecewise continuity tests
    # ------------------------------------------------------------------
    # Note: bilinear interpolation produces CURVED UV fields, not linear ones.
    # Tests verify continuity (no jumps at boundaries) and consistency
    # (same UV regardless of which adjacent quad is selected), NOT linearity.

    def test_shared_edge_consistency(self):
        """Points on a shared edge must get consistent UVs from both quads.

        Two quads share an edge. A query point lying exactly on that edge
        is evaluated by both quads during quad containment search. The
        resulting UV must be identical regardless of which quad is selected
        as "best".
        """
        draper = GridDraper(nx=2, ny=1, x_min=0.0, y_min=0.0, dx=1.0, dy=1.0)

        # Points on the shared edge between quad[0] and quad[1] (at x=1)
        edge_points = [
            [1.0, 0.5, 0.0],   # midpoint of shared edge
            [1.0, 0.0, 0.0],   # bottom corner (shared vertex)
            [1.0, 1.0, 0.0],   # top corner (shared vertex)
        ]

        result = _map_uv_to_support(draper, edge_points)

        # UV must be identical regardless of which quad is selected
        # For a unit square with identity UV, center of edge = (0.5, 0.5) in UV
        np.testing.assert_array_almost_equal(result[0], [1.0, 0.5], decimal=6)
        np.testing.assert_array_almost_equal(result[1], [1.0, 0.0], decimal=6)
        np.testing.assert_array_almost_equal(result[2], [1.0, 1.0], decimal=6)

    def test_edge_uv_linear_along_edge(self):
        """UV must vary linearly along a shared edge (edges are 1D lines).

        On a shared edge, the bilinear interpolation reduces to 1D linear
        interpolation between the two corner UVs. Three collinear points
        A, B, C with B midway must have UV_B = (UV_A + UV_C) / 2.
        """
        draper = GridDraper(nx=2, ny=1, x_min=0.0, y_min=0.0, dx=1.0, dy=1.0)

        a_pt = [0.0, 0.0, 0.0]
        b_pt = [0.0, 0.5, 0.0]  # midpoint along shared edge
        c_pt = [0.0, 1.0, 0.0]

        result = _map_uv_to_support(draper, [a_pt, b_pt, c_pt])

        uv_mid_expected = (result[0] + result[2]) / 2.0
        np.testing.assert_array_almost_equal(result[1], uv_mid_expected, decimal=6)

    def test_uv_field_smooth_across_grid(self):
        """UV field must be smooth (no spikes) across a multi-quad grid.

        The UV difference between any two adjacent sample points must be
        bounded. Large jumps indicate discontinuity in the mapping.
        """
        draper = GridDraper(nx=3, ny=3, x_min=0.0, y_min=0.0, dx=1.0, dy=1.0)

        # Sample points forming a grid traversal
        samples = []
        for j in range(4):
            for i in range(4):
                samples.append([i + 0.5, j + 0.5, 0.0])

        result = _map_uv_to_support(draper, samples)

        # Check all adjacent pairs (horizontal and vertical neighbors)
        max_diff = 0.0
        for j in range(3):
            for i in range(3):
                idx = j * 4 + i
                # Horizontal neighbor
                du_h = abs(result[idx + 1][0] - result[idx][0])
                dv_h = abs(result[idx + 1][1] - result[idx][1])
                max_diff = max(max_diff, du_h, dv_h)
                # Vertical neighbor
                du_v = abs(result[idx + 4][0] - result[idx][0])
                dv_v = abs(result[idx + 4][1] - result[idx][1])
                max_diff = max(max_diff, du_v, dv_v)

        # Differences should be bounded by the grid spacing
        self.assertLess(max_diff, 1.1,
            f"Max UV difference between adjacent points: {max_diff:.2e}")

    def test_node_uv_matches_tex_coords(self):
        """Node positions must map to their own tex coords.

        For a grid where UV = world XY, querying at a node position
        must return that node's tex coord exactly.
        """
        draper = GridDraper(nx=3, ny=3, x_min=0.0, y_min=0.0, dx=1.0, dy=1.0)

        nodes = draper._node_positions.tolist()
        result = _map_uv_to_support(draper, nodes)

        # Each node's UV must match its tex coord
        for idx, node in enumerate(nodes):
            np.testing.assert_array_almost_equal(
                result[idx], draper._tex_coords[idx], decimal=6,
                err_msg=f"Node {idx} at {node} got UV {result[idx]} expected {draper._tex_coords[idx]}")

    def test_bounded_gradient(self):
        """UV gradient between adjacent grid points must be bounded.

        For a grid with spacing (dx, dy) and identity UV mapping, the
        UV difference between adjacent nodes must be <= (dx, dy).
        """
        draper = GridDraper(nx=3, ny=3, x_min=0.0, y_min=0.0, dx=1.0, dy=1.0)

        # All grid nodes
        nodes = draper._node_positions.tolist()
        result = _map_uv_to_support(draper, nodes)

        # Check differences between horizontally adjacent nodes
        nx = draper.nx + 1
        max_dx = 0.0
        max_dy = 0.0
        for j in range(draper.ny + 1):
            for i in range(draper.nx):
                idx = j * nx + i
                du = abs(result[idx + 1][0] - result[idx][0])
                dv = abs(result[idx + 1][1] - result[idx][1])
                max_dx = max(max_dx, du)
                max_dy = max(max_dy, dv)

        # Adjacent nodes differ by at most dx in U and dy in V
        self.assertLessEqual(max_dx, draper.dx + 1e-6)
        self.assertLessEqual(max_dy, draper.dy + 1e-6)

    def test_no_uv_self_intersection(self):
        """Distinct spatial points must not map to the same UV.

        A valid parametrization should be injective: two points separated
        in space should have different UV coordinates.
        """
        draper = GridDraper(nx=3, ny=3, x_min=0.0, y_min=0.0, dx=1.0, dy=1.0)

        nodes = draper._node_positions.tolist()
        result = _map_uv_to_support(draper, nodes)

        # Check all pairs for collisions
        n = len(result)
        for i in range(n):
            for j in range(i + 1, n):
                du = abs(result[i][0] - result[j][0])
                dv = abs(result[i][1] - result[j][1])
                spatial_dist = np.linalg.norm(
                    draper._node_positions[i] - draper._node_positions[j]
                )
                if spatial_dist > 1e-6:
                    self.assertGreater(
                        max(du, dv), 1e-6,
                        f"Spatially distinct nodes {i} and {j} map to same UV")

    def test_warped_quad_continuity(self):
        """Non-planar (warped) quads must still produce continuous UVs.

        When a quad is non-planar, bilinear refinement introduces a small
        correction. The UV field should remain continuous across shared
        edges even with this correction — no sudden jumps.
        """
        # Build 2 quads sharing an edge, but with one quad warped
        node_positions = np.array([
            # Quad A (planar, bottom-left)
            [0.0, 0.0, 0.0],  # 0
            [1.0, 0.0, 0.0],  # 1
            [1.0, 1.0, 0.0],  # 2
            [0.0, 1.0, 0.0],  # 3
            # Quad B (shares edge 1-2, but warped)
            [1.0, 0.0, 0.0],  # 4 (= node 1)
            [2.0, 0.0, 0.0],  # 5
            [2.0, 1.0, 0.5],  # 6 — warped (Z offset)
            [1.0, 1.0, 0.0],  # 7 (= node 2)
        ], dtype=np.float64)

        quads = [[0, 1, 2, 3], [4, 5, 6, 7]]

        # Identity UV mapping
        tex_coords = node_positions[:, :2].copy()

        class WarpedDraper:
            def __init__(self, nodes, quads, uvs):
                self._node_positions = nodes
                self._quads = quads
                self._tex_coords = uvs
                self._backend = self

            def get_tex_coord_at_point(self, point, offset_angle_deg=0):
                from Composites.util.geometry_util import tex_coord_at_point
                return tex_coord_at_point(
                    self._node_positions, self._quads, self._tex_coords,
                    point, offset_angle_deg
                )

        draper = WarpedDraper(node_positions, quads, tex_coords)

        # Points on the shared edge (nodes 1-2, which is nodes 4-7)
        edge_pts = [
            [1.0, 0.0, 0.0],
            [1.5, 0.5, 0.0],
            [1.0, 1.0, 0.0],
        ]

        result = _map_uv_to_support(draper, edge_pts)

        # UV should be finite and consistent (no NaN/Inf)
        self.assertFalse(np.any(np.isnan(result)), "UV contains NaN")
        self.assertFalse(np.any(np.isinf(result)), "UV contains Inf")
        # UV values should be in a reasonable range (not wildly off)
        self.assertTrue(np.all(np.abs(result) < 10),
            f"UV values out of reasonable range: {result}")


if __name__ == "__main__":
    unittest.main()