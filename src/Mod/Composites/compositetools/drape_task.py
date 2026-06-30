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
    import FreeCAD


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

        # 3. Create backend and run diagnostics
        backend = NextDrapeBackend(_SolverParams(fp.DrapePitch), lcs, shape)
        diag = backend.diagnostics()

        # 4. Run the C++ solve
        solve_result = backend._run_solve()

        # 5. Build draped mesh
        from Composites.features.CompositeShell import (
            _build_drapecd_mesh,
        )

        node_positions = solve_result.get("node_positions", [])
        quads = solve_result.get("quads", [])
        drapecd_mesh = _build_drapecd_mesh(node_positions, quads)

        # 6. Collect results
        return {
            "backend": backend,
            "drapecd_mesh": drapecd_mesh,
            "solve_result": solve_result,
            "diag": diag,
            "valid": backend.is_valid(),
            "quality_pass": backend.quality_pass(),
            "tex_coords": backend.get_tex_coords(),
        }
    except Exception as exc:
        return exc
