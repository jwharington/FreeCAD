# SPDX-License-Identifier: LGPL-2.1-or-later
"""NextDrape backend — C++ solver via FreeCAD Composites module.

Wraps the nextdrape C++ solver (built as Composites_drape when FreeCAD is
configured with BUILD_COMPOSITES=ON). The solver runs natively on the
TopoDS_Shape with zero-copy access — no BREP serialization.
"""

from __future__ import annotations

import json
import os

import numpy as np
from typing import TYPE_CHECKING, Any

from .drape_backend import DrapeBackend

if TYPE_CHECKING:
    import FreeCAD  # noqa: F401


def _import_engine():
    """Import the nextdrape DrapeEngine class (the clean frontend).

    FreeCAD holds a persistent DrapeEngine: compute() runs the solve and
    builds the UV-query index internally; lookup_uv() answers point
    queries. This keeps the k-d tree / brute-force algorithm choice and
    the flat-data round-trip inside nextdrape — FreeCAD no longer reaches
    into KDTreeLocator.
    """
    import Composites_drape
    return Composites_drape.DrapeEngine


def _dump_solver_input(shape: Any, seed: dict, params: dict) -> None:
    """Dump the exact solver inputs to FC_DRAPE_DUMP_DIR when set.

    Reproduction aid for the nextdrape ``drape_cli --shapefile`` harness
    (the drape-side twin of the mould path's ``FC_PARTING_DUMP_DIR``):
    write the BREP plus the seed and params dicts that feed
    ``DrapeEngine.compute``, so a failing solve can be debugged at the
    nextdrape level on byte-identical geometry.

    Each solve writes a new file: a run dumps several solves (initial
    drape, re-drapes on remainders, foot shells at their scaled pitch)
    whose B-spline bounding boxes inflate to the same box, so the tag
    carries a solve counter, the pitch and the face count to keep them
    apart — the bbox alone collapsed them onto one file.
    """
    dump_dir = os.environ.get("FC_DRAPE_DUMP_DIR")
    if not dump_dir:
        return
    global _dump_sequence
    _dump_sequence += 1
    bbox = shape.BoundBox
    tag = (f"{_dump_sequence:02d}"
           f"_{bbox.XLength:.1f}x{bbox.YLength:.1f}x{bbox.ZLength:.1f}"
           f"_{bbox.Center.x:.1f}_{bbox.Center.y:.1f}_{bbox.Center.z:.1f}"
           f"_p{params.get('pitch', 0):g}_f{len(shape.Faces)}")
    os.makedirs(dump_dir, exist_ok=True)
    shape.exportBrep(os.path.join(dump_dir, f"{tag}.brep"))
    with open(os.path.join(dump_dir, f"{tag}.json"), "w") as f:
        json.dump({"seed": seed, "params": params}, f, indent=2, default=float)


_dump_sequence = 0


def _region_box(region: Any) -> tuple[float, float, float, float]:
    """The tight x/y bounding box of ``region`` from its vertices."""
    vs = [v.Point for v in region.Vertexes]
    return (
        min(v.x for v in vs), max(v.x for v in vs),
        min(v.y for v in vs), max(v.y for v in vs),
    )


def _bilinear(corners, s, t):
    """Point (x, y, z, u, v) inside a cell, from its four cyclic corners."""
    w = ((1.0 - s) * (1.0 - t), s * (1.0 - t), s * t, (1.0 - s) * t)
    return tuple(sum(w[k] * corners[k][i] for k in range(4))
                 for i in range(5))


