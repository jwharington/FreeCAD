# TODO — all outstanding work, both tracks

**Date:** 2026-10-11 · **Scope:** every work item open as of this date across the
two tracks that are currently live.  This file is only the **ordered list and
the state**: each item names what closes it and what blocks it.  The reasoning
lives in the documents each item cites — the handover, the plan and the reviews.

Two tracks, independent of each other:

| track | repo | branch | the document that owns the reasoning |
|---|---|---|---|
| **A — LS8e FEM donation, last step (WP8)** | `~/Desktop/Projects/RTOA/LS8e` | `fuselage-v2-bulkhead-visibility` | `Design/ls8e-design-tools/propeller/cad/HANDOVER-2026-10-11-fuselagev2-modularisation.md`, `cad/PLAN-ls8e-fem-donation-2026-10-11.md`, `cad/REVIEW-2026-10-11-femstudy-is-a-workbench.md` |
| **B — mixed shell+solid FEM** | `/home/jmw/opt/FreeCAD` | `fem-mixmesh` | `src/Mod/Composites/docs/plan-mixed-shell-solid-fem.md`, `docs/adr/0004-shell-solid-coupling-and-interface-dimension.md` |

**Not listed here:** unrelated working-tree files in either repo (loose images,
PDFs, generated result trees), and the wider Composites backlog in
`docs/known-issues.md`.

**Already done and verified (do not re-open):** the `FuselageV2.py` split
(study `2ad176e`) and the run-report move (FreeCAD `cdb123827a`, study
`df8a50d`), with both gates re-run clean on 2026-10-11 (geometry build exit 0;
`propeller/test` 130 passed / 0 failed); mixed-plan **Stages 1–9** (the
mixed path is on by default, the motivating laminate wing solves, §11.1, §11.2,
§11.5, §11.6, §11.7, §11.12, §11.13 are closed); and **B9.1 / B9.1b / B9.4** —
the compound-of-solids use-after-free, the stale edge-read cache, and the
refusal of a support whose bodies do not touch, all nextdrape fixes taken into
FreeCAD by `bf5129fc5b` / `6d9f0dc10d`.  **B9.5 is open — the drape suite has
two RED acceptance canaries.  By the owner's decision it sits at the BOTTOM of
this list** (see the last section), so the mixed and donation items are taken
first; it is deferred, not accepted.

---

# Track A — WP8 step 5, and the doc commit

Repo: study, branch `fuselage-v2-bulkhead-visibility`.

- [ ] **A1 — commit the stale-doc updates.** Four study files are edited and
      uncommitted: `cad/HANDOVER-2026-10-11-fuselagev2-modularisation.md`,
      `cad/PLAN-ls8e-fem-donation-2026-10-11.md`,
      `cad/REVIEW-2026-10-11-femstudy-is-a-workbench.md`,
      `cad/REVIEW-2026-10-11-fem-donation-and-study-adoption.md` — they now
      record the commits above and the 130/0 suite instead of "in flight /
      uncommitted".  *Exit:* `git status` clean for those four paths.
      *Blocks:* nothing.  *Do first* — it makes the rest of the file's citations
      point at committed text.

