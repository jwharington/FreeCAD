# SPDX-License-Identifier: LGPL-2.1-or-later

"""Legacy Draper adapter implementing the drape backend seam.

Wraps the flatmesh-based Draper class behind the DrapeBackend
abstract contract. Used as a fallback when nextdrape is unavailable
or when the user selects the "legacy" backend.

The legacy Draper class is defined inline here to avoid importing
from draper.py which now wraps nextdrape.
"""

from __future__ import annotations

import flatmesh
import numpy as np
from FreeCAD import (
    Base,
    Rotation,
    Vector,
)
from Part import Vertex

from ..util.mesh_util import (
    axes_mapped,
    calc_lambda_vec,
    eval_lam,
)
from .drape_backend import DrapeBackend


DEGREES_PER_RADIAN = 180.0 / pi
LEGACY_HEATMAP_DERIVE_ERROR = "unable to derive legacy heatmap payload"


def _z_rotation(offset_angle_deg):
    return Rotation(Vector(0, 0, 1), offset_angle_deg)


class _FlatmeshDraper:
    """Original flatmesh-based fabric draping solver.

    Embedded here to keep the legacy backend self-contained.
    """

    unwrap_steps = 5
    unwrap_relax_weight = 0.95

    def __init__(self, mesh, lcs, shape):
        def get_flattener():
            if not mesh.Points:
                return None
            points = np.array([[i.x, i.y, i.z] for i in mesh.Points])
            faces = np.array([list(i) for i in mesh.Topology[1]])
            flattener = flatmesh.FaceUnwrapper(points, faces)
            flattener.findFlatNodes(
                self.unwrap_steps,
                self.unwrap_relax_weight,
            )
            return flattener

        self.mesh = mesh
        self.shape = shape
        self.flattener = get_flattener()
        if not self.flattener:
            raise ValueError("Can't flatten shape")

        self.fabric_points = [Vector(*n) for n in self.flattener.ze_nodes]

        def calc_flat_placement():
            placement = lcs.getGlobalPlacement()
            T_lcs = placement.Rotation.inverted()
            tri_global, tri_fabric = self._get_facet(placement.Base)
            tri_global = [T_lcs * p for p in tri_global]
            center = T_lcs * placement.Base
            lam = calc_lambda_vec(center, tri_global)
            q = axes_mapped(lam, tri_fabric, tri_global)
            R = Rotation(q[0], q[1], Vector(0, 0, 1), "ZXY").inverted()
            origin = Vector(eval_lam(lam, tri_fabric))
            return Base.Placement(-origin, R, origin)

        self.T_fo = calc_flat_placement()
        self.fabric_points = [self.T_fo * p for p in self.fabric_points]
        self.strains = np.vstack(
            [self.calc_strain(i) for i in range(mesh.CountFacets)]
        )

    def isValid(self):
        return bool(self.flattener)

    def _get_tris(self, i):
        simp = self.mesh.Topology[1][i]
        tri_global = [self.mesh.Points[i].Vector for i in simp]
        tri_fabric = [self.fabric_points[i] for i in simp]
        return tri_global, tri_fabric

    def _get_facet(self, center):
        dist = [center.distanceToPoint(p.Vector) for p in self.mesh.Points]

        def tri_dist(tri):
            return np.sum([dist[i] for i in tri])

        totd = [tri_dist(tri) for tri in self.mesh.Topology[1]]
        facet = np.argmin(totd)
        return self._get_tris(facet)

    def _rotation_from_tris(self, center, normal, tri_global, tri_fabric):
        lam = calc_lambda_vec(center, tri_global)
        d = axes_mapped(lam, tri_global, tri_fabric)
        return Rotation(d[0], d[1], normal, "ZXY").inverted()

    def _get_lcs_at_point(self, center, normal):
        tri_global, tri_fabric = self._get_facet(center)
        return self._rotation_from_tris(center, normal, tri_global, tri_fabric)

    def get_lcs(self, tri):
        center = (tri[0] + tri[1] + tri[2]) / 3
        normal = (tri[1] - tri[0]).cross(tri[2] - tri[1]).normalize()
        return self._get_lcs_at_point(center, normal)

    def get_lcs_at_point(self, center):
        def get_uv(p):
            dmin = None
            pint = None
            fmin = None
            vert = Vertex(p.x, p.y, p.z)
            for f in self.shape.Faces:
                distance, points, info = f.distToShape(vert)
                if (not fmin) or (distance < dmin):
                    dmin = distance
                    pint = points[0][0]
                    fmin = f
            return (fmin.Surface.parameter(pint), fmin)

        def get_normal_projected(point):
            ((u, v), surface) = get_uv(point)
            return surface.valueAt(u, v), surface.normalAt(u, v)

        p, normal = get_normal_projected(center)
        return self._get_lcs_at_point(p, normal)

    def get_tex_coord_at_point(self, point, offset_angle_deg=0):
        tri_global, tri_fabric = self._get_facet(point)
        lam = calc_lambda_vec(point, tri_global)
        return _z_rotation(offset_angle_deg) * eval_lam(lam, tri_fabric)

    def get_tex_coords(self, offset_angle_deg=0):
        T = _z_rotation(offset_angle_deg)
        return [T * p for p in self.fabric_points]

    def get_boundaries(self, offset_angle_deg=0):
        T = self.T_fo * _z_rotation(offset_angle_deg)
        wires = []
        boundaries = self.flattener.getFlatBoundaryNodes()
        for edge in boundaries:
            points = [T * Vector(*node) for node in edge]
            wires.append(points)
        return wires

    def calc_strain(self, facet):
        G, F = self._get_tris(facet)
        center = (G[0] + G[1] + G[2]) / 3
        normal = (G[1] - G[0]).cross(G[2] - G[1]).normalize()
        R = self._rotation_from_tris(center, normal, G, F)
        Gp = [R * g for g in G]
        D = [g - f for g, f in zip(Gp, F)]
        u = Vector(*[d.x for d in D])
        v = Vector(*[d.y for d in D])
        beta = Vector(F[1].y - F[2].y, F[2].y - F[0].y, F[0].y - F[1].y)
        gamma = Vector(F[2].x - F[1].x, F[0].x - F[2].x, F[1].x - F[0].x)
        two_area = abs(((F[1] - F[0]).cross(F[2] - F[0])).z)
        exx = beta.dot(u)
        eyy = gamma.dot(v)
        exy = gamma.dot(u) + beta.dot(v)
        return np.array([exx, eyy, exy]) / two_area


