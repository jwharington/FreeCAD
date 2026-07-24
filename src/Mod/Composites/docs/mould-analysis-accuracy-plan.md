# Composites Mould Analysis Accuracy Plan

**Date:** 2026-07-23 (revised 2026-07-25)
**Status:** Heuristic stack retired; non-planar solver pending (Phase 1, C++ in nextdrape)
**Scope:** the mould-analysis verdict path in `tools/mould_analysis.py`

## Decision

The mould-analysis path stays in Python. The old heuristic stack (slice-area
profile, accessibility ray-sampling, slice refinement, manufacturability /
decomposition / multipart subsystem, auto-ranking) has been **removed**. The
verdict is now driven by a single authoritative necessary test — **withdrawal
clearance** — with a lightweight draft-face signal reported alongside it. The
remaining open work is the non-planar parting solver (C++ in nextdrape),
behind which the Python side is already wired.

## CRITICAL execution guardrails

- **CRITICAL:** Do not run `propblade` tests or benchmarks until the very final task of this plan is complete.
- **CRITICAL:** Do not run any code path, test target, benchmark mode, fixture loader, or helper that directly or indirectly involves `propblade` unless the user has given explicit approval in this chat immediately before that run.
- **CRITICAL:** Do not run FreeCAD via MCP until the very final task of this plan is complete.
- Until final acceptance, use headless-only fast-loop work (`box` / `blade` / `loft`) for iteration.

## Current architecture

The verdict path is minimal and geometric:

1. **Normalization** — `normalize_source_shape` produces an effective solid.
2. **Draft-face screening** — `_classify_draft_faces` labels each face
   safe / risky / ambiguous against the draw direction. This feeds
   `_analysis_gate_status`, an **informational** Pass/Warning signal. It
   never returns Fail and is **decoupled from the verdict** — a box's
   parting face is "risky" by the dot test, yet a box is perfectly mouldable.
3. **Parting surface + mould halves** — `propose_parting_surface` (planar,
   the default) and `make_mould_halves`. A non-planar stub
   (`_propose_non_planar_parting`) returns NotImplemented and falls back to
   planar until the C++ solver lands.
4. **Withdrawal clearance** — `_withdrawal_clearance_validity_check`
   withdraws each mould half along the draw direction and fails on any
   non-zero intersection with the source. This is the **authoritative
   necessary test** and the sole source of a hard Fail.
5. **Validation** — `validate_mould_result` aggregates parting status, half
   validity, and withdrawal clearance into the top-level verdict.

The draw direction is **user-specified and authoritative** — there is no
auto-ranking. `analyze_source_shape` analyzes only the given direction and
truthfully reports whether it releases.

### What was removed and why

The retired stack answered weaker, indirect questions and produced false
confidence (the seam documented in the non-planar investigation):

- **Slice-area profile / direction-profile / profile-violations** — a
  monotonicity proxy for accessibility; indirect and dominated runtime.
- **`_sample_draw_accessibility`** — a `shape.common(ray)` + edge-count
  heuristic. It reported Pass for the box (the false confidence) and was
  load-bearing only for the now-removed gate input.
- **Slice refinement layer** (`_geometric_refinement_*`,
  `_slice_refinement_payload`, `_geometric_accuracy_*`,
  `_format_violation*`, `_analysis_method_label`,
  `_analysis_confidence_label`) — demoted, then removed.
- **Manufacturability / decomposition / multipart subsystem** (~1300 lines:
  overlay bands/groups/clusters, calibration, score breakdown, risk class,
  recommendations, multipart execution) — a separate feature built on the
  removed counts; retired with them.
- **Auto-ranking** (`_candidate_scores`, `_candidate_draw_directions`,
  ranking diagnostics, `DrawDirectionRanking` FP property) — replaced by
  user-specified draw direction.
- **FP properties** `UndercutCount` / `UndercutSummary` / `UndercutRegions`
  / `DraftViolationCount` / `DraftViolationSummary` /
  `DraftViolationRegions`.

`mould_analysis.py` went from ~3900 to ~2200 lines.

## Necessary validity test

One definitive test answers: "is this mould process valid?" It is a
**necessary** test, not a sufficient proof. If it fails, the mould model is
invalid. If it passes, the process has cleared the minimum bar; it does not
prove the solver is complete or optimal.

