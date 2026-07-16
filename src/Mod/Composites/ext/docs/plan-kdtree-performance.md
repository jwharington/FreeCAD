# Plan: KDTree-Based Spatial Indexing for UV Mapping Performance

**Date:** 2026-07-15
**Last Updated:** 2026-07-16
**Status:** IMPLEMENTATION COMPLETE — Awaiting verification gates (accuracy, integration, performance)
**Scope:** nextdrape core — C++ k-d tree spatial index replacing O(N) brute-force quad iteration
**Separation:** This plan covers only the nextdrape/native-side work. FreeCAD integration (UV clamping, shader rendering, ViewProvider) is in `docs/plan-freecad-uv-quality.md`.

---

## Executive Summary

Replace the O(N) brute-force quad iteration in `tex_coord_at_point()` with a C++ k-d tree over quad centroids, reducing per-point lookup from O(N) to O(log N). Expected overall speedup: ~37× for GUI-mode drape mesh rendering (matching headless performance).

**Root cause:** `geometry_util.py`'s `tex_coord_at_point()` iterates all quads (~700) for each support surface vertex (~10K), yielding ~7M evaluations per render. The k-d tree narrows candidates to 1–8 quads before bilinear refinement.

---

## Progress Report

### ✅ Implementation — Complete

All code has been written, committed, and wired into the runtime. The k-d tree activates automatically for meshes with ≥100 quads; smaller meshes fall back to brute-force.

| Item | Status | Location |
|------|--------|----------|
| `KDTreeLocator.hpp` | DONE | `src/3rdParty/nextdrape/include/nextdrape/` |
| `KDTreeLocator.cpp` | DONE | `src/3rdParty/nextdrape/src/` |
| pybind11 bindings | DONE | `src/Mod/Composites/App/CompositesDrape.cpp` |
| CMakeLists.txt | DONE | kdtree++ include path in `nextdrape_core` |
| `NextDrapeBackend` wiring | DONE | `tools/drape_backend_nextdrape.py` — `_quad_locator` lazy-init |
| `_RehydratedBackend` wiring | DONE | `features/CompositeShell.py` — `_quad_locator` lazy-init |
| Python tests | DONE | `compositestests/test_kd_tree_locator.py` — 6 test cases |

### ❌ Previously Blocked — Resolved

| Issue | Severity | Resolution |
|-------|----------|------------|
| C++ segfault on `lookup()` | CRITICAL | Fixed — no longer crashes on single quad or small grids |
| kdtree++ API mismatches | HIGH | Fixed — switched to `find_nearest()` |
| C++ unit tests not wired | LOW | Still pending — see Gates below |

### 📊 Current Test Results

```
test_kd_tree_locator.py — 6 tests
  test_min_quads_for_kdtree        ✓
  test_empty_quads                 ✓
  test_single_quad_center          ✓  (previously crashed)
  test_small_grid_accuracy         ✓  (previously returned [0,0])
  test_z_offset                    ✓
  test_large_mesh_kdtree_activation ✓ (previously crashed)
```

All 6 Python tests pass. Remaining verification gates are accuracy, integration, and performance benchmarks.

---

## 1. Architecture

### 1.1 Runtime Call Chain (Active)

```
coin_geometry.py:_map_uv_to_support()
  → for each support vertex (M ≈ 10K):
      backend.get_tex_coord_at_point(point)

NextDrapeBackend.get_tex_coord_at_point()
  → if n_quads >= 100:
       self._quad_locator.lookup(point, tex_coords)   ← C++ k-d tree
    else:
       geometry_util.tex_coord_at_point()              ← brute-force

_RehydratedBackend.get_tex_coord_at_point()
  → same pattern: _quad_locator.lookup() or brute-force
```

### 1.2 Where KDTree Sits

The k-d tree sits between the high-level backend and `tex_coord_at_point()`. It acts as a spatial index narrowing the candidate quad set from N to a handful (typically 1–8) before the expensive bilinear refinement runs.

**Key insight:** The nearest centroid to the query point is almost always the containing quad. Validation happens via plane distance + bilinear bounds.

### 1.3 Fallback Behavior

