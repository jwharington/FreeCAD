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
from .coin_geometry import (
    build_drapecd_coin,
    find_switch,
    inject_coin_geometry,
    inject_cut_edges,
    remove_cut_edges,
    remove_existing_coin_geometry,
)
from .VPCompositeShell import ViewProviderCompositeShell




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
        fc_placement.Rotation = FreeCAD.Rotation(quat[0], quat[1], quat[2], quat[3])
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
        fc_placement.Rotation = FreeCAD.Rotation(quat[0], quat[1], quat[2], quat[3])
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
            from ..util.geometry_util import (
                tex_coord_nearest_quad_fallback,
            )
            return tex_coord_nearest_quad_fallback(
                [px, py, pz], node_positions, quads, tex_coords
            )

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
        self, obj, support=None, laminate=None, rosette=None
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

    def _inject_drape_geometry(self, fp, drapecd_coin, cut_edges=None) -> None:
        """Inject draped mesh geometry into the view-provider scene graph.

        Runs synchronously inside execute(). Errors are swallowed so a
        GUI/scene-graph hiccup never aborts the drape solve or the
        document recompute that called it.
        """
        vp = getattr(fp, "ViewObject", None)
        if not (vp and hasattr(vp, "Proxy")):
            return
        drape_host = getattr(vp.Proxy, "drape_host", None)
        try:
            if drape_host is not None:
                remove_existing_coin_geometry(drape_host)
                inject_coin_geometry(drape_host, drapecd_coin)
                if cut_edges is not None:
                    remove_cut_edges(drape_host)
                    inject_cut_edges(drape_host, cut_edges)
            vp.Proxy.reload_shader()
            vp.Proxy._set_shell_transparency(vp)
        except Exception:
            pass

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

        # drapecd_mesh is now just the Coin3D separator (build_drapecd_coin)
        drapecd_coin = drapecd_mesh

        # Inject draped mesh geometry + reload shader synchronously.
        cut_edges = result.get("cut_edges")
        self._inject_drape_geometry(fp, drapecd_coin, cut_edges)

        # Update the view
        view_object = getattr(fp, "ViewObject", None)
        if view_object:
            view_object.update()

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
        drapecd_coin = build_drapecd_coin(node_positions, quads)

        # Inject draped mesh geometry + reload shader synchronously.
        self._inject_drape_geometry(fp, drapecd_coin)

        # Human-readable quality status (from rehydrated solve result)
        qual = solve_result.get("quality", {})
        fp.DrapeQuality = repr(qual) if diag.get("status") != "failed" else "invalid"

        # Transparency is set by _inject_drape_geometry above

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
        lcs = fp.Rosette.LocalCoordinateSystem if fp.Rosette else None
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
            case "Rosette":
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
        # Both NextDrapeBackend and _RehydratedBackend implement the draper
        # protocol (get_lcs_at_point, get_tex_coord_at_point, get_lcs, ...)
        # directly, so the backend itself is the draper.
        return self._backend

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
