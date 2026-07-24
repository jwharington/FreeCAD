# Handover — Mould-Analysis Slimming Pass (in progress, broken working tree)

**Date:** 2026-07-24
**State:** ⚠️ The working tree is **broken and uncommitted**. `src/Mod/Composites/tools/mould_analysis.py` has had ~1,400 lines deleted (3 function blocks) but the **call sites that reference the deleted functions have NOT been updated yet** — the module will not import. This handover tells you exactly how to finish (or revert).

---

## TL;DR for the next agent

You are mid-way through a **full rip** of the old heuristic stack from `mould_analysis.py`: the accessibility ray-sampler, the refinement layer, and the entire manufacturability/decomposition/multipart subsystem. The user confirmed "full rip, including FP properties" because they expect that subsystem is "junk code that wouldn't have worked."

**Two options:**
1. **Finish the rip** (recommended — most of the deletion is done): fix the ~16 dangling references listed below, rewrite the affected functions, strip the result-dict/FP fields, update tools + tests, build, run the 3 mould test modules, commit.
2. **Revert and restart smaller:** `git checkout -- src/Mod/Composites/tools/mould_analysis.py` returns to the last good commit (`bffe41dd3a`); then redo more carefully.

The last **good** commit is `bffe41dd3a` ("Remove dead slice helpers"). Everything in this handover is **uncommitted** on top of it.

---

## Git state

```
bffe41dd3a  Remove dead slice helpers (slice-area / direction-profile / profile-violations)   ← LAST GOOD COMMIT
7e7e9b5e6a  Phase 0: non-planar parting interface + stub (no nextdrape)
10045a05e4  Plan: non-planar parting implementation (phased, OCCT-verified)
```

Working tree: `M src/Mod/Composites/tools/mould_analysis.py` (uncommitted, broken).

---

## What's already been deleted (3 blocks, via `sed`)

These function blocks have been removed from `mould_analysis.py` (line numbers are the ORIGINAL pre-deletion ranges; the file is now 2,526 lines, was ~3,900):

1. **Block 1 — decomposition/multipart/manufacturability subsystem (orig lines 239–1280):** `_decomposition_plan_status`, `_clean_decomposition_regions`, `_decomposition_plan_regions`, `_decomposition_plan_candidates`, `_decomposition_plan_summary`, `_decomposition_readiness_payload`, `_axis_bounds`, `_axis_clip_box`, `_split_offsets_from_violations`, `_multipart_offset_sets`, `_multipart_piece_slices`, `_multipart_attempt`, `_select_best_multipart_attempt`, `_multipart_execution_payload`, `_region_interval`, `_manufacturability_overlay_bands`, `_manufacturability_overlay_groups`, `_manufacturability_overlay_group_summary`, `_manufacturability_overlay_top_clusters`, `_manufacturability_overlay_cluster_summary`, `_manufacturability_calibration_weights`, `_manufacturability_calibration_inputs`, `_manufacturability_score_breakdown`, `_manufacturability_risk_class`, `_largest_overlay_group`, `_manufacturability_recommendations`, `_not_applicable_manufacturability_payload`, `_manufacturability_payload`. (Confirmed self-contained — all callers were inside the block except 3 entry points called from `analyze_source_shape`, which still dangle — see below.)

2. **Block 2 — `_sample_draw_accessibility` (orig lines 2323–2466):** the accessibility ray-sampler (the fragile `shape.common(ray)` + edge-count heuristic the user questioned).

3. **Block 3 — refinement layer (orig lines 2483–2693):** `_slice_refinement_needed`, `_geometric_accuracy_mm`, `_geometric_accuracy_summary`, `_geometric_accuracy_status`, `_geometric_refinement_profile_and_violations`, `_geometric_refinement_payload`, `_slice_refinement_payload`, `_format_violation_regions`, `_format_violations`, `_analysis_method_label`, `_analysis_confidence_label`.

**Kept (do not remove):** `_analysis_gate_status` (now at line 1281 — must be rewritten to drop the `accessibility` param, see below), `make_mould_halves`, `_withdrawal_clearance_validity_check`, `validate_mould_result`, `_classify_draft_faces`, `_backface_area_ratio`, `_whole_side_draft_envelope`, `_sample_face_draft_alignment`, `propose_parting_surface`, `_propose_non_planar_parting` (the Phase 0 stub), `normalize_source_shape`, `analyze_source_shape`.

---

## The dangling references to fix (current line numbers in the broken file)

Run this to see them: `grep -n "_sample_draw_accessibility\|_decomposition_readiness_payload\|_not_applicable_manufacturability_payload\|_multipart_execution_payload\|_manufacturability_payload\|_slice_refinement_payload\|_geometric_refinement\|_geometric_accuracy_\|_format_violation\|_analysis_method_label\|_analysis_confidence_label" src/Mod/Composites/tools/mould_analysis.py`

