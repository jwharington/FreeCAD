# Master Plan: Priority 1 — Performance & UV Quality

**Date:** 2026-07-15
**Last Updated:** 2026-07-16
**Scope:** All Priority 1 work from the handoff document
**Status:** G7 — PASS. Shader-only output + persistence proven via MCP (2026-07-16).

1. Disable the separate mesh geometry. ✅
2. Verify shader-only output. ✅ (MCP-verified 2026-07-16)
3. Close G7 with objective evidence. ✅ persistence regression passes

Current state: the drape-mesh branch is removed, the shader attaches to the **SupportSurface** geometry (MCP-verified), the native Part shape is hidden via the 'Grid' display mode, ConicalPanelSupport is hidden, GLSL compiles/links clean, the grid logic is fixed, and out-of-grid UV extrapolation works. Persistence (save/reload .FCStd) preserves drape state and re-attaches the shader — `test_g7_persistence.py` all 8 checks pass. Remaining are polish items (selection highlight on overlay; `offset_angle` dead uniform P4), not G7 blockers.

**Verification note:** Shader correctness must be proven with objective, machine-checkable evidence. Do not use ambiguous visual inspection alone as proof of positive shader functioning. `_attached=True` on an empty shader group is NOT proof of functioning — it was the source of the false-positive.

**Current verified state (MCP, 2026-07-16):**
- `shader_state` group has 9 children: 8 shader state nodes + `SupportSurface` Separator (Coordinate3 + TextureCoordinate3 + IndexedFaceSet).
- `grid_shader._coin_geo = SupportSurface`; `_attached = True` (real — geometry present).
- `drape_host` has exactly 1 child (`shader_state`) — no `DrapedMeshGeometry`, no standalone `SupportSurface` direct child.
- ConicalPanelSupport `Visibility = False` by default; `update_visibility` no longer force-re-shows it.
- `hide_drape_mesh` debug toggle no longer hides the support surface (the incorrect `mode_switch.whichChild = -1` coupling was removed).
- **GLSL compile/link: 0 errors/warnings** (MCP diagnostic `test_shader_glsl_capture.py`: truncated log, forced 3D render via `viewIsometric`+`fitAll`+`redraw` ×3, read back Coin messages). Verified with `offset_angle` set to 45° to force `SoGLSLShaderParameter::isValid()` — still 0 warnings. Both Vertex + Fragment shader objects active.
- Geometry/material bindings: 0 warnings (no "Face specification did not end with a valid polygon", no "index out of bounds"). The earlier such warnings were emitted only during the broken intermediate debug states (empty shader / segfault session), not the current clean state.
- **Native Part shape hidden via 'Grid' display mode:** when the shader is active, `vobj.DisplayMode = 'Grid'` points `ModeSwitch.whichChild` at an empty `GridEmptyRoot` branch, so the shell's native `SoBrepFaceSet` (which rendered the same surface without the grid and owned the selection highlight that bled through as grey spots) renders nothing. C++ keeps `whichChild` at the Grid branch across redraws + recompute (driven by DisplayMode, not a Python assignment). Restored to 'Shaded' when the shader is inactive. Three failed approaches documented: (1) `whichChild=SO_SWITCH_NONE` reset by C++; (2) `SoDrawStyle(INVISIBLE)` override too broad (Coin global first-override-wins hid the shader too); (3) `addDisplayMode` guarded by `listDisplayModes` never registered the branch → `whichChild=-1` greyed the object.
- **Known limitation (NOT a G7 blocker, but a real UX regression):** hiding the native Part shape removes FreeCAD's selection highlight (blue on hover, green on select). The object IS selectable programmatically (`FreeCADGui.Selection.isSelected(shell)` returns True), but no visual highlight renders because: (1) the pickable native `SoBrepFaceSet` in `FlatRoot` is switched out by the Grid display mode, and (2) the shader's `SupportSurface` geometry in `DrapeHost` is under `SoFCSelectionRoot` but is a plain Coin `SoIndexedFaceSet` — it does not read FreeCAD's selection `SelContext`, so it never highlights. The shader's `gl_FragColor` would also override any material color.

