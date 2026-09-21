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


def _dart_wire_shapes(fp: Any) -> list[Any] | None:
    """Collect DrapeCuts projection shapes for the solver.

    Returns ``None`` if no cut wires are specified, otherwise the list of
    the projection objects' Part.Shape wires. These are passed to the
    solver as genuine wires (``dart_wires``) — the C++ layer locates each
    wire's owning face and samples its p-curves natively, so no compound
    embedding or tessellation is involved.
    """
    cuts = getattr(fp, "DrapeCuts", None)
    if not cuts or not hasattr(fp, "DrapeCuts") or len(fp.DrapeCuts) == 0:
        return None

    import FreeCAD

    doc = fp.Document
    result: list[Any] = []
    for obj_ref in fp.DrapeCuts:
        # obj_ref may be a document object (GUI) or a string name.
        obj = obj_ref if hasattr(obj_ref, "Shape") else doc.getObject(obj_ref)
        if obj is None:
            continue
        shape = obj.Shape if hasattr(obj, "Shape") else None
        if shape is None or shape.isNull():
            continue
        result.append(shape)
    return result if result else None


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

        dart_wires = _dart_wire_shapes(fp)

        # 3. Create backend and run diagnostics
        backend = NextDrapeBackend(
            _SolverParams(fp.DrapePitch), lcs, shape,
            dart_wires=dart_wires,
        )
        diag = backend.diagnostics()

        # 4. Run the C++ solve
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