| Line | Dangling call | Fix |
|---|---|---|
| 767 | `_direction_geometric_evidence` calls `_sample_draw_accessibility` + builds `accessibility` key + `_analysis_gate_status(draft, accessibility)` | Remove the accessibility call + key; gate → `_analysis_gate_status(draft_face_screening)` (draft-only). Evidence dict: `{cache_key, direction, draft_face_screening, backface_ratio, analysis_gate_status}`. |
| 839 | `_evaluate_split_strategy_attempt` calls `_slice_refinement_payload` → uses `profile`, `violations`, `undercut_count`, `draft_violation_count`, `geometric_accuracy_*`, `slice_refinement_*` | Remove the refinement payload + all its derived fields. The attempt keeps: draft_face_screening, analysis_gate_status, geometric_evidence, parting, mould_halves, withdrawal_clearance, validation, status, reason, planner_score (simplified), selection_reason, exception, non_planar_result. |
| 1281 | `_analysis_gate_status(draft_face_screening, accessibility)` | Rewrite to `_analysis_gate_status(draft_face_screening)`: draft-only — `Pass` if no risky faces, `Warning` if `risky_face_count > 0`. (WC is the authoritative check, handled separately in `validate_mould_result`.) |
| ~1858 | `_planner_score(strategy, status, undercut_count, draft_violation_count)` | Simplify to `_planner_score(strategy, status)` — drop the count penalty: `status_rank*1000 + direction_score - rank*1e-3`. |
| 1803, 2142, 2380 | `_decomposition_readiness_payload(...)` | Remove the call + the `decomposition_plan_*` result fields. |
| 1878, 2176 | `_not_applicable_manufacturability_payload(...)` | Remove. |
| 2314 | `_analysis_method_label(...)` | Remove; drop `analysis_method` result field (or set to a constant `"geometric_screening"`). |
| 2319–2320, 2323, 2329 | `_format_violation_regions` / `_format_violations` | Remove; drop `undercut_regions`/`draft_violation_regions`/`undercut_summary`/`draft_violation_summary` and the `undercut_count`/`draft_violation_count` they come from. |
| 2367 | `_analysis_confidence_label(...)` | Remove; drop `analysis_confidence` (or set constant). |
| 2390 | `_multipart_execution_payload(...)` | Remove; drop `multipart_*` result fields. |
| 2397 | `_manufacturability_payload(...)` | Remove; drop `manufacturability_*` result fields (there are MANY — overlay bands, groups, clusters, calibration, recommendations, score breakdown — all go). |