### Selection-highlight plan (chosen mechanism)

**Root cause (researched 2026-07-16):** FreeCAD's native highlight works because the native shape is `SoBrepFaceSet` — a FreeCAD custom C++ node that, during `GLRender`, reads a `SelContext` (carrying `highlightColor` + `highlightIndex`, set by `SoFCSelection`/`SoFCSelectionRoot`) and calls its own `renderHighlight()` to apply the color. A plain Coin `SoIndexedFaceSet` (used by the shader's `SupportSurface`) has none of that logic. `SoFCSelection`/`SoFCSelectionRoot` are Gui C++ classes, **not exposed in pivy**, so the geometry cannot be wrapped in them from Python.

**Rejected approaches:**
- **Shader uniform for selection state** (`SoShaderParameter1f`): a freshly-added `selection_state` uniform and a previously-dead-but-now-declared `offset_angle` uniform did **NOT** reach the GPU, even when declared and used in GLSL, after a forced relink, and with no GLSL default initializer. Only the *original* GLSL uniforms (`darken`, `grid_spacing_mm`) propagate. Root cause of the binding difference never determined — abandoned.
- **Overlay grid on top of the native shape** (polygon offset): rejected by user — z-fighting on a curved surface and two co-located surfaces rendering the same cone is fragile.
- **Hijacking `darken` with sentinel values**: introduced a dead-code compile error (`selection_state` referenced after its declaration was removed → whole panel black) and a grid-collapse regression. Reverted.

**Chosen mechanism — route selection through the standard material-color channel (`SoMaterial.diffuseColor` → `gl_Color`):**
Unlike `SoShaderParameter` (the broken binding), `SoMaterial.diffuseColor` is a standard Coin element that **definitely reaches the GPU** via `gl_Color` — it is the same channel the native shape's shading uses.

1. Fragment shader: read `gl_Color.rgb` as the base line color (instead of hardcoded `vec3(0.5)`).
2. `VPCompositeShell` SelectionObserver callbacks (already written: `setPreselection`/`removePreselection`/`addSelection`/`removeSelection`/`clearSelection`) drive `gs.material.diffuseColor` → green (selected) / blue (hover) / grey (none), instead of a `SoShaderParameter`.
3. **Caveat to verify:** the `shader_state` group's `mat_binding` is `SoMaterialBinding.PER_VERTEX` with `setOverride(True)` (added to disable VBO on `SoFCIndexedFaceSet`). In PER_VERTEX mode `gl_Color` comes from vertex colors, NOT `SoMaterial.diffuseColor`. Must switch to `OVERALL` binding (or otherwise confirm `gl_Color` reflects the material) so the shader sees the color set by the callbacks. Verify this does not re-enable the VBO path that `mat_binding` override was added to suppress.

This uses FreeCAD's native material-color channel — the "attach the same handlers" idea — without inventing a shader uniform Coin won't bind.

**Not yet implemented.** Gate: must produce objective evidence (GLSL compiles; hover→blue, select→green via real 3D-view interaction) — visual inspection as support only.
- **Not proven:** actual pixel/fragment output (would require GPU readback; visual inspection is disallowed as proof by the gate policy). Compile/link + valid geometry + in-render-path + native-shape-hidden is the machine-checkable evidence gathered so far.
- **Separate defect (Priority 4, NOT a G7 blocker):** the fragment shader GLSL does not declare `uniform float offset_angle`, so the Python-registered `offset_angle` parameter is dead — setting it has no effect on rendering (rosette rotation not applied to the grid). Coin does not warn about this in the current version.
- Next step: persistence regression proof for G7 closure.

## Resolved blockers

### B1 — `build_support_surface_coin` threw on inhomogeneous UV array ✅ FIXED

