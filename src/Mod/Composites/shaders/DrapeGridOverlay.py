# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Render draped mesh fibre directions as coloured line segments.

Draws short line segments through each quad centroid, oriented along
the warp and weft directions rotated by the lamina's stacking angle.
This gives a clear visual indication of fibre orientation on the
draped surface for the selected lamina layer.
"""

from __future__ import annotations

import math
from typing import Any

import FreeCADGui
from pivy import coin


def _apply_rotation(u: float, v: float, angle_deg: float) -> tuple[float, float]:
    """Rotate a UV pair by the rosette offset angle."""
    if not angle_deg:
        return u, v
    ang = math.radians(angle_deg)
    c, s = math.cos(ang), math.sin(ang)
    return u * c - v * s, u * s + v * c


class DrapeGridOverlay:
    """Builds and manages a Coin3D scene-graph overlay of fibre directions."""

    def __init__(self) -> None:
        self.warp_color = (0.1, 0.4, 0.9)   # blue
        self.weft_color = (0.9, 0.4, 0.1)   # orange
        self.line_width = 1.0

        self._draw_style = coin.SoDrawStyle()
        self._draw_style.lineWidth = self.line_width

        self._warp_material = coin.SoMaterial()
        self._warp_material.diffuseColor = self.warp_color

        self._weft_material = coin.SoMaterial()
        self._weft_material.diffuseColor = self.weft_color

        # Group that holds the complete overlay (added as display mode).
        # Must be SoSeparator so all children render together when used
        # as a Coin3D display mode (SoSwitch whichChild=0 only shows child 0).
        self.root = coin.SoSeparator()
        self.root.setName("DrapeGridOverlay")
        self.root.addChild(self._draw_style)

        # Placeholders — repopulated by attach()
        self._warp_sep = coin.SoSeparator()
        self._weft_sep = coin.SoSeparator()
        self.root.addChild(self._warp_sep)
        self.root.addChild(self._weft_sep)

        self._attached = False

    # ------------------------------------------------------------------
    def attach(
        self,
        mesh_feat: Any,
        node_positions: list,
        quads: list,
        offset_angle_deg: float = 0.0,
    ) -> None:
        """Build the warp/weft line sets and insert into the mesh scene graph.

        Parameters
        ----------
        mesh_feat : FreeCAD Mesh::Feature
            The DrapeMesh feature whose RootNode will host the overlay.
        node_positions : list of [x,y,z]
            3D coordinates of each draper node.
        quads : list of [i0,i1,i2,i3]
            Quad connectivity.  Warp edges are i0->i1 and i2->i3.
            Weft edges are i1->i2 and i3->i0.
        offset_angle_deg : float
            Lamina stacking angle (degrees).  Rotates the fibre direction
            relative to the draper's warp/weft grid.
        """
        warp_coords, warp_idx = self._build_segments(
            node_positions, quads, offset_angle_deg, warp=True
        )
        weft_coords, weft_idx = self._build_segments(
            node_positions, quads, offset_angle_deg, warp=False
        )

        # Clear previous content
        self._warp_sep.removeAllChildren()
        self._weft_sep.removeAllChildren()

        # Warp lines
        self._warp_sep.addChild(self._warp_material)
        wc = coin.SoCoordinate3()
        wc.point.setValues(0, len(warp_coords), warp_coords)
        self._warp_sep.addChild(wc)
        wl = coin.SoLineSet()
        wl.numVertices.setValues(0, len(warp_idx), warp_idx)
        self._warp_sep.addChild(wl)

        # Weft lines
        self._weft_sep.addChild(self._weft_material)
        wc2 = coin.SoCoordinate3()
        wc2.point.setValues(0, len(weft_coords), weft_coords)
        self._weft_sep.addChild(wc2)
        wl2 = coin.SoLineSet()
        wl2.numVertices.setValues(0, len(weft_idx), weft_idx)
        self._weft_sep.addChild(wl2)

        # Attach is handled externally by the CompositeShell ViewProvider
        # via addDisplayMode — do NOT attach to the DrapeMesh RootNode here.

    # ------------------------------------------------------------------
    def _build_segments(
        self,
        node_positions: list,
        quads: list,
        offset_angle_deg: float,
        warp: bool,
    ) -> tuple[list, list]:
        """Build line segments showing fibre direction within each quad.

        For each quad, draws a line segment through the centroid, oriented
        along the warp (or weft) direction, rotated by the lamina angle.

        Returns (coords, num_vertices) where coords is a flat list of
        [x,y,z] and num_vertices is a list of 2s (each line = 2 vertices).
        """
        import numpy as np

        coords: list[list[float]] = []
        num_vertices: list[int] = []

        # The lamina angle rotates the fibre direction relative to the
        # draper's warp/weft grid.  For a 0° ply, fibres run along warp.
        # For a 45° ply, fibres run at 45° to warp.
        angle_rad = math.radians(offset_angle_deg)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        for q in quads:
            if len(q) < 4:
                continue
            i0, i1, i2, i3 = q[0], q[1], q[2], q[3]

            p0 = np.asarray(node_positions[i0], dtype=float)
            p1 = np.asarray(node_positions[i1], dtype=float)
            p2 = np.asarray(node_positions[i2], dtype=float)
            p3 = np.asarray(node_positions[i3], dtype=float)

            # Quad centroid
            centroid = (p0 + p1 + p2 + p3) / 4.0

            # Warp direction: i0->i1 (and i3->i2)
            # Weft direction: i1->i2 (and i0->i3)
            if warp:
                base_dir = p1 - p0
            else:
                base_dir = p2 - p1

            # Compute surface normal via cross product of quad edges
            edge1 = p1 - p0
            edge2 = p3 - p0
            normal = np.cross(edge1, edge2)
            norm_len = np.linalg.norm(normal)
            if norm_len < 1e-10:
                continue
            normal = normal / norm_len

            # Rotate base_dir by angle_rad around the surface normal.
            # Rodrigues' rotation formula:
            #   v_rot = v*cos + (n×v)*sin + n*(n·v)*(1-cos)
            v = base_dir
            n = normal
            v_rot = (v * cos_a
                     + np.cross(n, v) * sin_a
                     + n * np.dot(n, v) * (1.0 - cos_a))

            # Normalize and scale to ~80% of half-edge length for visibility
            v_len = np.linalg.norm(v_rot)
            if v_len < 1e-10:
                continue
            v_dir = v_rot / v_len

            # Segment length: 80% of the average edge length
            edge_len = (np.linalg.norm(p1 - p0) + np.linalg.norm(p2 - p1)) / 2.0
            seg_len = edge_len * 0.8

            p_start = centroid - v_dir * (seg_len / 2.0)
            p_end = centroid + v_dir * (seg_len / 2.0)

            coords.append([float(p_start[0]), float(p_start[1]), float(p_start[2])])
            coords.append([float(p_end[0]), float(p_end[1]), float(p_end[2])])
            num_vertices.append(2)

        return coords, num_vertices

    # ------------------------------------------------------------------
    def detach(self, mesh_feat: Any | None = None) -> None:
        """Remove the overlay from the scene graph."""
        if self._attached and mesh_feat is not None:
            try:
                root = mesh_feat.ViewObject.RootNode
                root.removeChild(self.root)
            except Exception:
                pass
        self._attached = False
        self._warp_sep.removeAllChildren()
        self._weft_sep.removeAllChildren()

