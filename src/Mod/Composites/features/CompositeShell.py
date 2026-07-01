# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

import hashlib
import json
from datetime import datetime, timezone

import numpy as np

from FreeCAD import Console

from .. import (
    COMPOSITE_SHELL_TOOL_ICON,
    is_comp_type,
    roma_map,
)
from ..tools.drape_backend_nextdrape import NextDrapeBackend


def _build_drapecd_mesh(node_positions, quads):
    """Build Coin3D geometry from draper node_positions and quads.

    Preserves 1:1 mapping: vertex i = node_positions[i].
    No deduplication — matches old working version behavior.

    Returns a tuple of (coin_separator, mesh_proxy) where:
    - coin_separator: SoSeparator with SoCoordinate3 + SoIndexedFaceSet
    - mesh_proxy: Minimal Mesh.Mesh for FreeCAD Mesh::Feature compatibility
    """
    from pivy import coin

    # Coordinate3: one point per draper node (no dedup)
    coords = coin.SoCoordinate3()
    pts = [coin.SbVec3f(float(p[0]), float(p[1]), float(p[2])) for p in node_positions]
    coords.point.setValues(0, len(pts), pts)

    # IndexedFaceSet: triangulated quads with node indices.
    # Keep an explicit face→quad mapping so colors can be assigned per quad
    # without ambiguity: each quad contributes two triangles.
    face_set = coin.SoIndexedFaceSet()
    indices = []
    material_indices = []
    for quad_idx, q in enumerate(quads):
        i0, i1, i2, i3 = [int(idx) for idx in q]
        # Two triangles per quad, separated by -1.
        indices.extend([i0, i1, i2, -1])
        indices.extend([i0, i2, i3, -1])
        # Explicitly map both triangles back to the originating quad.
        material_indices.extend([quad_idx, -1, quad_idx, -1])
    indices.append(-1)  # End of all faces
    material_indices.append(-1)
    face_set.coordIndex.setValues(0, len(indices), indices)
    face_set.materialIndex.setValues(0, len(material_indices), material_indices)

    # Build a simple SoSeparator with coords + face_set
    sep = coin.SoSeparator()
    sep.addChild(coords)
    sep.addChild(face_set)

    # Minimal mesh proxy for FreeCAD Mesh::Feature compatibility
    import Mesh
    import FreeCAD
    mesh_proxy = Mesh.Mesh()
    v1 = FreeCAD.Vector(0, 0, 0)
    v2 = FreeCAD.Vector(0.001, 0, 0)
    v3 = FreeCAD.Vector(0, 0.001, 0)
    mesh_proxy.addFacets([(v1, v2, v3)])

    return sep, mesh_proxy


