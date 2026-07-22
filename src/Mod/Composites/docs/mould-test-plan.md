# Mould System — Test Plan

**Date:** 2026-07-16
**Scope:** Test coverage for the Composites mould system: `MouldAnalysisFP`
(feature), `PartPlaneFP` (feature), and their backing tools
`tools/mould_analysis.py`, `tools/part_plane.py`.
**Status:** Plan. Existing coverage is happy-path-only on simple primitives.

## Deprecation done (2026-07-16)

Removed the deprecated cavity-cut mould path:
- `tools/mould.py` (old blank+cut mould generator) — deleted.
- `features/Mould.py` (`MouldFP` / `CompositeMouldCommand`) — deleted.
- `Composites_Mould` command registration removed from `InitGui.py` and
  `ToolbarGroup.py`.
- `MouldFP` references removed from `demos/generate_feature_demos.py`.
- `test_mould.py`: MouldFP-specific tests removed (`test_mould_on_cylinder`,
  `test_mould_on_box_with_custom_overhangs`, `test_mould_on_lofted_source`,
  `_make_mould`, `assert_mould_ready`); class renamed `TestMouldFP` →
  `TestMouldAnalysis`. MouldAnalysis + PartPlane tests retained.

The `Mould.svg` icon + `MOULD_TOOL_ICON` are **retained** — `MouldAnalysis`
  already uses them. The new mould system is `MouldAnalysis` (produces mould
  halves via `make_mould_halves` in `mould_analysis.py`).

## Current state (as found)

`compositestests/test_mould.py` — tests PASS, but:

`compositestests/test_mould.py` — 8 tests, all PASS. But:
- Every test uses a simple primitive (cylinder / box / loft) and only asserts
  shape-not-null + status-not-"Waiting for source". No correctness checks on
  the *content* of the result (volumes, parting-plane orientation, undercut
  counts, draw-direction ranking).
- No error-path / edge-case coverage (null source, degenerate shapes,
  non-manifold, boolean-cut failure).
- No unit tests for the pure-Python analysis helpers in `mould_analysis.py`
  (overlay grouping, manufacturability score, decomposition planning,
  normalization hints) — these are deterministic and the easiest/fastest to
  test in isolation.
- The run emits warnings (`Not all input shapes are mappable`, `still touched
  after recompute`) that no test asserts on — these should either be fixed or
  pinned as expected behavior.

## Test layers

### Layer 1 — Pure-Python unit tests (no FreeCAD geometry needed)

Target: `tools/mould_analysis.py` helper functions. These are deterministic
pure functions over dicts/lists/scalars — fast, no GUI, no OCC. This is where
coverage is thinnest relative to code volume (~2900 lines, 5 public functions
+ dozens of helpers).

`compositestests/test_mould_analysis_unit.py` (new):

- **`_manufacturability_score_breakdown`** — monotonicity: each component
  increases the total; clamps at saturation; weights normalize to 1.0;
  `total` ∈ [0,1].
- **`_manufacturability_risk_class`** — boundary thresholds (0.34, 0.67)
  map to low/medium/high; exact-boundary values.
- **`_manufacturability_overlay_groups`** — bands cluster by kind + proximity;
  severity tier from span + density; labels deduped; empty input → [].
- **`_manufacturability_overlay_bands`** — parses `[n] a→b` region text;
  ignores unparseable; swaps reversed intervals.
- **`_decomposition_plan_status`** — the full status matrix
  (analysis/validation × Waiting/Fail/Warning/Ready/Pass).
- **`_decomposition_plan_candidates`** — emits the right candidate set per
  status + undercut/draft counts.
- **`_split_offsets_from_violations`** — midpoints within axis bounds,
  deduped, clamped to `max_extra_splits`, skips baseline.
- **`_multipart_offset_sets`** — depth-1 and depth-2 sets; empty → [].
- **`_select_best_multipart_attempt`** — ranking tuple (status → reduction →
  volume → −depth → −offset distance); tie-breaks deterministically.
- **`_extract_normalization_hints`** — thickness from each candidate prop;
  invalid (non-numeric / non-positive) states; laminate detection.
- **`_quantity_to_mm`** — `getValueAs` path, `.Value` path, raw float, None.

These should be pure-Python (import the module, call functions, assert on
returned dicts) — no FreeCAD document, no Part shapes. Fast and stable.

### Layer 2 — Geometry-behavior tests (FreeCAD + Part, no GUI)

Target: the public functions that take/return `Part.Shape`.

`compositestests/test_mould_geometry.py` (new):

- **`propose_parting_surface`** — for a box, the parting plane is at the
  bbox midpoint along the dominant axis; `surface_normal` is the axis unit
  vector; `surface_offset` equals the midpoint coordinate; the returned
  shape is a valid non-null face.
- **`propose_parting_surface`** — for each of X/Y/Z draw directions on a
  known box, the plane orientation matches (parametrized).
- **`make_mould_halves`** — on a box, produces two non-null solids whose
  combined volume ≈ source volume + small parting-surface slack; each half
  lies on the correct side of the parting plane.
