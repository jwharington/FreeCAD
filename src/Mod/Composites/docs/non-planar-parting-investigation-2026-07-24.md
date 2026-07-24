# Non-Planar Parting Investigation

**Date:** 2026-07-24 (rigorous rewrite)
**Status (2026-07-25):** The false-confidence seam documented below is now **closed** — withdrawal clearance is wired into `analyze_source_shape` and is the authoritative verdict (WC=Fail escalates to Fail). The accessibility heuristic referenced in §"The false-confidence seam" has been removed; the analysis gate is now draft-only and informational. This doc is retained as the record of *why* planar parting was proven insufficient and *why* the seam existed. The recommended next model has since been superseded by the marching-equator C++ spec — see `non-planar-parting-requirements.md`.
**Scope:** Determine whether the planar parting model is sufficient for the twisted `blade`/`loft` mould geometry, identify why the solver previously looked acceptable despite that, and recommend the next parting-surface model. Implementation of any non-planar model is explicitly blocked until the model is selected and approved.

## Conclusion (up front)

1. **Planar parting is insufficient for `blade` and `loft`.** The authoritative necessary test — withdrawal clearance — fails for *every* axis-aligned planar direction on both shapes. This is proven by a committed negative regression, not assumed.
2. **The solver previously looked acceptable because the authoritative test was never wired into the analysis verdict.** `_withdrawal_clearance_validity_check` is defined in `mould_analysis.py` but is **not called by `analyze_source_shape`**. It is exercised only by the inspection CLI and direct tests. That is the missing test seam that allowed false confidence — the analysis reported `Warning` while the mould was physically un-releasable.
3. **The recommended next model is the existing `make_part_plane` / `make_part_plane3` parting-surface builders in `tools/part_plane.py`**, wired into `analyze_source_shape` behind the withdrawal-clearance gate. These already produce non-planar surfaces (a lofted parting surface from sampled silhouette points, and a reflect-line/silhouette surface). They are not new code to write; they are an existing path to evaluate and integrate.
4. **This recommendation is conditional on validation.** The non-planar builders must be proven (via withdrawal clearance) to actually release `blade`/`loft` before adoption. That validation requires surface-based mould-half splitting, which the current `make_mould_halves` (planar normal+offset only) does not support — see Open Questions.

## Evidence: planar parting fails on twisted geometry

Measured via the committed `inspect_mould_results.py` inspector (`--direction {x,y,z}`), which runs the full `propose_parting_surface` → `make_mould_halves` → `_withdrawal_clearance_validity_check` pipeline for each axis. Withdrawal clearance is the authoritative necessary test: each mould half must translate along the draw direction without intersecting the source.

| shape | draw dir | analysis `status` | `validation_status` | `analysis_gate_status` | **withdrawal_clearance** |
|---|---|---|---|---|---|
| blade | +X | Warning | Warning | Warning | **Fail** |
| blade | +Y | Warning | Warning | Warning | **Fail** |
| blade | +Z | Warning | Warning | Warning | **Fail** |
| loft  | +X | Warning | Warning | Warning | **Fail** |
| loft  | +Y | Warning | Warning | Warning | **Fail** |
| loft  | +Z | Fail | Fail | Fail | **Fail** |

Two facts stand out:

- **No planar direction releases either shape.** Even the "best" direction leaves the mould halves colliding with the source on withdrawal. Planar parting is therefore insufficient for these geometries — a non-planar parting surface (or a fundamentally different parting model) is required.
- **The analysis verdict (at investigation time) disagreed with the authoritative test.** For 5 of 6 cases the analysis said `Warning` while withdrawal clearance said `Fail`. This was the symptom of the false-confidence seam documented below — now closed: withdrawal clearance is wired into the verdict, so blade/loft now truthfully report `Fail`.

## The false-confidence seam

`grep` confirms `_withdrawal_clearance_validity_check` is **defined** in `mould_analysis.py` (line ~2829) but **never called** inside `analyze_source_shape`. The function's only callers are:

- `compositestests/inspect_mould_results.py` (the inspection CLI)
- `compositestests/test_mould_geometry.py` (direct unit tests of the helper)

At investigation time, the analysis pipeline that produced `status` / `validation_status` answered a *weaker* question — "do the draft-face screening and accessibility heuristics look plausible?" — not "can the mould actually withdraw?" A shape could pass the heuristics (Warning, not Fail) while being physically un-releasable. That was the root cause of the historical false confidence: the necessary validity test existed but was not in the decision path.

**This seam is now closed.** Withdrawal clearance is called per attempt inside `_evaluate_split_strategy_attempt`, its status is passed to `validate_mould_result`, and WC=Fail is a hard validation failure. The accessibility heuristic has been removed; the draft-face gate is informational only. The evidence table above reflects the state at investigation time (analysis=Warning, WC=Fail); under the current code the analysis status for blade/loft is `Fail` (WC-driven).

## Negative regression (committed)

`TestPlanarPartingInsufficiency` in `test_mould_geometry.py` pins the blocking negative result so the planar model can never silently re-accept twisted geometry:

- `test_blade_fails_withdrawal_clearance_under_every_planar_direction` — blade WC = Fail for +X, +Y, +Z.
- `test_loft_fails_withdrawal_clearance_under_every_planar_direction` — loft WC = Fail for +X, +Y, +Z.
- `test_twisted_shapes_are_never_reported_ready_under_planar_analysis` — neither shape is ever `Ready`/`Pass` under any planar direction (pins that the false-confidence path stays blocked).

These are the "Required negative regression" deliverable from the accuracy plan.

## Candidate models

