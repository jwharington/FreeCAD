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
        cut_wires: list | None = None,
        cut_shape: Any = None,
        use_cut_shape: bool = False,
    ) -> None:
        self._solve = _import_solver()
        self._mesh = mesh
        self._lcs = lcs
        self._shape = shape
        self._cut_wires = cut_wires
        self._cut_shape = cut_shape
        self._use_cut_shape = use_cut_shape
        self._result: dict | None = None
        self._valid = True

    @staticmethod
    def _extract_occ_shape(shape: Any) -> Any:
        """Return the shape as-is — the C++ code handles Part.Shape directly."""
        return shape

    # ── Lazy solve ───────────────────────────────────────────────

    def _run_solve(self) -> dict:
        """Run the solver once and cache the result."""
        debug_file = "/tmp/nextdrape_debug.txt"
        with open(debug_file, "a") as f:
            f.write(f"[_run_solve] START, _result={self._result}\n")
            f.flush()
        if self._result is None:
            seed = self._build_seed()
            params = self._build_params()
            with open(debug_file, "a") as f:
                f.write(f"[_run_solve] seed: {seed}\n")
                f.write(f"[_run_solve] params: {params}\n")
                f.write(f"[_run_solve] shape type: {type(self._shape)}\n")
                f.write("[_run_solve] calling solve...\n")
                f.flush()

            solver_shape = self._cut_shape if self._use_cut_shape else self._shape
            self._result = self._solve(solver_shape, seed, params)

            with open(debug_file, "a") as f:
                f.write(f"[_run_solve] solved, success={self._result.get('success')}\n")
                if not self._result.get("success"):
                    f.write(f"[_run_solve] error={self._result.get('error')}\n")
                # Always dump full result for diagnostics
                f.write(f"[_run_solve] result keys: {list(self._result.keys())}\n")
                f.flush()
            if not self._result.get("success"):
                self._valid = False
        return self._result

    # ── DrapeBackend protocol ────────────────────────────────────

    def is_valid(self) -> bool:
        return self._valid

    def quality_pass(self) -> bool:
        """Return whether the drape quality check passed."""
        r = self._run_solve()
        qual = r.get("quality", {})
        return bool(qual.get("overall_pass", True))

    def diagnostics(self) -> dict[str, Any]:
        """Return backend diagnostics payload."""
        r = self._run_solve()
        if not r.get("success"):
            return {
                "backend": self.backend_name,
                "status": "failed",
                "failure_reason": r.get("error", "solve failed"),
            }
        d = r.get("diagnostics", {})
        return {
            "backend": self.backend_name,
            "status": "valid",
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
            ang = math.radians(-offset_angle_deg)
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
            ang = math.radians(-offset_angle_deg)
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

        Computes the local coordinate system from the draped surface:
        - Origin: centroid of the triangle
        - X-axis: warp direction (along the u-direction)
        - Z-axis: surface normal (cross product of warp and weft)
        - Y-axis: cross(Z, X) to complete right-handed frame
        """
        import FreeCAD
        import numpy as np
        from scipy.spatial.transform import Rotation

        r = self._run_solve()
        if not r.get("success"):
            return None

        node_positions = np.asarray(r["node_positions"])  # (N, 3)
        quads = r.get("quads", [])  # list of [i0, i1, i2, i3]

        if not quads or len(node_positions) == 0:
            return None

        # Extract triangle vertices from the tri argument
        # tri is expected to be a tuple/list of 3 vertex indices or 3D points
        if isinstance(tri, (list, tuple)) and len(tri) == 3:
            # Could be indices or points
            first = tri[0]
            if isinstance(first, (int, np.integer)):
                # Indices
                i0, i1, i2 = [int(idx) for idx in tri]
                v0, v1, v2 = node_positions[i0], node_positions[i1], node_positions[i2]
            else:
                # FreeCAD.Vector, tuples, lists, or any iterable of 3 floats
                try:
                    v0, v1, v2 = np.asarray(tri[0]), np.asarray(tri[1]), np.asarray(tri[2])
                except Exception:
                    return None
        else:
            return None

        # Centroid
        centroid = (v0 + v1 + v2) / 3.0

        # Warp direction (edge v0->v1, approximating u-direction)
        warp = v1 - v0
        warp_norm = np.linalg.norm(warp)
        if warp_norm < 1e-10:
            return None
        warp_unit = warp / warp_norm

        # Weft direction (edge v0->v2, approximating v-direction)
        weft_raw = v2 - v0
        weft_norm = np.linalg.norm(weft_raw)
        if weft_norm < 1e-10:
            return None

        # Orthogonalize weft against warp (Gram-Schmidt)
        weft_unit = weft_raw - np.dot(weft_raw, warp_unit) * warp_unit
        weft_unit_norm = np.linalg.norm(weft_unit)
        if weft_unit_norm < 1e-10:
            return None
        weft_unit = weft_unit / weft_unit_norm

        # Surface normal (right-hand rule: warp × weft)
        normal = np.cross(warp_unit, weft_unit)
        normal_norm = np.linalg.norm(normal)
        if normal_norm < 1e-10:
            return None
        normal_unit = normal / normal_norm

        # Y-axis: cross(Z, X) to complete right-handed frame
        y_axis = np.cross(normal_unit, warp_unit)

        # Build rotation matrix from basis vectors
        rot_matrix = np.column_stack([warp_unit, y_axis, normal_unit])
        rotation = Rotation.from_matrix(rot_matrix)

        # Convert to FreeCAD Placement
        quat = rotation.as_quat()  # SciPy returns [x, y, z, w]
        fc_placement = FreeCAD.Placement()
        fc_placement.Rotation = FreeCAD.Rotation(quat[3], quat[0], quat[1], quat[2])
        fc_placement.Base = FreeCAD.Vector(centroid[0], centroid[1], centroid[2])

        return fc_placement
    def get_lcs_at_point(self, center: Any) -> Any | None:
        """Return LCS at a 3D point by finding the nearest quad.

        Computes the local coordinate system from the draped surface
        at the closest quad to the given point.
        """
        import FreeCAD
        import numpy as np
        from scipy.spatial.transform import Rotation

        r = self._run_solve()
        if not r.get("success"):
            return None

        node_positions = np.asarray(r["node_positions"])  # (N, 3)
        quads = r.get("quads", [])  # list of [i0, i1, i2, i3]

        if not quads or len(node_positions) == 0:
            return None

        cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
        cp = np.array([cx, cy, cz])

        best_quad = None
        best_dist = float("inf")

        for q in quads:
            i0, i1, i2, i3 = [int(idx) for idx in q]
            centroid = (node_positions[i0] + node_positions[i1] +
                       node_positions[i2] + node_positions[i3]) / 4.0
            dist = np.linalg.norm(cp - centroid)
            if dist < best_dist:
                best_dist = dist
                best_quad = q

        if best_quad is None:
            return None

        i0, i1, i2, i3 = [int(idx) for idx in best_quad]
        v0, v1, v2, v3 = node_positions[i0], node_positions[i1], node_positions[i2], node_positions[i3]

        # Centroid
        centroid = (v0 + v1 + v2 + v3) / 4.0

        # Warp direction (v0->v1)
        warp = v1 - v0
        warp_norm = np.linalg.norm(warp)
        if warp_norm < 1e-10:
            return None
        warp_unit = warp / warp_norm

        # Weft direction (v0->v3), orthogonalized against warp
        weft_raw = v3 - v0
        weft_unit = weft_raw - np.dot(weft_raw, warp_unit) * warp_unit
        weft_unit_norm = np.linalg.norm(weft_unit)
        if weft_unit_norm < 1e-10:
            return None
        weft_unit = weft_unit / weft_unit_norm

        # Normal
        normal = np.cross(warp_unit, weft_unit)
        normal_norm = np.linalg.norm(normal)
        if normal_norm < 1e-10:
            return None
        normal_unit = normal / normal_norm

        # Y-axis
        y_axis = np.cross(normal_unit, warp_unit)

        rot_matrix = np.column_stack([warp_unit, y_axis, normal_unit])
        rotation = Rotation.from_matrix(rot_matrix)
        quat = rotation.as_quat()  # SciPy returns [x, y, z, w]

        fc_placement = FreeCAD.Placement()
        fc_placement.Rotation = FreeCAD.Rotation(quat[3], quat[0], quat[1], quat[2])
        fc_placement.Base = FreeCAD.Vector(centroid[0], centroid[1], centroid[2])

        return fc_placement

    def get_tex_coord_at_point(self, point: Any, offset_angle_deg: float = 0) -> Any | None:
        """Return texture coordinate at a 3D point via bilinear interpolation.

        Finds the quad containing the projected 3D point and interpolates
        the UV coordinates from the four corner nodes.
        """
        r = self._run_solve()
        if not r.get("success"):
            return None

        node_positions = np.asarray(r["node_positions"])  # (N, 3)
        quads = r.get("quads", [])  # list of [i0, i1, i2, i3]
        tex_coords = np.asarray(r["tex_coords"])  # (N, 2)

        if not quads or len(node_positions) == 0:
            return None

        # Convert input point to numpy
        px, py, pz = float(point[0]), float(point[1]), float(point[2])

        best_quad = None
        best_dist = float("inf")
        best_u, best_v = 0.0, 0.0

        for q in quads:
            i0, i1, i2, i3 = [int(idx) for idx in q]
            c0 = node_positions[i0]
            c1 = node_positions[i1]
            c2 = node_positions[i2]
            c3 = node_positions[i3]

            # Compute quad centroid and normal
            centroid = (c0 + c1 + c2 + c3) / 4.0
            v1 = c1 - c0
            v2 = c3 - c0
            normal = np.cross(v1, v2)
            norm_len = np.linalg.norm(normal)
            if norm_len < 1e-10:
                continue
            normal /= norm_len

            # Project point onto quad plane
            to_point = np.array([px, py, pz]) - centroid
            dist_to_plane = abs(np.dot(to_point, normal))

            if dist_to_plane > 5.0:  # Too far from plane
                continue

            # Solve for (u, v) in quad parametric space
            # P = c0 + u*(c1-c0) + v*(c3-c0) + u*v*(c2-c1-c3+c0)
            # Simplified: use least squares on the planar projection
            proj_point = np.array([px, py, pz]) - normal * dist_to_plane * np.sign(
                np.dot(to_point, normal)
            )

            # Build 2D basis from quad edges
            e0 = c1 - c0
            e1 = c3 - c0
            e0_norm = np.linalg.norm(e0)
            e1_norm = np.linalg.norm(e1)
            if e0_norm < 1e-10 or e1_norm < 1e-10:
                continue
            e0_unit = e0 / e0_norm
            e1_unit = e1 - np.dot(e1, e0_unit) * e0_unit
            e1_unit_norm = np.linalg.norm(e1_unit)
            if e1_unit_norm < 1e-10:
                continue
            e1_unit /= e1_unit_norm

            delta = proj_point - c0
            u_est = np.dot(delta, e0_unit) / e0_norm
            v_est = np.dot(delta, e1_unit) / e1_norm

            # Check if (u, v) is inside the quad [0,1]x[0,1]
            if -0.05 <= u_est <= 1.05 and -0.05 <= v_est <= 1.05:
                # Refine with bilinear inverse
                c_corner = c2 - c1 - c3 + c0
                if np.linalg.norm(c_corner) > 1e-10:
                    # Quadratic in u: (c_corner·e0_unit)*u² + ...
                    a_u = np.dot(c_corner, e0_unit)
                    b_u = np.dot(e0, e0_unit) + np.dot(c_corner, e1_unit) * v_est - np.dot(delta, e0_unit)
                    c_u = np.dot(e0, e0_unit) * v_est + np.dot(c0, e0_unit) - np.dot(delta, e0_unit)
                    if abs(a_u) > 1e-15:
                        disc = b_u * b_u - 4 * a_u * c_u
                        if disc >= 0:
                            u_est = (-b_u + np.sqrt(disc)) / (2 * a_u)
                            if 0 <= u_est <= 1:
                                a_v = np.dot(c_corner, e1_unit)
                                b_v = np.dot(e1, e1_unit) + np.dot(c_corner, e0_unit) * u_est - np.dot(delta, e1_unit)
                                c_v = np.dot(e1, e1_unit) * u_est + np.dot(c0, e1_unit) - np.dot(delta, e1_unit)
                                if abs(a_v) > 1e-15:
                                    disc_v = b_v * b_v - 4 * a_v * c_v
                                    if disc_v >= 0:
                                        v_est = (-b_v + np.sqrt(disc_v)) / (2 * a_v)
                else:
                    u_est = np.dot(delta, e0_unit) / e0_norm
                    v_est = np.dot(delta, e1_unit) / e1_unit_norm

                if 0 <= u_est <= 1 and 0 <= v_est <= 1:
                    # Interpolate UV coordinates
                    uv = (
                        (1 - u_est) * (1 - v_est) * tex_coords[i0]
                        + u_est * (1 - v_est) * tex_coords[i1]
                        + u_est * v_est * tex_coords[i2]
                        + (1 - u_est) * v_est * tex_coords[i3]
                    )
                    dist = np.linalg.norm(proj_point - (c0 + u_est * (c1 - c0) + v_est * (c3 - c0)))
                    if dist < best_dist:
                        best_dist = dist
                        best_quad = q
                        best_u, best_v = uv[0], uv[1]

        if best_quad is None:
            return None

        # Apply offset angle rotation
        if offset_angle_deg:
            import math
            ang = math.radians(-offset_angle_deg)
            cos_a, sin_a = math.cos(ang), math.sin(ang)
            best_u, best_v = (
                best_u * cos_a - best_v * sin_a,
                best_u * sin_a + best_v * cos_a,
            )

        return [best_u, best_v]

    @property
    def strains(self) -> np.ndarray:
        """Per-quad strains as [warp, weft, shear] when available.

        Backward compatibility:
        - legacy payloads may only expose shear_angle -> returns (N,)
        - newer payloads expose warp_strain/weft_strain/shear_angle -> returns (N,3)
        """
        r = self._run_solve()
        if not r.get("success"):
            return np.array([])

        shear = np.asarray(r.get("shear_angle", []), dtype=float)
        warp = np.asarray(r.get("warp_strain", []), dtype=float)
        weft = np.asarray(r.get("weft_strain", []), dtype=float)

        if shear.ndim == 1 and warp.ndim == 1 and weft.ndim == 1:
            if len(shear) and len(warp) == len(shear) and len(weft) == len(shear):
                return np.column_stack([warp, weft, shear])
        return shear

    # ── Internal helpers ─────────────────────────────────────────

    def _project_point_to_surface(self, point) -> list:
        """Project a point onto the shape surface.

        When the center of mass lies inside a solid (e.g. a cylinder),
        projecting it onto the surface ensures the draper seed lands
        on valid geometry rather than failing with NonDrapable.

        Strategy: push the point to the nearest bounding-box face by
        clamping each coordinate independently and measuring the
        resulting displacement.  Pick the axis that yields the
        shortest push.
        """
        shape = self._shape
        bbox = shape.BoundBox

        px, py, pz = point
        candidates: list[tuple[float, list[float]]] = []

        # Push along X
        cx_high = max(px, bbox.XMax) if px < bbox.XMax else min(px, bbox.XMin)
        cx_low = min(px, bbox.XMin) if px > bbox.XMin else max(px, bbox.XMax)
        for cx_val in (cx_high, cx_low):
            d = abs(cx_val - px)
            candidates.append((d, [cx_val, py, pz]))

        # Push along Y
        cy_high = max(py, bbox.YMax) if py < bbox.YMax else min(py, bbox.YMin)
        cy_low = min(py, bbox.YMin) if py > bbox.YMin else max(py, bbox.YMax)
        for cy_val in (cy_high, cy_low):
            d = abs(cy_val - py)
            candidates.append((d, [px, cy_val, pz]))

        # Push along Z
        cz_high = max(pz, bbox.ZMax) if pz < bbox.ZMax else min(pz, bbox.ZMin)
        cz_low = min(pz, bbox.ZMin) if pz > bbox.ZMin else max(pz, bbox.ZMax)
        for cz_val in (cz_high, cz_low):
            d = abs(cz_val - pz)
            candidates.append((d, [px, py, cz_val]))

        # Return the candidate with the shortest push
        candidates.sort(key=lambda c: c[0])
        return candidates[0][1] if candidates else point

    def _build_seed(self) -> dict:
        """Build nextdrape SeedInput dict.

        Uses the Rosette LCS (LocalCoordinateSystem) to position the
        seed point and orient the warp direction.  Falls back to the
        shape center-of-mass projected onto the surface when no LCS
        is available.
        """
        mesh = self._mesh
        shape = self._shape

        # ── Seed point ───────────────────────────────────────────
        if hasattr(mesh, "seed_point") and mesh.seed_point is not None:
            point = list(mesh.seed_point)
        elif self._lcs and hasattr(self._lcs, "Placement"):
            # Use the LCS placement base as the seed point
            base = self._lcs.Placement.Base
            point = [base.x, base.y, base.z]
        elif hasattr(shape, "CenterOfMass"):
            com = shape.CenterOfMass
            point = self._project_point_to_surface(com)
        else:
            point = [0.0, 0.0, 0.0]

        # ── Warp direction ───────────────────────────────────────
        if hasattr(mesh, "warp_direction") and mesh.warp_direction is not None:
            warp_dir = list(mesh.warp_direction)
        elif self._lcs and hasattr(self._lcs, "Placement"):
            # Use the LCS X-axis as the warp direction (fiber direction).
            # The Rosette LCS is oriented with X along fibers, Z normal
            # to the surface.  Transform the standard X vector by the
            # LCS rotation to get the world-space warp direction.
            from FreeCAD import Vector

            rot = self._lcs.Placement.Rotation
            axis = rot.multVec(Vector(1, 0, 0))
            warp_dir = [axis.x, axis.y, axis.z]
        else:
            warp_dir = [1.0, 0.0, 0.0]

        return {"point": point, "warp_direction": warp_dir}

    def _build_params(self) -> dict:
        """Build nextdrape DrapeParams dict."""
        mesh = self._mesh
        pitch = getattr(mesh, "pitch", 5.0)
        params: dict[str, Any] = {
            "pitch": pitch,
            "max_warp_steps": getattr(mesh, "max_warp_steps", 40),
            "max_weft_steps": getattr(mesh, "max_weft_steps", 40),
            "shear_warn_deg": getattr(mesh, "shear_warn_deg", 20.0),
            "shear_fail_deg": getattr(mesh, "shear_fail_deg", 35.0),
            "strain_fail": getattr(mesh, "strain_fail", 0.15),
            "projection_tol": getattr(mesh, "projection_tol", 0.5),
            "boundary_tol": getattr(mesh, "boundary_tol", 1e-3),
            "use_geodesic": getattr(mesh, "use_geodesic", False),
        }
        # When cut wires are specified, enable the C++ cut-wire blocking
        # engine. The wires are embedded in the compound support Shape
        # so C++ DiscoverCutWires() can discover them natively.
        if self._cut_wires:
            params["cut_wires_enabled"] = True
            params["cut_wires_proximity_tol"] = 0.5
            params["cut_wires_block_nodes"] = True
            params["cut_wires_block_quads"] = True
        return params
