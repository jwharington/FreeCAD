# Master Plan: Priority 1 — Performance & UV Quality

**Date:** 2026-07-15
**Last Updated:** 2026-07-16
**Scope:** All Priority 1 work from the handoff document
**Status:** Implementation incomplete — G7 reopened; awaiting verification and ownership cleanup for shader rendering and drape state storage

---

## Overview

Two independent workstreams run in parallel:

| Stream | File | Owner |
|--------|------|-------|
| **nextdrape core** — k-d tree spatial index (**C++**) | `ext/docs/plan-kdtree-performance.md` | nextdrape developer |
| **FreeCAD integration** — UV clamping, continuity, shader perf | `docs/plan-freecad-uv-quality.md` | FreeCAD developer |

Plus a separate cosmetic bug tracking document:
| Priority 4 bugs | `docs/plan-priority4-bugs.md` | Investigator |

## Workstream Dependencies

```
┌─────────────────────┐    ┌──────────────────────┐
│  nextdrape core     │    │  FreeCAD integration │
│  (k-d tree, C++)    │    │  (UV quality)        │
│                     │    │                      │
│  nextdrape/KDTreeLocator.hpp│ │  util/geometry_util.py│
│  nextdrape/src/KDTreeLocator.cpp│ │  features/*.py       │
│  nextdrape/tests/test_kd_tree_locator.cpp│
│                     │    │                      │
│  C++ unit tests (standalone)│    │  test_uv_mapping.py  │
└─────────────────────┘    └──────────────────────┘
         │                          │
         │    Shared:               │
         │    geometry_util.py      │
         │    compositestests/      │
         └────────┬─────────────────┘
                  │
          test_uv_mapping.py
          (runs for both streams)
```

**Shared dependency:** `util/geometry_util.py` — both streams touch this file.
- nextdrape stream: C++ QuadLocator called from Python wrappers (calls through to `tex_coord_at_point`)
- FreeCAD stream: adds soft_clamp, shared-edge averaging inside `tex_coord_at_point`

**Execution order:** Either stream can start first. The shared file changes are non-overlapping:
- k-d tree wraps the function call (external, C++)
- UV quality modifies the function body (internal, Python)

## Architecture Decision: KDTreeLocator in nextdrape

The KDTreeLocator C++ class was initially developed in `src/Mod/Composites/App/` but was **relocated to `src/3rdParty/nextdrape/`** to enable standalone testing within nextdrape's own unit test harness. The Composites duplicates (`KDTreeLocator.h`, `KDTreeLocator.cpp`) were deleted — the pybind11 bindings in `CompositesDrape.cpp` already bind `nextdrape::KDTreeLocator`.

This means:
- nextdrape owns the KDTreeLocator implementation and its C++ tests
- Composites tests via Python bindings (`compositestests/test_kd_tree_locator.py`)
- The C++ test file was moved from `App/tests/` to `nextdrape/tests/`
- The nextdrape CMakeLists.txt was updated to include the test and fix libkdtree include path for standalone builds

## Execution Sequence

### Phase A: Parallel (Day 1–2) ✅ COMPLETE

1. **Stream 1 (nextdrape):** Implement `KDTreeLocator` C++ class ✅
2. **Stream 2 (FreeCAD):** Implement `soft_clamp` in `util/geometry_util.py` ✅

Both streams write tests in parallel.

### Phase B: Integration (Day 2–3) ✅ COMPLETE

3. Expose QuadLocator via pybind11 in `Composites_drape.cpp` ✅
4. Wire soft_clamp into `tex_coord_at_point()` (Stream 2) ✅
5. Wire QuadLocator into `NextDrapeBackend` Python wrapper ✅
6. Implement shared-edge UV averaging (Stream 2) ✅

### Phase C: Cross-Validation (Day 3–4) ⏸ PENDING

> Note: G7 is the next priority focus. Reopen it until the shader renders in FreeCAD MCP and drape state is fully owned by the C++ backend rather than serialized on `CompositeShell`.

7. Run full test suite (`test_uv_mapping.py` + C++ unit tests) — TBD
8. Visual verification in FreeCAD GUI — TBD
9. Performance measurement (confirm ~37× speedup) — TBD

### Phase D: Polish (Day 4–5) ⏸ PENDING

10. Priority 4 bug investigation (if time permits) — TBD
11. Final review and merge — TBD

## Commit Strategy

Commits alternate between streams to keep CI green:

```
commit 1: feat(composites): add soft_clamp utility          ← Stream 2
commit 2: feat(nextdrape): add KDTreeLocator C++ class     ← Stream 1 (in nextdrape/)
commit 3: fix(composites): clamp UV extrapolation          ← Stream 2
commit 4: feat(composites): bind QuadLocator via pybind11  ← Stream 1
commit 5: enhance(composites): UV continuity at edges      ← Stream 2
commit 6: refactor(nextdrape): relocate KDTreeLocator      ← Stream 1 (from Composites/)
commit 7: test(nextdrape): add C++ unit tests for KDTree  ← Stream 1 (in nextdrape/)
commit 8: test(composites): add UV quality tests           ← Stream 2
commit 9: (merge) perf(composites): k-d tree acceleration  ← Stream 1
commit 10:(merge) enh(composites): UV quality improvements  ← Stream 2
```