def _subdivide_into_region(pos, tex, quads, box, tol):
    """Refine cells bilinearly until sub-cells land inside the region.

    The fallback for a region narrower than the lattice — a 34 mm seat
    band against a 50 mm skin lattice can fall between rows, leaving the
    fast keep with nothing.  Cells meeting the region are subdivided in
    place, positions and texture coordinates interpolated bilinearly (so
    the weave is the source's field, sampled finer), and only sub-cells
    whose centre is inside the region are kept: nothing is painted outside
    the member's own faces.  Returns ``(factor, [(parent_row, corners)])``
    or ``(None, [])`` when no factor up to 16 lands a sub-cell inside.
    """
    for factor in (2, 4, 8, 16):
        cells = []
        for row, ids in enumerate(quads):
            ids = [int(i) for i in ids]
            corners = [(float(pos[i][0]), float(pos[i][1]), float(pos[i][2]),
                        float(tex[i][0]), float(tex[i][1])) for i in ids]
            xs = [c[0] for c in corners]
            ys = [c[1] for c in corners]
            if (max(xs) < box[0] or min(xs) > box[1]
                    or max(ys) < box[2] or min(ys) > box[3]):
                continue
            for i in range(factor):
                s0, s1 = i / factor, (i + 1) / factor
                for j in range(factor):
                    t0, t1 = j / factor, (j + 1) / factor
                    sub = [_bilinear(corners, s, t) for s, t in
                           ((s0, t0), (s1, t0), (s1, t1), (s0, t1))]
                    cx = sum(p[0] for p in sub) / 4.0
                    cy = sum(p[1] for p in sub) / 4.0
                    if (box[0] - tol <= cx <= box[1] + tol
                            and box[2] - tol <= cy <= box[3] + tol):
                        cells.append((row, sub))
        if cells:
            return factor, cells
    return None, []


def drape_result_over_region(result: dict, region: Any) -> tuple[dict, Any]:
    """Restrict a solved drape result to ``region``'s surface region.

    The lap-joint member is a cut of the support's own surface, and the
    support's common drape covers it continuously — so the member's weave
    is the solved drape over the member's region, borrowed from the source
    and never re-solved here.

    A cell is kept when its CENTRE lies in the region, so boundary cells
    come whole instead of being dropped for a corner outside and the weave
    reaches the region's edge.  When no cell centre falls in the region at
    all — a member narrower than the lattice, landing between rows — the
    cells that meet it are subdivided bilinearly until sub-cells do
    (:func:`_subdivide_into_region`): the fast keep, then a slow local
    refinement, both inside the member's own faces.

    The region is its own vertex bounding box (inflated by the placement
    slack).  Returns the filtered result dict and the old→new node index
    map (new_index = -1 where dropped).
    """
    x_min, x_max, y_min, y_max = _region_box(region)
    tol = 0.5  # the placement slack: boundary-row nodes stay in
    box = (x_min, x_max, y_min, y_max)

    pos = np.asarray(result["node_positions"], dtype=float)
    tex = np.asarray(result["tex_coords"], dtype=float)
    nodes: list = []
    coords: list = []
    index: dict = {}

    def node_of(position, uv):
        """Index of a node in the filtered arrays, created once."""
        key = (round(position[0], 6), round(position[1], 6),
               round(position[2], 6))
        i = index.get(key)
        if i is None:
            i = len(nodes)
            nodes.append([float(position[0]), float(position[1]),
                          float(position[2])])
            coords.append([float(uv[0]), float(uv[1])])
            index[key] = i
        return i

    kept_quads: list = []
    kept_rows: list = []
    for row, quad in enumerate(result["quads"]):
        ids = [int(i) for i in quad]
        cx = sum(float(pos[i][0]) for i in ids) / len(ids)
        cy = sum(float(pos[i][1]) for i in ids) / len(ids)
        if not (x_min - tol <= cx <= x_max + tol
                and y_min - tol <= cy <= y_max + tol):
            continue
        kept_quads.append([node_of(pos[i], tex[i]) for i in ids])
        kept_rows.append(row)

    refined = None
    if not kept_quads:
        factor, cells = _subdivide_into_region(pos, tex, result["quads"],
                                               box, tol)
        if factor is not None:
            refined = factor
            for parent, sub in cells:
                kept_quads.append(
                    [node_of((c[0], c[1], c[2]), (c[3], c[4])) for c in sub])
                kept_rows.append(parent)

    old_to_new = np.full(pos.shape[0], -1, dtype=int)
    for i in range(pos.shape[0]):
        key = (round(float(pos[i][0]), 6), round(float(pos[i][1]), 6),
               round(float(pos[i][2]), 6))
        if key in index:
            old_to_new[i] = index[key]

    filtered = dict(result)
    filtered["node_positions"] = nodes
    filtered["tex_coords"] = coords
    filtered["quads"] = kept_quads
    for key in ("warp_strain", "weft_strain", "shear_angle"):
        if key in result:
            arr = np.asarray(result[key], dtype=float)
            filtered[key] = arr[kept_rows] if kept_rows else arr[:0]

    diag = dict(result.get("diagnostics") or {})
    diag["total_nodes"] = len(nodes)
    diag["quads"] = len(kept_quads)
    if refined:
        diag["refined"] = refined
    filtered["diagnostics"] = diag
    return filtered, old_to_new