- [ ] **A2 — WP8 step 5: the mechanics leave the study.**  Lift the generic
      helpers out of `cad/fuselage/`, reduce `FuselageFem.py` to the hooks, and
      delete what is left of `propeller/cad` that exists only for the old
      driver.  Handover §6 measured **267 lines** of unambiguous helper, up to
      **435** once the laminate builders and tree rules are parameterised.
      Sub-items, in the order the blockers allow:

  - [ ] **A2.1 — `_log`, `_silence_occt_chatter`, `_timed`** (in
        `cad/fuselage/util.py`) → a Composites **build util**.  *Blocker:* none;
        they are already neutral.
  - [ ] **A2.2 — `_attach_vp`, `_shape_object`** (`util.py`) →
        `Composites.util` (VP attach is generic; `_shape_object` is a
        `Part::Feature` from a shape).  *Blocker:* none.
  - [ ] **A2.3 — `_extreme_y_point`** (`cad/fuselage/skin.py`) →
        `Composites.util.geometry_util`.  *Blocker:* none.
  - [ ] **A2.4 — `_is_composite_geometry`, `_apply_stack_model`**
        (`cad/fuselage/fem.py`) → `Composites.util` / `mechanics` (it is
        `StackModelType` policy).  *Blocker:* none.
  - [ ] **A2.5 — `_area`** (`cad/fuselage/partition.py`) →
        `util/geometry_util`.  *Blocker:* none; trivial.
  - [ ] **A2.6 — the laminate builders** `_make_lamina`,
        `build_skin_laminate`, `build_frame_laminate`
        (`cad/fuselage/laminate.py`) → a Composites laminate module.
        *Blocker:* their stack defaults (`SKIN_PLY_STACK`, `QI_PLY_THICKNESS`)
        must first become **arguments**.  Depends on A1 only for the doc trail.
  - [ ] **A2.7 — the tree rules** `_group_top_level`, `_apply_visibility`,
        `_log_drape_coverage` (`util.py`, `geometry.py`) → a Composites
        document/tree util.  *Blocker:* the fuselage's **name lists** must first
        become a rules argument (they name this airframe's objects).
  - [ ] **A2.8 — reduce `FuselageFem.py` to the hooks, and delete the dead
        `propeller/cad`.**  The hooks are `build(arguments)`,
        `geometry_arguments()`, `parts(doc)`, `constraints(doc, analysis)`,
        `snapshot(case)`, and optionally `mesh_name`, `laminates(doc)`.
        *Blocker:* A2.1–A2.7 land first, or the deleted copies are still the
        only copy.
  - **Two constraints on all of A2.**  Load cases stay on the Fem batch
        contract — `step_count` + `reaction_snapshots = [study.snapshot(case) …]`,
        never per-case `*CLOAD` blocks or one deck per case — so the same model
        stays drivable by **FemLink**.  And **no monkeypatching**: a knob
        arrives as an argument (as `band_ply_stack(base, schedule=None)` now
        does), never by moving a module global.
  - **Gate for A2:** `propeller/test` stays **130 passed / 0 failed**, and a
        real lc03 solve reproduces disp **22.3991 mm**, exposure **0.823**, λ₁
        **0.717** through the Composites driver.
  - **Exit for WP8 (PLAN §WP8):** the fuselage study builds, solves and reports
        through the donated driver and report, and a second part implements
        **only the hooks** with no copied mechanics.

---

# Track B — mixed shell+solid, what plan §11 leaves open

Repo: FreeCAD, branch `fem-mixmesh`.  Ordered by severity, as the plan orders
it.  "§" refers to `plan-mixed-shell-solid-fem.md`.

- [ ] **B1 — §11.4, the results-viewer toggle.**  Make a mixed result
      *distinguishable*: today a skin coincident with a solid face z-fights, and
      `ViewProviderFemMesh.VisibleElementFaces` is a **read-only computed
      getter** (`src/Mod/Fem/Gui/ViewProviderFemMeshPyImp.cpp`) with no
      dimension filter; `ColorMode` / `ShowInner` / `MaxFacesShowInner` do not
      separate shells from solids.  *Cost:* a C++ view-provider change **and a
      rebuild** — the only item here with a build cost.
      *Exit:* a toggle that hides one dimension, with the mixed wing and plate
      still displaying.

- [ ] **B2 — §11.8, coverage the plan does not reach.**  Two gaps:
  - [ ] **B2.1 — Stiffener / Bulkhead mixed coverage.**  `quasi_iso_stiffener_panel`
        is all shells; Bulkhead has no FEM example at all.  *Exit:* a mixed
        case that puts a shell stiffener or bulkhead on a solid feature.
  - [ ] **B2.2 — the GUI half of §8.**  `femtest/gui/test_mixed_shell_solid.py`
        does not exist, so §8's rule (*a case passes in both modes*) is unmet
        and the matrix is headless-only.  *Exit:* write the test **or** amend
        the rule — do not leave the rule standing against a tree that does not
        satisfy it.

- [ ] **B3 — §11.9, the `*CLOAD`-on-a-tie-slave hazard.**  A point force in a
      shell node is applied to an *expansion* node (`gen3dforc` writes the
      expansion MPC with the expanded node dependent), so a tied node can no
      longer be dependent and `gentiedmpc` drops the tie under a warning
      FreeCAD classifies as benign ("already constrained").  *Closing action:*
      a **write-time check** that reports a tie whose shell slave carries a
      `*CLOAD` node, naming the nodes and the remedy (swap master/slave, or load
      the master side).  *Blocker on the test:* the mixed face families f1–f4
      are **not** exposed (load/no-load runs are identical, `.nam` byte-identical),
      so the fixture must be built as **Dhondt's two-shell-layer arrangement**,
      not found in ours.  *Exit:* that fixture fails the check before it is
      written and asserts the remedy afterwards.

- [ ] **B4 — §11.11, the parked offset question and its latent bug.**  Parked,
      **not scheduled** — the research is recorded so it is not repeated.
      Extract only the one real defect from it:
  - [ ] **B4.1 — `_shell_slave_face` picks the wrong side.**
        `src/Mod/Fem/femsolver/calculix/write_constraint_tie.py:60-77` takes
        `S1`/`S2` from the **first** non-suppressed `geos_shellthickness` offset
        in the analysis and never consults the master, so with a sandwich's two
        opposite offsets one tie names the far face — a whole thickness out,
        silent, and today only unexposed because every fixture and example uses
        offset 0.  *Order if picked up:* (1) choose the slave face from the
        master's side; (2) derive the required tolerance in `checksanalysis`
        from geometry and **warn** when `tolerance < required`, naming faces,
        both numbers and the remedy; (3) only then set an offset in a fixture.
  - *Not scheduled:* making the offset land an expansion node on the contact
      plane (`o = g/t − 0.5`).  The requirement is **per tie pair, not per
      shell**, and it moves material through the thickness — it can at most be
      *reported*.

- [ ] **B5 — §11.3 residual.**  All four face families solve with zero untied
      nodes, but:
  - [ ] **B5.1 — only F1 has a compared-pair displacement check.**  The offset
        and bag families have no natural all-solid equivalent; decide whether to
        build one for each, or state why the check cannot exist per family.
  - [x] **B5.2 — DONE (2026-10-11).**  The mixed suite now solves once:
        `test_a_mixed_face_deck_solves_through_the_fem_solver` (a
        `@pytest.mark.slow` function) runs the f1 face-coupling example
        through `FemToolsCcx.run()` and asserts ccx accepts the deck and a
        result is read back.  What the result *means* stays with the
        Composites suite's `test_mixed_coupling_numerical.py`, which drives
        the composite pipeline — the division is stated in the test's own
        docstring, because this file's 31 structural fixtures carry no
        constraints and no loads and cannot be solved.  Verified:
        **32 passed** in 2.9 s.  (The `slow` marker is unregistered repo-wide,
        so this test warns exactly as the existing slow Fem tests do.)
  - [x] **B5.3 — DONE (2026-10-11).**  The skip lists named
        `"Mesh generation failed"` among the reasons to treat a build as
        lacking the FEM stack, so a genuine meshing failure was skipped
        instead of failing — the one thing those examples exist to catch.
        Removed from all five sites (`test_compositeexamples.py` × 4,
        `test_integration_freecad.py` × 1), and the four copies in the first
        file collapsed into one `MISSING_FEM_STACK_MARKERS` constant, which
        now names only genuine absence: no `ObjectsFem`, no analysis/solver/
        mesher factories, no `femtools.ccxtools`.  Verified: the two modules
        are 37 tests / 0 failed (6 skips, all GUI-in-headless).  The
        `test_mixed_shell_solid_plate_solves` and `_wing_solves` solver tests
        still pass.

- [ ] **B6 — the E (edge-interface) family.**  `e1`–`e3` are **refused loudly,
      not solved**.  ADR 0004 puts the family **in scope** and selects the same
      mechanism (`*TIE`, shell edge face S3–S6 → solid face); the blocker is
      FreeCAD's reference→surface mapping —
      `meshsetsgetter.get_constraints_tie_faces` supplies faces only.
      *First-choice fix:* let an Edge selection on a shell yield its edge face.
      `*EQUATION` stays the fallback.  *Exit:* `e1`–`e3` write and solve, and
      the loud refusal in `checksanalysis._tie_references_that_are_not_faces`
      narrows to genuinely inexpressible connections.

- [ ] **B7 — §12, assign the ties from the references the model already
      carries.**  **Status: proposal — review before any code.**  A pass that
      (1) collects solids from dimension-3 material references, (2) collects
      shell faces from shell-thickness references, (3) pairs them (parallel
      normals, planes within a tolerance), (4) creates one `Fem::ConstraintTie`
      per pair, shell reference first, with a **derived** tolerance.  It must be
      an explicit command/helper that creates tie objects — **not** something
      the writer or `meshsetsgetter` invents, which would be coupling no object
      records.  *Four preconditions:* over-coupling is the default failure
      (per-interface opt-out, a report, `COINCIDENT_TOLERANCE = 1e-6`); the
      tolerance must be derived, not typed; it **depends on B4.1** (per-shell
      slave lookup); and the mesh-disjointness rule (`mesh_parts_separately`,
      Trap A) must be **checked and refused**, not assumed.  *Out of scope for a
      first cut:* edge interfaces, multi-stage/contact ties, the task panel.
      *Exit:* on the wing and the plate, replacing their hand-written
      `add_tie` calls produces the same `*TIE` set up to names, the deck
      snapshot still reports *no deck changed*, and a second run creates nothing
      new.

- [ ] **B8 — §10, a per-skin laminate OFFSET.**  Adjacent to the plan and
      adoptable **out of order**: give the Composites laminate a per-skin offset
      and route it into FEM's `ShellThickness.Offset` (the writer already emits
      `OFFSET=`; a grep finds no offset in `src/Mod/Composites/objects/` or
      `util/fem_util.py`, so the leaf is missing).  Two design points: the
      offset must be **per skin, not per analysis**, and the **sign is
      load-bearing** (reversed signs make a sandwich *softer than no offset at
      all*, with nothing in a fringe plot to say so).  *Exit:* a shell-only
      sandwich matches an equivalent solid model within a tolerance stated
      before the run, and is measurably **stiffer** than the un-offsetted one —
      if it comes out softer, the sign is wrong.

