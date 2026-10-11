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
(study `2ad176e`), the run-report move (FreeCAD `cdb123827a`, study
`df8a50d`), and **Track A's A2** — the generic helpers and the study CLI are
Composites modules and `FuselageFem.py` is the hooks (FreeCAD `c396c90ea8`,
study `5692de7`), with the gates re-run clean on 2026-10-11 (geometry build
exit 0; `propeller/test` 130 passed / 0 failed; lc03 disp 22.399093 mm,
exposure 0.822963, λ₁ 0.7170082, mass 16288.826 g); mixed-plan **Stages 1–9** (the
mixed path is on by default, the motivating laminate wing solves, §11.1, §11.2,
§11.5, §11.6, §11.7, §11.12, §11.13 are closed); and **B9.1 / B9.1b / B9.4** —
the compound-of-solids use-after-free, the stale edge-read cache, and the
refusal of a support whose bodies do not touch, all nextdrape fixes taken into
FreeCAD by `bf5129fc5b` / `6d9f0dc10d`.  **B9.5 is open — the drape suite has
two RED acceptance canaries.  By the owner's decision it sits at the BOTTOM of
this list** (see the last section), so the mixed and donation items are taken
first; it is deferred, not accepted.

---

# Track A — WP8 step 5 (done)

Repo: study, branch `fuselage-v2-bulkhead-visibility`.  **No open item:** A1
and A2 are done and committed.

- [x] **A1 — DONE (2026-10-11).**  The four study docs record the commits and
      the 130/0 suite instead of "in flight / uncommitted" (study `ce6cdc8`),
      and this tracker was committed beside them (FreeCAD `f80227f908`).  The
      handover then gained a CONTINUATION block pointing here (study
      `c85e941`), so a reader arriving at either document lands on the same
      list.

- [x] **A2 — DONE (2026-10-11).**  The mechanics left the study for Composites
      (FreeCAD `c396c90ea8`, study `5692de7`).  The generic helpers are new
      modules under `src/Mod/Composites` — `util/build_util.py`,
      `util/object_util.py`, `util/stack_util.py`, `util/tree_util.py`,
      `tools/laminate_builder.py`, `fem/study_cli.py` — with `extreme_y_point`,
      `shape_area` and `edge_names_by_x` added to `util/geometry_util.py`; each
      has focused tests in `compositestests/`.  `FuselageFem.py` is now the
      hooks plus this airframe's spec, driven by `study_cli.main` over
      `add_arguments` / `configure` / `provenance`.  Both gates re-run clean:
      `propeller/test` 130 passed / 0 failed, and a real lc03 solve on the gate
      mesh reproduces disp **22.399093** mm, exposure **0.822963**, λ₁
      **0.7170082**, mass **16288.826 g**.

  - [x] **A2.1 — DONE.**  `BuildLog` and `silence_occt_chatter` live in
        `Composites.util.build_util`; the study names its timeline
        (`fuselage/util.py`) and imports the silencer.
  - [x] **A2.2 — DONE.**  `shape_object` and `attach_view_provider` live in
        `Composites.util.object_util`.
  - [x] **A2.3 — DONE.**  `extreme_y_point` lives in
        `Composites.util.geometry_util`; the study's copy is deleted.
  - [x] **A2.4 — DONE.**  `is_composite_geometry`
        (`util/object_util.py`) and `apply_stack_model` (`util/stack_util.py`,
        the model type now an argument).
  - [x] **A2.5 — DONE.**  `shape_area` lives in
        `Composites.util.geometry_util`.
  - [x] **A2.6 — DONE.**  `make_lamina`, `build_skin_laminate` and
        `build_frame_laminate` live in `Composites.tools.laminate_builder`;
        the stack and the whole material schedule are arguments, and the
        study's `fuselage/laminate.py` only binds this airframe's resin and
        angle set.  `build_skin_laminate` declares the laminate's volume
        fraction separately from the plies' because the study always did, so
        the gate reproduces bit for bit.
  - [x] **A2.7 — DONE.**  `apply_visibility`, `apply_review_visibility`,
        `group_top_level` (the rules an argument) and `log_drape_coverage` (the
        log callable an argument) live in `Composites.util.tree_util`; the
        airframe's name lists are `TREE_RULES` in `fuselage/geometry.py`.
  - [x] **A2.8 — DONE.**  `FuselageFem.py` is the hooks plus the study's data;
        its command line, case/load selection, refinement parsing and `Run`
        building are `Composites.fem.study_cli`, and `add_arguments` /
        `configure` / `provenance` are the seam.  The deletion half is
        unchanged: the reviewed list is **empty** and no surviving file is
        deleted (the inventory review, study `98adada`).
  - **Two constraints on all of A2** — met.  Load cases stay on the Fem batch
        contract (`step_count` + `reaction_snapshots`; `FuselageStudy.snapshot`
        is unchanged), and every knob arrives as an argument or a parsed
        option — the tests no longer monkeypatch `SELECTED_CASE`.
  - **Gate for A2** — met (see the A2 done note above).
  - **Exit for WP8 (PLAN §WP8):** the fuselage study builds, solves and reports
        through the donated driver and report, and a second part implements
        **only the hooks** with no copied mechanics.  The study now also
        delegates its command line, so a second part supplies
        `add_arguments`/`configure`/`provenance` and no CLI either.

---

# Track B — mixed shell+solid, what plan §11 leaves open