For meshes with fewer than 100 quads, the k-d tree build overhead exceeds the benefit. In that case, `lookup()` falls back to `bruteForce()` which scans all quads — identical behavior to the pre-KDTree code path.

### 1.1 Current Call Chain

```
coin_geometry.py:_map_uv_to_support()
  → for each support vertex (M ≈ 10K):
      backend.get_tex_coord_at_point(point)

drape_backend_nextdrape.py:NextDrapeBackend.get_tex_coord_at_point()
  → geometry_util.tex_coord_at_point()
      → for each quad (N ≈ 700):
          compute centroid, normal, plane distance
          bilinear refinement
          track best_quad

CompositeShell.py:_RehydratedBackend.get_tex_coord_at_point()
  → geometry_util.tex_coord_at_point()

AlignFibreRosette.py:draper.get_tex_coord_at_point()
  → geometry_util.tex_coord_at_point()
```

### 1.2 Target Call Chain

```
coin_geometry.py:_map_uv_to_support()
  → for each support vertex (M):
      backend.get_tex_coord_at_point(point)

drape_backend_nextdrape.py:NextDrapeBackend.get_tex_coord_at_point()
  → nextdrape::KDTreeLocator::lookup(point)   ← C++ via pybind11
     → kdtree.find_nearest(centroid) → O(log N)
     → return best_quad_index
  → geometry_util.tex_coord_at_point()
     → [optimized: only checks candidate quads, not all N]

CompositeShell.py:_RehydratedBackend.get_tex_coord_at_point()
  → nextdrape::KDTreeLocator::lookup(point)   ← SHARED C++ CLASS
  → geometry_util.tex_coord_at_point()

AlignFibreRosette.py:draper.get_tex_coord_at_point()
  → nextdrape::KDTreeLocator::lookup(point)
  → geometry_util.tex_coord_at_point()
```

### 1.3 Where KDTree Sits

The k-d tree sits between the high-level backend and `tex_coord_at_point()`. It acts as a spatial index narrowing the candidate quad set from N to a handful (typically 1–8) before the expensive bilinear refinement runs.

**Key insight:** The nearest centroid to the query point is almost always the containing quad. Validation happens via plane distance + bilinear bounds.

---

## 2. Implementation Status

### Step 1: Create KDTreeLocator C++ Class ✅

**Files:** `src/3rdParty/nextdrape/include/nextdrape/KDTreeLocator.hpp`, `src/3rdParty/nextdrape/src/KDTreeLocator.cpp`

Fully implemented. Uses kdtree++ (Martin F. Krafft). Stores quad centroids, builds tree in constructor. Falls back to brute-force for N < 100 quads.

### Step 2: Bind KDTreeLocator via pybind11 ✅

**File:** `src/Mod/Composites/App/CompositesDrape.cpp`

Bindings exposed in existing `Composites_drape` module. Constructor accepts Python lists, `lookup()` takes point + tex_coords, `min_quads_for_kdtree()` static, `last_lookup_us()` for profiling.

### Step 3: Wire into NextDrapeBackend ✅

**File:** `tools/drape_backend_nextdrape.py`

Lazy-import pattern (`_ensure_kdtree()`). After `_run_solve()`, constructs `KDTreeLocator` lazily on first `get_tex_coord_at_point()` call. Activated when `n_quads >= min_quads_for_kdtree()`.

### Step 4: Wire into _RehydratedBackend ✅

**File:** `features/CompositeShell.py`

Same pattern — imports `_ensure_kdtree`, checks threshold, builds `_quad_locator` on demand.

### Step 5: AlignFibreRosette — No Change Needed ✅

Delegates to backend which already uses KDTreeLocator.

### Step 6: coin_geometry.py — No Change Needed ✅

Delegates to `backend.get_tex_coord_at_point()`.

### Step 7: Edge Cases ✅

Handled in C++:
| Case | Handling |
|------|----------|
| Degenerate quads (zero area) | `bilinearRefine()` returns `{}` on zero-length edges |
| Empty quad list | `lookup()` returns `{}` early |
| Single quad | Skips k-d tree; brute-force path |
| Concurrent access | k-d tree immutable after construction → safe |
| Z-offset invariance | Plane projection handles out-of-plane points |

