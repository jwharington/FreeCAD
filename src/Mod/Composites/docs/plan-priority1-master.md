# Priority 1 — Performance & UV Quality (Delivered)

**Date:** 2026-07-15 → 2026-07-16
**Status:** Complete. All gates G0–G8 PASS. 22/22 Composites test modules green; nextdrape C++ tests 7/7 green.

## Objective

A k-d-tree-accelerated UV point lookup for the draped-mesh shader overlay, with the drape mesh removed from the render path, the grid shader rendering directly on the support surface, and full end-to-end + persistence proven with objective (machine-checkable) evidence.

## What was delivered

### nextdrape: `DrapeEngine::LookupUV` (clean frontend)
- `DrapeEngine::Compute` (const) builds a `std::unique_ptr<KDTreeLocator>` + caches `std::vector<Vec2>` tex_coords from the result (`result.nodes` + `result.texturePlan.{quads,flatNodes}`), reset at the start of every `Compute`, built only on the success path.
- `DrapeEngine::LookupUV(point) -> std::optional<Vec2>` queries the cached locator. The algorithm choice (k-d tree vs brute force) and the flat-data round-trip are internal to nextdrape.
- `KDTreeLocator` kept as a public header for nextdrape's own C++ unit tests (synthetic meshes with no OCC shape can't go through `Compute`).

### FreeCAD: decoupled from `KDTreeLocator`
- `CompositesDrape.cpp`: `py::class_<DrapeEngine>` with `compute()` + `lookup_uv()`. `solve()` is a thin wrapper over a temporary engine (backward compat). **The `KDTreeLocator` pybind binding was removed entirely** — the only public UV-lookup API is `DrapeEngine.lookup_uv`.
- `drape_backend_nextdrape.py`: `NextDrapeBackend` holds a persistent `self._engine`; `_run_solve` calls `engine.compute()`; `get_tex_coord_at_point` is a one-liner via `engine.lookup_uv`. Removed: the `_quad_locator` cache, `_ensure_kdtree`/`_import_kdtree`, the brute-force fallback call, and the `min_quads_for_kdtree` threshold check.

### Shader overlay (on the support surface)
- The drape-mesh branch is removed from the render path. The shader attaches to the **SupportSurface** geometry directly (`_coin_geo`), never injected as a competing child of `drape_host`.
- The native Part shape is hidden via the **'Grid' display mode**: an empty `GridEmptyRoot` branch registered via `addDisplayMode`; when the shader is active, `DisplayMode='Grid'` points `ModeSwitch.whichChild` at it so the native `SoBrepFaceSet` renders nothing. Restored to 'Shaded' when the shader is off.
- GLSL compiles/links clean (0 warnings). Grid logic: `min(gridX, gridY)` (was `max`, which only hit 0 at X∩Y intersections → black dots). Anti-moiré: non-zero feather + Nyquist fade. Out-of-grid UV extrapolation works (bilinear basis extrapolates — the `[-0.05,1.05]` bounding rejection in `evaluateQuad` was removed).

### Shader features
- **Grid rotation** (`offset_angle` uniform, declared+used in GLSL): the grid aligns with the selected layer's fibre orientation. Fixes P4 (was a dead uniform). Also fixed `get_offset_angle` (int/str key mismatch silently returned 0, which clobbered the angle on reload) and `onChanged("DisplayLayer")` (now calls `set_offset_angle` without a full reload when attached).
- **Per-axis grid spacing**: `GridSpacingX` / `GridSpacingY` `App::PropertyFloatConstraint` VP properties (default X=20mm, Y=10mm, i.e. 2:1 warp:weft). Replaced the single `grid_spacing_mm` uniform.
- **Selection highlight on the overlay**: two `SoShaderParameter` uniforms (`sel_color` vec3 + `sel_state` 1f) driven by the VP's `SelectionObserver` callbacks. The tint colors are read at runtime from FreeCAD's View preferences (`HighlightColor` for hover, `SelectionColor` for select) so the overlay matches the native highlight on other objects.

