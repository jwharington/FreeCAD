# Handover — B9.5, the two red drape acceptance canaries

**Date:** 2026-10-11 · **For:** the next agent taking B9.5 ·
**Tracker entry:** `TODO-2026-10-11-outstanding-work.md`, item **B9.5**
(reproduced in §2) · **Repo:** `src/3rdParty/nextdrape` (submodule of
`/home/jmw/opt/FreeCAD`)

This document supersedes the tracker's one-paragraph framing of B9.5. The most
important correction is in §3: **the two red tests are two different defects**,
with unrelated fixes, and only one of them is a birth law.

---

## 1. The objective and the owner's rule

The drape suite has **exactly two red acceptance canaries**. Neither may be made
green by changing an assertion, a tolerance or a threshold — the owner's rule
for this class is that a boundary link which stops short of the part edge must
**never be created in the first place**. Silencing the trap, widening the
tolerance, or deleting the assertion is not the fix; the law that leaves the
fabric short is.

## 2. Current state — measured 2026-10-11

Tree: nextdrape `master` @ **`e708584`**, clean. The authoritative failing set is
`docs/known-issues/nd-current-fails.txt`, and it names these two and no others:

```
[  FAILED  ] CoverageGeometry.BentPlateDiagnosticsPopulate
[  FAILED  ] TexturePlan.BoundaryLinksLieOnTheDevelopedTrim
```

Built and run:

```bash
cd /home/jmw/opt/FreeCAD/src/3rdParty/nextdrape
pixi run cmake --build build/pixi-debug -j$(nproc)
./build/pixi-debug/nextdrape_tests \
  --gtest_filter='CoverageGeometry.BentPlateDiagnosticsPopulate:TexturePlan.BoundaryLinksLieOnTheDevelopedTrim' \
  > /tmp/b95-tests.txt 2>&1
```

**`CoverageGeometry.BentPlateDiagnosticsPopulate`**

```
Expected: (cg.gapFraction) < (0.05), actual: 0.5 vs 0.05
Bent plate should have low gap fraction
```

Half the shape is uncovered — one of the two panels is lost entirely, not a
ragged rim.

**`TexturePlan.BoundaryLinksLieOnTheDevelopedTrim`** — the test prints one line
per baseline shape. Measured today, **14 of 17 shapes are clean** and three
carry rim links:

| shape | off-trim links | of snapped rim nodes | worst deviation |
|---|---:|---:|---:|
| **cyl-closed** | **23** | 198 | **36 mm** |
| **cubic** | **2** | 133 | **6.73 mm** |
| **web_band** | **52** | 351 | **40 mm** |
| rect, cyl, cyl-wide, cone, cone-frustum, poly, hinge, hinge-skew, hole, dartplate, saddle, saddle-dart, wide_rect, stiffener_foot | 0 | — | 0 |

(The old `docs/known-issues/drape-test-baseline-2026-09-30.md` recorded a much
larger set — rect 57, cyl 38, cyl-closed 154, cubic 65, web_band 58. That
snapshot predates the B9.1/B9.1b/B9.4 work and is **historic**, not current.)

Across the two tests, **308 `TRAP BOUNDARY-LINK-BORN-OFF-EDGE` events** fire,
by creating law:

| creating laws | events |
|---|---:|
| two-neighbor + two-neighbor | 117 |
| boundary-snapped + boundary-snapped | 42 |
| single-neighbor + single-neighbor | 37 |
| single-neighbor + two-neighbor | 33 |
| two-neighbor + single-neighbor | 32 |
| cross-face-ext + cross-face-ext | 20 |
| two-neighbor + boundary-snapped | 15 |
| single-neighbor + boundary-snapped | 6 |
| boundary-snapped + single-neighbor | 4 |
| two-neighbor + cross-face | 1 |

The `boundary-snapped + boundary-snapped` row is the sharp one: **both** ends
were placed by the snap law and the link is *still* off the trim. The trap and
the `TexturePlan` test are, however, measuring different channels — read §3.2.

## 3. The two defects are different

### 3.1 `CoverageGeometry.BentPlateDiagnosticsPopulate` — pitch-resonance fold stall

