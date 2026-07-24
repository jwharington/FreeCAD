# Mould System — Test Plan

**Date:** 2026-07-16 (revised 2026-07-25)
**Scope:** Test coverage for the Composites mould system: `MouldAnalysisFP`
(feature), `PartPlaneFP` (feature), and their backing tools
`tools/mould_analysis.py`, `tools/part_plane.py`.
**Status:** Coverage current. The heuristic-stack retirement (accessibility,
refinement, manufacturability/decomposition/multipart) removed the unit tests
for those helpers; the remaining tests pin the live verdict path.

## Deprecation done (2026-07-16)

Removed the deprecated cavity-cut mould path:
- `tools/mould.py` (old blank+cut mould generator) — deleted.
- `features/Mould.py` (`MouldFP` / `CompositeMouldCommand`) — deleted.
- `Composites_Mould` command registration removed from `InitGui.py` and
  `ToolbarGroup.py`.
- `MouldFP` references removed from `demos/generate_feature_demos.py`.
- `test_mould.py`: MouldFP-specific tests removed; class renamed
  `TestMouldFP` → `TestMouldAnalysis`. MouldAnalysis + PartPlane tests
  retained.

The `Mould.svg` icon + `MOULD_TOOL_ICON` are **retained** — `MouldAnalysis`
already uses them. The mould system is `MouldAnalysis` (produces mould halves
via `make_mould_halves` in `mould_analysis.py`).

## Heuristic-stack retirement (2026-07-25)

The accessibility ray-sampler, slice-refinement layer, and
manufacturability/decomposition/multipart subsystem were removed from
`mould_analysis.py` (~1700 lines). Consequently:

- `test_mould_analysis_unit.py` lost the unit classes for
  `_manufacturability_score_breakdown`, `_manufacturability_risk_class`,
  `_manufacturability_overlay_bands` / `_groups`, `_decomposition_plan_*`,
  `_split_offsets_from_violations`, `_multipart_offset_sets`,
  `_select_best_multipart_attempt`, `_region_interval`. It now covers only
  the surviving pure-Python helpers: `_quantity_to_mm` and
  `_extract_normalization_hints`.
- `test_mould_geometry.py` lost `TestAccessibilitySampling` and
  `TestDiscretizationSensitivity` (tested the removed sampler).
  `TestAnalysisGateStatus` was rewritten for the draft-only gate.
  `TestValidateMouldResult` was rewritten for the WC-driven validation.
- `test_mould.py` lost the `UndercutCount` / `DraftViolationCount` FP
  assertions (the properties were removed).

The verdict is now withdrawal-clearance-driven; the tests pin that path.

## Test layers

### Layer 1 — Pure-Python unit tests (no FreeCAD geometry needed)

Target: the deterministic pure-Python helpers in `tools/mould_analysis.py`.

`compositestests/test_mould_analysis_unit.py`:
- **`_quantity_to_mm`** — `getValueAs` path, `.Value` path, raw float/int,
  None, unparseable.
- **`_extract_normalization_hints`** — thickness from each candidate prop;
  invalid (non-numeric / non-positive) states; laminate detection; fallback
  through candidate props.

These are pure-Python (import the module, call functions, assert on returned
dicts) — no FreeCAD document, no Part shapes. Fast and stable.

### Layer 2 — Geometry-behavior tests (FreeCAD + Part, no GUI)

Target: the public functions that take/return `Part.Shape`.

`compositestests/test_mould_geometry.py`:
- **`propose_parting_surface`** — for each of X/Y/Z draw directions on a
  known box, the plane orientation matches; the returned shape is a valid
  non-null face.
- **`make_mould_halves`** — on a box, produces two non-null solids; each
  half lies on the correct side of the parting plane; each has positive
  stock volume.
- **`normalize_source_shape`** — a solid passes through with confidence
  "exact"; a null/empty shape returns confidence "fail".
- **`_classify_draft_faces`** — exact safe/risky/ambiguous counts and area
  totals for a box; midpoint-normal miss on twisted shapes.
- **`_whole_side_draft_envelope`** + **`_sample_face_draft_alignment`** —
  box releasable both sides; blade/loft globally negative; sphere/cone
  primitives pin sign logic and adaptive refinement.
- **`_analysis_gate_status`** — draft-only: Pass when clean, Warning
  otherwise, never Fail (decoupled from the verdict).
- **`validate_mould_result`** — WC-driven: clean inputs → Pass; failed
  parting / null half → Fail; WC=Fail → Fail; WC=Pass → Pass.
- **`_withdrawal_clearance_validity_check`** — box clearance Pass; forced
  collision fails the gate.
- **`analyze_source_shape`** — box Ready/Pass; null shape → "Waiting for
  source"; best direction mirrors the user-specified draw direction;
  split-strategy attempts reuse geometric evidence.
- **`TestPlanarPartingInsufficiency`** — blade/loft fail WC under every
  planar direction; never Ready/Pass under planar analysis.
- **`TestNonPlanarPartingInterface`** — Phase 0 stub returns NotImplemented
  and falls back to planar; parting-model properties present with defaults.
- **`test_fast_loop_shapes_separate_box_from_planar_limits`** — box
  Ready/Pass with WC=Pass; blade/loft Fail with WC=Fail; the
  analysis_gate is informational (Pass or Warning).

### Layer 3 — Feature/integration tests (`test_mould.py`)

Target: the `MouldAnalysisFP` / `PartPlaneFP` features end-to-end.

`compositestests/test_mould.py`:
- **Error paths:** null source → "Waiting for source"; empty shape → Fail;
  null source does not crash `PartPlaneFP`.
- **Draw-direction correctness:** the parting-surface normal follows the
  user-specified `PreferredDrawDirection`.
- **Persistence (round-trip):** `test_mould_workflow_round_trip` +
  `test_mould_halves_persist_across_reload` — mould halves survive reload.
- **Benchmark shapes:** box / cylinder / lofted source yield Ready moulds;
  PartPlane on box + cylinder.
- **Non-planar interface:** parting-model properties threaded to the stub;
  planar model unchanged on box.

## Design constraints for the tests

- **No GUI / no MCP.** All tests run headless under `run-tests.sh`
  (FreeCADCmd). Layer 1 is pure Python; Layers 2–3 use `Part` only.
- **Deterministic.** Use fixed primitives with exact coordinates.
- **One assert per test** for the unit layer; parametrize where the same
  logic spans multiple inputs.
- **Don't assert on Coin/scene-graph state.**
- **New modules are in `run-tests.sh`'s default list** so they're covered
  by the "all modules green" gate.

## Skipped: propblade fixture

`TestPropbladeFixture` in `test_mould_geometry.py` is `@unittest.skip` until
the final acceptance step. The `propblade.FCStd` fixture lives under
`compositestests/fixtures/` for that step. Do not reenable during routine
iteration — keep the fast loop under budget and propblade-free.

## Files

- `compositestests/test_mould_analysis_unit.py` (Layer 1)
- `compositestests/test_mould_geometry.py` (Layer 2)
- `compositestests/test_mould.py` (Layer 3)
- `~/.pi/agent/skills/freecad-dev/scripts/run-tests.sh` (runs every module,
  reports a summary, records per-test timings)