### Rosette symbol
- Lifted off the surface by ±0.5mm along local Z (clears z-fighting / occlusion by the shader's transparent pass).
- Drawn on **both sides** of the surface (mirrored about the LCS XY plane) so it's visible from either viewing direction.

### Reload / persistence
- **Reload duplicate-surface (flashing) fixed**: on reload, `attach()` ran `update_visibility` before the shader attached (`has_shader=False` → `DisplayMode='Shaded'`); `_inject_drape_geometry` now calls `update_visibility` after `reload_shader()` so `DisplayMode` flips to 'Grid' once the shader attaches.
- **Dead persistence path removed**: `_RehydratedBackend` (~259 lines) + `_rehydrate` (~44 lines) were dead (never called; the JSON properties they referenced were declared nowhere). Persistence works via re-solve-on-restore (`execute()` → C++ backend).
- **Laminate VP proxy corruption fixed** (`Laminate.py`): `ViewProviderLaminate(vobj)` (was passing the FeatureObject, corrupting the App proxy).

## Resolved blockers

- **B1** — `get_tex_coord_at_point` returned `[]` instead of `None` on a KDTree miss → inhomogeneous numpy array → `ValueError`. Fixed: empty results converted to `None`.
- **B2** — `_inject_drape_geometry` had `try: ... except: pass`, masking B1 as silent empty-shader success. Fixed: geometry injection has its own try/except that logs and returns early; `reload_shader` is not called on failure.
- **B3** — The drape-mesh fallback (`_coin_geo = backend._mesh`) hid B1/B2. Removed; do not restore.
- **B4** — `update_visibility` force-set `Support.Visibility = visible`, un-hiding what the demo hid. Removed.

## Objective evidence

- **Parity (zero behaviour change from the decoupling):** 200 node lookups — `engine.lookup_uv` vs the old direct `KDTreeLocator.lookup`: 0 mismatches, max diff `0.00e+00`. Same `KDTreeLocator::lookup` under the hood.
- **Selection tint reaches GPU** (opaque-pass readback, `transparency=0`/`darken=0`): NEUTRAL grey, GREEN=4238px (select), BLUE=4239px (hover), RED=4238px (direct), NEUTRAL again grey.
- **Grid rotation reaches GPU**: 0°vs45° = 1.3% pixel diff; 0°vs90° = 0% (correct — square grid invariant under 90°); noise floor 0°vs0° = 0%.
- **X/Y spacing independent**: swapping `(2,200)` vs `(200,2)` = 4.40% pixel diff (would be 0% if one uniform were dead).
- **Rosette visible from both sides**: offscreen render captures red/green axis pixels from the back-face view (was 0 from that side).
- **Persistence**: `test_g7_persistence.py` — save conical panel to .FCStd, reload, recompute; all 8 checks pass. 887 tex_coords identical before save → after reload.

## Gates

| Gate | Criteria | Status |
|------|----------|--------|
| G0 | All existing tests pass | ✅ 22 Composites modules, 0 failures (`run-tests.sh`) |
| G1 | KDTreeLocator compiles, basic lookup | ✅ 7/7 nextdrape C++ tests |
| G2 | Out-of-grid extrapolation | ✅ `evaluateQuad` bounding rejection removed; bilinear basis extrapolates. 727/727 support verts get distinct UVs |
| G3 | KD matches brute-force | ✅ `KdTreeMatchesBruteForce` (nextdrape C++): `lookup` == `bruteForceLookup` to 1e-9 on a 12×12 warped grid |
| G4 | UVs bounded at mesh edges | ✅ |
| G5 | >3× speedup on 50×50 grid | ✅ 124.95× (max diff 7.1e-15). *Note: measured on the direct-KDTree path; parity with `engine.lookup_uv` proven but not re-benchmarked.* |
| G6 | No UV jumps >0.05 at shared edges | ✅ |
| G7 | Full pipeline end-to-end | ✅ Shader-only output + persistence proven via MCP |
| G8 | All Composites tests pass | ✅ 22 modules, 0 failures |

## Open items

- **Performance re-measurement** (Phase C item 8): re-benchmark through `engine.lookup_uv` to confirm the persistent-engine + cached-locator path adds no overhead. G5's 124.95× was measured on the direct-KDTree path; parity proven, not re-timed.
- **Final review and merge** — your call.

## Key file locations

- nextdrape frontend: `src/3rdParty/nextdrape/include/nextdrape/DrapeEngine.hpp`, `src/3rdParty/nextdrape/src/DrapeEngine.cpp`
- KDTreeLocator: `src/3rdParty/nextdrape/{include/nextdrape/KDTreeLocator.hpp,src/KDTreeLocator.cpp}`
- pybind: `src/Mod/Composites/App/CompositesDrape.cpp`
- Python backend: `src/Mod/Composites/tools/drape_backend_nextdrape.py`
- Shader: `src/Mod/Composites/shaders/{Grid_fragment_shader.glsl,Grid_vertex_shader.glsl,MeshGridShader.py}`
- ViewProviders: `src/Mod/Composites/features/{VPCompositeShell.py,CompositeShell.py,RosetteSymbol.py,Laminate.py}`
- Decoupling design + evidence: `src/3rdParty/nextdrape/docs/uv-lookup-frontend-decoupling.md`
- Test runner: `~/.pi/agent/skills/freecad-dev/scripts/run-tests.sh` (runs all 22 modules, summary, no early-abort)