**Not a boundary-link defect.** The 2026-09-30 baseline diagnosed this
(`docs/known-issues/drape-test-baseline-2026-09-30.md`, §"1. Pitch-resonance
fold stall") and it still fits today's `gapFraction = 0.5`:

- Fixture `tests/test_coverage_geometry.cpp:188`: `MakeBentPlate(90, 100, 90,
  30)` — a 90 mm panel, a 90° crease, a 90 mm folded panel at 30° — seeded at
  `gp_Pnt(20, 20, 0)` along `+x`, **`params.pitch = 5.0`** (it overrides the
  default 4.0; `DefaultParams()` sets `pitch = 4.0`, `analyzeCoverage = true`).
- The march steps `x = 20, 25, …, 85, 90`; `20 + 14×5 = 90` lands a node
  **exactly on the crease**. The fold law's arc split is then degenerate
  (`arcOnSource ≈ 0`), `TraceFibreAcrossSeam` refuses, the mixed-cell route logs
  `SEAM-MIXED cell(15,±1) predecessors on different faces but neither step
  leaves through a shared edge; falling back to pitch-pitch` and fails. The
  seam column never places, the frontier cannot advance onto panel 2, and the
  solve reports `status = Ok` with half the shape uncovered.
- **Resonance, not resolution:** 4.0, 4.9, 5.1 and 6.0 all reach ≈1.0 — they
  *straddle* the crease; only the exact alignment triggers it.

*Fix shape:* the on-crease case must be threaded through **both** the seam trace
and the mixed-cell (straddling) route. A one-sided change to
`TraceFibreAcrossSeam` was tried and **reverted** — it does not reach the
bail-out. The test is a correct detector and stays red until the law is fixed.

### 3.2 `TexturePlan.BoundaryLinksLieOnTheDevelopedTrim` — rim links off the *developed* trim

This one is about the **flat channel**, not the 3D edge. Read the test's own
comment (`tests/test_quality_metrics.cpp:1570`): a marked boundary node's
texture position is the plan's only record of where the part edge develops, so
a rim node further from the **developed outline** than the placement slack is a
fault **even when its 3D position is perfect** — "which is precisely the case
red cannot see".

- Detector `DetectBoundaryLinksOffTrim` (`src/drape/QualityMetrics.cpp:1711`):
  for every boundary-link mark, each endpoint that is valid, `flatValid` and
  `placementKind == NodePlacementKind::BoundarySnapped` is measured by
  `DevelopedOutlineDistance(node.flatCached.p, result.texturePlan)`; a
  deviation above the tolerance is a fault. A node the solver never *claimed*
  sits on the edge is not counted here (the 3D channel owns that).
- Tolerance `OffTrimTolerance(params) = max(BoundaryDefectTolerance(params),
  0.06 × pitch)` (`QualityMetrics.hpp:127`); `BoundaryDefectTolerance =
  max(projectionTol, boundaryTol)` (`:111`). Worst deviations (6.7–40 mm) are
  one to two orders of magnitude above it.
- Mechanism (2026-09-30 baseline): the rim cells the birth passes refused never
  healed, so the link is born short. But the detector's channel means the
  precise question is: **why does a node marked `BoundarySnapped` develop off
  the outline?** It can be on the 3D edge (`DistanceToBoundary ≈ 0`) and still
  be wrong in the flat.

**First step, already surfaced — collect the rejecting gate.** When a boundary
snap does not place, `LatticeFrontierPhase2.cpp` (~`:624-660`) pushes a
`FailureDiagnostic` named **`boundary-snap-rejected`**:

> `boundary snap rejected by the <gate> gate; the drape edge stops short of the
> part edge here`

`<gate>` is `LatticeNodePlacer::LastRejectGate()` (`LatticeNodePlacer.hpp:186`),
set at the placement site. Today it can be:

| gate | set in |
|---|---|
| `collision` | `LatticeNodePlacer.cpp:966` (with `LastRejectSeparation()`) |
| `uv-domain` | `LatticeNodePlacer.cpp:989` |
| `cut-wire` | `LatticeNodePlacer.cpp:1011` |
| `unknown` | no gate was recorded — itself a lead |

Dump those diagnostics for **cyl-closed**, **cubic** and **web_band** and read
the gate. Do that before touching a law; every recent mistake in this repo came
from assuming a mechanism instead of reading it.

## 4. Code map

| what | where |
|---|---|
| Birth-time trap + the "provisional refusal" comment | `src/drape/QuadBuilder.cpp:463` (`TrapBornLinkFaults`), `OneSidedLinkStopsShort` test at `:530` |
| Post-growth trap / cutter (the red class, final) | `src/drape/QuadBuilder.cpp:723` (`CutShortBoundaryLinks`), trap at `:769`, abort at `:785` |
| Quad admission / revalidation | `QuadBuilder.cpp:565` (`RevalidateRefusedCells`), `:425` (`CutOffGridEdgesAtBirth`), `:792` (`ApplyCutWireBlocking`) |
| The shared red condition | `include/nextdrape/drape/QualityMetrics.hpp:138` (`OneSidedLinkStopsShort`), `:111` (`BoundaryDefectTolerance`), `:127` (`OffTrimTolerance`) |
| Off-trim detector (the failing test's subject) | `src/drape/QualityMetrics.cpp:1711` |
| 3D boundary-link detector (`boundaryLinkDefects`) | `src/drape/QualityMetrics.cpp:1561` |
| Where the result fields are filled | `src/drape/DrapeEngine.cpp:826-833` (`ComputeSingle`), `:945-950` (merge) |
| Reject-gate diagnostic | `src/drape/LatticeFrontierPhase2.cpp:~624-660`; gate at `LatticeNodePlacer.cpp:956-1011` |
| Boundary snap | `src/drape/DrapeEngine.cpp` — `BoundarySnapResult` (~`:549`), `TextureBoundarySource::Snap`, `MergeSnapFragments` (~`:700-715`) |
| Node placement laws (single/two-neighbour, seam, atlas) | `src/drape/LatticeNodePlacer.cpp` — two-neighbour solve `:1183`, one-neighbour fallback `:1232`, `IsFabricOverlap` `:936`, `TrySeamCrossing` `:1356` |
| Placement kinds | `include/nextdrape/shared/Types.hpp:118` (`NodePlacementKind`: Seed, TwoNeighbor, SingleNeighbor, CrossFace, CrossFaceExtended, BoundarySnapped) |
| The off-trim record | `include/nextdrape/shared/Types.hpp:571` (`boundaryLinksOffTrim`) |
| Existing per-fault probe | `tools/probes/offtrim_probe.cpp` — prints placement kind, flat position, deviation, whether the node is on the shape's free edges in 3D, and the nearest fabric node's distance to them |
| Test selectors | `include/nextdrape/shared/TestHelpers.hpp:929` (`BaselineShapeNames`), `:938` (`BuildScenario`), `:443` (`MakeBentPlate`) |

## 5. What has already been done, and ruled out

- **Boundary-snap work landed** — `handoff-2026-09-29-boundary-snap.md` §11,
  commits `ec19ca5`, `aa2f0bb` (superproject `f07271a924`): trim-bounded quads
  exempt from the runaway-lap face budget; a 2×pitch edge-span refusal;
  reservation ghosts removed; the sweep's record pass restored; trim development
  anchored on fabric only. That fixed the **fuselage skins** (borders reach the
  trim) but **not** the standard shapes — this is the unfixed remainder.
- **One-sided `TraceFibreAcrossSeam` change** (for 3.1) — tried, **reverted**;
  it does not reach the `SEAM-MIXED` bail-out.
- **The "boundary retry storm" is resolved and unrelated** —
  `docs/known-issues/perf-boundary-retry-storm-2026-09-29.md` is now a
  *perf* post-mortem (an O(N²) post-solve scan, fixed in `TexturePlanBuilder`
  and coverage). It explicitly records the surviving links as "a separate
  correctness item — see `handoff-2026-09-29-boundary-snap.md`". **Do not**
  re-open it as the cause.
- **The 12 other baseline failures were suite drift**, not engine bugs
  (coverage opt-in, the Cut/Snap fragment model, report JS format, a deleted
  doc). Do not "re-fix" them — see
  `docs/known-issues/drape-test-baseline-2026-09-30.md` §"Fixed in the same
  pass".
- **Prior diagnosis reading** (deeper history, if the gate points somewhere
  unexpected): `docs/diagnosis-link-defects-common-cause-2026-09-14.md`,
  `docs/drape-link-lifecycle-audit.md`,
  `docs/diagnosis-trim-cut-corner-cell-2026-09-14.md`,
  `docs/diagnosis-hole-yellow-links-2026-09-14.md`.

## 6. Constraints in force

From `src/3rdParty/nextdrape/AGENTS.md` (read it, and `docs/architecture.md`,
before changing any data flow):

- **No approximations, discretisations or fallbacks** without the owner's
  explicit permission in the current conversation. **No sampling** where an
  exact answer exists (banned earlier in this work for good reason).
- **No deduplication** of points/vertices/edges on the basis of coincidence
  without express permission — if you feel you need it, it is a symptom of an
  upstream construction bug; fix that.
- **No reconstructing curves from samples**, no drifting copies of source-of-truth
  data.
- **Trap errors at their earliest point** — fail at the exact operation, with
  the operation's identity.
- **No guessing when debugging** — trap with asserts and use gdb; read the
  implementation, not the docs, before changing a law.
- Every change applies the `clean-cpp` and `clean-code` skills; `boy-scout` is
  the working rule.
- **Never remove asserts** without asking.
- **Do not change seed location or orientation** in tests/scenarios without
  explicit permission.

From the FreeCAD repo (`/home/jmw/opt/FreeCAD/AGENTS.md`):

- **Never relax, widen or remove a test threshold/tolerance/assertion** to make
  a failing test pass — fix the code, or fix the algorithm.
- **No retry-until-success**: a flaky result is a bug to diagnose.
- **No environment variables for run-time options**; options are arguments.

## 7. Build and test — exact commands

Canonical build dir is `build/pixi-debug`; do not create another.

```bash
cd /home/jmw/opt/FreeCAD/src/3rdParty/nextdrape
pixi run cmake --build build/pixi-debug -j$(nproc)          # incremental

# the two canaries, alone
./build/pixi-debug/nextdrape_tests \
  --gtest_filter='CoverageGeometry.BentPlateDiagnosticsPopulate:TexturePlan.BoundaryLinksLieOnTheDevelopedTrim' \
  > /tmp/b95-tests.txt 2>&1

# the whole drape subsystem (never the whole binary — it also holds the mould
# suites, ~40 min, and aborts part-way under the trap-skip wrapper)
DRAPE='QualityMetrics.*:TextureGrid.*:TexturePlan.*:BoundaryLinkDefects.*:BoundaryLinkDefectProbe.*:BoundaryDefectProbe.*:BoundaryOrderFaults.*:CollisionDiag.*:SeamArcProbe.*:SplitEdgeProbe.*:BaselineShapes.*:CoverageGeometry.*:CutWireDiscovery.*:CutWireEngine.*:MultiSeedCoverage.*:SeamCrossing.*:SeamGeodesicPrimitives.*:BooleanExtrusion.*:ExactSolverRobustness.*:WP0BaselineHarness.*:WP1Observability.*:WP2NodeSolve.*:WP3FrameTransport.*:WP4StrainMetrics.*:WP5BoundarySeam.*:WP6Validation.*:FailureHandling.*:KDTreeLocatorTest.*:BooleanDiagnostic.*'
./build/pixi-debug/nextdrape_tests --gtest_filter="$DRAPE" > /tmp/drape-tests.txt 2>&1
```

Always redirect to a file; never pipe test output to the terminal. Diff a run
against `docs/known-issues/nd-current-fails.txt`, timing stripped — a
behaviour-neutral change leaves the failure set unchanged.

Visual check of a shape (the built-in report, not a new tool):

```bash
./build/pixi-debug/drape_cli --shape cyl-closed \
  --out /tmp/nd-out --report /tmp/nd-out/report.html
```

`drape_cli --all` runs all 17 shapes. The trap writes to raw `std::cerr`, so it
survives into the redirected file; use `tools/probes/offtrim_probe.cpp` (extend
it if it lacks a field) rather than adding an ad-hoc inspection script.

## 8. Exit criteria

1. `CoverageGeometry.BentPlateDiagnosticsPopulate` and
   `TexturePlan.BoundaryLinksLieOnTheDevelopedTrim` both green, with **no change
   to any assertion, tolerance or threshold**. For 3.2 that means the test's
   `EXPECT_TRUE(r.boundaryLinksOffTrim.empty())` passes because the detector
   finds nothing in the flat channel; for 3.1 it means `gapFraction < 0.05`
   because panel 2 is draped.
2. The `TRAP BOUNDARY-LINK-BORN-OFF-EDGE` census falls to (ideally) zero on the
   three shapes, and the creating-law histogram stops showing
   `boundary-snapped + boundary-snapped`.
3. `docs/known-issues/nd-current-fails.txt` updated to the new failing set.
4. The 2026-09-30 baseline's "current failures" table and the B9.5 tracker entry
   retired or rewritten, since they will then be stale.
5. Commit in the nextdrape submodule **and advance the superproject pointer**
   (`git -C /home/jmw/opt/FreeCAD add src/3rdParty/nextdrape`), as the
   boundary-snap handover did.

## 9. Not this task

- **Full-wrap faces still fold at the meeting line** (nose-cap holonomy;
  measured K ≈ 1–3e-6 mm⁻²): draped as one face the two circumferential fronts
  meet at the bottom with a 100–2500 mm flat mismatch, the collision gate reads
  it as double fabric and refuses the join, and a wedge stays uncovered. The
  L/R split removes it by construction — the recommended path for skins.
- Frame rings are 3 unsewn faces — the owner has said this is not a problem.
- A composite document saved from a script segfaults the GUI on restore
  (`Document::addObject`); geometry-only documents do not.

---

*Prepared from the tree at nextdrape `e708584`, FreeCAD `fem-mixmesh`, on
2026-10-11. Every number in §2 was measured on that tree, not copied from an
older baseline.*
