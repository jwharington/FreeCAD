# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Draping task — runs the C++ solve synchronously.

The solve blocks for ~1–2 seconds. In headless mode the Qt queued
callback channel doesn't deliver, so we run synchronously and return
the result dict directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import FreeCAD  # noqa: F401


def _tessellate_cut_wires(fp: Any) -> list[list[tuple[float, float, float]]] | None:
    """Tessellate DrapeCuts wires into lists of 3D point coordinates.

    Returns ``None`` if no cut wires are specified, or the list
    tessellated 3D point sequences otherwise.
    """
    cuts = getattr(fp, "DrapeCuts", None)
    if not cuts or not hasattr(fp, "DrapeCuts") or len(fp.DrapeCuts) == 0:
        return None

    result: list[list[tuple[float, float, float]]] = []
    import FreeCAD

    doc = fp.Document
    for obj_ref in fp.DrapeCuts:
        # obj_ref may be a document object (GUI) or a string name.
        obj = obj_ref if hasattr(obj_ref, "Shape") else doc.getObject(obj_ref)
        if obj is None:
            continue
        wire = obj.Shape if hasattr(obj, "Shape") else None
        if wire is None:
            continue
        for edge in wire.Edges:
            try:
                vals = edge.tessellate(50)
                pts: list[tuple[float, float, float]] = [
                    (float(v[0]), float(v[1]), float(v[2])) for v in vals[1]
                ]
                if len(pts) >= 2:
                    result.append(pts)
            except Exception:
                continue
    return result if result else None


def _get_shape_for_solver(fp: Any, default_shape: Any) -> tuple[Any, bool]:
    """Return a shape for the solver, embedding cut wires if present.

    Returns (shape, uses_cut_shape).  When DrapeCuts is non-empty we
    create a compound containing the support Shape + each cut wire, so
    the C++ layer can discover them via DiscoverCutWires().
    """
    cuts = getattr(fp, "DrapeCuts", None)
    if not cuts or not hasattr(fp, "DrapeCuts") or len(fp.DrapeCuts) == 0:
        return default_shape, False

    try:
        import FreeCAD
        from Part import makeCompound

        shapes = []
        base_shape = getattr(default_shape, "Shape", default_shape)
        if hasattr(base_shape, "ShapeType"):
            shapes.append(base_shape)
        else:
            shapes = [base_shape]

        cut_count = len(shapes)
        for obj_ref in cuts:
            obj = (
                obj_ref if hasattr(obj_ref, "Shape") else fp.Document.getObject(obj_ref)
            )
            if obj is None:
                continue
            wire = obj.Shape if hasattr(obj, "Shape") else None
            if wire is None:
                continue
            shapes.append(wire)

        combined = makeCompound(shapes)
        return combined, True
    except Exception:
        return default_shape, False


def run_drape_task(
    fp: "FreeCAD.FeaturePython",
    lcs: Any,
    shape: Any
) -> dict[str, Any] | BaseException:
    """Run the full draping pipeline synchronously.

    Returns the result dict on success, or the caught exception on failure.
    """
    try:
        from Composites.tools.drape_backend_nextdrape import (
            NextDrapeBackend,
        )

        # Lightweight params carrier (NextDrape no longer needs mesh input).
        class _SolverParams:
            def __init__(self, pitch):
                self.pitch = float(pitch)

        tess = _tessellate_cut_wires(fp)
        solver_shape, use_cut = _get_shape_for_solver(fp, shape)

        # 3. Create backend and run diagnostics
        backend = NextDrapeBackend(
            _SolverParams(fp.DrapePitch), lcs, shape,
            cut_wires=tess,
            cut_shape=solver_shape,
            use_cut_shape=use_cut,
        )
        diag = backend.diagnostics()

        # 4. Run the C++ solve
        if use_cut:
            solve_result = backend._run_solve()
        else:
            solve_result = backend._run_solve()

        # 5. Build draped mesh Coin3D geometry
        from Composites.features.coin_geometry import build_drapecd_coin

        node_positions = solve_result.get("node_positions", [])
        quads = solve_result.get("quads", [])
        drapecd_mesh = build_drapecd_coin(node_positions, quads, wireframe=False)

        # 6. Collect results
        return {
            "backend": backend,
            "drapecd_mesh": drapecd_mesh,
            "solve_result": solve_result,
            "diag": diag,
            "valid": backend.is_valid(),
            "quality_pass": backend.quality_pass(),
            "tex_coords": backend.get_tex_coords(),
            "cut_edges": tess,
            "cut_boundary_edges": solve_result.get("cut_boundary_edges", []),
            "cut_wire_diagnostics": solve_result.get("cut_wire_diagnostics", {}),
        }
    except Exception as exc:
        return exc