### Step 8: Performance Hooks ✅

`last_lookup_us()` exposed via pybind11. Timing wraps entire lookup (k-d tree or brute-force).

---

## 3. Tests

### 3.1 Python Integration Tests ✅

**File:** `compositestests/test_kd_tree_locator.py`

6 test cases — all passing:
| Test | Result |
|------|--------|
| `test_min_quads_for_kdtree` | ✅ Static method returns 100 |
| `test_empty_quads` | ✅ Returns empty list |
| `test_single_quad_center` | ✅ Returns [0.5, 0.5] within 1e-4 |
| `test_small_grid_accuracy` | ✅ 3×3 grid accurate to 1e-4 |
| `test_z_offset` | ✅ Z-offset invariant |
| `test_large_mesh_kdtree_activation` | ✅ 10×10 grid accurate to 1e-4 |

### 3.2 C++ Unit Tests — Pending

**File:** `src/3rdParty/nextdrape/tests/test_kd_tree_locator.cpp` (does not exist yet)

Should be created using nextdrape's GTest infrastructure. Would test the C++ internals directly (tree build, edge cases, performance characteristics) without FreeCAD dependency.

### 3.3 Existing Tests — No Changes Needed

- `test_uv_mapping.py` — delegates to `tex_coord_at_point()`, underlying function unchanged
- `test_rosette_integration.py` — delegates to `get_tex_coord_at_point()`, transparent improvement
- `test_composite_shell.py` — doesn't exercise UV mapping directly

---

## 4. Gates (Verification Criteria)

### Gate 0: Pre-implementation Baseline ✅

- [x] Run existing `test_uv_mapping.py` — all tests pass
- [ ] Record baseline performance: time 1000 `tex_coord_at_point()` calls on a representative mesh

### Gate 1: KDTreeLocator Compilation ✅

- [x] `KDTreeLocator` compiles and links ✅
- [x] pybind11 bindings expose class to Python ✅
- [x] Small grid (3×3) passes accuracy tests ✅
- [ ] C++ unit tests pass (pending — see §3.2)

### Gate 2: Accuracy Gate — Pending

- [ ] 1000 random interior points on 50×50 grid: KD result matches brute-force to 6 decimal places
- [ ] Edge cases (shared edges, degenerate quads, Z-offset) pass

### Gate 3: Integration Gate — Pending

- [x] `NextDrapeBackend.get_tex_coord_at_point()` uses KDTreeLocator ✅ (wired in `drape_backend_nextdrape.py`)
- [x] `_RehydratedBackend.get_tex_coord_at_point()` uses KDTreeLocator ✅ (wired in `CompositeShell.py`)
- [ ] Existing `test_uv_mapping.py` tests still pass
- [ ] Existing `test_rosette_integration.py` tests still pass
- [ ] Composite shell creation and drape solve work end-to-end

### Gate 4: Performance Gate — Pending

- [ ] 50×50 grid shows >3× speedup
- [ ] 100×100 grid shows >5× speedup
- [ ] Overall pipeline (tessellation + UV mapping) shows measurable improvement

### Gate 5: Production Readiness — Pending

- [ ] All existing Composites tests pass
- [ ] No regressions in memory usage (k-d tree overhead < 10% of total)
- [ ] No new warnings in FreeCAD console
- [ ] Code reviewed and documented

---

## 5. Commit Points

| # | Scope | Message |
|---|-------|---------|
| 1 | `src/3rdParty/nextdrape/include/nextdrape/KDTreeLocator.hpp` (new) | `feat(nextdrape): add KDTreeLocator C++ k-d tree class` |
| 2 | `src/3rdParty/nextdrape/src/KDTreeLocator.cpp` (new) | `feat(nextdrape): implement k-d tree spatial index` |
| 3 | `src/3rdParty/nextdrape/CMakeLists.txt` | `build(nextdrape): add KDTreeLocator to nextdrape_core` |
| 4 | `src/Mod/Composites/App/CompositesDrape.cpp` | `feat(composites): bind nextdrape::KDTreeLocator via pybind11` |
| 5 | `tools/drape_backend_nextdrape.py` | `refactor(nextdrape): use KDTreeLocator for UV point lookup` |
| 6 | `features/CompositeShell.py` | `refactor(rehydrated): use KDTreeLocator for UV point lookup` |
| 7 | `src/3rdParty/nextdrape/tests/test_kd_tree_locator.cpp` (new) | `test(nextdrape): add C++ unit tests for KDTreeLocator` |
| 8 | (merge) | `perf(composites): k-d tree acceleration for UV mapping` |