Also strip from the **result dict** (`analyze_source_shape`'s `result.update({...})`): `accessibility_summary`, `accessibility_checks`, `profile_summary`, `profile_violations`, `slice_refinement_required`, `slice_refinement_summary`, `analysis_method`, `analysis_confidence`, `geometric_accuracy_mm`, `geometric_accuracy_tolerance_mm`, `geometric_accuracy_status`, `geometric_accuracy_summary`, `undercut_count`, `undercut_summary`, `undercut_regions`, `draft_violation_count`, `draft_violation_summary`, `draft_violation_regions`, `decomposition_plan_*`, `multipart_execution_*`, `manufacturability_*` (all the overlay/calibration/recommendations fields). And from `_base_analysis_result()` (the null-shape stub) + `_failed_attempt_from_exception` (which had hardcoded `accessibility`/`draft_face_screening` Fail dicts).

Also check `_plan_split_strategies`, `_split_strategy_diagnostics`, `_split_strategy_attempt_diagnostics`, `_format_split_strategy_summary` — they may reference removed strategy/attempt fields (`analysis_gate_status` stays; `accessibility_status`, `slice_refinement_*` go).

---

## End-state architecture (what the code should look like when done)

- **`_direction_geometric_evidence(shape, direction)`** → `{cache_key, direction, draft_face_screening, backface_ratio, analysis_gate_status}`. No accessibility.
- **`_analysis_gate_status(draft_face_screening)`** → draft-only: `Pass` (no risky faces) / `Warning` (risky faces exist). (The WC check is separate — in `validate_mould_result` via `withdrawal_clearance_status` — and is the authoritative Fail.)
- **`_evaluate_split_strategy_attempt`** → evidence (draft + gate) + parting + mould_halves (planar or non-planar stub) + WC + `validate_mould_result(parting_status, halves_status, analysis_gate_status, parting_shape, half_a, half_b, withdrawal_clearance_status=wc)`. No refinement, no violations, no counts, no accuracy, no method, no confidence.
- **`_planner_score(strategy, status)`** → `status_rank*1000 + direction_score - rank*1e-3`.
- **`analyze_source_shape` result** keeps: `status`, `summary`, `shape`, `draw_direction_score`, `best_draw_direction`, `split_strategy_*`, `normalization_*`, `draft_face_summary`, `draft_face_classifications`, `parting_surface_*`, `mould_halves_*`, `mould_half_*`, `withdrawal_clearance_*`, `validation_*`, `parting_model`, `parting_line`, `parting_skirt_rays`, `non_planar_*`. **Everything else goes.**
- **`validate_mould_result`** keeps its `analysis_gate_status` + `withdrawal_clearance_status` params; the `geometric_accuracy_mm` param can stay optional (callers pass `None`) or be removed — your call, but removing it is cleaner/smaller.

---

## FP property removals (`features/MouldAnalysis.py`)

Remove from `MouldAnalysisFP.__init__` and from `execute()` assignments:
- `UndercutCount`, `UndercutSummary`, `UndercutRegions`
- `DraftViolationCount`, `DraftViolationSummary`, `DraftViolationRegions`

Keep: `Source`, `PreferredDrawDirection`, `PartingModel`, `PartingLandWidth`, `PartingStockMargin`, `PartingStockFootprint`, `AnalysisStatus`, `DrawDirectionScore`, `BestDrawDirection`, `PartingSurfaceStatus/Normal/Offset/Area/Summary/Shape`, `MouldHalvesStatus/Summary/HalfA/HalfB`, `ValidationStatus/Summary/Checks`, `AnalysisSummary`, `Shape`.

(Removing FeaturePython properties means saved docs drop them on reload — FreeCAD handles gracefully. The user confirmed this is OK.)

---

## Tool updates

- **`compositestests/inspect_mould_results.py`** — `_print_report` reads `accessibility_summary`, `profile_summary`, `geometric_accuracy_summary`, `draft_face_summary`. Drop the removed ones (keep `draft_face_summary`, `withdrawal_clearance_*`, `parting_*`, `mould_halves_*`, `validation_*`).
- **`tools/profile_mould_analysis.py`** — already had the slice probes removed (committed in `bffe41dd3a`); check it doesn't reference removed result fields. It imports `_classify_draft_faces`, `_sample_draw_accessibility` (!!) — **`_sample_draw_accessibility` was deleted**, so this import must go, and any probe using it goes too.

---

## Test updates (`compositestests/`)

Remove entirely:
- `TestAccessibilitySampling` (uses `_sample_draw_accessibility` — deleted)
- `TestDiscretizationSensitivity` (uses `_sample_draw_accessibility` — deleted)
- `TestAnalysisGateStatus` (drives the gate with `accessibility` evidence — the gate is now draft-only; the draft-only cases can be kept if desired, but the accessibility-crafted cases go)

Update:
- `test_fast_loop_shapes_separate_box_from_planar_limits` — drop `analysis_method`, `slice_refinement_required`, `analysis_gate_status` (or update to draft-only gate). Currently asserts blade/loft `analysis_gate_status="Warning"`, `status="Fail"` (WC-driven), box `Ready`. With draft-only gate, blade/loft gate is still `Warning` (risky draft faces) — so `analysis_gate_status` assertions may still hold; check. Drop `analysis_method`/`slice_refinement_required` assertions.
- `test_top_level_evidence_fields_present` — drop assertions on removed fields (`analysis_method`, `analysis_confidence`, `accessibility_summary`, `accessibility_checks`, `profile_summary`, `profile_violations`, `geometric_accuracy_*`, `slice_refinement_*`).
- `test_slice_refinement_regression_fields_present` — this whole test is about refinement fields; **delete it**.
- `test_manufacturability_metrics_present` — delete (manufacturability gone).
- `test_candidate_strategies_reuse_geometric_evidence` — checks `first_attempt["analysis_gate_status"]` and `accessibility_status`; drop the `accessibility_status` assertion.
- `test_mould_analysis_unit` module — has MANY unit tests for decomposition/multipart/manufacturability (`TestDecompositionPlanCandidates`, `TestDecompositionPlanStatus`, `TestManufacturability*`, `TestMultipartOffsetSets`, `TestSelectBestMultipartAttempt`, `TestSplitOffsetsFromViolations`, etc.). **Remove all those test classes** (they test deleted code). Keep `TestQuantityToMm`, `TestRegionInterval` (if `_region_interval` deleted, remove this too), and any other tests for retained helpers.
- `test_mould.py` — `test_mould_analysis_on_lofted_source` etc. shouldn't reference removed FP properties; check `assert_analysis_ready` and any `UndercutCount`/`DraftViolationCount` asserts.

---

## Broader context (so you don't lose the plot)

This slimming is part of the **mould-analysis accuracy plan** (`docs/mould-analysis-accuracy-plan.md`). The big picture:

- **Phase 0 DONE** (`7e7e9b5e6a`): non-planar parting interface + stub (`_propose_non_planar_parting`, `PartingModel` FP property). Planar stays default.
- **This slimming pass** (in progress, this handover): remove the old heuristic stack (accessibility + refinement + manufacturability) so the new system is built on a minimal base. WC is the authoritative gate (already wired in `4526c45419`).
- **Phase 1 (nextdrape C++, parallel, in progress elsewhere):** the marching-equator parting solver. Spec: `docs/non-planar-parting-requirements.md`. Implementation plan: `docs/non-planar-parting-implementation-plan.md` (OCCT APIs verified against OCCT 8 via context7). Algorithm: bbox in local frame (z=D, origin bbox center), bbox-touching start, **recurring** z-midpoint rule for tangent-surface degenerate ranges, clockwise (from −Z) equator march (`normal·D=0`) in each face's `(u,v)` across surface boundaries, surface-normal ray skirt, part line as per-surface `(u,v)` spline chain, exact BREP shell split (`BRepFeat_SplitShape::SplitByWire`). `reflectLines`/`Contap_Contour` NOT used (unreliable). Fork/degenerate → error. Axis system pinned: `gp_Ax3` Z=D, origin bbox center, X via OCCT default, clockwise from −Z, AABB of transformed shape (not OBB).
- **Phase 2 (after Phase 1):** wire the real binding, flip `PartingModel` default, add blade/loft WC=Pass acceptance tests.
- Draw direction is **user-specified and authoritative** (auto-ranking was removed in `26e7db16f3`).

---

## Discipline rules (the user has been strict about these — read `freecad-dev` SKILL.md "Discipline" section)

- **NEVER write `/tmp/*.py` scripts.** Recurring inspection → committed CLI in `compositestests/` or extend `run-tests.sh`. Shell output captures (`> /tmp/x.out`) are fine; authoring executable `/tmp/*.py` is not.
- **Run only mould test modules:** `test_mould_geometry`, `test_mould`, `test_mould_analysis_unit`. Do NOT run the full 25-module suite or chase failures in unrelated modules.
- **Use the scripts:** `~/.pi/agent/skills/freecad-dev/scripts/build-install-freecad.sh` (must print `=== Done ===`), `run-tests.sh` (now records per-test timings to a tmp file — printed at start; subTest-aware).
- After editing Python in `src/`, rebuild before testing (the pixi install is what `run-tests.sh` loads).
- The nextdrape C++ binding has had recurring `FlatPnt2d` API breaks (`.X()`→`.p.X()`); if the build fails on `CompositesDrape.cpp`, that's the same class of fix.
- Observe directly, don't speculate. If a test result is ambiguous, run the single test via `FreeCADCmd -t <full.test.id>`.

---

## Key files

- `src/Mod/Composites/tools/mould_analysis.py` — the file being slimmed (broken, uncommitted)
- `src/Mod/Composites/features/MouldAnalysis.py` — the FP (properties to remove)
- `src/Mod/Composites/tools/profile_mould_analysis.py` — profiling helper (broken import of deleted `_sample_draw_accessibility`)
- `src/Mod/Composites/compositestests/inspect_mould_results.py` — inspector (reads removed fields)
- `src/Mod/Composites/compositestests/test_mould_geometry.py` + `test_mould.py` + `test_mould_analysis_unit.py` — tests to update
- `src/Mod/Composites/docs/mould-analysis-accuracy-plan.md` — master plan
- `src/Mod/Composites/docs/non-planar-parting-requirements.md` — the C++ spec
- `src/Mod/Composites/docs/non-planar-parting-implementation-plan.md` — the phased plan (OCCT-verified)
- `~/.pi/agent/skills/freecad-dev/SKILL.md` — Discipline section + timings doc

---

## Suggested completion order

1. Fix `_direction_geometric_evidence` (line 767) — drop accessibility.
2. Rewrite `_analysis_gate_status` (line 1281) — draft-only.
3. Fix `_evaluate_split_strategy_attempt` (line 839) — drop refinement payload + derived fields.
4. Simplify `_planner_score` (line ~1858) — drop count params.
5. Rewrite `analyze_source_shape` (line ~3500+) — remove the 3 decomposition/multipart/manufacturability payload calls + strip the result dict.
6. Fix `_base_analysis_result` + `_failed_attempt_from_exception` — strip removed fields/hardcoded dicts.
7. Check `_plan_split_strategies` / `_split_strategy_diagnostics` / `_split_strategy_attempt_diagnostics` / `_format_split_strategy_summary` for removed-field refs.
8. FP: remove the 6 properties.
9. Tools: fix `inspect_mould_results.py`, `profile_mould_analysis.py`.
10. Tests: remove/update as above.
11. `build-install-freecad.sh` → `run-tests.sh test_mould_geometry test_mould test_mould_analysis_unit`.
12. Commit the slimming pass.

**Do not commit until all 3 mould modules are green.**
