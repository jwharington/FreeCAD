"""Python-side wiring for the non-planar parting binding (Phase 2 draft).

DRAFT — not yet wired into tools/mould_analysis.py. Shows how
_propose_non_planar_parting calls the CompositesParting binding and maps the
C++ result dict to the Phase 0 result contract. The current stub returns
NotImplemented; this replaces the stub body once the binding lands.

Lives in tools/mould_analysis.py next to _propose_non_planar_parting.
"""

# The binding is imported lazily so the module loads without the C++ build.
# CompositesParting is the pybind11 module name (see CompositesParting.cpp).
# try:
#     import CompositesParting as _parting
# except ImportError:
#     _parting = None


def _propose_non_planar_parting(
    shape,
    direction,
    land_width=25.0,
    stock_margin=0.1,
    stock_footprint=None,
):
    """Call the C++ marching-equator solver and map to the result contract.

    Returns the dict shape documented in the Phase 0 contract:
        status   — "ready" | "not_implemented" | "fork_degenerate" | ...
        summary  — human-readable
        parting_line         — per-surface (u,v) spline chain (or None)
        parting_skirt_rays   — retained surface-normal rays (or [])
        upper_shell / lower_shell — the split source halves
        mould_half_a_shape / mould_half_b_shape — the closed mould halves
        tangent_face_midpoints — diagnostics for the recurring midpoint rule
        error    — detail string on failure
    """
    # if _parting is None:
    #     return _non_planar_not_implemented(
    #         "CompositesParting binding not available (nextdrape C++ pending)"
    #     )
    #
    # # Unpack the stock-footprint override: Vector → (dx, dy) tuple.
    # footprint = (0.0, 0.0)
    # if stock_footprint is not None and stock_footprint.Length > 0:
    #     footprint = (stock_footprint.x, stock_footprint.y)
    #
    # try:
    #     raw = _parting.compute_non_planar_parting(
    #         shape,
    #         (direction.x, direction.y, direction.z),
    #         land_width,
    #         stock_margin,
    #     )
    # except Exception as exc:
    #     return _non_planar_not_implemented(
    #         f"CompositesParting binding raised: {exc}"
    #     )
    #
    # if not raw["success"]:
    #     # Non-ready: surface the failure reason, let the caller degrade to
    #     # planar (the analysis verdict stays WC-driven).
    #     return {
    #         "status": raw["status"],
    #         "summary": raw["summary"],
    #         "parting_line": None,
    #         "upper_shell": None,
    #         "lower_shell": None,
    #         "skirt_rays": [],
    #         "mould_half_a_shape": None,
    #         "mould_half_b_shape": None,
    #         "tangent_face_midpoints": raw.get("tangent_face_midpoints", []),
    #         "error": raw["summary"],
    #     }
    #
    # # success: decode the BREP bytes back into Part shapes.
    # def _shape(brep_bytes):
    #     if not brep_bytes:
    #         return Part.Shape()
    #     return Part.readBytes(brep_bytes)
    #
    # return {
    #     "status": "ready",
    #     "summary": raw["summary"],
    #     "parting_line": _shape(raw["part_line_3d"]),  # TODO: per-surface chain
    #     "upper_shell": _shape(raw["upper_shell"]),
    #     "lower_shell": _shape(raw["lower_shell"]),
    #     "skirt_rays": [],  # TODO: marshal from raw["skirt"] if needed
    #     "mould_half_a_shape": _shape(raw["mould_half_lower"]),
    #     "mould_half_b_shape": _shape(raw["mould_half_upper"]),
    #     "tangent_face_midpoints": raw.get("tangent_face_midpoints", []),
    #     "error": "",
    # }
    raise NotImplementedError("draft wiring — uncomment when the binding lands")