---

## 6. Performance Expectations

### 6.1 Complexity Analysis

| Metric | Before | After |
|--------|--------|-------|
| Per-point complexity | O(N) | O(log N) + O(K) |
| N (typical GUI) | ~700 quads | ~700 quads |
| M (support vertices) | ~10K triangles | ~10K triangles |
| Total ops | M × N = 7M | M × (log N + K) ≈ 100K |
| Speedup factor | 1× | ~70× theoretical |

Where K is the fallback search window (typically 1–8 quads).

### 6.2 Expected Speedup Breakdown

| Stage | Before (ms) | After (ms) | Speedup |
|-------|-------------|------------|---------|
| k-d tree build | 0 | ~2 ms | N/A (one-time) |
| Per-point lookup | ~0.5 ms | ~0.01 ms | ~50× |
| 1000-point batch | ~500 ms | ~10 ms | ~50× |
| Full pipeline (GUI) | ~3700 ms | ~100 ms | ~37× |

### 6.3 Memory Overhead

| Component | Size |
|-----------|------|
| Quad centroids (N × 3 doubles) | 24 bytes × N |
| Quad index array (N ints) | 4 bytes × N |
| k-d tree internal nodes | ~16 bytes × N |
| **Total overhead** | ~44 bytes × N (~31 KB for 700 quads) |

Negligible compared to the mesh data itself.

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| k-d tree build slower than brute-force for small N | High | Low | Skip k-d tree for N < 100 quads |
| Nearest centroid ≠ containing quad for distorted meshes | Medium | Medium | Fallback search with configurable radius |
| pybind11 binding complexity | Low | Medium | Add as function in existing module, not new module |
| Regression in UV accuracy | Low | High | Extensive accuracy tests against brute-force baseline |
| Thread safety issues | Low | Medium | k-d tree is immutable after construction |
| C++ segfault in lookup() | ~~HIGH~~ | ~~CRITICAL~~ | **RESOLVED** — no longer crashes |

---

## 8. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Use k-d tree over quad centroids (not nodes) | Centroids give better quad-locality; nodes would need duplicate storage |
| Hybrid approach (k-d tree + bilinear refinement) | Pure k-d tree nearest-neighbor isn't sufficient for quad containment |
| Keep `tex_coord_at_point()` as-is initially | Minimizes risk; KDTreeLocator isolates the optimization |
| Use kdtree++ library (not hand-rolled) | Battle-tested, well-maintained, already in FreeCAD source tree |
| Move to nextdrape module | Enables standalone testing without FreeCAD dependency |
| Bind in existing `Composites_drape` module | Avoids second `.so`; simpler deployment; follows existing pattern |
| Threshold N < 100 for k-d tree skip | Build overhead dominates for small meshes |

---

## 9. Future Enhancements (Out of Scope)

- **BVH (Bounding Volume Hierarchy):** Better for ray-quad intersection testing
- **GPU-accelerated lookup:** Offload to fragment shader (already partially done)
- **Adaptive refinement:** Subdivide large quads for better spatial locality
- **Parallel k-d tree build:** Use OpenMP for very large meshes (>100K quads)

---

## 10. Next Steps

1. **Gate 2:** Write accuracy test comparing KDTreeLocator output against brute-force on 50×50 grid (6dp match)
2. **Gate 3:** Run full integration test suite (`test_uv_mapping.py`, `test_rosette_integration.py`, end-to-end drape solve)
3. **Gate 4:** Measure speedup — profile `tex_coord_at_point()` with/without k-d tree on representative meshes
4. **Gate 5:** Full Composites test sweep, memory profiling, console warning audit
5. **§3.2:** Create C++ GTest unit tests in `src/3rdParty/nextdrape/tests/`