Repo: FreeCAD, branch `fem-mixmesh`.  Ordered by severity, as the plan orders
it.  "§" refers to `plan-mixed-shell-solid-fem.md`.  **New-session entry
point:** `handoff-2026-10-11-mixed-shell-solid-next.md` (Track A is closed, so
this is the only open track).

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
  - [x] **B2.2 — DONE (2026-10-11), by amending the rule.**  The plan's §8
        admission rule demanded that each case "pass in both modes" and
        `femtest/gui/test_mixed_shell_solid.py` was never written, so the rule
        stood against a tree that could not satisfy it.  Writing the GUI test
        was the wrong fix: `TestFemGui` is **not in `__unit_test__`**
        (`InitGui.py:59`, commented out 2025-10-30 for unexplained CI
        failures), so a GUI-only assertion would be run by nothing.
        The rule now names the risk instead of the mode — the deck must not
        depend on which entry point built the analysis — and §8 records why
        that holds by construction: one `setup()` builds every mixed case's
        analysis for both entry points, and each mixed example's single
        `GuiUp` branch is view-only (`constraint_mixed_face_coupling.py:114`,
        `constraint_mixed_edge_coupling.py:107`).  §11.8's GUI bullet is closed
        with the trigger to revisit (when `TestFemGui` returns to
        `__unit_test__`); its `Stiffener`/`Bulkhead` half stays open as B2.1.

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
        **Traced 2026-10-11:** the function takes only `ccxwriter`, so it cannot
        see which shell the tie's slave is, even though its caller
        `write_meshdata_constraint(f, femobj, tie_obj, ccxwriter)`
        (`write_constraint_tie.py:79`) holds the tie's resolved faces and the tie
        object.  Choosing by the master needs the signed distance from the slave
        shell's reference surface to the master plane along the shell normal —
        §11.11's `o`/`g` table — a geometry query the writer does not make
        today; today's rule (`1 if Offset < 0 else 2`) is correct only for a
        master sitting **on** the reference surface (`g = 0`).
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

- [x] **B6 — DONE (2026-10-11).**  `e1`–`e3` write and **solve**.  The
      handover's "what is missing" was wrong on the code: the mapping OCC edge →
      element edge index → `S(3 + index)` already exists —
      `calculixutils.define_masks` sets `offset = 2` in 3D, so the edge masks
      are exactly `{edge → S3-S6}` — and `write_constraint_tie.py` already
      wrote `elem,S{fno}` for a sub-element surface.  What was broken is the
      **table the edge was resolved against**: `get_subelements_by_references`
      searched `sets_getter.femelement_table`, and `get_femelement_table`
      fills that with the highest dimension only — the volumes in a mixed
      mesh — so a shell Edge matched no element and `TieSlaveFaces` came back
      empty (the loud refusal then hid the resolution bug).  Fixed in
      `femmesh/meshtools.py`: `get_elements_by_reference_dimension` case 1
      resolves an Edge whose object is a shell against the dimension-2 table
      with the edge masks (`get_dimension_tables`, factored out of
      `get_elements_by_references_of_dimension`), and
      `get_subelements_by_references` takes the table to search.
      `checksanalysis._tie_references_that_are_not_faces` narrowed to accept
      that Edge — a shell edge face *is* a surface — while an Edge on a solid,
      a Vertex and a Solid stay refused.
      **A second defect the solve exposed:** a line load on a shell edge in a
      mixed mesh wrote an empty `*CLOAD` for the same reason;
      `MeshSetsGetter.get_constraints_force_nodeloads` now selects the
      dimension-2 table for an Edge on a shell (`_edge_load_element_table`).
      e1/e3's edge faces straddle the solid's plane, so their tie tolerance is
      the shell thickness — half a thickness is what reaches the expansion
      nodes.  Verified: `test_mixed_shell_solid.py` **38 passed**, including
      `test_a_mixed_edge_deck_solves_through_the_fem_solver` for e1/e2/e3
      (`has_missed_ties()` false, non-zero displacement),
      `test_edge_tie_slave_is_the_shells_edge_face` and
      `test_edge_load_on_a_shell_reaches_the_deck`.

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
        now **stable**, same failures on every run — see B9.5 for the two that
        remain.
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
        FreeCAD `6d9f0dc10d`.  `boxes_compound` is no longer a baseline shape (it
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
| ~~A2.1–A2.8~~ done | — | — |
| B1, B2.1, B3, B5.1, B8, B9.2, B9.3 | — | — |
| B4.1 | — | B7 |
| B7 | review; B4.1 | — |

**Closed 2026-10-11, blocking nothing now:** `A1`, `A2`, `B9.1`, `B9.1b`,
`B9.4`, `B5.2`, `B5.3`, `B2.2`.  `B9.5` is deferred to the bottom of this
list, and `B2` / `B5` / `B4` / `B9` stay unticked only because a sibling
inside them is open.

Tracks A and B do not touch each other: different repos, different branches, no
shared file.

## Ordering, if worked straight through

1. ~~**A1** (commit the docs), then **B9.1**, **B5.2**, **B5.3**, **B2.2** — the
   small, self-contained cleanups.~~ **Done 2026-10-11**, together with `B9.1b`
   and `B9.4`, which the B9.1 investigation turned up.
2. ~~**B6** (the E family)~~ **done 2026-10-11**; **B4.1** — the remaining real
   defect reachable without a rebuild.
3. **B3**, **B2.1**, **B5.1**, **B8** — the ones needing a fixture.
4. **B1** — the C++ change, last because it needs a rebuild.
5. ~~**A2** — the study-side donation tail, whose gate is the lc03
   reproduction.~~ **Done 2026-10-11** (FreeCAD `c396c90ea8`, study `5692de7`).
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