- [ ] **B9 — §11.10, housekeeping and deliberate leftovers.**
  - [x] **B9.1 — DONE (2026-10-11).** The `test_rosette_scenarios` SIGSEGV was a
        **use-after-free in nextdrape**, not the guard.  Measured on a synced
        tree: a compound of two *disjoint, convex, planar-faced* boxes crashed
        too, so the fixture's overlap was never the trigger and any compound of
        solids did.  `SweepSlot` took a raw `Node*` from the placer,
        `MaterialiseSlotRecord` then grew the node array and freed the buffer
        that pointer referred to, and the fold law read the freed node — its
        face handle came out null and reached `FaceGeometryCache::For`.  GDB
        showed the pointer outside the live array.  Fixed by re-fetching the
        source and target after materialising (nextdrape `274341e`), with
        `boxes_compound` as the regression fixture; it now drapes and joins
        `BaselineShapeNames`.  FreeCAD `bf5129fc5b`.
        **Not the fix:** widening `_require_drapable_shape` — a compound of
        solids is a legitimate drape support, so refusing it removes a
        capability instead of repairing the crash.
  - [x] **B9.1b — DONE (2026-10-11).** The investigation turned up a second,
        systemic defect: `DiscretisedEdge` cached polylines in a never-cleared
        static keyed by a raw `TShape` pointer while holding only the polyline,
        so a later edge allocated at the same address read another edge's
        polyline.  The drape suite was order-dependent and nondeterministic —
        6-9 failures with a different set every run, and a five-test prefix
        that failed repeatedly then stopped failing under valgrind (whose
        allocator makes the aliasing benign), which is what identified a stale
        key rather than a memory error.  Fixed by holding the edge in the entry
        and clearing the cache per solve (nextdrape `964dfcf`).  The suite is
        now **stable at 194 ok / 2 failed** across repeated runs.
  - [x] **B9.4 — DONE (2026-10-11).** The question was settled by the owner as a
        rule: a compound whose bodies are apart, or touch only at a point, is
        not a drape support and must be refused with an error code.  The check
        reuses the connectivity code that already exists —
        `SplitIntoConnectedFaceGroups` for the components and
        `seam::SharedEdges` (whole edges matched by endpoint, so a shared
        corner is not a joint) for the link — and the drape returns
        `DrapeStatus::InvalidInput` with a `shape-disconnected` diagnostic.
        Bodies joined along an edge or a face still merge as before, so the
        two-island panel remainder is unaffected.  nextdrape `e708584`,
        FreeCAD `<bump>`.  `boxes_compound` is no longer a baseline shape (it
        is refused by design); `drape_cli --all` is 17/17 `status=ok`.
  - [ ] **B9.2 — delete the flag getter and its branches** —
        `femsolver/settings.py::get_allow_mixed_elements` and its call sites —
        **after one release has shipped** with the default on.  Deliberate, not
        overdue.
  - [ ] **B9.3 — decide the branch's fate.**  All commits are on `fem-mixmesh`
        off `fem-unified`, unmerged, unreviewed, unupstreamed, and **no PR is
        planned** — it is the working record.  *Exit:* keep that decision
        explicit (this line), or open the PR.