**Status: done and wired.** `_withdrawal_clearance_validity_check` is called
inside `_evaluate_split_strategy_attempt` (per attempted draw direction), its
status is passed into `validate_mould_result` as `withdrawal_clearance_status`,
and WC=Fail is a hard validation failure that escalates the top-level
`status` to `Fail`. The result dict surfaces `withdrawal_clearance_status` /
`withdrawal_clearance_summary` / `withdrawal_clearance_failure_count`.

This closes the false-confidence seam: the analysis no longer reports
`Warning` for shapes whose mould halves physically collide with the source on
withdrawal. `blade` / `loft` (and any tapered/twisted shape un-releasable
under a planar midpoint parting) now truthfully report `Fail`; `box` /
`cylinder` stay `Ready`. The heuristic `analysis_gate_status` remains a
separate field so the cause is visible (e.g. gate=Warning but WC=Fail).

### Withdrawal-clearance procedure

Given the base object, each mould half, and a draw-direction vector:

- for each mould half:
  - withdraw the mould half by a small amount along the draw direction
  - check for intersections between the mould half and the base object
  - if any intersection occurs with non-zero volume, the test fails
  - repeat until the mould half is clear of the test object and the
    bounding boxes no longer intersect

Required properties:

- target the actual mould split, not just helper outputs
- fail on geometry that cannot be released by the current parting model
- be deterministic and repeatable
- produce evidence that a human can inspect in FreeCAD and in headless logs
- be specific enough to distinguish "invalid mould process" from "solver is
  merely incomplete"

## Non-planar parting research

The current solver assumes a planar split. Twisted geometry shows that
assumption is insufficient. The investigation is complete; the spec and
implementation plan are written:

- **`docs/non-planar-parting-investigation-2026-07-24.md`** — proves planar
  insufficiency (WC fails for every axis-aligned planar direction on blade
  and loft) and identifies the false-confidence seam.
- **`docs/non-planar-parting-requirements.md`** — the C++ spec (marching
  equator `normal·D=0`, surface-normal-ray skirt, exact BREP shell split).
- **`docs/non-planar-parting-implementation-plan.md`** — phased plan with
  OCCT 8 API cross-reference. Phase 0 (Python interface + stub) is done;
  Phase 1 (nextdrape C++ solver) is pending.

The non-planar model: the part line is traced by marching the
`normal·D=0` equator across surface boundaries (not `reflectLines` /
`Contap_Contour`, which are unreliable on freeforms). The skirt projects
outward along surface-normal rays to the block boundary, preserving
D-height. The tangent-surface degenerate (where `normal·D=0` holds over a
z-range) chooses the D-midpoint — a recurring rule, not a one-off. The
exact shell split uses `BRepFeat_SplitShape::SplitByWire`. Fork / degenerate
→ error out.

## Quality gate ordering

The solver must be quality-correct before any performance interpretation is
trusted.

- Fast-loop geometry on `box`, `blade`, and `loft` must reach `Ready/Pass`
  before any tolerance-ladder benchmark is considered valid.
- `box` / `cylinder` are `Ready` (they withdraw cleanly under planar
  parting). `blade` / `loft` are `Fail` (WC failure) — this is the
  intentional blocking negative result that proves planar parting is
  insufficient for twisted geometry. They will not reach `Ready` until the
  non-planar solver lands.
- The non-planar parting model is selected and specified; implementation is
  blocked on the Phase 1 C++ work in nextdrape.
- `propblade` acceptance is blocked by both the fast-loop quality gate and
  the tolerance-ladder benchmark gate.
- After the performance/accuracy tests are complete, run the box/blade/loft
  moulds in FreeCAD via MCP for visual verification, then stop and wait for
  the user's explicit approval before doing any further implementation or
  acceptance work.
- Any benchmark result taken while the quality gate is open is diagnostic
  only and must not be treated as evidence of solver health.

## Accuracy-scaling requirement

Performance tests must also measure how runtime changes as the
geometric-accuracy requirement tightens. This is a recurring regression
requirement: the same benchmark shapes should be run at multiple tolerances
whenever the mould-analysis path changes, and periodically thereafter to
guard against drift.

Required tolerance ladder: 1.0 mm, 0.1 mm, 0.01 mm.

If runtime does not materially change across that ladder, treat it as a sign
that the accuracy requirement is not influencing solver effort. If a looser
tolerance yields the same runtime as a tighter one while the reported
geometric accuracy degrades, treat that as a solver bug, not a valid
optimization.

