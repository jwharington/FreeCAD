# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

import FreeCAD

import hashlib
import json
import time
from datetime import datetime, timezone

import numpy as np

from FreeCAD import Console

_profiler_data = {}

def _profiler(label):
    '''Call at entry/exit to record elapsed time.'''
    if label not in _profiler_data:
        _profiler_data[label] = time.perf_counter()
    else:
        elapsed = time.perf_counter() - _profiler_data.pop(label)
        ms = elapsed * 1000
        # Print to stderr with flush
        import sys
        sys.stderr.write(f'[PROFILER] {label}: {ms:.0f}ms\n')
        sys.stderr.flush()
        return elapsed
    return None

from .. import (
    COMPOSITE_SHELL_TOOL_ICON,
    is_comp_type,
    roma_map,
)
from ..tools.drape_backend_nextdrape import NextDrapeBackend, _ensure_kdtree
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
    """Legacy compatibility backend for old saved drape payloads.

    The current implementation keeps the live cache on the proxy and
    recomputes via the C++ backend on restore. This helper is retained
    only so older saved documents can still be interpreted if they carry
    the historical JSON payload fields.

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

        # Use KDTreeLocator if available (large mesh)
        n_quads = len(self._quads)
        if n_quads >= _ensure_kdtree().min_quads_for_kdtree():
            # Build or reuse KDTreeLocator (C++ via pybind11)
            if not hasattr(self, "_quad_locator"):
                self._quad_locator = _ensure_kdtree()(
                    self._node_positions.tolist(),
                    self._quads,
                )
            return self._quad_locator.lookup(list(point), self._tex_coords.tolist())

        from ..util.geometry_util import tex_coord_at_point
        return tex_coord_at_point(
            self._node_positions, self._quads, self._tex_coords, point, offset_angle_deg
        )

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
from ..util.geometry_util import shape_fingerprint
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
        self, obj, support=None, laminate=None, rosette=None, hide_drape_mesh=False
    ):
        self._initializing = True
        self.hide_drape_mesh = bool(hide_drape_mesh)
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

        # The live drape cache stays on the proxy/backend only. It is rebuilt
        # from the nextdrape solver on recompute and is not serialized on the
        # FeaturePython object.
        self._cached_shape_fingerprint = ""
        self._cached_rosette_angle = None
        self._cached_drape_pitch = None
        self._cached_drape_cuts_fingerprint = ""

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

        # Attach ViewProvider so it persists in the saved document
        vobj = obj.ViewObject
        if vobj is not None:
            vobj.Proxy = ViewProviderCompositeShell(vobj)

    def onDocumentRestored(self, fp):
        """Restore ViewProvider and initialise tracking fields."""
        # Re-attach ViewProvider: FreeCAD serialises Proxy as an int
        # (memory address) on save, so on restore it is not a Python
        # object any more.  Detect the corruption and re-attach.
        try:
            vobj = fp.ViewObject
            if vobj is not None and isinstance(getattr(vobj, "Proxy", None), int):
                vobj.Proxy = ViewProviderCompositeShell(vobj)
        except Exception:
            pass

        for attr, value in (
            ("_cached_shape_fingerprint", ""),
            ("_cached_rosette_angle", None),
            ("_cached_drape_pitch", None),
            ("_cached_drape_cuts_fingerprint", ""),
        ):
            if not hasattr(self, attr):
                setattr(self, attr, value)

        super().onDocumentRestored(fp)

    def execute(self, fp):
        # During document restore, the FeaturePython's properties may not be
        # registered yet (proxy __init__ hasn't run, properties are added
        # incrementally). Bail out until they are; a later recompute once
        # restore completes runs the real logic.
        if not hasattr(fp, "Support") or not hasattr(fp, "Laminate"):
            return
        # Always hide the native LCS symbology so only the rosette
        # disk+arrows are visible in the 3D view.
        self._hide_lcs_view(fp)

        # If DrapePitch was changed without an explicit recompute, do it now.
        if getattr(fp.Proxy, "_needs_recompute", False):
            fp.Proxy._needs_recompute = False

        if not fp.Support:
            return
        if not fp.Laminate:
            # No laminate — fall back to the support shape.
            fp.Shape = fp.Support.Shape
            return

        # ── In-memory fast-path: skip when the live backend cache matches ──
        if self._can_use_persisted(fp):
            return

        def get_lcs():
            rosette = fp.Rosette
            if rosette:
                lcs = getattr(rosette, "LocalCoordinateSystem", None)
                if lcs:
                    return lcs
            return fp.Support

        # During document restore the rosette FeaturePython may not have its
        # properties registered yet (proxy __init__ hasn't run). Fall back to
        # 0.0 so the shell can still solve cleanly after restore.
        self._rosette_angle = float(
            getattr(getattr(fp, "Rosette", None), "Angle", 0.0) or 0.0
        )

        # ── Full solve — run synchronously ─────────────────────────
        _profiler('drape_solve')
        self._diag(fp, "running drape solve")
        fp.Shape = fp.Support.Shape
        result = self._run_drape_sync(fp, get_lcs())
        _profiler('drape_solve')
        if isinstance(result, Exception):
            self._diag(fp, f"drape failed: {result}")
            self._mark_failed(fp, str(result))
        else:
            self._diag(fp, "drape completed")
            _profiler('complete_drape')
            self._complete_drape(fp, result)
            _profiler('complete_drape')
            if _profiler_data:
                print(f'[PROFILER] TOTAL: {sum(_profiler_data.values()):.0f}ms', flush=True)

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
        _profiler('inject_drape_geometry')
        # Get ViewObject — may be None during initial solve before GUI attach.
        vp = getattr(fp, "ViewObject", None)
        if vp is None and fp.Document is not None:
            # Try to find the ViewObject via the document's object list.
            for obj in fp.Document.Objects:
                if getattr(obj, "Name", None) == fp.Name:
                    vp = getattr(obj, "ViewObject", None)
                    break
        if not (vp and hasattr(vp, "Proxy")):
            return
        drape_host = getattr(vp.Proxy, "drape_host", None)
        if drape_host is None:
            return

        # Build and inject the support-surface geometry. If this fails we
        # must NOT proceed to reload_shader() — attaching the shader to an
        # empty scene graph silently produces a no-op overlay that reports
        # _attached=True. Log the error and leave the shader detached so
        # the failure is visible instead of masked.
        try:
            remove_existing_coin_geometry(drape_host)
            if fp.Support and hasattr(fp.Support, "Shape"):
                from .coin_geometry import build_support_surface_coin
                support_coin = build_support_surface_coin(
                    fp.Support.Shape,
                    deflection=1.0,
                    draper=self,
                )
                # Name uniquely so _find_coin_geometry prioritises it.
                support_coin.setName("SupportSurface")
                # Hand the geometry directly to the shader. It goes into the
                # shader_state group on attach() — never as a direct child of
                # drape_host — so there is no competing native render branch
                # and no remove-from-root refcount hazard.
                if hasattr(vp.Proxy, "grid_shader") and vp.Proxy.grid_shader:
                    vp.Proxy.grid_shader._coin_geo = support_coin
            if cut_edges is not None:
                remove_cut_edges(drape_host)
                inject_cut_edges(drape_host, cut_edges)
        except Exception as exc:
            import traceback
            Console.PrintWarning(
                f"[Composites][Drape] {fp.Name}: support-surface geometry "
                f"injection failed — shader left detached: {exc}\n"
            )
            traceback.print_exc()
            _profiler('inject_drape_geometry')
            return

        vp.Proxy.reload_shader()
        vp.Proxy._set_shell_transparency(vp)
        _profiler('inject_drape_geometry')

    def _complete_drape(self, fp, result):
        """Update FreeCAD properties and load shader (main thread)."""
        _profiler('complete_drape')

        backend = result["backend"]
        self._backend = backend
        drapecd_mesh = result["drapecd_mesh"]
        solve_result = result["solve_result"]
        diag = result["diag"]
        valid = result["valid"]
        quality_pass = result["quality_pass"]

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

        # Keep the live cache state on the proxy/backend only.
        self._store_cache_state(fp)

        # Inject support-surface geometry + reload shader synchronously.
        # The separate drape mesh is intentionally kept out of the GUI scene graph.
        cut_edges = result.get("cut_edges")
        self._inject_drape_geometry(fp, drapecd_mesh, cut_edges)

        # Update the view
        view_object = getattr(fp, "ViewObject", None)
        if view_object:
            view_object.update()

    def _mark_failed(self, fp, error_msg):
        """Mark the shell as failed (main thread)."""

        self._backend = None
        self._cached_shape_fingerprint = ""
        self._cached_rosette_angle = None
        self._cached_drape_pitch = None
        self._cached_drape_cuts_fingerprint = ""
        fp.DrapeValid = False
        fp.QualityPass = False
        fp.DrapeQuality = "error: " + error_msg[:200]
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
        for cut in cuts:
            name = getattr(cut, "Name", "") or getattr(cut, "Label", "") or str(cut)
            h.update(name.encode())
        return h.hexdigest()[:16]

    def _shape_fingerprint(self, shape) -> str:
        """Delegate to shared geometry_util function."""
        return shape_fingerprint(shape)

    def _can_use_persisted(self, fp) -> bool:
        """Return True if the in-memory backend cache still matches the shell."""
        backend = getattr(self, "_backend", None)
        if backend is None or not backend.is_valid():
            return False
        if not hasattr(fp, "Support") or not fp.Support:
            return False
        try:
            current_shape_fp = self._shape_fingerprint(fp.Support.Shape)
        except Exception:
            return False
        if current_shape_fp != getattr(self, "_cached_shape_fingerprint", ""):
            return False
        try:
            current_angle = float(fp.Rosette.Angle) if fp.Rosette else 0.0
        except Exception:
            return False
        if abs(current_angle - float(getattr(self, "_cached_rosette_angle", 0.0) or 0.0)) > 0.001:
            return False
        try:
            current_pitch = float(fp.DrapePitch)
        except Exception:
            return False
        cached_pitch = getattr(self, "_cached_drape_pitch", None)
        if cached_pitch is None or abs(current_pitch - float(cached_pitch)) > 0.001:
            return False
        try:
            cuts_fp = self._drape_cuts_fingerprint(fp)
        except Exception:
            return False
        if cuts_fp != getattr(self, "_cached_drape_cuts_fingerprint", ""):
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
        drapecd_coin = build_drapecd_coin(node_positions, quads, wireframe=False)

        # Inject draped mesh geometry + reload shader synchronously.
        self._inject_drape_geometry(fp, drapecd_coin)

        # Human-readable quality status (from rehydrated solve result)
        qual = solve_result.get("quality", {})
        fp.DrapeQuality = repr(qual) if diag.get("status") != "failed" else "invalid"

        # Transparency is set by _inject_drape_geometry above

    def _store_cache_state(self, fp) -> None:
        """Store the live backend cache state on the proxy only."""
        self._cached_shape_fingerprint = self._shape_fingerprint(fp.Support.Shape)
        self._cached_rosette_angle = float(fp.Rosette.Angle) if fp.Rosette else 0.0
        self._cached_drape_pitch = float(fp.DrapePitch)
        self._cached_drape_cuts_fingerprint = self._drape_cuts_fingerprint(fp)

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
        rosette = fp.Rosette
        if not rosette:
            return
        lcs = getattr(rosette, "LocalCoordinateSystem", None)
        if lcs is None:
            # Restore ordering: the rosette exists but its child LCS link
            # has not been restored yet. No-op; a later recompute hides it.
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

# Command registration moved to InitGui.py to avoid FreeCADGui dependency