class BorrowedDrapeBackend(DrapeBackend):
    """Serves a region of another shell's solved drape.

    The lap-joint foot band: the support's common drape covers the band
    continuously, so the foot's weave is that solved drape restricted to
    the band — the same nodes, quads and texture coordinates, no second
    solve.  Frame queries (get_lcs*) are point-based and delegate to the
    source backend directly: the band lies on the source's surface, so the
    source's locator resolves the foot's points exactly.
    """

    backend_name = "nextdrape-borrowed"

    def __init__(self, source: "NextDrapeBackend", result: dict) -> None:
        self._source = source
        self._result = result
    def is_valid(self) -> bool:
        return bool(self._result.get("success")) and self._source.is_valid()

    def diagnostics(self) -> dict[str, Any]:
        d = dict(self._result.get("diagnostics") or {})
        return {
            "backend": self.backend_name,
            "status": "valid",
            "solver": "nextdrape",
            "nodes": int(d.get("total_nodes", 0)),
            "quads": len(self._result.get("quads", [])),
            "coverage_ratio": d.get("coverage_ratio"),
            "max_shear_deg": d.get("max_shear_deg", 0.0),
            "max_strain": d.get("max_strain", 0.0),
            "solve_time_ms": 0.0,
            "failure_diagnostics": d.get("failure_diagnostics", []),
            "borrowed_from": self._source.backend_name,
        }

    def quality_pass(self) -> bool:
        return bool(
            (self._result.get("quality") or {}).get("overall_pass", False)
        )

    def get_tex_coords(self, offset_angle_deg: float = 0) -> list[Any] | None:
        import math

        tex = np.asarray(self._result["tex_coords"], dtype=float)
        if offset_angle_deg:
            ang = math.radians(-offset_angle_deg)
            cos_a, sin_a = math.cos(ang), math.sin(ang)
            tex = np.column_stack([
                tex[:, 0] * cos_a - tex[:, 1] * sin_a,
                tex[:, 0] * sin_a + tex[:, 1] * cos_a,
            ])
        return [[float(u), float(v)] for u, v in tex]

    def get_boundaries(self, offset_angle_deg: float = 0) -> list[list[Any]] | None:
        # The master's outline: the band's rim segments are part of it.  A
        # flat-space clip would need the band's flat region (v2); the panel's
        # own shell draws the full weave anyway.
        return self._source.get_boundaries(offset_angle_deg)

    def strains(self) -> np.ndarray:
        cols = [
            np.asarray(self._result[key], dtype=float).reshape(-1, 1)
            for key in ("warp_strain", "weft_strain", "shear_angle")
            if key in self._result
        ]
        return np.hstack(cols) if cols else None

    def get_lcs(self, element: Any) -> Any | None:
        return self._source.get_lcs(element)

    def get_lcs_batch(self, elements) -> list:
        return self._source.get_lcs_batch(elements)

    def get_lcs_at_point(self, center: Any) -> Any | None:
        return self._source.get_lcs_at_point(center)

    def get_tex_coord_at_point(self, point: Any,
                               offset_angle_deg: float = 0) -> Any | None:
        return self._source.get_tex_coord_at_point(point, offset_angle_deg)