# Re-export Draper as an alias for backward compatibility
Draper = _FlatmeshDraper


class LegacyDrapeBackend(DrapeBackend):
    backend_name = "legacy"
    linear_strain_warning_limit = 1e-4
    shear_strain_warning_limit_deg = 15.0

    def __init__(self, mesh: Any, lcs: Any, shape: Any):
        self.draper = Draper(mesh, lcs, shape)

    def is_valid(self) -> bool:
        return bool(self.draper and self.draper.isValid())

    def _empty_heatmap_payload(self, status: str, error: str | None) -> dict[str, Any]:
        return {
            "strain_heatmap_3d": None,
            "strain_heatmap_3d_status": status,
            "strain_heatmap_3d_error": error,
            "strain_heatmap_flat": None,
            "strain_heatmap_flat_status": status,
            "strain_heatmap_flat_error": error,
        }

    def diagnostics(self) -> dict[str, Any]:
        output_ready = self.is_valid()
        status = "ok" if output_ready else "invalid"
        payload: dict[str, Any] = {
            "backend": self.backend_name,
            "status": status,
            "failure_reason": None,
            "output_ready": output_ready,
            "linear_strain_warning_limit": self.linear_strain_warning_limit,
            "shear_strain_warning_limit_deg": self.shear_strain_warning_limit_deg,
        }

        if not output_ready:
            payload.update(self._empty_heatmap_payload(status="not_available", error=None))
            return payload

        heatmaps = self._build_strain_heatmaps()
        if heatmaps is None:
            payload.update(
                self._empty_heatmap_payload(
                    status="invalid_payload",
                    error=LEGACY_HEATMAP_DERIVE_ERROR,
                )
            )
            return payload

        linear_values = heatmaps["linear_values"]
        shear_values_deg = heatmaps["shear_values_deg"]
        linear_abs_extreme = max((abs(v) for v in linear_values), default=0.0)
        shear_abs_extreme = max((abs(v) for v in shear_values_deg), default=0.0)

        payload.update(
            {
                "linear_strain_min": min(linear_values),
                "linear_strain_max": max(linear_values),
                "shear_angle_abs_max_deg": shear_abs_extreme,
                "linear_strain_warning_exceeded": (
                    linear_abs_extreme > self.linear_strain_warning_limit
                ),
                "shear_strain_warning_exceeded": (
                    shear_abs_extreme > self.shear_strain_warning_limit_deg
                ),
                "strain_heatmap_3d": {
                    "coordinates": heatmaps["coordinates_3d"],
                    "linear_values": linear_values,
                    "shear_values_deg": shear_values_deg,
                    "boundary_loops_3d": [],
                },
                "strain_heatmap_3d_status": "ok",
                "strain_heatmap_3d_error": None,
                "strain_heatmap_flat": {
                    "coordinates_uv": heatmaps["coordinates_uv"],
                    "linear_values": linear_values,
                    "shear_values_deg": shear_values_deg,
                    "boundary_loops_uv": heatmaps["boundary_loops_uv"],
                },
                "strain_heatmap_flat_status": "ok",
                "strain_heatmap_flat_error": None,
            }
        )
        return payload

    def _build_strain_heatmaps(self) -> dict[str, list] | None:
        mesh = getattr(self.draper, "mesh", None)
        strains = getattr(self.draper, "strains", None)
        topology = getattr(mesh, "Topology", None)
        points = getattr(mesh, "Points", None)

        if not topology or len(topology) < 2:
            return None

        faces = topology[1]
        if not isinstance(faces, (list, tuple)):
            return None
        if points is None or strains is None:
            return None

        max_rows = min(len(faces), len(strains))

        coordinates_3d: list[list[float]] = []
        coordinates_uv: list[list[float]] = []
        linear_values: list[float] = []
        shear_values_deg: list[float] = []

        for row_idx in range(max_rows):
            face = faces[row_idx]
            if not isinstance(face, (list, tuple)) or len(face) < 3:
                continue

            try:
                p0 = getattr(points[face[0]], "Vector", points[face[0]])
                p1 = getattr(points[face[1]], "Vector", points[face[1]])
                p2 = getattr(points[face[2]], "Vector", points[face[2]])
                center = (p0 + p1 + p2) / 3
            except Exception:
                continue

            xyz = self._vector_xyz(center)
            if xyz is None:
                continue

            try:
                uv_point = self.draper.get_tex_coord_at_point(center)
            except Exception:
                continue

            uv = self._vector_uv(uv_point)
            if uv is None:
                continue

            exx, eyy, exy = self._strain_components(row_idx)
            linear = exx if abs(exx) >= abs(eyy) else eyy
            shear_deg = abs(exy) * DEGREES_PER_RADIAN

            coordinates_3d.append(xyz)
            coordinates_uv.append(uv)
            linear_values.append(float(linear))
            shear_values_deg.append(float(shear_deg))

        if not coordinates_3d:
            return None

        boundary_loops_uv = self._boundary_loops_uv()
        return {
            "coordinates_3d": coordinates_3d,
            "coordinates_uv": coordinates_uv,
            "linear_values": linear_values,
            "shear_values_deg": shear_values_deg,
            "boundary_loops_uv": boundary_loops_uv,
        }

    def _strain_components(self, idx: int) -> tuple[float, float, float]:
        try:
            row = self.draper.strains[idx]
            exx = float(row[0])
            eyy = float(row[1])
            exy = float(row[2])
            return exx, eyy, exy
        except Exception:
            return 0.0, 0.0, 0.0

    def _boundary_loops_uv(self) -> list[list[list[float]]]:
        loops: list[list[list[float]]] = []
        try:
            boundaries = list(self.draper.get_boundaries() or [])
        except Exception:
            return loops

        for boundary in boundaries:
            loop: list[list[float]] = []
            if not isinstance(boundary, (list, tuple)):
                continue
            for point in boundary:
                uv = self._vector_uv(point)
                if uv is not None:
                    loop.append(uv)
            if len(loop) >= 3:
                loops.append(loop)
        return loops

    @staticmethod
    def _vector_xyz(point: Any) -> list[float] | None:
        try:
            return [float(point.x), float(point.y), float(point.z)]
        except Exception:
            return None

    @staticmethod
    def _vector_uv(point: Any) -> list[float] | None:
        try:
            return [float(point.x), float(point.y)]
        except Exception:
            return None

    def get_tex_coords(self, offset_angle_deg: float = 0) -> list[Any] | None:
        return self.draper.get_tex_coords(offset_angle_deg=offset_angle_deg)

    def get_boundaries(self, offset_angle_deg: float = 0) -> list[list[Any]] | None:
        return self.draper.get_boundaries(offset_angle_deg=offset_angle_deg)

    def get_lcs(self, tri: Any) -> Any | None:
        return self.draper.get_lcs(tri)

    def get_lcs_at_point(self, center: Any) -> Any | None:
        return self.draper.get_lcs_at_point(center)

    def get_tex_coord_at_point(self, point: Any, offset_angle_deg: float = 0) -> Any | None:
        return self.draper.get_tex_coord_at_point(
            point,
            offset_angle_deg=offset_angle_deg,
        )

    @property
    def strains(self) -> Any:
        return self.draper.strains