## Test Matrix

| Test Suite | Stream 1 | Stream 2 | Both |
|------------|----------|----------|------|
| C++ unit tests (KDTreeLocator) | ✓ (nextdrape/) | | |
| `test_uv_mapping.py` | | ✓ | ✓ |
| `test_rosette_integration.py` | | ✓ | ✓ |
| `test_composite_shell.py` | | ✓ | ✓ |
| Visual verification | | ✓ | ✓ |
| Performance benchmarks | ✓ | | |

## Gates

**Gate policy:** do not mark a gate closed until the behavior is covered by an automated test that fails before the fix and passes after it. For rendering and persistence issues, establish a real FreeCAD/headless or MCP-backed regression test before reopening the gate.

**G7 closure requirements:**
- Shader rendering must be covered by a FreeCAD MCP or GUI-backed regression test that proves the view provider/shader path is active, not just instantiated.
- Drape state ownership must be covered by a persistence regression test that proves the internal drape payload is not stored on `CompositeShell` and is restored via the C++ backend.
- Visual verification may support the diagnosis, but it does not close the gate by itself.

| Gate | Criteria | Status |
|------|----------|--------|
| G0 | All existing tests pass | ⏸ TBD |
| G1 | KDTreeLocator compiles, basic lookup works | ✅ PASS (7/7 tests) |
| G2 | soft_clamp correct, no regressions | ✅ PASS |
| G3 | Accuracy: KD matches brute-force to 6dp | ✅ PASS — `test_kd_tree_locator.py` compares KD lookup against the brute-force reference to 6dp |
| G4 | UVs bounded at mesh edges | ✅ PASS |
| G5 | >3× speedup on 50×50 grid | ✅ PASS — flat 50×50 benchmark measured 124.95× speedup with max diff 7.1e-15 |
| G6 | No UV jumps >0.05 at shared edges | ✅ PASS |
| G7 | Full pipeline works end-to-end | ⏸ REOPENED — shader rendering is not active in MCP, and drape state still serializes on `CompositeShell` |
| G8 | All Composites tests pass | ⏸ TBD |

**Order of closure:** G7 is the first blocker to resolve; G0/G8 only count once G7 is back to a real passing state and backed by regression tests.

## Files Modified

| File | Stream | Status |
|------|--------|--------|
| `src/3rdParty/nextdrape/include/nextdrape/KDTreeLocator.hpp` | 1 | ✅ Written |
| `src/3rdParty/nextdrape/src/KDTreeLocator.cpp` | 1 | ✅ Written |
| `src/3rdParty/nextdrape/CMakeLists.txt` | 1 | ✅ Updated |
| `src/Mod/Composites/App/CompositesDrape.cpp` | 1 | ✅ pybind11 bindings added |
| `src/Mod/Composites/util/geometry_util.py` | 2 | ✅ soft_clamp, shared-edge averaging |
| `src/Mod/Composites/tools/drape_backend_nextdrape.py` | 1 | ✅ Wired into NextDrapeBackend |
| `src/Mod/Composites/features/CompositeShell.py` | 1,2 | ✅ Wired into _RehydratedBackend |
| `src/Mod/Composites/features/AlignFibreRosette.py` | 1 | ✅ Transparent (delegates to backend) |
| `src/Mod/Composites/compositestests/test_uv_mapping.py` | 2 | ✅ UV quality tests |
| `src/Mod/Composites/compositestests/test_compositeexamples.py` | 2 | ✅ Added end-to-end full-pipeline smoke test |
| `src/Mod/Composites/compositestests/test_kd_tree_locator.py` | 1 | ✅ Added KD-vs-brute-force comparison test |
| `src/3rdParty/nextdrape/tests/test_kd_tree_locator.cpp` | 1 | ✅ 7 C++ tests, all passing |
| `src/3rdParty/nextdrape/include/nextdrape/KDTreeLocator.hpp` | — | Moved from `App/` to `nextdrape/` |
| `src/Mod/Composites/App/KDTreeLocator.h` | — | Deleted (moved to nextdrape/) |
| `src/Mod/Composites/App/KDTreeLocator.cpp` | — | Deleted (moved to nextdrape/) |

## References

- Handoff document: `/tmp/handoff_composites_shader_support.md`
- nextdrape k-d tree plan: `ext/docs/plan-kdtree-performance.md` (update: QuadLocator is C++, not Python)
- FreeCAD UV quality plan: `docs/plan-freecad-uv-quality.md`
- Priority 4 bugs: `docs/plan-priority4-bugs.md`