class _RehydratedBackend:
    """Transient backend rebuilt from persisted JSON properties.

    When the support shape hasn't changed across recompute cycles,
    the draper solve result is reconstructed from FreeCAD properties
    (NodePositionsJSON, QuadsJSON, TexCoordsJSON, StrainsJSON, QualityJSON)
    instead
    of re-running the C++ solver.  This class implements the same
    interface as NextDrapeBackend so that execute() and all public
    accessor methods on CompositeShellFP work identically.

    Attributes
    ----------
    _node_positions : ndarray (N, 3)
        Draped node positions in world space.
    _quads : list[list[int]]
        Quad connectivity as lists of four vertex indices.
    _tex_coords : ndarray (N, 2)
        Texture (UV) coordinates per node.
    _strains : ndarray
        Persisted per-quad strain payload:
        - legacy: (M,) shear angles only
        - current: (M,3) [warp_strain, weft_strain, shear_angle]
    _status : str
        Solve status from the original solve ("valid" or "failed").
    _failure_reason : str or None
        Reason string if the original solve failed.
    """

    backend_name = "nextdrape"

    def __init__(
        self,
        node_positions_json: str,
        quads_json: str,
        tex_coords_json: str,
        strains_json: str,
        quality_json: str = "{}",
        status: str = "valid",
        failure_reason: str | None = None,
    ) -> None:
        self._node_positions = np.array(json.loads(node_positions_json))
        self._quads = json.loads(quads_json)
        self._tex_coords = np.array(json.loads(tex_coords_json)) if tex_coords_json else np.empty((0, 2))
        self._strains = np.array(json.loads(strains_json)) if strains_json else np.array([])
        self._quality = json.loads(quality_json)
        self._status = status
        self._failure_reason = failure_reason

    # ── DrapeBackend protocol ────────────────────────────────────

    def is_valid(self) -> bool:
        return self._status == "valid"

    def diagnostics(self) -> dict:
        if self._status != "valid":
            return {
                "backend": self.backend_name,
                "status": "failed",
                "failure_reason": self._failure_reason or "solve_failed",
            }
        return {
            "backend": self.backend_name,
            "status": "valid",
            "solver": "nextdrape",
            "nodes": len(self._node_positions),
            "quads": len(self._quads),
            "max_shear_deg": float(np.max(self._strains)) if len(self._strains) else 0.0,
            "max_strain": float(np.max(self._strains)) if len(self._strains) else 0.0,
        }

    def get_tex_coords(self, offset_angle_deg: float = 0) -> list | None:
        if self._status != "valid" or len(self._tex_coords) == 0:
            return None
        tex = self._tex_coords.copy()
        if offset_angle_deg:
            import math
            ang = math.radians(-offset_angle_deg)
            cos_a, sin_a = math.cos(ang), math.sin(ang)
            tex = np.column_stack([
                tex[:, 0] * cos_a - tex[:, 1] * sin_a,
                tex[:, 0] * sin_a + tex[:, 1] * cos_a,
            ])
        return [[float(u), float(v)] for u, v in tex]

    def get_boundaries(self, offset_angle_deg: float = 0) -> list | None:
        # Boundaries are not persisted — return empty list
        # (consistent with a fresh solve returning no boundaries)
        return []

    def get_lcs(self, tri) -> "FreeCAD.Placement | None":
        """Compute LCS from persisted node_positions and quads."""
        import FreeCAD
        from scipy.spatial.transform import Rotation

        if self._status != "valid" or not self._quads or len(self._node_positions) == 0:
            return None

        node_positions = self._node_positions
        quads = self._quads

        if isinstance(tri, (list, tuple)) and len(tri) == 3:
            first = tri[0]
            if isinstance(first, (int, np.integer)):
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

        centroid = (v0 + v1 + v2) / 3.0

        warp = v1 - v0
        warp_norm = np.linalg.norm(warp)
        if warp_norm < 1e-10:
            return None
        warp_unit = warp / warp_norm

        weft_raw = v2 - v0
        weft_unit = weft_raw - np.dot(weft_raw, warp_unit) * warp_unit
        weft_unit_norm = np.linalg.norm(weft_unit)
        if weft_unit_norm < 1e-10:
            return None
        weft_unit = weft_unit / weft_unit_norm

        normal = np.cross(warp_unit, weft_unit)
        normal_norm = np.linalg.norm(normal)
        if normal_norm < 1e-10:
            return None
        normal_unit = normal / normal_norm

        y_axis = np.cross(normal_unit, warp_unit)
        rot_matrix = np.column_stack([warp_unit, y_axis, normal_unit])
        rotation = Rotation.from_matrix(rot_matrix)
        quat = rotation.as_quat()

        fc_placement = FreeCAD.Placement()
        fc_placement.Rotation = FreeCAD.Rotation(quat[3], quat[0], quat[1], quat[2])
        fc_placement.Base = FreeCAD.Vector(centroid[0], centroid[1], centroid[2])
        return fc_placement

    def get_lcs_at_point(self, center) -> "FreeCAD.Placement | None":
        """Compute LCS at a 3D point from persisted data."""
        import FreeCAD
        from scipy.spatial.transform import Rotation

        if self._status != "valid" or not self._quads or len(self._node_positions) == 0:
            return None

        node_positions = self._node_positions
        quads = self._quads

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

        centroid = (v0 + v1 + v2 + v3) / 4.0
        warp = v1 - v0
        warp_norm = np.linalg.norm(warp)
        if warp_norm < 1e-10:
            return None
        warp_unit = warp / warp_norm

        weft_raw = v3 - v0
        weft_unit = weft_raw - np.dot(weft_raw, warp_unit) * warp_unit
        weft_unit_norm = np.linalg.norm(weft_unit)
        if weft_unit_norm < 1e-10:
            return None
        weft_unit = weft_unit / weft_unit_norm

        normal = np.cross(warp_unit, weft_unit)
        normal_norm = np.linalg.norm(normal)
        if normal_norm < 1e-10:
            return None
        normal_unit = normal / normal_norm

        y_axis = np.cross(normal_unit, warp_unit)
        rot_matrix = np.column_stack([warp_unit, y_axis, normal_unit])
        rotation = Rotation.from_matrix(rot_matrix)
        quat = rotation.as_quat()

        fc_placement = FreeCAD.Placement()
        fc_placement.Rotation = FreeCAD.Rotation(quat[3], quat[0], quat[1], quat[2])
        fc_placement.Base = FreeCAD.Vector(centroid[0], centroid[1], centroid[2])
        return fc_placement

    def get_tex_coord_at_point(self, point, offset_angle_deg: float = 0) -> list | None:
        """Interpolate UV at a 3D point from persisted data."""
        if self._status != "valid" or not self._quads or len(self._node_positions) == 0:
            return None

        node_positions = self._node_positions
        quads = self._quads
        tex_coords = self._tex_coords

        px, py, pz = float(point[0]), float(point[1]), float(point[2])

        best_quad = None
        best_dist = float("inf")
        best_u, best_v = 0.0, 0.0

        for q in quads:
            i0, i1, i2, i3 = [int(idx) for idx in q]
            c0, c1, c2, c3 = node_positions[i0], node_positions[i1], node_positions[i2], node_positions[i3]

            centroid = (c0 + c1 + c2 + c3) / 4.0
            v1, v2 = c1 - c0, c3 - c0
            normal = np.cross(v1, v2)
            norm_len = np.linalg.norm(normal)
            if norm_len < 1e-10:
                continue
            normal /= norm_len

            to_point = np.array([px, py, pz]) - centroid
            dist_to_plane = abs(np.dot(to_point, normal))
            if dist_to_plane > 5.0:
                continue

            proj_point = np.array([px, py, pz]) - normal * dist_to_plane * np.sign(
                np.dot(to_point, normal)
            )

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
            v_est = np.dot(delta, e1_unit) / e1_unit_norm

            if -0.05 <= u_est <= 1.05 and -0.05 <= v_est <= 1.05:
                c_corner = c2 - c1 - c3 + c0
                if np.linalg.norm(c_corner) > 1e-10:
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
        return self._strains

    # ── execute() compatibility ──────────────────────────────────
    # execute() calls _backend._run_solve() to obtain raw solve data.
    # We provide the same dict interface so execute() works unchanged.

    def _run_solve(self) -> dict:
        """Return cached solve result dict (no actual solve performed)."""
        strains = np.asarray(self._strains)
        if strains.ndim == 2 and strains.shape[1] >= 3:
            warp = strains[:, 0].tolist()
            weft = strains[:, 1].tolist()
            shear = strains[:, 2].tolist()
        else:
            warp = []
            weft = []
            shear = strains.tolist()

        return {
            "success": self._status == "valid",
            "error": self._failure_reason,
            "node_positions": self._node_positions.tolist(),
            "quads": self._quads,
            "tex_coords": self._tex_coords.tolist(),
            "warp_strain": warp,
            "weft_strain": weft,
            "shear_angle": shear,
            "quality": self._quality,
        }


from ..tools.fibre import (
    make_fibre_length_analysis,
    make_fibre_orientation_analysis,
)
from ..util import mesh_util
from .Command import BaseCommand
from .Container import getCompositesContainer
from .Laminate import is_laminate
from .Rosette import is_rosette
from .VPCompositeBase import CompositeBaseFP


def is_composite_shell(obj):
    return is_comp_type(
        obj,
        "Part::FeaturePython",
        "Composite::Shell",
    )