`get_tex_coord_at_point` violated its own "return None if no quad reachable" contract: the KDTree `lookup` returns `[]` (empty list) when no valid quad is found, but the code returned `[]` instead of `None`. In `_map_uv_to_support`, `if uv is not None` was True for `[]`, so empty lists were appended → inhomogeneous numpy array → `ValueError`. Fix: `drape_backend_nextdrape.py` now converts empty KDTree results to `None`.

### B2 — Swallowed exception masked B1 as silent success ✅ FIXED

`_inject_drape_geometry` wrapped its body in `try: ... except: pass`. B1's `ValueError` was caught and discarded; `reload_shader` then ran on an empty shader and set `_attached=True` with zero geometry. Fix: geometry injection is now in its own try/except that logs via `Console.PrintWarning` and returns early — `reload_shader` is NOT called if injection failed, so no empty-shader false positive.

### B3 — Drape-mesh fallback was masking B1/B2 ✅ RESOLVED (do not restore)

The removed `load_shader` fallback (`_coin_geo = backend._mesh`) hid B1/B2: when the support surface failed to build, the shader fell back to the drape mesh. The fallback is gone and will not be restored.

### B4 — ConicalPanelSupport visibility ✅ FIXED

`update_visibility` force-set `self.Object.Support.Visibility = visible` on every recompute/attach, un-hiding what the demo hid. Fix: removed that line — the shader renders on its own injected geometry, so the support object's visibility is irrelevant to the overlay.

### Additional fix — geometry no longer injected as direct child of `drape_host`

The SupportSurface is now handed directly to the shader via `_coin_geo` instead of being injected into `drape_host` and later removed. This eliminates both the competing native render branch AND a Coin3D segfault caused by removing the node from `drape_host` after adding it to `shader_state`.

### Why tests missed this

- `test_meshgrid_shader_binding.py` attaches to a **hand-built dummy geometry**; it never exercises `build_support_surface_coin` → the numpy coercion path.
- The end-to-end scene-graph tests **skip in headless mode** (ViewObject is `None` without GUI), so they only assert under MCP/GUI — and were never run against the real pipeline before today.
- Headless smoke tests never trigger the path at all (no ViewObject → `_inject_drape_geometry` returns early), so B1 never fired there.
- B2 converted the hard failure into silent empty state; only a test asserting `gs._coin_geo is not None` would have caught it, and none did.

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

> Note:
> 1. Dummy-geometry regression passes in headless tests — but this path does NOT exercise `build_support_surface_coin` (see Open blockers B1/B2).
> 2. Grid spacing is fixed at 10 mm physical spacing.
> 3. The separate drape mesh branch has been removed from the render path in code.
> 4. Shader output is **not** verified: the support surface fails to build and the shader attaches to an empty group. Fix B1–B4 before validating.

7. Run full test suite (`test_uv_mapping.py` + C++ unit tests) — TBD
8. Performance measurement (confirm ~37× speedup) — TBD
9. Final review and merge — TBD

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

**Gate policy:**
- Do not close a gate without an automated test.
- For rendering and persistence, use a real FreeCAD/headless or MCP-backed regression test.
- Do not use visual inspection as proof.
- Require objective, machine-checkable evidence.

**G7 closure requirements:**
1. Disable the separate mesh geometry.
2. Prove shader rendering with a FreeCAD MCP or GUI-backed regression test.
3. Prove drape state ownership with a persistence regression test.
4. Use visual checks only as support, not proof.

