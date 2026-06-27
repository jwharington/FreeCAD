# SPDX-License-Identifier: LGPL-2.1-or-later
"""NextDrape backend — C++ solver via FreeCAD Composites module.

Wraps the nextdrape C++ solver (built as Composites_drape when FreeCAD is
configured with BUILD_COMPOSITES=ON). The solver runs natively on the
TopoDS_Shape with zero-copy access — no BREP serialization.
"""

from __future__ import annotations

import numpy as np
from typing import TYPE_CHECKING, Any

from .drape_backend import DrapeBackend

if TYPE_CHECKING:
    import FreeCAD  # noqa: F401


def _import_solver():
    """Import the C++ nextdrape solver module.

    Tries the FreeCAD-integrated build first (Composites.Composites_drape),
    then falls back to the portable dev install (ext._native).
    """
    import os
    import sys

    # Ensure the FreeCAD build Mod dir is on sys.path so Composites_drape
    # can be found.  This is needed when running FreeCADCmd outside of a
    # full FreeCAD GUI session where the build dir is auto-registered.
    _build_mod = os.environ.get("FREECAD_BUILD_MOD")
    if _build_mod and _build_mod not in sys.path:
        sys.path.insert(0, _build_mod)

    try:
        from Composites import Composites_drape as _nd
        return _nd.solve
    except ImportError:
        pass
    try:
        from ..ext import _native
        solver = getattr(_native, "solve", None)
        if solver is None:
            raise ImportError("_native.solve is None")
        return solver
    except ImportError:
        raise RuntimeError(
            "nextdrape C++ extension not available. "
            "Build FreeCAD with BUILD_COMPOSITES=ON, or install the standalone .so."
        )


class NextDrapeBackend(DrapeBackend):
    """Wraps the C++ nextdrape solver (Composites_drape module)."""

    backend_name = "nextdrape"

    def __init__(
        self,
        mesh: Any,
        lcs: Any,
        shape: Any,
    ) -> None:
        self._solve = _import_solver()
        self._mesh = mesh
        self._lcs = lcs
        self._shape = shape
        self._result: dict | None = None
        self._valid = True

    @staticmethod
    def _extract_occ_shape(shape: Any) -> Any:
        """Return the shape as-is — the C++ code handles Part.Shape directly."""
        return shape

    # ── Lazy solve ───────────────────────────────────────────────

    def _run_solve(self) -> dict:
        """Run the solver once and cache the result."""
        if self._result is None:
            seed = self._build_seed()
            params = self._build_params()
            self._result = self._solve(self._shape, seed, params)
            if not self._result.get("success"):
                self._valid = False
        return self._result

    # ── DrapeBackend protocol ────────────────────────────────────

    def is_valid(self) -> bool:
        return self._valid

    def diagnostics(self) -> dict[str, Any]:
        """Return backend diagnostics payload."""
        r = self._run_solve()
        if not r.get("success"):
            return {"error": r.get("error", "solve failed")}
        d = r.get("diagnostics", {})
        return {
            "solver": "nextdrape",
            "nodes": d.get("total_nodes", 0),
            "quads": len(r.get("quads", [])),
            "coverage_ratio": d.get("coverage_ratio", 0.0),
            "max_shear_deg": d.get("max_shear_deg", 0.0),
            "max_strain": d.get("max_strain", 0.0),
            "solve_time_ms": d.get("solve_time_ms", 0.0),
        }

    def get_tex_coords(self, offset_angle_deg: float = 0) -> list[Any] | None:
        """Return texture (UV) coordinates as a list of FreeCAD Vectors."""
        r = self._run_solve()
        if not r.get("success"):
            return None
        tex = np.asarray(r["tex_coords"])  # (N, 2)
        if offset_angle_deg:
            import math
            ang = math.radians(offset_angle_deg)
            cos_a, sin_a = math.cos(ang), math.sin(ang)
            tex = np.column_stack([
                tex[:, 0] * cos_a - tex[:, 1] * sin_a,
                tex[:, 0] * sin_a + tex[:, 1] * cos_a,
            ])
        # Convert to list of tuples matching legacy style
        return [[float(u), float(v)] for u, v in tex]

    def get_boundaries(self, offset_angle_deg: float = 0) -> list[list[Any]] | None:
        """Return boundary loops from the drape solve."""
        r = self._run_solve()
        if not r.get("success"):
            return []
        bds = r.get("boundaries", [])
        if offset_angle_deg:
            import math
            ang = math.radians(offset_angle_deg)
            cos_a, sin_a = math.cos(ang), math.sin(ang)
            rotated_bds = []
            for loop in bds:
                rotated_loop = []
                for pt in loop:
                    u, v = pt[0], pt[1]
                    ru = u * cos_a - v * sin_a
                    rv = u * sin_a + v * cos_a
                    rotated_loop.append((ru, rv))
                rotated_bds.append(rotated_loop)
            return rotated_bds
        return bds

    def get_lcs(self, tri: Any) -> Any | None:
        """Return LCS transforms for a triangle facet.

        TODO: compute proper LCS from draped surface normals + warp/weft.
        Returns identity for now.
        """
        import FreeCAD

        return FreeCAD.Placement()
    def get_lcs_at_point(self, center: Any) -> Any | None:
        """Return LCS at a 3D point. Identity for now."""
        import FreeCAD

        return FreeCAD.Placement()

    def get_tex_coord_at_point(self, point: Any, offset_angle_deg: float = 0) -> Any | None:
        """Return texture coordinate at a 3D point. Not yet supported."""
        return None

    @property
    def strains(self) -> np.ndarray:
        """Per-quad shear angles (degrees)."""
        r = self._run_solve()
        if not r.get("success"):
            return np.array([])
        return np.asarray(r.get("shear_angle", []))

    # ── Internal helpers ─────────────────────────────────────────

    def _build_seed(self) -> dict:
        """Build nextdrape SeedInput dict.

        Requires a seed point ON the surface and a warp direction
        (tangent to the surface).
        """
        mesh = self._mesh
        shape = self._shape

        if hasattr(mesh, "seed_point") and mesh.seed_point is not None:
            point = list(mesh.seed_point)
        elif hasattr(shape, "CenterOfMass"):
            com = shape.CenterOfMass
            point = [com.x, com.y, com.z]
        else:
            point = [0.0, 0.0, 0.0]

        if hasattr(mesh, "warp_direction") and mesh.warp_direction is not None:
            warp_dir = list(mesh.warp_direction)
        else:
            warp_dir = [1.0, 0.0, 0.0]

        return {"point": point, "warp_direction": warp_dir}

    def _build_params(self) -> dict:
        """Build nextdrape DrapeParams dict."""
        mesh = self._mesh
        pitch = getattr(mesh, "pitch", 5.0)
        return {
            "pitch": pitch,
            "max_warp_steps": getattr(mesh, "max_warp_steps", 40),
            "max_weft_steps": getattr(mesh, "max_weft_steps", 40),
            "shear_warn_deg": getattr(mesh, "shear_warn_deg", 20.0),
            "shear_fail_deg": getattr(mesh, "shear_fail_deg", 35.0),
            "projection_tol": getattr(mesh, "projection_tol", 0.5),
            "boundary_tol": getattr(mesh, "boundary_tol", 1e-3),
            "use_geodesic": getattr(mesh, "use_geodesic", False),
        }