class PersistedDrapeBackend(DrapeBackend):
    """The solved drape restored from the document's persisted weave
    arrays.

    Serves the same DrapeEngine UV locator (``engine.load``) that the
    live solve built, so a restored session answers texture-coordinate
    and fabric-frame queries without re-solving: the shell's execute()
    takes the _can_use_persisted fast path and the GUI weave rebuilds
    from the locator.  Only the locator protocol is live — strains and
    boundary loops come back empty until a genuine re-solve replaces
    this backend.
    """

    backend_name = "nextdrape-persisted"

    def __init__(self, node_positions, quads_flat, tex_flat) -> None:
        self._engine = _import_engine()()
        self._node_positions = np.asarray(node_positions, dtype=float)
        self._quads_flat = [int(i) for i in quads_flat]
        self._tex_flat = [float(c) for c in tex_flat]
        self._engine.load(
            [(float(p[0]), float(p[1]), float(p[2]))
             for p in self._node_positions],
            self._quads_flat,
            self._tex_flat,
        )

    def _run_solve(self) -> dict:
        return self.raw_result()

    def raw_result(self) -> dict:
        n = len(self._quads_flat) // 4
        return {
            "success": True,
            "node_positions": self._node_positions,
            "quads": [self._quads_flat[4 * i:4 * i + 4] for i in range(n)],
            "tex_coords": np.asarray(self._tex_flat, dtype=float).reshape(-1, 2),
        }

    def is_valid(self) -> bool:
        return True

    def quality_pass(self) -> bool:
        # The persisted shell's own QualityPass property governs the
        # reported verdict; the locator backend carries no quality state.
        return True

    def diagnostics(self) -> dict:
        return {
            "backend": self.backend_name,
            "status": "valid",
            "solver": "nextdrape",
            "nodes": int(len(self._node_positions)),
            "quads": int(len(self._quads_flat) // 4),
        }

    def get_tex_coords(self, offset_angle_deg: float = 0) -> list | None:
        tex = np.asarray(self._tex_flat, dtype=float).reshape(-1, 2)
        if offset_angle_deg:
            import math
            ang = math.radians(-offset_angle_deg)
            cos_a, sin_a = math.cos(ang), math.sin(ang)
            tex = np.column_stack([
                tex[:, 0] * cos_a - tex[:, 1] * sin_a,
                tex[:, 0] * sin_a + tex[:, 1] * cos_a,
            ])
        return [[float(u), float(v)] for u, v in tex]

    def get_boundaries(self, offset_angle_deg: float = 0) -> list:
        # Boundary loops are not persisted; a genuine re-solve restores
        # them.
        return []

    def strains(self) -> np.ndarray | None:
        return None

    def get_tex_coord_at_point(self, point: Any,
                               offset_angle_deg: float = 0) -> Any | None:
        uv = self._engine.lookup_uv(
            [float(point[0]), float(point[1]), float(point[2])]
        )
        return [uv[0], uv[1]] if uv is not None else None

    def get_lcs_at_point(self, center: Any) -> Any | None:
        frame = self._engine.lookup_lcs(
            [float(center[0]), float(center[1]), float(center[2])]
        )
        if frame is None:
            return None
        warp, _weft, normal = frame
        return NextDrapeBackend._placement(warp, normal, center)

    def get_lcs(self, element: Any) -> Any | None:
        centroid = NextDrapeBackend._element_centroid(self, element)
        if centroid is None:
            return None
        frame = self._engine.lookup_lcs(
            [float(centroid[0]), float(centroid[1]), float(centroid[2])]
        )
        if frame is None:
            return None
        warp, _weft, normal = frame
        return NextDrapeBackend._placement(warp, normal, centroid)

    def get_lcs_batch(self, elements) -> list:
        return [self.get_lcs(element) for element in elements]


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
        dart_wires: list | None = None,
    ) -> None:
        # Persistent frontend: compute() builds the UV-query index that
        # lookup_uv() then serves. The engine owns the algorithm choice
        # (k-d tree vs brute force) and the flat data; FreeCAD never
        # reassembles node_positions/quads/tex_coords or caches a locator.
        self._engine = _import_engine()()
        self._mesh = mesh
        self._lcs = lcs
        self._shape = shape
        self._cut_wires = cut_wires
        self._cut_shape = cut_shape
        self._use_cut_shape = use_cut_shape
        # Dart wires as Part.Shape objects — passed to the solver as
        # genuine wires (dartWires), not tessellated point lists.
        self._dart_wires = dart_wires
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
            solver_shape = self._cut_shape if self._use_cut_shape else self._shape
            _dump_solver_input(solver_shape, seed, params)
            self._result = self._engine.compute(solver_shape, seed, params)
            if not self._result.get("success"):
                self._valid = False
        return self._result

    # ── DrapeBackend protocol ────────────────────────────────────

    def raw_result(self) -> dict | None:
        """The cached solve result dict (the borrowed-drape source)."""
        return self._run_solve()

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
        payload = {
            "backend": self.backend_name,
            "status": "valid",
            "solver": "nextdrape",
            "nodes": d.get("total_nodes", 0),
            "quads": len(r.get("quads", [])),
            "coverage_ratio": d.get("coverage_ratio"),  # None when unmeasured
            "max_shear_deg": d.get("max_shear_deg", 0.0),
            "max_strain": d.get("max_strain", 0.0),
            "solve_time_ms": d.get("solve_time_ms", 0.0),
            "failure_diagnostics": d.get("failure_diagnostics", []),
        }
        return payload

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

    def _element_centroid(self, element):
        """Centroid of a 3-node (triangle) or 4-node (quad) element.

        Accepts coordinate points (FreeCAD.Vector, tuple, list) or drape
        node indices.
        """
        if not isinstance(element, (list, tuple)) or len(element) < 3:
            return None
        if isinstance(element[0], (int, np.integer)):
            r = self._run_solve()
            if not r.get("success"):
                return None
            pos = np.asarray(r["node_positions"], dtype=float)
            try:
                pts = np.array([pos[int(k)] for k in element[:4]])
            except (IndexError, ValueError):
                return None
        else:
            try:
                pts = np.array(
                    [np.asarray(p, dtype=float).reshape(3) for p in element[:4]]
                )
            except (TypeError, ValueError):
                return None
        return pts.mean(axis=0)

    @staticmethod
    def _placement(warp, normal, origin):
        """FreeCAD Placement with X = warp, Z = normal, right-handed."""
        import FreeCAD
        from scipy.spatial.transform import Rotation

        w = np.asarray(warp, dtype=float)
        n = np.asarray(normal, dtype=float)
        w = w / np.linalg.norm(w)
        n = n / np.linalg.norm(n)
        y_axis = np.cross(n, w)
        rot = Rotation.from_matrix(np.column_stack([w, y_axis, n]))
        q = rot.as_quat()  # scipy order [x, y, z, w]
        plc = FreeCAD.Placement()
        plc.Rotation = FreeCAD.Rotation(q[0], q[1], q[2], q[3])
        plc.Base = FreeCAD.Vector(
            float(origin[0]), float(origin[1]), float(origin[2])
        )
        return plc

    def get_lcs(self, element: Any) -> Any | None:
        """Material frame at a mesh element (3- or 4-node), from the drape.

        The element's centroid is located on the drape by nextdrape's own
        k-d tree lookup (``DrapeEngine.lookup_lcs``), which returns the
        located quad's warp/weft/normal — the material frame the solver
        actually laid down, and therefore already carrying the shell's
        rosette angle.  No flat-lattice indices are used here.
        """
        centroid = self._element_centroid(element)
        if centroid is None:
            return None
        frame = self._engine.lookup_lcs(
            [float(centroid[0]), float(centroid[1]), float(centroid[2])]
        )
        if frame is None:
            return None
        warp, _weft, normal = frame
        return self._placement(warp, normal, centroid)

    def get_lcs_batch(self, elements) -> list:
        """Material frames for many elements, in input order."""
        return [self.get_lcs(element) for element in elements]

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
        fc_placement.Rotation = FreeCAD.Rotation(quat[0], quat[1], quat[2], quat[3])
        fc_placement.Base = FreeCAD.Vector(centroid[0], centroid[1], centroid[2])

        return fc_placement

    def get_tex_coord_at_point(self, point: Any, offset_angle_deg: float = 0) -> Any | None:
        """Return texture coordinate at a 3D point via the engine's query.

        Delegates to DrapeEngine::lookup_uv, which owns the spatial index
        built during compute(). offset_angle_deg is accepted for caller
        compatibility but not applied here — grid rotation is handled in
        get_tex_coords() (bulk UVs) and by the shader's offset_angle
        uniform, not per-point. (The previous KDTree path likewise ignored
        it.)
        """
        r = self._run_solve()
        if not r.get("success"):
            return None
        uv = self._engine.lookup_uv(list(point))
        return [uv[0], uv[1]] if uv is not None else None

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
        """Project a point onto the shape surface (true nearest point).

        When the centre of mass lies inside a closed surface (e.g. on a
        cylinder's axis), projecting it onto the surface ensures the
        draper seed lands on valid geometry rather than failing with
        NonDrapable.

        Strategy: `distToShape` against a vertex — the solution point is
        guaranteed to lie ON the shape.  This replaces a bounding-box
        clamp that pushed the point to the nearest bbox face: on a
        closed surface the clamp landed off-surface (a bbox face is not
        the shell) and the solve failed with `solver_failure`
        (known-issue #7).
        """
        import Part

        shape = self._shape
        vertex = Part.Vertex(point[0], point[1], point[2])
        _dist, points, _info = shape.distToShape(vertex)
        nearest = points[0][0]
        return [nearest.x, nearest.y, nearest.z]

    # A frame placed by RosetteFP sits exactly on its face (parametric
    # centre, vertex, or edge midpoint); anything farther off is not a
    # placed frame.
    _ON_SURFACE_TOL = 1e-4

    def _point_on_shape(self, point) -> bool:
        """Whether the point lies on the support surface."""
        import Part

        if not hasattr(self._shape, "distToShape"):
            return True
        vertex = Part.Vertex(point[0], point[1], point[2])
        import FreeCAD
        try:
            dist, _points, _info = self._shape.distToShape(vertex)
        except Exception:
            # BRepExtrema_DistShapeShape throws on a point lying ON a
            # periodic face's seam (the cyl-closed restore path: the seed
            # meridian coincides with the parameter wrap).  Not a placement
            # failure — fall back to the face-level inside test.
            return self._shape.isInside(
                FreeCAD.Vector(*point), self._ON_SURFACE_TOL, True
            )
        return dist <= self._ON_SURFACE_TOL

    def _frame_seed(self):
        """(point, warp_direction) from the LCS frame, or None.

        The frame is only trusted when its origin lies ON the support:
        an object that merely carries a Placement is not a fibre frame.
        An unplaced rosette LCS (the shell re-drapes mid transfer wiring,
        before the transfer's own LCS has been placed) and the
        rosette-less support fallback both present the identity
        placement — seeding at the origin failed the solve whenever the
        geometry did not contain it (known-issue #11), healed only by
        whatever recompute happened to follow.
        """
        if not (self._lcs is not None and hasattr(self._lcs, "Placement")):
            return None
        base = self._lcs.Placement.Base
        point = [base.x, base.y, base.z]
        if not self._point_on_shape(point):
            return None
        # Use the LCS X-axis as the warp direction (fiber direction).
        # The Rosette LCS is oriented with X along fibers, Z normal
        # to the surface.  Transform the standard X vector by the
        # LCS rotation to get the world-space warp direction.
        from FreeCAD import Vector

        rot = self._lcs.Placement.Rotation
        axis = rot.multVec(Vector(1, 0, 0))
        return point, [axis.x, axis.y, axis.z]

    def _com_seed(self):
        """(point, warp_direction) from the centre of mass projected onto
        the surface — the rosette-less fallback seed (known-issue #7)."""
        point = [0.0, 0.0, 0.0]
        if hasattr(self._shape, "CenterOfMass"):
            com = self._shape.CenterOfMass
            point = self._project_point_to_surface(com)
        return point, [1.0, 0.0, 0.0]

    def _build_seed(self) -> dict:
        """Build nextdrape SeedInput dict.

        Seed point and warp direction come from the same source: the
        mesh when it carries an explicit seed, the rosette LCS frame
        when it carries a real, on-surface frame, or the shape
        centre-of-mass projection otherwise.
        """
        mesh = self._mesh
        if hasattr(mesh, "seed_point") and mesh.seed_point is not None:
            warp_dir = [1.0, 0.0, 0.0]
            if hasattr(mesh, "warp_direction") and mesh.warp_direction is not None:
                warp_dir = list(mesh.warp_direction)
            return {"point": list(mesh.seed_point), "warp_direction": warp_dir}
        point, warp_dir = self._frame_seed() or self._com_seed()
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
            # Real coverage measurement (the sampling analysis): opt-in here
            # because the 95 % coverage gate reads it.  The C++ default is
            # off (O(samples x quads + quads^2)); tests and the CLI opt in
            # on their own side.
            "analyze_coverage": True,
        }
        # When cut wires are specified, enable the C++ cut-wire blocking
        # engine. The dart wires themselves go through "dart_wires" as
        # genuine Part.Shape wires — the C++ layer unwraps them and
        # discovers their owning faces natively.
        if self._cut_wires or self._dart_wires:
            params["cut_wires_enabled"] = True
            params["cut_wires_proximity_tol"] = 0.5
            params["cut_wires_block_nodes"] = True
            params["cut_wires_block_quads"] = True
        if self._dart_wires:
            params["dart_wires"] = self._dart_wires
        return params
