# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Drape solver backed by the nextdrape C++ kinematic draping engine.

Wraps the nextdrape C++ solver (via pybind11) behind the same API that
the legacy flatmesh-based Draper exposed, so CompositeShell, LCS tools,
and TexturePlan continue to work without changes.

Usage::

    from freecad.Composites.tools.draper import Draper

    draper = Draper(mesh, lcs, shape)
    if draper.isValid():
        coords = draper.get_tex_coords(offset_angle_deg=0)
        boundaries = draper.get_boundaries(offset_angle_deg=0)
        strains = draper.strains
"""

from __future__ import annotations

from typing import Any


class Draper:
    """nextdrape-backed fabric draping solver.

    Parameters
    ----------
    mesh : Any
        FreeCAD FEM mesh object providing node points and topology.
    lcs : Any
        FreeCAD placement / LCS object (defines fabric origin and warp direction).
    shape : Any
        FreeCAD Part::Feature or Part::Shape with a ``Shape`` attribute
        holding the OCC TopoDS_Shape to drape onto.
    """

    def __init__(
        self,
        mesh: Any,
        lcs: Any,
        shape: Any,
    ) -> None:
        from .drape_backend_nextdrape import NextDrapeBackend

        self._backend = NextDrapeBackend(mesh, lcs, shape)

    def isValid(self) -> bool:
        return self._backend.is_valid()

    # ── Whole-mesh queries ──────────────────────────────────────

    def get_tex_coords(self, offset_angle_deg: float = 0):
        """Fabric-plane texture coordinates for all mesh nodes."""
        return self._backend.get_tex_coords(offset_angle_deg=offset_angle_deg)

    def get_boundaries(self, offset_angle_deg: float = 0):
        """Closed boundary wire loops in fabric plane."""
        return self._backend.get_boundaries(offset_angle_deg=offset_angle_deg)

    # ── Per-point queries ───────────────────────────────────────

    def get_lcs(self, tri: list[Any]):
        """Local coordinate system for a triangle facet."""
        return self._backend.get_lcs(tri)

    def get_lcs_at_point(self, center: Any):
        """Local coordinate system at a 3D point."""
        return self._backend.get_lcs_at_point(center)

    def get_tex_coord_at_point(
        self, point: Any, offset_angle_deg: float = 0
    ):
        """Fabric-plane texture coordinate at a 3D point."""
        return self._backend.get_tex_coord_at_point(
            point, offset_angle_deg=offset_angle_deg
        )

    # ── Strains ─────────────────────────────────────────────────

    @property
    def strains(self):
        """Per-facet strain tensors ``(exx, eyy, exy)``."""
        return self._backend.strains

    # ── Diagnostics ─────────────────────────────────────────────

    def diagnostics(self) -> dict[str, Any]:
        """Backend diagnostics payload (strain heatmaps, status, etc.)."""
        return self._backend.diagnostics()