---

## Dependencies, in one place

| item | blocked by | blocks |
|---|---|---|
| A1 | — | (doc trail only) |
| A2.1–A2.5 | — | A2.8 |
| A2.6 | stack defaults become arguments | A2.8 |
| A2.7 | name lists become a rules argument | A2.8 |
| A2.8 | A2.1–A2.7 | — |
| B1–B3, B5, B6, B8, B9 | — | — |
| B4.1 | — | B7 |
| B7 | review; B4.1 | — |
| B2.2 | decision: write the test or amend §8's rule | — |

Tracks A and B do not touch each other: different repos, different branches, no
shared file.

## Ordering, if worked straight through

1. **A1** (commit the docs), then **B9.1**, **B5.2**, **B5.3**, **B2.2** — the
   small, self-contained cleanups.
2. **B6** (the E family) and **B4.1** — the two real defects that are reachable
   without a rebuild.
3. **B3**, **B2.1**, **B5.1**, **B8** — the ones needing a fixture.
4. **B1** — the C++ change, last because it needs a rebuild.
5. **A2** — the study-side donation tail, whose gate is the lc03 reproduction.
6. **B7** — after **B4.1** lands and the proposal has been reviewed.

---

# Bottom of the list — deferred by the owner (2026-10-11)

Parked, not forgotten, and not accepted: a failing test is a defect.  These are
at the bottom by the owner's decision, so that the mixed and donation items
ahead of them are taken first.

