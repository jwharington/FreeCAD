# Plan: KDTree-Based Spatial Indexing for UV Mapping Performance (Delivered)

**Date:** 2026-07-15 → 2026-07-16
**Status:** Complete. The k-d tree is implemented in nextdrape and exposed
through the `DrapeEngine::LookupUV` frontend; FreeCAD no longer binds or
calls `KDTreeLocator` directly. All verification gates pass.

## What was delivered

A k-d tree over quad centroids gives O(log N) UV point lookup, replacing the
O(N) brute-force quad scan. The index is owned by `DrapeEngine` (built in
`Compute`, queried via `LookupUV`), so the algorithm choice and flat-data
management are internal to nextdrape.

| Item | Status | Location |
|------|--------|----------|
| `KDTreeLocator` class | DONE | `src/3rdParty/nextdrape/include/nextdrape/KDTreeLocator.hpp`, `src/3rdParty/nextdrape/src/KDTreeLocator.cpp` |
| `DrapeEngine::LookupUV` frontend | DONE | `src/3rdParty/nextdrape/include/nextdrape/DrapeEngine.hpp`, `src/3rdParty/nextdrape/src/DrapeEngine.cpp` |
| C++ unit tests | DONE | `src/3rdParty/nextdrape/tests/test_kd_tree_locator.cpp` (7 tests) |
| FreeCAD pybind (engine only) | DONE | `src/Mod/Composites/App/CompositesDrape.cpp` — `DrapeEngine.compute`/`lookup_uv` |
| FreeCAD backend wiring | DONE | `src/Mod/Composites/tools/drape_backend_nextdrape.py` — persistent `self._engine` |

**Decoupling note:** the original design had FreeCAD bind `KDTreeLocator`
directly and manage a `_quad_locator` cache. That coupling was removed —
`KDTreeLocator` is now a private implementation detail of `DrapeEngine`,
exposed only to nextdrape's own C++ tests. See
`src/3rdParty/nextdrape/docs/uv-lookup-frontend-decoupling.md` for the full
design + the parity evidence (0 mismatches, `engine.lookup_uv` vs direct
`KDTreeLocator.lookup`).

## Verification

- **G1** (compiles + basic lookup): ✅ 7/7 nextdrape C++ tests.
- **G3** (KD matches brute-force): ✅ `KdTreeMatchesBruteForce` — on one
  12×12 warped grid, `lookup()` (k-d path) == `bruteForceLookup()`
  (exhaustive, same selection rule) to 1e-9.
- **G5** (>3× speedup): ✅ 124.95× on a 50×50 grid (max diff 7.1e-15).
  *Measured on the direct-KDTree path; parity with `engine.lookup_uv`
  proven, not re-benchmarked.*
- **Parity** (zero behaviour change from the decoupling): 200 node lookups,
  0 mismatches, max diff `0.00e+00`.

For the full delivered state, see `docs/plan-priority1-master.md`.
