# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Render draped mesh warp/weft edges as coloured line sets.

Replaces the GLSL shader approach with a simple Coin3D overlay that
draws quad edges coloured by direction:
  - Warp edges (i0->i1, i2->i3): one colour
  - Weft edges (i1->i2, i3->i0): another colour

This avoids all shader/texture-coordinate plumbing and gives a clear
visual indication of the fibre orientation on the draped surface.
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
    ang = math.radians(-angle_deg)
    c, s = math.cos(ang), math.sin(ang)
    return u * c - v * s, u * s + v * c


class DrapeGridOverlay:
    """Builds and manages a Coin3D scene-graph overlay of warp/weft edges."""

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

        # Group that holds the complete overlay (added to display mode)
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
            Rosette rotation angle (applied to UV to classify direction).
        """
        # Build line sets
        warp_coords, warp_idx = self._build_edges(
            node_positions, quads, offset_angle_deg, warp=True
        )
        weft_coords, weft_idx = self._build_edges(
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

        # Insert overlay into the DrapeMesh root if not already there
        if not self._attached:
            try:
                root = mesh_feat.ViewObject.RootNode
                root.addChild(self.root)
                self._attached = True
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _build_edges(
        self,
        node_positions: list,
        quads: list,
        offset_angle_deg: float,
        warp: bool,
    ) -> tuple[list, list]:
        """Collect edge endpoints for warp or weft edges.

        Returns (coords, num_vertices) where coords is a flat list of
        [x,y,z] and num_vertices is a list of 2s (each line = 2 vertices).
        """
        coords: list[list[float]] = []
        num_vertices: list[int] = []

        for q in quads:
            if len(q) < 4:
                continue
            i0, i1, i2, i3 = q[0], q[1], q[2], q[3]

            # Warp edges: i0->i1, i2->i3
            # Weft edges: i1->i2, i3->i0
            if warp:
                edges = [(i0, i1), (i2, i3)]
            else:
                edges = [(i1, i2), (i3, i0)]

            for a, b in edges:
                pa = node_positions[a]
                pb = node_positions[b]
                coords.append([float(pa[0]), float(pa[1]), float(pa[2])])
                coords.append([float(pb[0]), float(pb[1]), float(pb[2])])
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