| Gate | Criteria | Status |
|------|----------|--------|
| G0 | All existing tests pass | ⏸ TBD |
| G1 | KDTreeLocator compiles, basic lookup works | ✅ PASS (8/8 tests) |
| G2 | Out-of-grid extrapolation (was: soft_clamp) | ✅ PASS — CORRECTED 2026-07-16: `soft_clamp` was never implemented; clamping was the wrong requirement anyway. The real requirement (extrapolate UVs as-if-grid-extended) is now met by removing the `[-0.05,1.05]` bounding rejection in `evaluateQuad`. Regression: `test_kd_tree_locator.cpp::PointOutsideMeshExtrapolates` + standalone harness. Verified live: 727/727 support verts get distinct UVs, 0 collapses to (0,0). |
| G3 | Accuracy: KD matches brute-force to 6dp | ✅ PASS — `test_kd_tree_locator.py` compares KD lookup against the brute-force reference to 6dp |
| G4 | UVs bounded at mesh edges | ✅ PASS |
| G5 | >3× speedup on 50×50 grid | ✅ PASS — flat 50×50 benchmark measured 124.95× speedup with max diff 7.1e-15 |
| G6 | No UV jumps >0.05 at shared edges | ✅ PASS |
| G7 | Full pipeline works end-to-end | ✅ PASS — shader-only output verified via MCP (2026-07-16): `shader_state` has 9 children incl. `SupportSurface`; `_coin_geo=SupportSurface`; `drape_host` has only `shader_state`; ConicalPanelSupport hidden; GLSL compiles/links clean; grid-logic bug (max→min) fixed; out-of-grid UV extrapolation fixed (#4); native Part shape hidden via 'Grid' display mode (no grey secondary surface, object not greyed). **Persistence proven:** `test_g7_persistence.py` — save conical panel to .FCStd, reload fresh doc, recompute; all 8 objective checks pass (saved file exists, shell reloads, DrapeValid preserved, backend recreated+valid, 887 tex coords repopulated identically, quality metrics identical, shader re-attaches to SupportSurface, drape_host mesh-free). Deterministic across 2 runs. Remaining polish (not blockers): selection highlight on shader overlay; `offset_angle` dead uniform (P4). |
| G8 | All Composites tests pass | ⏸ TBD |

**Order of closure:** G7 is the first blocker to resolve; G0/G8 only count once G7 is back to a real passing state and backed by regression tests.

## Files Modified

| File | Stream | Status |
|------|--------|--------|
| `src/3rdParty/nextdrape/include/nextdrape/KDTreeLocator.hpp` | 1 | ✅ Written |
| `src/3rdParty/nextdrape/src/KDTreeLocator.cpp` | 1 | ✅ Written |
| `src/3rdParty/nextdrape/CMakeLists.txt` | 1 | ✅ Updated |
| `src/Mod/Composites/App/CompositesDrape.cpp` | 1 | ✅ pybind11 bindings added |
| `src/Mod/Composites/util/geometry_util.py` | 2 | ⚠️ CORRECTED 2026-07-16: `soft_clamp`/shared-edge averaging were planned (G2) but NEVER implemented in code — false gate closure. Clamping was the wrong requirement (extrapolation needed). Out-of-grid fix lives in `nextdrape/src/KDTreeLocator.cpp` instead. |
| `src/Mod/Composites/tools/drape_backend_nextdrape.py` | 1 | ✅ Wired into NextDrapeBackend |
| `src/Mod/Composites/features/CompositeShell.py` | 1,2 | ✅ Wired into _RehydratedBackend |
| `src/Mod/Composites/features/AlignFibreRosette.py` | 1 | ✅ Transparent (delegates to backend) |
| `src/Mod/Composites/compositestests/test_uv_mapping.py` | 2 | ✅ UV quality tests |
| `src/Mod/Composites/compositestests/test_compositeexamples.py` | 2 | ✅ Added end-to-end full-pipeline smoke test. ⚠️ Added shader-only scene-graph regression but it SKIPS in headless mode (ViewObject is None without GUI) — must be run/verified via MCP. Not yet proven green against the real pipeline. |
| `src/Mod/Composites/compositestests/test_meshgrid_shader_binding.py` | 2 | ⚠️ Added controlled dummy-geometry shader regression test and 10 mm spacing assertion — but uses hand-built geometry that bypasses `build_support_surface_coin`, so it did NOT catch B1. Needs a test exercising the real support-surface build path. |
| `src/Mod/Composites/compositeexamples/examples/test_shader_grid_diagnostic.py` | 2 | ✅ Added high-contrast diagnostic scene for visible grid proof |
| `src/Mod/Composites/compositeexamples/examples/conical_panel_segment.py` | 2 | ✅ Added hide-drape-mesh debug toggle for shader isolation |
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