- **`normalize_source_shape`** — a solid passes through with confidence
  "exact"; a compound-of-solids normalizes to a single effective solid;
  a null/empty shape returns confidence "fail".
- **`analyze_source_shape`** — on a box, `status` is Ready/Pass;
  `BestDrawDirection` is one of the axis candidates; `DrawDirectionRanking`
  is non-empty; `manufacturability_metrics` has the expected keys; the
  summary strings are non-empty.
- **`analyze_source_shape`** — null shape → status "Waiting for source"
  (the documented early-return), no exception.
- **`validate_mould_result`** — pure function: given Pass parting + Pass
  halves + zero violations → "Pass"; given Fail parting → "Fail";
  given undercuts → "Warning". (This straddles L1/L2; place with L2 since
  it takes shape args, even though it doesn't inspect them deeply.)

### Layer 3 — Feature/integration tests (extend `test_mould.py`)

Target: the `MouldFP` / `MouldAnalysisFP` / `PartPlaneFP` features end-to-end,
including the failure modes the current tests skip.

Add to `compositestests/test_mould.py`:

- **Error paths:**
  - `MouldFP` with a null/empty Source shape → `GenerationStatus == "fail_closed"`,
    `GenerationSummary` is non-empty, shape is null (no crash, no exception).
  - `MouldFP` where the boolean cut throws → `fail_closed` + `reason_code ==
    cut_exception` (use a degenerate source that breaks `cut`).
  - `MouldAnalysisFP` with null Source → `AnalysisStatus == "Waiting for
    source"` (or "Fail" — pin whichever the code actually does).
- **Overhang geometry:** on a known box with custom X/Y/Z overhangs, the
  mould blank's bounding box extends by exactly the overhang on each side
  (asserts the buffer math, not just "not null").
- **Draw-direction ranking correctness:** on a tall thin box (e.g. 2×2×20),
  the Z axis wins `BestDrawDirection` (smallest extent → highest bbox score).
  On a flat wide box (20×20×2), Z does *not* win. This is the first test
  that asserts the analysis picked the *right* answer, not just *an* answer.
- **Undercut detection:** a shape with a genuine undercut (e.g. an L-bracket
  / T-section) reports `UndercutCount > 0`; a plain box reports 0.
- **Persistence (round-trip):** already covered by
  `test_mould_workflow_round_trip` — keep, but add an assertion that
  `GenerationStatus` survives reload (not just shape-not-null).
- **Pin the warnings:** decide whether `Not all input shapes are mappable`
  and `still touched after recompute` are bugs (fix the code) or expected
  (assert/suppress). Do **not** weaken tests to hide them — investigate first.

## Design constraints for the tests

- **No GUI / no MCP.** All tests must run headless under `run-tests.sh`
  (FreeCADCmd). Layer 1 is pure Python; Layers 2–3 use `Part` only (no
  ViewObject). The existing `test_mould.py` already runs headless — match
  that pattern.
- **Deterministic.** Use fixed primitives (cylinder radius/height, box dims)
  with exact coordinates, not random or CAD-imported geometry.
- **One assert per test** for the unit layer; parametrize where the same
  logic spans multiple inputs (draw directions, status matrix).
- **Don't assert on Coin/scene-graph state** — that's GUI territory, out of
  scope for the mould *geometry/analysis* tests.
- **Add new modules to `run-tests.sh`'s default list** so they're covered by
  the "all modules green" gate (the script was fixed this session to run
  every module and report a summary).

## Open questions (to resolve before/while implementing)

1. The `Not all input shapes are mappable` warning during mould-halves
   construction — is it a real geometry defect or benign? Investigate in
   Layer 3.
2. Should `analyze_source_shape` on a null shape return "Waiting for source"
   or "Fail"? The code has an early-return; pin the actual behavior.
3. The manufacturability calibration weights (`MANUFACTURABILITY_CALIBRATION_*
   in `mould_analysis.py`) are magic numbers. Tests should assert the *math*
   (weights sum to 1.0, components saturate), not the specific values —
   unless those values are a contract.
4. `tools/part_plane.py` imports `CAM` (Path workbench) — does that work
   headless? If not, `PartPlaneFP` tests may need to skip or mock. Check
   whether the existing `test_part_plane_on_cylinder` actually exercises
   `make_parting_surface3` or a simpler path.

## Suggested order

1. Layer 1 (pure-Python unit tests) — highest value/effort ratio, no
   geometry dependencies, fastest to write and run.
2. Layer 3 error paths + draw-direction correctness — these expose real
   bugs the happy-path tests miss.
3. Layer 2 geometry-behavior tests — fill in the public-function contracts.
4. Resolve the open questions (warnings, null-shape contract, CAM import).

## Files

- New: `compositestests/test_mould_analysis_unit.py` (Layer 1)
- New: `compositestests/test_mould_geometry.py` (Layer 2)
- Extended: `compositestests/test_mould.py` (Layer 3)
- Updated: `~/.pi/agent/skills/freecad-dev/scripts/run-tests.sh` (add new modules)