The prior draft of this doc recommended building a "smooth parting surface from a sampled PartLine." On reading the code, **those builders already exist** in `src/Mod/Composites/tools/part_plane.py` — the work is integration and validation, not new construction.

| Model | Location | Construction | Testability | Fit for twisted geometry | Status |
|---|---|---|---|---|---|
| Planar midpoint face | `propose_parting_surface` (mould_analysis.py) | Rectangular face at bbox midpoint on the draw axis | Excellent (deterministic) | **Proven insufficient** (this investigation) | Current; negative-regression pinned |
| Lofted parting surface from sampled silhouette | `make_part_plane` / `part_line_points` (part_plane.py) | Slices shape at N Z-stations, finds silhouette points on each side, lofts a surface through the two boundary curves | Good (deterministic; WC applies directly) | Plausible — preserves camber via multi-station loft | **Best primary candidate** (exists, needs validation) |
| Reflect-line / silhouette surface | `make_part_plane3` (part_plane.py) | OCC `shape.reflectLines` (OutLine + Sharp), splits shape along those edges, keeps upward-normal faces | Medium (OCC silhouette can be fragile on freeforms) | Potentially good; Z-specific | Support / alternative |
| TechDraw projection offset | `make_part_plane2` (part_plane.py) | Outer wire of a TechDraw projection, offset inward | Good | **Still planar** — not a non-planar solution | Rejected for this purpose |

### Why the lofted-silhouette surface is the primary candidate

- It produces a single continuous non-planar surface that follows the shape's silhouette across multiple stations, so it can preserve camber that a single plane flattens.
- It already exists and is named consistently with the repo's terminology (`part_line_points` → `make_parting_surface` aliases).
- It is directly testable with the same withdrawal-clearance gate — no new validity framework needed.
- The prior draft's "bowl problem" caveat (a naive two-section linear loft flattens camber) is addressed by the existing N-station sampling (20 Z-stations by default), though the sampling density may need tuning for highly cambered shapes.

### Why the reflect-line path is support, not primary

`make_part_plane3` depends on OCC's `reflectLines` with `EdgeType="OutLine"`/`"Sharp"`, which is known to be fragile on freeform geometry (silent empty results, missing edges). It is better used as a diagnostic/seed generator than as the authoritative parting surface. If the lofted-silhouette path proves insufficient, the reflect-line path is the fallback to investigate, not the default.

## What this investigation does NOT yet prove

Honest limits of the current evidence:

1. **The non-planar builders have not been validated by withdrawal clearance.** Doing so requires splitting mould halves along a *surface* (not a plane), which `make_mould_halves` does not currently support — it takes a planar `surface_normal` + `surface_offset`. Validating the non-planar model therefore requires either extending `make_mould_halves` to accept a surface, or a separate surface-split helper. This is implementation work that is blocked pending model selection.
2. **The non-planar builders are Z-axis-specific.** `part_plane`, `make_part_plane`, and `make_part_plane3` all hardcode `Vector(0, 0, 1)`. With the draw direction now user-specified and authoritative, these builders must be generalized to an arbitrary draw direction before integration. This is straightforward (the slicing/projection direction is a parameter) but is real work.
3. **Sampling density for highly cambered shapes is an open question.** The default 20 stations may be too few or too many; the WC gate will be the arbiter.

## Recommendation

1. **Adopt the lofted-silhouette parting surface (`make_part_plane`) as the primary non-planar model**, generalised to the user-specified draw direction, and wired into `analyze_source_shape` behind the withdrawal-clearance gate.
2. **Make withdrawal clearance part of the analysis verdict**, not just an inspection-only check. Until this is done, the analysis will continue to report `Warning` for shapes that are physically un-releasable — the false-confidence seam stays open. This is the single highest-leverage fix, independent of which parting model is chosen.
3. **Keep `make_part_plane3` (reflect-line) as a diagnostic/fallback**, not the primary path.
4. **Implementation is blocked** until this recommendation is approved. The first implementation step should be a minimal validation: extend `make_mould_halves` (or add a helper) to split along the lofted-silhouette surface, then run withdrawal clearance on blade/loft. If it passes, proceed with integration; if not, fall back to the reflect-line path or reconsider the model.

## Open questions

- Should the non-planar parting surface be exposed in the UI (a new FP property) or stay internal to `analyze_source_shape`?
- How should `make_mould_halves` be extended to accept a surface rather than a plane? (Generalised split along an arbitrary surface, or a dedicated surface-split helper?)
- What sampling density (number of stations) does the lofted-silhouette surface need for highly cambered shapes, and should it adapt to curvature?
- Should the reflect-line helper be refactored into a reusable diagnostic extractor, or left as-is until needed?
- Should withdrawal clearance be added as a hard validation check inside `analyze_source_shape` *before* the non-planar model lands, so the false-confidence seam is closed regardless of parting-model progress?

## Files reviewed

- `src/Mod/Composites/tools/mould_analysis.py` — `analyze_source_shape`, `propose_parting_surface`, `_withdrawal_clearance_validity_check` (defined, not called from analysis)
- `src/Mod/Composites/tools/part_plane.py` — `part_plane`, `make_part_plane`, `make_part_plane2`, `make_part_plane3` (the existing non-planar builders)
- `src/Mod/Composites/features/MouldAnalysis.py` — the FP that consumes the analysis result
- `src/Mod/Composites/features/PartPlane.py` — the parting-surface FP
- `src/Mod/Composites/compositestests/inspect_mould_results.py` — the inspector used to gather the evidence table
- `src/Mod/Composites/compositestests/test_mould_geometry.py` — the committed negative regression
- `src/Mod/Composites/docs/mould-analysis-accuracy-plan.md`