## Root-cause testability

Each remaining suspected fault source must stay independently testable:

- **Draft-face misclassification** — synthetic-geometry regressions compare
  face-screening output against shapes with obvious expected
  classifications. `TestDraftFaceClassification` pins exact counts for a
  box; `test_midpoint_normal_can_miss_local_negative_draft_on_twisted_shapes`
  proves midpoint normals can hide a local undercut.
- **Whole-side draft envelope** — `_whole_side_draft_envelope` samples every
  face and aggregates the worst draft per candidate mould side.
  `TestWholeSideDraftEnvelope` + `TestDraftEnvelopePrimitives` (sphere/cone
  with adaptive refinement) distinguish a local midpoint miss from a true
  global parting-model failure.
- **Planar parting assumption** — `TestPlanarPartingInsufficiency` pins that
  blade/loft fail WC under every planar direction and are never Ready/Pass
  under planar analysis.
- **Validation coupling** — `TestValidateMouldResult` isolates validation
  from screening: WC=Fail escalates to Fail; clean inputs stay Pass.
- **Withdrawal clearance** — `TestWithdrawalClearanceValidity` exercises the
  real mould split and requires a deterministic fail on collision.

The removed fault sources (accessibility sampling weakness, discretization
artifacts, candidate-direction heuristic mismatch) are moot: the code they
tested no longer exists, and the questions they answered are now settled by
the authoritative WC test.

## Success criteria

- [x] The verdict path is geometric, not slice-monotonicity based.
- [x] Withdrawal clearance is the authoritative gate; the false-confidence
  seam is closed.
- [x] The draft-face gate is informational and decoupled from the verdict.
- [x] The draw direction is user-specified; auto-ranking is removed.
- [x] Planar parting insufficiency is proven and pinned by negative
  regression.
- [x] The dead heuristic stack is retired (~1700 lines removed).
- [ ] The non-planar parting solver lands (Phase 1, C++ in nextdrape) and
  blade/loft reach Ready/Pass.
- [ ] The tolerance-ladder benchmark confirms runtime scales with accuracy.
- [ ] The `propblade` acceptance benchmark passes on the hardest geometry.

## Open tasks

- [ ] **Phase 1: non-planar parting solver (C++ in nextdrape).** Marching
  equator, surface-normal-ray skirt, exact BREP shell split. Pybind11
  binding consumed by `analyze_source_shape`. Parallel track; nextdrape has
  its own debugging in progress.
- [ ] **Phase 2: wire binding + flip gate.** Once the C++ solver lands, wire
  the real binding into `_propose_non_planar_parting`, flip `PartingModel`
  default to NonPlanar, add blade/loft WC=Pass acceptance tests.
- [ ] **Tolerance-ladder benchmark.** Run box/blade/loft at 1.0 / 0.1 /
  0.01 mm and record how runtime scales. Blocked until the non-planar
  solver is validated (blade/loft reach Ready).
  - Visual gate: after this benchmark, run the box/blade/loft moulds in
    FreeCAD via MCP for visual verification.
  - Approval gate: after visual verification, stop and wait for the user's
    explicit approval before continuing.
- [ ] **Reenable the propblade fixture.** Acceptance-only; restore when the
  final acceptance step is approved.
- [ ] **Final acceptance benchmark on `propblade`.** CRITICAL sequencing: no
  `propblade` runs and no FreeCAD MCP runs before this final step. Do not
  execute until the user explicitly approves the run in this chat.

## Related files

- `src/Mod/Composites/tools/mould_analysis.py` — the analysis path
- `src/Mod/Composites/features/MouldAnalysis.py` — the FP
- `src/Mod/Composites/tools/profile_mould_analysis.py` — profiling helper
- `src/Mod/Composites/compositestests/test_mould_geometry.py` — geometry tests
- `src/Mod/Composites/compositestests/test_mould_analysis_unit.py` — unit tests
- `src/Mod/Composites/compositestests/test_mould.py` — feature tests
- `src/Mod/Composites/compositestests/inspect_mould_results.py` — inspection CLI
- `src/Mod/Composites/compositestests/run_inspect_mould_results.py` — CLI wrapper
- `src/Mod/Composites/docs/non-planar-parting-investigation-2026-07-24.md`
- `src/Mod/Composites/docs/non-planar-parting-requirements.md`
- `src/Mod/Composites/docs/non-planar-parting-implementation-plan.md`
