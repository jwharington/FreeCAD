# Non-Planar Parting — Implementation Plan

**Date:** 2026-07-24 (updated 2026-07-25)
**Status:** Phase 0 + FreeCAD integration DONE. Phase 1 (nextdrape C++ solver) IN PROGRESS — the degenerate path (box, cylinder) and the single-face general march (sphere) run end-to-end to `Ready`; multi-face handoff + the genuinely non-planar split remain. Companion to `non-planar-parting-requirements.md`.
**Scope:** Replace the planar midpoint parting for twisted/cambered geometry with the marching-equator parting solver, behind the withdrawal-clearance gate already wired into `analyze_source_shape`.

## Algorithm summary (the agreed construction)

For full detail see `non-planar-parting-requirements.md`. Summarised here so the plan is self-contained:

1. **Setup** — fit a bounding box in a local coordinate system where `z` is the draw direction `D`.
2. **Starting point** — pick an arbitrary point on the body that touches the bounding box. If its local surface is perpendicular to `D` (normal ∥ `D`), scan up/down in `z` to find the highest and lowest `z` on the body; the `z`-midpoint is the starting point.
3. **Loop around the whole surface until back to start** — march clockwise (viewed from the bbox center) along the equator (`normal·D = 0`), integrating locally in each surface's `(u, v)` space, transitioning across surface boundaries (compound — different `(u, v)` frames per face). At each point shoot a ray outward along the **surface normal** to intersect the rectangular mould boundary; retain the ray (the skirt segment). **Whenever** a tangent-surface degenerate range is encountered (normal ⊥ `D` over a `z`-range), scan for the `z`-midpoint as in step 2 — this is a recurring rule, not a one-off. Fork / degenerate path → error out (invalid mould).
4. **Output** — (a) the part line as a **chain of splines, one per surface, in each surface's local `(u, v)` parametric space**; (b) the base geometry **cut into upper and lower shells exactly along this line** (OCCT parametric face-split); plus the retained surface-normal rays forming the skirt, and the rectangular block cap closing each half into a valid solid.

`reflectLines` / `Contap_Contour` are **not** used (reflectLines is unreliable on freeforms — tried before). The part line is traced by marching.

## Axis system (pinned)

- **Local frame:** `gp_Ax3` with **Z = draw direction `D`**, **origin at the bbox center**. Built via `gp_Ax3::createFromNormal(D)` (OCCT picks an X reference; if global X is parallel to `D` it falls back to global Y — documented as the deterministic pick, not user-controllable).
- **Transform-in:** the source shape is transformed into this local frame via `BRepBuilderAPI_Transform` + `gp_Trsf` (the `gp_Ax3` → identity transform). All marching, bbox, and `z`-midpoint logic runs in local coordinates. Results are mapped back to the original frame via the inverse transform.
- **Clockwise sense:** the equator march proceeds clockwise **viewed from −Z** (i.e. looking back along `D`, from above the upper `+D` mould half down toward the lower). Both senses close the loop; this one is fixed for determinism.
- **Bbox in the local frame:** an axis-aligned bbox of the *transformed* shape (`BRepBndLib::boundingBox`, not the OBB) — this is what "touches the bounding box" and the `z_max`/`z_min` for the midpoint rule are measured against.

## OCCT 8 API cross-reference (verified via context7 / OCCTSwift)