class CompositeShellFP(CompositeBaseFP):
    Type = "Composite::Shell"

    def __init__(
        self, obj, support=None, laminate=None, lcs=None, rosette=None
    ):
        self._initializing = True
        obj.addProperty(
            type="App::PropertyLinkGlobal",
            name="Support",
            group="References",
            doc="Shell shape",
        )

        obj.setPropertyStatus("Support", "LockDynamic")
        obj.setPropertyStatus("Support", "ReadOnly")

        obj.addProperty(
            type="App::PropertyLinkGlobal",
            name="LocalCoordinateSystem",
            group="Materials",
            doc="Local coordinate system used for orthotropic materials",
        )

        obj.addProperty(
            type="App::PropertyLinkGlobal",
            name="Rosette",
            group="Materials",
            doc="Rosette defining the fibre orientation origin and angle",
        )

        obj.addProperty(
            type="App::PropertyLinkGlobal",
            name="Laminate",
            group="Materials",
            doc="Laminate material",
        )
        # section could be composite laminate, or homogeneous lamina

        obj.addProperty(
            type="App::PropertyFloat",
            name="DrapePitch",
            group="Draping",
            doc="Drape mesh pitch (node spacing) in mm",
        )
        obj.DrapePitch = 20.0

        obj.addProperty(
            type="App::PropertyLinkList",
            name="DrapeCuts",
            group="Draping",
            doc="Wires defining cut paths on the support surface during draping",
        )

        obj.addProperty(
            type="App::PropertyString",
            name="DrapeDiagnostics",
            group="Draping",
            doc="Read-only JSON diagnostics for drape backend status",
        )
        obj.setPropertyStatus("DrapeDiagnostics", "ReadOnly")

        obj.addProperty(
            type="App::PropertyBool",
            name="DrapeValid",
            group="Draping",
            doc="Whether the drape solve succeeded (persisted across recompute)",
        )
        obj.DrapeValid = False
        obj.setPropertyStatus("DrapeValid", "ReadOnly")

        obj.addProperty(
            type="App::PropertyBool",
            name="QualityPass",
            group="Draping",
            doc="Whether the drape quality check passed (readonly)",
        )
        obj.QualityPass = True
        obj.setPropertyStatus("QualityPass", "ReadOnly")

        obj.addProperty(
            type="App::PropertyString",
            name="DrapeQuality",
            group="Draping",
            doc="Human-readable draping quality status",
        )
        obj.setPropertyStatus("DrapeQuality", "ReadOnly")

        obj.addProperty(
            type="App::PropertyString",
            name="TexCoordsJSON",
            group="Draping",
            doc="Serialized texture coordinates from the drape solve",
        )

        # Persisted draper solve data — allows skipping re-solve when the
        # support shape is unchanged across recompute cycles.
        obj.addProperty(
            type="App::PropertyString",
            name="NodePositionsJSON",
            group="Draping",
            doc="Serialized node positions [N,3] from the drape solve",
        )
        obj.addProperty(
            type="App::PropertyString",
            name="QuadsJSON",
            group="Draping",
            doc="Serialized quad connectivity [M,4] from the drape solve",
        )
        obj.addProperty(
            type="App::PropertyString",
            name="StrainsJSON",
            group="Draping",
            doc="Serialized per-quad shear angles from the drape solve",
        )
        obj.addProperty(
            type="App::PropertyString",
            name="QualityJSON",
            group="Draping",
            doc="Serialized quality result from the drape solve",
        )

        obj.addProperty(
            type="App::PropertyString",
            name="ShapeFingerprint",
            group="Draping",
            doc="SHA256 hash of the support shape for detecting geometry changes",
            hidden=True,
        )

        obj.addProperty(
            type="App::PropertyFloat",
            name="_LastRosetteAngle",
            group="Draping",
            doc="Cached rosette angle for detecting angle changes",
            hidden=True,
        )

        obj.addProperty(
            type="App::PropertyFloat",
            name="_LastDrapePitch",
            group="Draping",
            doc="Cached drape pitch for detecting pitch changes",
            hidden=True,
        )

        obj.addProperty(
            type="App::PropertyString",
            name="_DrapeCutsFingerprint",
            group="Draping",
            doc="Cached fingerprint of DrapeCuts for persisted solve data",
            hidden=True,
        )

        obj.addProperty(
            type="App::PropertyLinkGlobal",
            name="Mesh",
            group="Orthographic",
            doc="Mesh for orthotropic materials",
            hidden=True,
        )

        obj.DrapeDiagnostics = ""
        obj.LocalCoordinateSystem = lcs
        obj.Rosette = rosette
        obj.Laminate = laminate
        obj.Support = support

        self._rosette_angle = 0.0
        self._backend = None
        self._needs_recompute = False

        super().__init__(obj)
        self._initializing = False

    def onDocumentRestored(self, fp):
        """Initialize tracking fields for documents saved before they existed."""
        # Ensure DrapeCuts property exists on older FCStd files
        # that were saved before this property was added.
        if not hasattr(fp, "DrapeCuts"):
            fp.addProperty(
                type="App::PropertyLinkList",
                name="DrapeCuts",
                group="Draping",
                doc="Wires defining cut paths on the support surface during draping",
            )
        if not hasattr(fp, "_LastDrapePitch") or fp._LastDrapePitch is None:
            fp._LastDrapePitch = float(fp.DrapePitch)
        if not hasattr(fp, "_LastRosetteAngle") or fp._LastRosetteAngle is None:
            fp._LastRosetteAngle = float(fp.Rosette.Angle) if fp.Rosette else 0.0
        if not hasattr(fp, "_DrapeCutsFingerprint") or not fp._DrapeCutsFingerprint:
            fp._DrapeCutsFingerprint = self._drape_cuts_fingerprint(fp)
        if not hasattr(fp, "ShapeFingerprint") or not fp.ShapeFingerprint:
            try:
                fp.ShapeFingerprint = self._shape_fingerprint(fp.Support.Shape)
            except Exception:
                pass
        super().onDocumentRestored(fp)

    def execute(self, fp):
        # Always hide the native LCS symbology so only the rosette
        # disk+arrows are visible in the 3D view.
        self._hide_lcs_view(fp)

        # If DrapePitch was changed without an explicit recompute, do it now.
        if getattr(fp.Proxy, "_needs_recompute", False):
            fp.Proxy._needs_recompute = False

        if (not fp.Support) or (not fp.Laminate):
            return

        def get_lcs():
            if fp.Rosette:
                return fp.Rosette.LocalCoordinateSystem
            if fp.LocalCoordinateSystem:
                return fp.LocalCoordinateSystem
            return fp.Support

        self._rosette_angle = float(fp.Rosette.Angle) if fp.Rosette else 0.0

        # ── Try to rehydrate from persisted data ───────────────────
        if self._can_use_persisted(fp):
            self._diag(fp, "rehydrating from persisted drape")
            try:
                self._rehydrate(fp)
                return
            except Exception as exc:
                self._diag(fp, f"rehydrate failed: {exc}")

        # ── Full solve — run synchronously ─────────────────────────
        self._diag(fp, "running drape solve")
        fp.Shape = fp.Support.Shape
        result = self._run_drape_sync(fp, get_lcs())
        if isinstance(result, Exception):
            self._diag(fp, f"drape failed: {result}")
            self._mark_failed(fp, str(result))
        else:
            self._diag(fp, "drape completed")
            self._complete_drape(fp, result)

    def _diag(self, fp, message):
        try:
            name = getattr(fp, "Name", "<unnamed>")
            Console.PrintMessage(f"[Composites][Drape] {name}: {message}\n")
        except Exception:
            pass

    def _run_drape_sync(self, fp, lcs):
        """Run the draper solve synchronously and return the result dict."""
        from ..compositetools.drape_task import run_drape_task

        return run_drape_task(
            fp,
            lcs,
            fp.Support.Shape,
        )

    def _complete_drape(self, fp, result):
        """Update FreeCAD properties and load shader (main thread)."""
        import json

        backend = result["backend"]
        self._backend = backend
        drapecd_mesh = result["drapecd_mesh"]
        solve_result = result["solve_result"]
        diag = result["diag"]
        valid = result["valid"]
        quality_pass = result["quality_pass"]
        tex_coords = result["tex_coords"]

        # Diagnostics
        self._set_drape_diagnostics(
            fp,
            backend=diag.get("backend", "nextdrape"),
            status=diag.get("status", "invalid"),
            failure_reason=diag.get("failure_reason"),
            extras={
                k: v for k, v in diag.items()
                if k not in {"backend", "status", "failure_reason"}
            },
        )

        fp.DrapeValid = valid
        fp.QualityPass = quality_pass

        qual = solve_result.get("quality", {})
        fp.DrapeQuality = repr(qual)

        if tex_coords is not None:
            fp.TexCoordsJSON = json.dumps(tex_coords)
        else:
            fp.TexCoordsJSON = ""

        # Persist solve data for rehydration
        self._persist_solve_data(fp, solve_result)

        # Store mesh in backend for ViewProvider shader attachment
        backend._mesh = drapecd_mesh
        backend._mesh_feat = fp.Mesh

        # Create/update DrapeMesh feature
        if not hasattr(fp, "Mesh") or fp.Mesh is None:
            fp.Mesh = fp.Document.addObject(
                "Mesh::Feature",
                "DrapeMesh",
            )
            fp.setPropertyStatus("Mesh", "LockDynamic")
            fp.setPropertyStatus("Mesh", "ReadOnly")

        # drapecd_mesh is now a (coin_separator, mesh_proxy) tuple
        drapecd_coin, mesh_proxy = drapecd_mesh
        fp.Mesh.Mesh = mesh_proxy  # Minimal proxy for Mesh::Feature compat

        # Defer geometry injection + shader load to the next event-loop
        # iteration.  Setting fp.Mesh.Mesh triggers an asynchronous
        # RootNode rebuild inside FreeCAD; if we inject geometry and
        # attach the shader synchronously, the rebuild wipes them out.
        vp = getattr(fp, "ViewObject", None)
        coin_to_inject = drapecd_coin
        cut_edges = result.get("cut_edges")
        if vp:
            try:
                from PySide6 import QtCore

                def _deferred():
                    try:
                        mesh_vobj = getattr(fp.Mesh, "ViewObject", None)
                        if mesh_vobj and hasattr(mesh_vobj, "RootNode"):
                            root = mesh_vobj.RootNode
                            self._remove_existing_coin_geometry(root)
                            self._inject_coin_geometry(root, coin_to_inject)
                            self._remove_cut_edges(root)
                            self._inject_cut_edges(root, cut_edges)
                        if hasattr(vp, "Proxy"):
                            vp.Proxy.reload_shader()
                            vp.Proxy._set_shell_transparency(vp)
                    except Exception:
                        pass

                QtCore.QTimer.singleShot(0, _deferred)
            except Exception:
                # Fallback: synchronous injection
                mesh_vobj = getattr(fp.Mesh, "ViewObject", None)
                if mesh_vobj and hasattr(mesh_vobj, "RootNode"):
                    root = mesh_vobj.RootNode
                    self._remove_existing_coin_geometry(root)
                    self._inject_coin_geometry(root, drapecd_coin)
                    self._remove_cut_edges(root)
                    self._inject_cut_edges(root, result.get("cut_edges"))
                if vp and hasattr(vp, "Proxy"):
                    try:
                        vp.Proxy.reload_shader()
                    except Exception:
                        pass

        # Make shell semi-transparent so drape mesh shows through
        if vp:
            try:
                vp.Proxy._set_shell_transparency(vp)
            except Exception:
                pass

        # Update the view
        view_object = getattr(fp, "ViewObject", None)
        if view_object:
            view_object.update()

    def _find_switch(self, node):
        """Find the Switch child inside the given Coin3D node (recursive).

        Returns the Switch node itself, or None if not found.
        """
        children = node.getChildren()
        if children is None:
            return None
        for i in range(int(children.getLength())):
            c = children[i]
            if c and "Switch" in str(c.getTypeId().getName()):
                return c
        return None

    def _remove_existing_coin_geometry(self, root):
        """Remove any previously injected Coin3D geometry from root."""
        children = root.getChildren()
        if children is None:
            return
        for i in range(int(children.getLength()) - 1, -1, -1):
            c = children[i]
            if c is None:
                continue
            if c.getName() == "DrapedMeshGeometry":
                root.removeChild(i)

    def _inject_coin_geometry(self, root, coin_geo):
        """Inject Coin3D geometry as a child of root."""
        coin_geo.setName("DrapedMeshGeometry")
        root.addChild(coin_geo)

    def _inject_cut_edges(self, root, cut_edges: list) -> None:
        """Inject cut-edge line geometry as visible overlays.

        Each cut is a list of 3D point tuples forming a polyline.
        A red line is drawn through the points so cut boundaries
        are clearly visible on top of the draped mesh.
        """
        from pivy import coin

        if not cut_edges:
            return

        sep = coin.SoSeparator()

        for walk in cut_edges:
            pc = len(walk)
            if pc < 2:
                continue
            wire_sep = coin.SoSeparator()
            # Red material
            wire_mat = coin.SoMaterial()
            wire_mat.diffuseColor.setValue(1.0, 0.0, 0.0)
            wire_sep.addChild(wire_mat)
            # 3D coordinates
            wire_coords = coin.SoCoordinate3()
            pts: list[coin.SbVec3f] = [
                coin.SbVec3f(float(p[0]), float(p[1]), float(p[2]))
                for p in walk
            ]
            wire_coords.point.setValues(0, pc, pts)
            wire_sep.addChild(wire_coords)
            # Linear line segments
            line_set = coin.SoLineSet()
            wire_sep.addChild(line_set)
            sep.addChild(wire_sep)

        # Put cut-edge layer *after* the main mesh so it draws on top.
        root.addChild(sep)

    def _remove_cut_edges(self, root) -> None:
        """Remove previously injected cut-edge separator from root."""
        from pivy import coin
        children = root.getChildren()
        if children is None or children.getLength() == 0:
            return
        last = children[children.getLength() - 1]
        if (
            last
            and not str(last.getTypeId().getName())
            in ("Separator", "Switch", "Path", "Group")
        ):
            # Check if it looks like a cut-edge group:
            # Coordinate3 + SoLineSet
            sub = last.getChildren()
            if sub and sub.getLength() >= 2:
                has_coord = has_lineset = False
                for j in range(int(sub.getLength())):
                    sc = sub[j]
                    if sc is None:
                        continue
                    st = str(sc.getTypeId().getName())
                    if st == "Coordinate3":
                        has_coord = True
                    if "LineSet" in st:
                        has_lineset = True
                if has_coord and has_lineset:
                    root.removeChild(last)

    def _mark_failed(self, fp, error_msg):
        """Mark the shell as failed (main thread)."""
        import json

        self._backend = None
        fp.DrapeValid = False
        fp.QualityPass = False
        fp.DrapeQuality = "error: " + error_msg[:200]
        fp.TexCoordsJSON = ""
        fp.NodePositionsJSON = ""
        fp.QuadsJSON = ""
        fp.StrainsJSON = ""
        self._set_drape_diagnostics(
            fp,
            backend="nextdrape",
            status="error",
            failure_reason="solver_unsolved",
        )
        Console.PrintWarning(f"CompositeShell drape setup failed: {error_msg}\n")
        view_object = getattr(fp, "ViewObject", None)
        if view_object:
            view_object.update()

    # ── Persistence helpers ────────────────────────────────────────

    def _drape_cuts_fingerprint(self, fp) -> str:
        """Compute a fingerprint of the DrapeCuts wire list.

        Used in _can_use_persisted to detect when cut wires change.
        """
        import hashlib
        h = hashlib.sha256()
        h.update(b"dravecif:int")
        cuts = getattr(fp, "DrapeCuts", None) or []
        h.update(f"n{len(cuts)}".encode())
        for label in cuts:
            h.update(f"{label!s}".encode())
        return h.hexdigest()[:16]

    def _shape_fingerprint(self, shape) -> str:
        """Compute a fast structural hash of a FreeCAD shape.

        Used to detect whether the support geometry has changed between
        recompute cycles.  Combines shape-level metadata that is cheap
        to compute but sufficiently discriminative.
        """
        h = hashlib.sha256()
        h.update(b"shape:v1:")
        try:
            h.update(getattr(shape, "Label", "").encode())
        except Exception:
            pass
        try:
            h.update(f"{shape.Volume:.6f}".encode())
        except Exception:
            pass
        try:
            bb = shape.BoundBox
            h.update(f"{bb.XMin:.3f},{bb.YMin:.3f},{bb.ZMin:.3f},"
                     f"{bb.XMax:.3f},{bb.YMax:.3f},{bb.ZMax:.3f}".encode())
        except Exception:
            pass
        try:
            verts, edges, faces, shells = (
                len(shape.Vertexes),
                len(shape.Edges),
                len(shape.Faces),
                len(shape.Shells),
            )
            h.update(f"V{verts}E{edges}F{faces}S{shells}".encode())
        except Exception:
            pass
        return h.hexdigest()[:16]

    def _can_use_persisted(self, fp) -> bool:
        """Return True if persisted solve data is still valid."""
        # Must have a valid prior solve
        if not fp.DrapeValid:
            return False
        # Must have all persisted fields
        if not (fp.NodePositionsJSON and fp.QuadsJSON and fp.TexCoordsJSON):
            return False
        # Support shape must be unchanged
        if not fp.Support:
            return False
        try:
            current = self._shape_fingerprint(fp.Support.Shape)
        except Exception:
            return False
        stored = getattr(fp, "ShapeFingerprint", "")
        if not stored:
            return False
        if current != stored:
            return False
        # Rosette angle affects texture coordinate rotation.
        # If the angle changed, the persisted tex_coords are stale.
        try:
            current_angle = float(fp.Rosette.Angle) if fp.Rosette else 0.0
            stored_angle = getattr(fp, "_LastRosetteAngle", 0.0)
            if abs(current_angle - stored_angle) > 0.001:
                return False
        except Exception:
            return False
        # Drape cuts affect the drape solve result.
        # If cut wires changed, the persisted payload is stale.
        try:
            cuts_fp = self._drape_cuts_fingerprint(fp)
            stored_cuts_fp = getattr(fp, "_DrapeCutsFingerprint", "")
            if stored_cuts_fp and cuts_fp != stored_cuts_fp:
                return False
        except Exception:
            return False
        # Drape pitch affects the drape solve result.
        # If the pitch changed, persisted node positions/quads are stale.
        try:
            current_pitch = float(fp.DrapePitch)
            stored_pitch = getattr(fp, "_LastDrapePitch", None)
            # If _LastDrapePitch was never recorded (e.g. data saved before
            # this check existed), distrust the persisted payload.
            if stored_pitch is None:
                return False
            if abs(current_pitch - stored_pitch) > 0.001:
                return False
        except Exception:
            return False
        return True

    def _rehydrate(self, fp) -> None:
        """Replace _backend with a _RehydratedBackend from persisted data."""
        self._backend = _RehydratedBackend(
            node_positions_json=fp.NodePositionsJSON,
            quads_json=fp.QuadsJSON,
            tex_coords_json=fp.TexCoordsJSON,
            strains_json=fp.StrainsJSON,
            quality_json=fp.QualityJSON if hasattr(fp, "QualityJSON") else "{}",
            status="valid",
            failure_reason=None,
        )

        # Update diagnostics from rehydrated state
        diag = self._backend.diagnostics()
        self._set_drape_diagnostics(
            fp,
            backend=diag.get("backend", "nextdrape"),
            status=diag.get("status", "invalid"),
            failure_reason=diag.get("failure_reason"),
            extras={
                k: v for k, v in diag.items()
                if k not in {"backend", "status", "failure_reason"}
            },
        )

        # Run fibre analysis (uses rehydrated strains/boundaries)
        if diag.get("status") != "failed":
            self.fibre_analysis(fp)

        # Rebuild the draped mesh from persisted node_positions + quads
        solve_result = self._backend._run_solve()
        node_positions = solve_result.get("node_positions", [])
        quads = solve_result.get("quads", [])
        drapecd_coin, mesh_proxy = _build_drapecd_mesh(node_positions, quads)

        # Ensure DrapeMesh feature exists
        if not hasattr(fp, "Mesh") or fp.Mesh is None:
            fp.Mesh = fp.Document.addObject(
                "Mesh::Feature",
                "DrapeMesh",
            )
            fp.setPropertyStatus("Mesh", "LockDynamic")
            fp.setPropertyStatus("Mesh", "ReadOnly")

        fp.Mesh.Mesh = mesh_proxy  # Minimal proxy for Mesh::Feature compat

        # Defer geometry injection + shader load to the next event-loop
        # iteration (same reason as _complete_drape).
        vp = getattr(fp, "ViewObject", None)
        coin_to_inject = drapecd_coin
        if vp:
            try:
                from PySide6 import QtCore

                def _deferred():
                    try:
                        mesh_vobj = getattr(fp.Mesh, "ViewObject", None)
                        if mesh_vobj and hasattr(mesh_vobj, "RootNode"):
                            root = mesh_vobj.RootNode
                            self._remove_existing_coin_geometry(root)
                            self._inject_coin_geometry(root, coin_to_inject)
                        if hasattr(vp, "Proxy"):
                            vp.Proxy.reload_shader()
                            vp.Proxy._set_shell_transparency(vp)
                    except Exception:
                        pass

                QtCore.QTimer.singleShot(0, _deferred)
            except Exception:
                mesh_vobj = getattr(fp.Mesh, "ViewObject", None)
                if mesh_vobj and hasattr(mesh_vobj, "RootNode"):
                    root = mesh_vobj.RootNode
                    self._remove_existing_coin_geometry(root)
                    self._inject_coin_geometry(root, drapecd_coin)
                if vp and hasattr(vp, "Proxy"):
                    try:
                        vp.Proxy.reload_shader()
                    except Exception:
                        pass

        # Human-readable quality status (from rehydrated solve result)
        qual = solve_result.get("quality", {})
        fp.DrapeQuality = repr(qual) if diag.get("status") != "failed" else "invalid"

        # Transparency is set by the deferred callback above

    def _persist_solve_data(self, fp, solve_result: dict) -> None:
        """Store solve result arrays as JSON properties for rehydration."""
        fp.NodePositionsJSON = json.dumps(
            solve_result.get("node_positions", []).tolist()
        )
        fp.QuadsJSON = json.dumps(
            solve_result.get("quads", [])
        )
        shear = np.asarray(solve_result.get("shear_angle", []), dtype=float)
        warp = np.asarray(solve_result.get("warp_strain", []), dtype=float)
        weft = np.asarray(solve_result.get("weft_strain", []), dtype=float)
        if (
            shear.ndim == 1
            and warp.ndim == 1
            and weft.ndim == 1
            and len(shear)
            and len(warp) == len(shear)
            and len(weft) == len(shear)
        ):
            strains_payload = np.column_stack([warp, weft, shear]).tolist()
        else:
            # Backward compatibility: persist shear-only if full tensor is absent.
            strains_payload = shear.tolist()
        fp.StrainsJSON = json.dumps(strains_payload)
        fp.QualityJSON = json.dumps(
            solve_result.get("quality", {})
        )
        # Cache the shape fingerprint so _can_use_persisted skips rehashing
        fp.ShapeFingerprint = self._shape_fingerprint(fp.Support.Shape)
        # Cache the rosette angle so _can_use_persisted detects changes
        fp._LastRosetteAngle = float(fp.Rosette.Angle) if fp.Rosette else 0.0
        # Cache the drape pitch so _can_use_persisted detects changes
        fp._LastDrapePitch = float(fp.DrapePitch)
        # Cache cut-wire fingerprint so _can_use_persisted detects wire changes
        fp._DrapeCutsFingerprint = self._drape_cuts_fingerprint(fp)

    def fibre_analysis(self, fp):
        histograms_length = make_fibre_length_analysis(fp)
        Console.PrintMessage("Material fibre length analysis:")
        for material, histogram in histograms_length.items():
            Console.PrintMessage(f"  {material}: {histogram.average_length}")
        orientation_fraction = make_fibre_orientation_analysis(fp)
        Console.PrintMessage("Orientation fraction analysis:")
        for orientation, fraction in orientation_fraction.items():
            Console.PrintMessage(f"  {orientation}: {fraction:.2f}")

    def _make_backend(self, mesh, lcs, shape):
        return NextDrapeBackend(mesh, lcs, shape)

    def _hide_lcs_view(self, fp):
        """Hide the native LCS symbology (planes + 3D arrows)."""
        lcs = fp.LocalCoordinateSystem
        if lcs is None and fp.Rosette:
            lcs = fp.Rosette.LocalCoordinateSystem
        if lcs is None:
            return
        lcs_vobj = getattr(lcs, "ViewObject", None)
        if lcs_vobj is not None:
            lcs_vobj.Visibility = False

    def _set_drape_diagnostics(
        self,
        fp,
        *,
        backend,
        status,
        failure_reason,
        extras=None,
    ):
        payload = {
            "schema_version": "1.0",
            "backend": backend,
            "status": status,
            "failure_reason": failure_reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if extras:
            payload.update(extras)
        fp.DrapeDiagnostics = json.dumps(payload, sort_keys=True)

    def onChanged(self, fp, prop):
        if getattr(self, "_initializing", False):
            return
        match prop:
            case "Laminate":
                fp.recompute()
            case "LocalCoordinateSystem" | "Rosette":
                fp.recompute()
            case "DrapePitch":
                # Mark the shell as needing a recompute.  The actual
                # recompute is deferred — the user (or a script) must
                # call fp.recompute() explicitly after settling on a
                # new pitch value.  This avoids hanging the GUI when
                # dragging the slider (each tick would trigger a
                # 1-2s solve).
                fp.Proxy._needs_recompute = True

            case "DrapeCuts":
                fp.Proxy._needs_recompute = True

            case "Support":
                fp.recompute()

    def _require_valid(self):
        """Assert the draper is valid; raise if it isn't."""
        assert self._backend is not None and self._backend.is_valid(), (
            "Draper not valid – execute() should have produced a valid backend"
        )

    def get_tex_coords(self, offset_angle_deg):
        self._require_valid()
        return self._backend.get_tex_coords(
            offset_angle_deg=offset_angle_deg
            + getattr(self, "_rosette_angle", 0.0),
        )

    def get_draper(self):
        self._require_valid()
        return self._backend.draper

    def get_drape_lcs(self, tris):
        self._require_valid()
        return self._backend.get_lcs(tris)

    def get_boundaries(self, offset_angle_deg):
        self._require_valid()
        return self._backend.get_boundaries(
            offset_angle_deg=offset_angle_deg
            + getattr(self, "_rosette_angle", 0.0),
        )

    def get_strains(self):
        self._require_valid()
        return self._backend.strains

    def get_stack_assembly(self, fp):
        lam_obj = fp.Laminate
        return lam_obj.Proxy.get_stack_assembly(lam_obj)


class ViewProviderCompositeShell:
    def __init__(self, obj):
        # Lazy import to avoid GUI dependency in headless mode
        from ..shaders.MeshGridShader import MeshGridShader

        self.grid_shader = MeshGridShader()

        obj.addProperty(
            "App::PropertyFloatConstraint",
            "Darken",
            "AnalysisOptions",
            "Grid darkness",
        )
        obj.Darken = 0.5

        obj.addProperty(
            "App::PropertyBool",
            "ShowRosette",
            "Rosette",
            "Show fibre orientation rosette symbol in 3D view",
        )
        obj.ShowRosette = True

        obj.addProperty(
            "App::PropertyFloat",
            "RosetteScale",
            "Rosette",
            "Radius of fibre orientation rosette symbol (mm)",
        )
        obj.RosetteScale = 20.0

        obj.Proxy = self

    def setDisplayMode(self, mode):
        return mode

    def getDisplayModes(self, obj):
        # Keep standard display modes and add strain overlays.
        # The shader now attaches to the DrapeMesh RootNode directly, so a
        # dedicated "Grid" display mode is no longer required.
        return [
            "Shaded",
            "Wireframe",
            "Flat Lines",
            "Points",
            "Strain XX",
            "Strain YY",
            "Strain XY",
        ]

    def getDefaultDisplayMode(self):
        return "Shaded"

    def getIcon(self):
        return COMPOSITE_SHELL_TOOL_ICON

    def claimChildren(self):
        children = []
        if hasattr(self.Object, "Mesh") and self.Object.Mesh:
            children.append(self.Object.Mesh)
        if hasattr(self.Object, "LocalCoordinateSystem") and self.Object.LocalCoordinateSystem:
            children.append(self.Object.LocalCoordinateSystem)
        return children

    def attach(self, obj):
        self.Active = False

        self.ViewObject = obj
        self.Object = obj.Object

        # Lazily create grid_shader if deserialized from file (__init__ skipped)
        if not hasattr(self, "grid_shader"):
            from ..shaders.MeshGridShader import MeshGridShader
            self.grid_shader = MeshGridShader()

        # Shader is attached directly to the DrapeMesh RootNode in load_shader().
        # No dedicated "Grid" display mode node is needed.

        # Always hide the native LCS symbology (planes + 3D arrows);
        # the rosette disk+arrows provide the same orientation info
        # without cluttering the view.
        self._hide_lcs(obj.Object)

        # Add DisplayLayer property to ViewObject (enumeration for layer
        # selection dropdown). Must be added here because FreeCAD mirrors
        # App::PropertyEnumeration from the FeaturePython to the ViewObject
        # but adds the 'hidden' flag on mirroring.
        if not hasattr(obj, "DisplayLayer"):
            obj.addProperty(
                "App::PropertyEnumeration",
                "DisplayLayer",
                "AnalysisOptions",
                "Select layer to display",
            )
            obj.DisplayLayer = ["0"]
            obj.DisplayLayer = "0"

        # Fibre orientation rosette: always-visible overlay on the root node
        from pivy import coin

        from .RosetteSymbol import RosetteSymbol

        self.rosette = RosetteSymbol()
        self.rosette_switch = coin.SoSwitch()
        self.rosette_switch.addChild(self.rosette.separator)
        self.rosette_switch.whichChild = 0  # visible by default
        try:
            obj.RootNode.addChild(self.rosette_switch)
        except AttributeError:
            pass  # RootNode not available in non-GUI / test environments

        # needed to trigger color update
        self.onChanged(obj, "Color")

    def update_display_layer(self, fp):
        if not hasattr(fp.ViewObject, "DisplayLayer"):
            return
        display_layer_opts = list(fp.Laminate.StackOrientation.keys())
        sel = fp.ViewObject.DisplayLayer
        fp.ViewObject.DisplayLayer = display_layer_opts
        if sel in display_layer_opts:
            return
        if display_layer_opts:
            fp.ViewObject.DisplayLayer = display_layer_opts[0]

    def _hide_lcs(self, fp):
        """Always hide the native LCS symbology (planes + 3D arrows)."""
        lcs = fp.LocalCoordinateSystem
        if lcs is None and fp.Rosette:
            lcs = fp.Rosette.LocalCoordinateSystem
        if lcs is None:
            return
        lcs_vobj = getattr(lcs, "ViewObject", None)
        if lcs_vobj is not None:
            lcs_vobj.Visibility = False

    def update_visibility(self, vobj):
        visible = vobj.Visibility
        mesh_vobj = getattr(self.Object, "Mesh", None)
        if mesh_vobj is not None:
            mesh_vobj.Visibility = visible
        self._set_shell_transparency(vobj)
        if self.Object.Support:
            self.Object.Support.Visibility = visible

    def _set_shell_transparency(self, vobj):
        """Make the shell semi-transparent when a drape mesh is visible."""
        mesh = getattr(self.Object, "Mesh", None)
        has_mesh = mesh is not None and getattr(mesh, "ViewObject", None) and mesh.ViewObject.Visibility
        try:
            vobj.Transparency = 50 if has_mesh else 0
        except Exception:
            pass

    def update_mesh_material(self, vobj):
        # use draper to determine distortion for coloring
        mesh = vobj.Object.Mesh
        if mesh is None:
            return
        n = mesh.Mesh.CountFacets
        if "Material" not in mesh.PropertiesList:
            mesh.addProperty("Mesh::PropertyMaterial", "Material")
        try:
            strains = vobj.Object.Proxy.get_strains()
        except Exception:
            strains = None
        if strains is not None:
            import MeshEnums

            # Backward-safe shape handling:
            # - legacy nextdrape persisted data: (N,) shear only
            # - newer format: (N,3) [warp, weft, shear]
            strains_arr = np.asarray(strains)
            if strains_arr.ndim == 1:
                nrows = len(strains_arr)
                strains_arr = np.column_stack([
                    np.zeros(nrows),
                    np.zeros(nrows),
                    strains_arr,
                ])
            elif strains_arr.ndim != 2 or strains_arr.shape[1] < 3:
                self.update_visibility(vobj)
                return

            material = {
                "binding": MeshEnums.Binding.PER_FACE,
                "transparency": [0.0] * n,
                "ambientColor": [(0.5, 0.5, 0.5)] * n,
                "diffuseColor": [(0.5, 0.5, 0.5)] * n,
                "shininess": [0.0] * n,
            }
            cont = getCompositesContainer()
            limit_pos = cont.MaxStrainTension
            limit_neg = cont.MaxStrainCompression
            match vobj.DisplayMode:
                case "Strain XX":
                    index = 0
                case "Strain YY":
                    index = 1
                case "Strain XY":
                    index = 2
                    limit_pos = cont.MaxStrainShear
                    limit_neg = cont.MaxStrainShear
                case _:
                    index = -1
            if index >= 0:
                s = strains_arr[:, index]

                def map_val(x):
                    if x > 0:
                        ratio = x / limit_pos if limit_pos != 0 else 0.0
                        s = min(1.0, (1.0 + ratio) / 2)
                    elif x < 0:
                        ratio = x / limit_neg if limit_neg != 0 else 0.0
                        s = max(0.0, (1.0 + ratio) / 2)
                    else:
                        s = 0.5
                    return roma_map(s)[0:3]

                material["diffuseColor"] = [map_val(x) for x in s]
            mesh.Material = material
            mesh.ViewObject.Coloring = True
        self.update_visibility(vobj)

    def updateData(self, fp, prop):
        match prop:
            case "LocalCoordinateSystem" | "Support" | "Rosette":
                self.update_rosette(self.ViewObject)
            case "Laminate":
                if fp.Laminate:
                    self.update_display_layer(fp)
                self.update_rosette(self.ViewObject)
            case _:
                return
        self.reload_shader()

    def update_rosette(self, vobj):
        """Rebuild the rosette symbol from the current laminate and LCS."""
        if not hasattr(self, "rosette"):
            return
        obj = vobj.Object
        laminate = obj.Laminate
        if not laminate or not hasattr(laminate, "StackOrientation"):
            return
        stack_orientation = laminate.StackOrientation
        if not hasattr(stack_orientation, "values"):
            return
        orientations = list(stack_orientation.values())
        if not orientations:
            return

        lcs = None
        if obj.Rosette:
            lcs = obj.Rosette.LocalCoordinateSystem
        elif obj.LocalCoordinateSystem:
            lcs = obj.LocalCoordinateSystem

        if lcs:
            base = lcs.Placement.Base
            position = (base.x, base.y, base.z)
            q = lcs.Placement.Rotation.Q
            rotation = (q[0], q[1], q[2], q[3])
        else:
            position = (0.0, 0.0, 0.0)
            rotation = (0.0, 0.0, 0.0, 1.0)

        scale = vobj.RosetteScale if hasattr(vobj, "RosetteScale") else 20.0
        self.rosette.update(orientations, position, rotation, scale)

    def onChanged(self, vobj, prop):
        match prop:
            case "Visibility":
                self.update_visibility(vobj)
            case "DisplayMode":
                self.update_mesh_material(vobj)
            case "Darken":
                # Darken property no longer applies to the line-set overlay.
                pass
            case "DisplayLayer":
                self.reload_shader()
            case "ShapeAppearance":
                self._set_shell_transparency(vobj)
            case "ShowRosette":
                from pivy import coin

                if hasattr(self, "rosette_switch"):
                    self.rosette_switch.whichChild = (
                        0 if vobj.ShowRosette else coin.SO_SWITCH_NONE
                    )
            case "RosetteScale":
                self.update_rosette(vobj)
            case _:
                pass

    def onDelete(self, vobj, sub):
        self.remove_shader()
        return True

    def reload_shader(self):
        if getattr(self, "_reloading", False):
            return
        self._reloading = True
        try:
            self.remove_shader()
            self.load_shader()
        finally:
            self._reloading = False

    def get_offset_angle(self, vobj):
        if not hasattr(vobj.ViewObject, "DisplayLayer"):
            return 0
        layer = vobj.ViewObject.DisplayLayer
        if not vobj.Laminate:
            return 0
        if layer in vobj.Laminate.StackOrientation:
            return int(vobj.Laminate.StackOrientation[layer])
        return 0

    def load_shader(self):
        try:
            if self.Active:
                return
            # Skip if already properly attached
            if hasattr(self, "grid_shader") and self.grid_shader and self.grid_shader._attached:
                return
            # self.Object is the FeaturePython object, self.Object.Proxy is the FP proxy.
            vobj = self.Object
            obj = vobj.Proxy

            # Guard: _backend may not exist during document deserialization
            if not hasattr(obj, "_backend") or obj._backend is None:
                return

            mesh_feat = getattr(vobj, "Mesh", None)
            if mesh_feat is None or mesh_feat.Mesh is None:
                return

            mesh_data = mesh_feat.Mesh
            if mesh_data.CountFacets == 0:
                return

            # Get texture coordinates from the backend.
            # With Coin3D geometry (no deduplication), tex_coords[i]
            # directly corresponds to vertex/coordinate index i.
            tex_coords = obj._backend.get_tex_coords()
            if tex_coords is None or len(tex_coords) == 0:
                return

            offset_angle_deg = self.get_offset_angle(vobj)
            # Lazily create grid_shader if deserialized from file
            if not hasattr(self, "grid_shader"):
                from ..shaders.MeshGridShader import MeshGridShader
                self.grid_shader = MeshGridShader()
            if self.grid_shader:
                self.grid_shader.attach(
                    vobj,  # ViewObject (used to get the document)
                    mesh_feat,  # DrapeMesh feature (provides RootNode)
                    tex_coords,
                    offset_angle_deg,
                )
                self.Active = True
                import FreeCADGui

                FreeCADGui.Selection.addObserver(self)
        except Exception as e:
            # Log errors during deserialization or other non-critical contexts
            import traceback
            print(f'load_shader ERROR: {e}')
            traceback.print_exc()

    def remove_shader(self):
        if not self.Active:
            return
        vobj = self.Object
        mesh_feat = getattr(vobj, "Mesh", None)
        if mesh_feat is not None and hasattr(self, "grid_shader"):
            try:
                self.grid_shader.detach(vobj)
            except Exception:
                pass
        self.Active = False
        try:
            import FreeCADGui
            FreeCADGui.Selection.removeObserver(self)
        except Exception:
            pass

    def __getstate__(self):
        return {}

    def __setstate__(self, state):
        return None


class CompositeShellCommand(BaseCommand):
    icon = COMPOSITE_SHELL_TOOL_ICON
    menu_text = "Composite shell"
    tool_tip = """Create composite shell.
        Select support feature, laminate and local coordinate system or rosette."""
    sel_args = [
        {
            "key": "support",
            "type": "Part::Feature",
        },
        {
            "key": "laminate",
            "test": is_laminate,
        },
        {
            "key": "rosette",
            "test": is_rosette,
            "optional": True,
        },
        {
            "key": "lcs",
            "type": "Part::LocalCoordinateSystem",
            "optional": True,
        },
    ]
    type_id = "Part::FeaturePython"
    instance_name = "CompositeShell"
    cls_fp = CompositeShellFP
cls_vp = ViewProviderCompositeShell

try:
    import FreeCADGui

    FreeCADGui.addCommand(
        "Composites_CompositeShell",
        CompositeShellCommand(),
    )
except ImportError:
    pass  # Headless mode - no GUI command registration