- [ ] **B9.5 — the drape suite's acceptance canaries are RED.**  The suite is
      **197 passed / 2 failed**, and both failures reproduce unchanged on
      pristine `aba05cc` with none of the B9.1 work applied — pre-existing, not
      caused by it:
      - `CoverageGeometry.BentPlateDiagnosticsPopulate`
        (`test_coverage_geometry.cpp:235`): `gapFraction` **0.5** against a
        required < 0.05, on `MakeBentPlate(90, 100, 90, 30)`.
      - `TexturePlan.BoundaryLinksLieOnTheDevelopedTrim`:
        `boundaryLinksOffTrim` non-empty — **cyl-closed 23, cubic 2,
        web_band 52**.

      Both are the documented `BOUNDARY-LINK-BORN-OFF-EDGE` defect firing: rim
      cells are refused by the single-neighbour and two-neighbour laws and are
      never healed, so a boundary link is born spanning the empty gap — 15-28 mm
      against a 5 mm pitch — and the fabric stops short of the part edge.  That
      uncovered strip is the `gapFraction`.  `QuadBuilder.cpp:752`
      (`OneSidedLinkStopsShort`) marks the link a fabric cut; `:769` traps it.
      **The fix is the birth law** — never the assertions and never the
      thresholds.  *First step:* the acceptance gate that refuses the rim cell
      is named by the reject-gate diagnostic (`LastRejectGate()`), which is
      already surfaced.