Verified against OCCT 8.0.0p1 (this project's version). Items marked *(verify)* are the genuinely uncertain ones for the C++ author to confirm on freeform geometry.

| Step | OCCT API | Notes |
|---|---|---|
| Local frame | `gp_Ax3` (`createFromNormal(D)`) | Z = D, origin at bbox center |
| Transform shape into frame | `gp_Trsf` + `BRepBuilderAPI_Transform` | map results back via inverse |
| Axis-aligned bbox (local) | `BRepBndLib::boundingBox` (`Add`) | NOT the OBB — AABB of the transformed shape |
| Surface normal at (u,v) | `BRepAdaptor_Surface` + `D1(u,v)` | for the `normal·D=0` march constraint |
| Project 3D pt → UV | `GeomAPI_ProjectPointOnSurf` | for the start point and edge handoffs |
| Ray vs shape (skirt ray) | `intersectLine(origin, direction)` → `BRepIntCurveSurface`-style | returns point + parameter + **face UV** — gives the hit face for the part-line chain |
| Project 3D curve → UV pcurve | `GeomProjLib::Curve2d` (`projectCurve`) | the part-line `(u,v)` spline from the marched 3D curve; returns a `Geom2d_BSplineCurve` |
| Fit 2D BSpline through UV points | `Geom2dAPI_PointsToBSpline` *(verify name on OCCT 8)* | fallback if `GeomProjLib` isn't suitable |
| Split face along UV wire | `BRepFeat_SplitShape::SplitByWire(wire, face)` | the exact parametric shell split; UV spline is the native input |
| Side selection after split | `BRepBuilderAPI_MakeFace(surface, wire, inside:)` | keep the `+D`/`−D` sub-face |
| Skirt surface from rays | `BRepOffsetAPI_MakePipe` / loft through ray-ends *(verify best variant)* | capped by rectangular block faces |
| Surface-to-surface handoff | `BRep_Tool::Parameters(edge, face)` on both faces | shared edge → adjacent face's `(u,v)` frame |

`reflectLines` / `Contap_Contour` are deliberately **not** in this table.

## Phasing

- **Phase 0 — Python interface + stub (no nextdrape).** ✅ DONE (`7e7e9b5e6a`). FP properties (`PartingModel`, `PartingLandWidth`, `PartingStockMargin`, `PartingStockFootprint`), `analyze_source_shape` extension, `_propose_non_planar_parting` stub, 5 `TestNonPlanarPartingInterface` tests.
- **Phase 1 — nextdrape C++ solver.** ⏳ IN PROGRESS. Skeleton + GTest harness landed (`c42ef43`); stages 1-3 (local frame, start point, degenerate detection) coded + validated (`4c07406`); degenerate path (box, cylinder) runs end-to-end to Ready (`09ee8e1`, `e5c8e7f`); general grid-based march traces the sphere equator and reaches Ready (`81f93d2`, `517a485`); cone limitation pinned (`d3c000d`). REMAINING: multi-face handoff (cone, blade, loft), genuinely non-planar split (BRepFeat), ruled skirt (BRepFill).
- **Phase 2 — wire the real binding + flip the gate.** ⏳ PARTIAL. The binding (`Composites_parting.so`) is built + installed and `_propose_non_planar_parting` calls it (`0f2a789fcf`); box under `NonPlanar` reaches `ready` end-to-end through Python. The default flip + blade/loft WC=Pass acceptance tests remain blocked on Phase 1's freeform march.

---

## Phase 0 — Python interface + stub (start now, no nextdrape)

### 0.1 MouldAnalysis FP properties

Add to `features/MouldAnalysis.py` (`MouldAnalysisFP.__init__`), in the `MouldAnalysis` property group:

- `PartingModel` — `App::PropertyEnumeration`, values `("Planar", "NonPlanar")`, default `"Planar"`. The user selects the parting model. Planar is the current behaviour (kept as the safe default until the C++ solver is validated).
- `PartingLandWidth` — `App::PropertyFloat`, default `25.0` (mm), group `MouldAnalysis`. The minimum skirt projection width; passed to the non-planar solver.
- `PartingStockMargin` — `App::PropertyFloat`, default `0.1` (fraction of bbox), group `MouldAnalysis`. Auto stock-block margin.
- `PartingStockFootprint` — `App::PropertyVector`, default `Vector(0, 0, 0)` (mm), group `MouldAnalysis`. `(dx, dy, 0)` explicit override of the rectangular block footprint in the local `⊥D` plane; `(0,0,0)` means auto-derive from bbox + margin. Documents the "auto or user" decision from requirements.

`onChanged` triggers recompute on these (add to the existing `("Source", "PreferredDrawDirection")` tuple).

### 0.2 `analyze_source_shape` contract extension

In `tools/mould_analysis.py`, extend `analyze_source_shape` to accept the parting-model parameters and surface them in the result. **No behaviour change** when `PartingModel == "Planar"` (the current path). When `"NonPlanar"`, call the new `_propose_non_planar_parting` (the stub) instead of `propose_parting_surface` + `make_mould_halves`.

New result-dict keys (always present; `None`/empty when planar):

- `parting_model` — `"Planar"` or `"NonPlanar"`.
- `parting_line` — the part-line chain (per-surface `(u, v)` splines) when non-planar; `None` when planar or not yet implemented.
- `parting_skirt_rays` — the retained surface-normal rays when non-planar; `None`/empty otherwise.
- `non_planar_status` — `"not_implemented"` (stub), `"ready"` (post-Phase-2), or an error string (`"fork_degenerate"`, etc.).
- `non_planar_summary` — human-readable.

Existing keys (`parting_surface_shape`, `parting_surface_normal`, `parting_surface_offset`, `mould_half_a_shape`, `mould_half_b_shape`, `withdrawal_clearance_status`, …) stay; for non-planar, `parting_surface_normal` mirrors `D` (the parting surface's nominal normal) and `parting_surface_offset` is the `z`-midpoint of the part line (for reporting only).

### 0.3 The stub

`_propose_non_planar_parting(shape, direction, land_width, stock_margin, stock_footprint)` in `mould_analysis.py`:

- Returns a result dict shaped exactly like the real solver's output: `status="NotImplemented"`, `summary`, `parting_line=None`, `upper_shell=None`, `lower_shell=None`, `skirt_rays=[]`, `error="non-planar parting not yet implemented (nextdrape C++ pending)"`.
- `_evaluate_split_strategy_attempt` checks the stub's `status`: if `"NotImplemented"`, it falls back to the planar path and sets `non_planar_status="not_implemented"` in the attempt (so the analysis still produces a verdict via the planar path + WC gate). This keeps the fast loop green and the interface observable during Phase 0/1.

### 0.4 Phase 0 tests (Python, committed)

In `compositestests/test_mould_geometry.py`:

- `TestNonPlanarPartingInterface`:
  - `test_planar_model_unchanged` — `PartingModel="Planar"` produces the same status/keys as today on box/blade/loft (regression guard).
  - `test_non_planar_properties_present` — the FP exposes `PartingModel`, `PartingLandWidth`, `PartingStockMargin`, `PartingStockFootprint` with the right defaults.
  - `test_non_planar_stub_falls_back_to_planar` — `PartingModel="NonPlanar"` on a box returns `non_planar_status="not_implemented"` and the planar verdict (Ready for box).
  - `test_non_planar_result_keys_present` — the new result-dict keys exist for both models.
- All Phase 0 tests are Python-only, run under the existing `run-tests.sh test_mould_geometry` / `test_mould` fast loop, and require no nextdrape build.

**Phase 0 exit:** interface committed, planar behaviour unchanged, stub observable, fast loop green. Unblocks parallel Phase 1.

---

## Phase 1 — nextdrape C++ solver (parallel)

Implemented in the `nextdrape` submodule, exposed via a pybind11 binding mirroring `CompositesDrape`. The Composites side is not blocked.

### 1.1 Binding interface (the contract Phase 2 consumes)

```cpp
// nextdrape binding entry point (pybind11), consumed by mould_analysis.py
struct NonPlanarPartingResult {
    // (a) the part line
    std::vector<std::pair<TopoDS_Face, std::vector<Handle(Geom2d_BSplineCurve)>>> part_line_uv;
    //    — one (face, uv-splines) entry per surface traversed, in chain order.
    TopoDS_Compound part_line_3d;  // the same line as 3D curves, for visualisation/diag.

    // (b) the split base geometry
    TopoDS_Shape upper_shell;
    TopoDS_Shape lower_shell;

    // the skirt + closed mould halves
    TopoDS_Shape skirt;            // swept surface from retained normal rays
    TopoDS_Solid  mould_half_upper; // upper_shell + skirt + block cap, cavity cut
    TopoDS_Solid  mould_half_lower;

    // diagnostics
    std::vector<std::pair<TopoDS_Face, double>> tangent_face_midpoints; // (face, chosen z-midpoint)
    std::string status;   // "ready" | "fork_degenerate" | "no_bbox_touch_point" | ...
    std::string summary;
};
NonPlanarPartingResult compute_non_planar_parting(
    const TopoDS_Shape& source,
    const gp_Dir& draw_direction,
    double land_width,
    double stock_margin,
    const gp_XY& stock_footprint_override  // (0,0) => auto
);
```

### 1.2 Concrete C++ steps

1. **Local frame.** Build `gp_Ax3` with Z = `D`, origin at bbox center (`createFromNormal(D)` — OCCT picks X deterministically). Build `gp_Trsf` from this `gp_Ax3` to identity; transform the source via `BRepBuilderAPI_Transform`. Keep the inverse transform to map results back.
2. **Bbox + start point.** `BRepBndLib::boundingBox` (AABB) of the transformed shape. Pick an arbitrary point where the body touches the bbox (a vertex on the `+x`/`−x`/`+y`/`−y` extreme face, or a sampled point — pick deterministically and document). Project to the surface via `GeomAPI_ProjectPointOnSurf` to get its `(u,v)`.
3. **Start `z`-midpoint rule.** At the start point, get the surface normal via `BRepAdaptor_Surface::D1(u,v)`. If `normal ∥ D` (within ε), scan up/down in `z` (ray intersections via `intersectLine` along ±Z, or face-domain march) to find `z_max`, `z_min`; set start `z = (z_max + z_min)/2`. Record in `tangent_face_midpoints`.
4. **Equator march.** From the start, march clockwise (viewed from −Z) along `normal·D = 0`:
   - Integrate in the current face's `(u,v)` using the constraint `N(u,v)·D = 0` (a 1D implicit curve in `(u,v)` — trace with a contour-following integrator).
   - At each marched point, shoot a ray along the **surface normal** via `intersectLine(point, normal)` to the rectangular block boundary; retain the ray segment in `skirt`. The hit's face-UV is the next part-line sample.
   - **Recurring midpoint rule:** if the march enters a region where `normal·D = 0` holds over a `z`-range, apply the `z`-midpoint scan from step 3 and record in `tangent_face_midpoints`.
   - **Surface transitions:** at face boundaries, hand off to the adjacent face's `(u,v)` via `BRep_Tool::Parameters(edge, face)` on both faces, continuing the equator constraint on the new face.
   - Terminate when the march returns to the start (within ε).
   - **Fork / degenerate path → return `status="fork_degenerate"`** (no recovery; invalid mould).
5. **Part line as `(u,v)` splines.** For each face traversed, build a `Geom2d_BSplineCurve` from the marched `(u,v)` points via `Geom2dAPI_PointsToBSpline` (or `GeomProjLib::Curve2d` projecting the 3D marched curve). Build `part_line_3d` as the 3D image for diagnostics.
6. **Exact shell split.** For each face, split along its `(u,v)` part-line spline using `BRepFeat_SplitShape::SplitByWire(wire, face)` — the `(u,v)` spline is exactly the form this routine consumes. Select the `+D`/`−D` sub-faces via `BRepBuilderAPI_MakeFace(surface, wire, inside:)` (or by centroid side). Assemble into `upper_shell` / `lower_shell`.
7. **Skirt + closure.** Build the skirt surface from the retained normal rays (`BRepOffsetAPI_MakePipe` or a loft through the ray-end curves). Cap with the rectangular block faces. Cut the source cavity. → `mould_half_upper` / `mould_half_lower` (valid solids).
8. **Map back** to the original frame via the inverse transform from step 1.

### 1.3 OCCT API notes (verified against OCCT 8 via context7)

See the **OCCT 8 API cross-reference** table above. The two genuinely uncertain items, flagged for the C++ author to confirm on freeform geometry:

- `Geom2dAPI_PointsToBSpline` exact name/behaviour on OCCT 8 for fitting a 2D BSpline through UV points (vs `GeomProjLib::Curve2d` projecting the 3D curve — likely preferred since it yields a native on-surface pcurve directly).
- `BRepFeat_SplitShape::SplitByWire` behaviour when the wire is a `Geom2d` pcurve vs a 3D wire (confirm the `(u,v)`-spline input path).

`reflectLines` / `Contap_Contour` are **not** used (unreliable on freeforms).

### 1.4 Phase 1 tests (C++ unit, in nextdrape)

Nextdrape-side unit tests on synthetic primitives (box, cylinder, cone, sphere) — these have known equators and validate the march + split before the freeform shapes:

- box along `+Z`: equator is the four vertical edges' midpoint loop; skirt is flat (planar part line); upper/lower shells are the box halves. WC=Pass.
- cylinder along `+Z`: equator is a circle at `z`-mid (tangent-surface degenerate — the side wall; midpoint rule must fire); shells are the two cylinder halves. WC=Pass.
- cone (apex up) along `+Z`: equator is a circle; one half un-releasable (the apex hooks) — WC=Fail on that half, expected.
- sphere along `+Z`: equator is the great circle; both halves releasable. WC=Pass.

These pin the solver's correctness on geometry with analytic answers before blade/loft.

**Plus one coverage-backfill test (asked for by the nextdrape agent):**

- `CrossFaceAdvance` handoff — the lattice fallback that was its only caller
  was removed in `okish2` (`b64c32e`), leaving `SurfaceProjection::
  CrossFaceAdvance` with zero coverage. Add a focused unit test: two adjacent
  faces of a known compound, advance across their shared edge, assert the
  target point + target face + chirality preservation. Lives in the
  nextdrape test suite; unblocks confident reuse in the equator march.

---

## Phase 2 — wire the real binding + flip the gate

### 2.1 Replace the stub

In `_propose_non_planar_parting` (Python), call the `Composites_drape` (or a new `Composites_parting`) binding's `compute_non_planar_parting`. Map the C++ result to the result-dict shape from Phase 0.2. On `status != "ready"`, propagate the error string into `non_planar_status` and fall back to planar (so the analysis still produces a verdict — the non-planar failure is a Warning, not a crash).

### 2.2 Flip the default

Once Phase 1 validates blade/loft (WC=Pass for ≥1 direction each), set `PartingModel` default to `"NonPlanar"` (or auto-select: non-planar when the planar WC fails). Keep `"Planar"` available as an explicit override.

### 2.3 Phase 2 tests (committed, Python via the binding)

- `TestNonPlanarPartingSolver`:
  - `test_box_non_planar_releases` — WC=Pass, both halves, `parting_model="NonPlanar"`.
  - `test_cylinder_non_planar_handles_tangent_side_wall` — the midpoint rule fires on the cylindrical side; `tangent_face_midpoints` non-empty; WC=Pass.
  - `test_blade_non_planar_releases_under_some_direction` — the load-bearing validation: WC=Pass for ≥1 direction (replaces the current `TestPlanarPartingInsufficiency` expectation for blade once non-planar is the model).
  - `test_loft_non_planar_releases_under_some_direction` — same for loft.
  - `test_fork_degenerate_errors_cleanly` — a crafted non-convex shape that forks returns `non_planar_status="fork_degenerate"` and the analysis degrades to planar (Warning), no crash.
- Update `TestPlanarPartingInsufficiency`: keep it, but it now asserts planar fails **only when `PartingModel="Planar"`** (the negative regression for the planar model specifically, not for the solver as a whole).

---

## Sequencing and dependencies

```
Phase 0 (Python interface + stub)  ── start now, no blocker
        │
        │  (parallel)
        ▼
Phase 1 (nextdrape C++ solver)      ── nextdrape track, own debugging
        │
        └──▶ Phase 2 (wire binding + flip gate + tests)
```

- Phase 0 and Phase 1 are independent; Phase 0 lands first and is mergeable on its own.
- Phase 2 depends on both. Its tests are the acceptance gate for the non-planar model.
- Throughout, the WC gate stays authoritative; the planar model + its negative regression remain as the fallback and the documented baseline.

## Progress (2026-07-25)

**Phase 0** ✅, **FreeCAD integration** ✅, **Phase 1 degenerate + single-face general march** ✅. Current state of the nextdrape C++ solver (`src/3rdParty/nextdrape/`):

- `include/nextdrape/NonPlanarPartingSolver.hpp` + `src/NonPlanarPartingSolver.cpp` — the 7-stage pipeline, registered in `nextdrape_core`.
- `tests/test_non_planar_parting.cpp` — 8 GTests (box, cylinder, sphere end-to-end Ready; cone limitation pinned; contract + status).
- `src/Mod/Composites/App/CompositesParting.cpp` — pybind11 binding (`Composites_parting`), registered as its own MODULE target in `src/Mod/Composites/CMakeLists.txt`.
- `tools/mould_analysis.py::_propose_non_planar_parting` — calls the binding, decodes BREP bytes to `Part.Shape`, maps to the Phase 0 contract. Box under `PartingModel="NonPlanar"` reaches `ready` end-to-end through Python.

**What works:** box, cylinder (degenerate path — plane-section at z_mid), sphere (general grid-based `N·D=0` zero-set trace + near-planar split). All run to `Ready` with split shells + closed cavity-cut mould halves, mapped back to the original frame.

**Next steps (Phase 1 remainder):**
1. Multi-face handoff — the cone's equator is on a face *boundary* (sign change between adjacent faces, not within one). Check shared edges (via `DiscoverSharedEdges`) for `N·D` sign changes; trace the equator along face boundaries; wire `SurfaceProjection::CrossFaceAdvance`. Unlocks cone + blade + loft.
2. Genuinely non-planar split — blade/loft part lines have real z-variation (the near-planar half-space cut rejects them). Build per-face `(u,v)` pcurves via `GeomProjLib::Curve2d`, split each face via `BRepFeat_SplitShape::SplitByWire`, select +D/-D sub-faces.
3. Ruled skirt — `BRepFill` ruled surface between the part line and the block boundary (verified OCCT 8).
4. `CrossFaceAdvance` coverage-backfill test (owed to the nextdrape agent — lands with step 1).

Build/run (nextdrape standalone, documented in the `nextdrape-cli-tests` skill):
```
cd src/3rdParty/nextdrape
pixi run cmake --build build/pixi-debug -j$(nproc)
./build/pixi-debug/nextdrape_tests --gtest_filter='NonPlanarParting.*'
```

## What I start on now (Phase 0)

Phase 0 is done. The current work is Phase 1's general-march remainder (above).
