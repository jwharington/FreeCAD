# Master Plan: Priority 1 — Performance & UV Quality

**Date:** 2026-07-15
**Scope:** All Priority 1 work from the handoff document

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

### Phase A: Parallel (Day 1–2)

1. **Stream 1 (nextdrape):** Implement `KDTreeLocator` C++ class in `nextdrape/KDTreeLocator.{h,cpp}`
2. **Stream 2 (FreeCAD):** Implement `soft_clamp` in `util/geometry_util.py`

Both streams write tests in parallel.

### Phase B: Integration (Day 2–3)

3. Expose QuadLocator via pybind11 in `Composites_drape.cpp`
4. Wire soft_clamp into `tex_coord_at_point()` (Stream 2)
5. Wire QuadLocator into `NextDrapeBackend` Python wrapper (Stream 1)
6. Implement shared-edge UV averaging (Stream 2)

### Phase C: Cross-Validation (Day 3–4)

7. Run full test suite (`test_uv_mapping.py` + C++ unit tests)
8. Visual verification in FreeCAD GUI
9. Performance measurement (confirm ~37× speedup)

### Phase D: Polish (Day 4–5)

10. Priority 4 bug investigation (if time permits)
11. Final review and merge

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

| Gate | Criteria | Who |
|------|----------|-----|
| G0 | All existing tests pass | Both |
| G1 | KDTreeLocator compiles, basic lookup works | Stream 1 |
| G2 | soft_clamp correct, no regressions | Stream 2 |
| G3 | Accuracy: KD matches brute-force to 6dp | Stream 1 |
| G4 | UVs bounded at mesh edges | Stream 2 |
| G5 | >3× speedup on 50×50 grid | Stream 1 |
| G6 | No UV jumps >0.05 at shared edges | Stream 2 |
| G7 | Full pipeline works end-to-end | Both |
| G8 | All Composites tests pass | Both |

## Files Modified

| File | Stream | Change |
|------|--------|--------|
| `nextdrape/KDTreeLocator.h` (new) | 1 | C++ k-d tree spatial index header (in nextdrape/) |
| `nextdrape/src/KDTreeLocator.cpp` (new) | 1 | C++ k-d tree spatial index impl (in nextdrape/) |
| `nextdrape/tests/test_kd_tree_locator.cpp` (new) | 1 | C++ unit tests (in nextdrape/) |
| `nextdrape/CMakeLists.txt` | 1 | Add KDTreeLocator + test, fix libkdtree include |
| ~~`App/KDTreeLocator.h`~~ | — | **DELETED** — moved to nextdrape/ |
| ~~`App/KDTreeLocator.cpp`~~ | — | **DELETED** — moved to nextdrape/ |
| ~~`App/tests/test_kd_tree_locator.cpp`~~ | — | **DELETED** — moved to nextdrape/ |
| `App/CompositesDrape.cpp` | 1 | pybind11 bindings for QuadLocator |
| `util/geometry_util.py` | 2 | soft_clamp, shared-edge averaging |
| `tools/drape_backend_nextdrape.py` | 1 | Python wrapper calls C++ QuadLocator |
| `features/CompositeShell.py` | 1,2 | Python wrapper + use soft_clamp |
| `features/AlignFibreRosette.py` | 1 | Transparent improvement |
| `compositestests/test_uv_mapping.py` | 2 | UV quality tests |
| `compositestests/test_kd_tree_locator.py` | 1 | Python binding tests (uses nextdrape::KDTreeLocator) |

## References

- Handoff document: `/tmp/handoff_composites_shader_support.md`
- nextdrape k-d tree plan: `ext/docs/plan-kdtree-performance.md` (update: QuadLocator is C++, not Python)
- FreeCAD UV quality plan: `docs/plan-freecad-uv-quality.md`
- Priority 4 bugs: `docs/plan-priority4-bugs.md`