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

- [x] **B1 — §11.4, the results-viewer toggle (DONE 2026-10-11, re-scoped to
      the mesh view).**  Make a mixed result *distinguishable*: a skin
      coincident with a solid face z-fights, and none of `ColorMode` /
      `ShowInner` / `MaxFacesShowInner` separates shells from solids.
      *Cost:* a C++ view-provider change **and a rebuild** — the only item here
      with a build cost.
      - **Root cause.**  `ViewProviderFemMesh.cpp` computed
        `bool ShowFaces = (numFaces > 0 && numVolu == 0)`, so a **mixed** mesh
        took the volume-faces-only branch and the shell faces
        (`FemMesh::getFacesOnly()`, the faces belonging to no volume) were never
        emitted at all — the skin was invisible, with no knob to bring it back.
      - **Fix.**  A new `FemGui::ViewProviderFemMesh.ShowDimensions` enum
        (`All` / `Shells` / `Solids`, default `All`, group *Display Options*,
        settable from Python like any property).  `createMesh` takes it and, on
        a mixed mesh, sizes the face helper for the shells and/or the volumes
        per the mode, runs the face loop (keeping only ids in `getFacesOnly()`
        so the solid's skin is not drawn twice) and/or the volume loop; a
        non-mixed mesh has one answer and ignores the mode.  Changing the
        property rebuilds, like `ShowInner`.
      - **Re-scoped, and why.**  The plan named `ViewProviderFemMesh`, but a
        solved model is drawn by a `Fem::FemPostPipeline`
        (`Pipeline_CCX_Results`): `importCcxFrdResults.py` makes the result
        *mesh* invisible and VTK (`vtkGeometryFilter`) draws the result, emitting
        the 2-D shell cells beside the solid's boundary faces.  That view is
        **B1.1** below; B1's exit is met on the mesh object's view — show
        `..._FEMMesh` (or `CCX_Results_Mesh`), hide the pipeline, switch
        `ShowDimensions`.
      - **Premise guarded headlessly:**
        `test_mixed_shell_solid.py::test_every_variant_meshes_to_a_mixed_femmesh`
        asserts `FacesOnly` and `Volumes` are both non-empty for every face and
        edge variant, which is the split the toggle acts on.
  - [ ] **B1.1 — the VTK pipeline result view (implemented 2026-10-11,
        awaiting the visual check).**  The default result display is
        `Fem::FemPostPipeline`.
        - **Fix.**  `FemGui::ViewProviderFemPostObject.ShowDimensions` (`All` /
          `Shells` / `Solids`, default `All`, *Display Options*) feeds a
          `vtkExtractCellsByType` inserted before the four display algorithms.
          The cell types it keeps are chosen from the dataset's own
          `GetCellTypes()` summary (by `vtkCellTypes::GetDimension`), so
          `Shells` keeps the 2-D cells and `Solids` the 3-D ones; `All`, and any
          dataset holding one dimension only, pass everything through, so the
          default render is unchanged.  `ViewProviderFemPostPipeline` inherits
          the property — that is the object actually on screen.
        - **Why before `vtkGeometryFilter`.**  It turns both dimensions into 2-D
          polydata, after which nothing distinguishes a shell cell from a
          solid's boundary face.
        - *Exit:* the pipeline hides shells or solids like B1 on the mesh.  Gui
          module — no headless test; the owner's visual check.

- [x] **B2 — §11.8, coverage the plan does not reach.**  Both gaps closed:
  - [x] **B2.1 — DONE (2026-10-11).**  The real case: the Composites
        **`StiffenerFP` feature on a solid spar**.  `mixed_shell_solid_stiffener`
        (registered in `compositeexamples/registry.py`) puts a QI panel
        `Composite::Shell` on a `Part::Feature` face at the spar's top, a
        `StiffenerFP` on that panel (its own QI laminate), and couples the panel
        to the solid with a `*TIE`.  The stiffener's `<name>_Web` and
        `<name>_Foot` shells are `Composite::Shell` (via `SeamGeometryFP`), so
        the FEM section provider accepts them; each is given its own shell
        section over **every** face of its shape.  The shell assembly is meshed
        as one compound (folds stay conforming) and the solid on its own, then
        merged node-disjoint and tied.  Verified:
        `test_mixed_shell_solid_stiffener.py` **1 passed** — solves, non-zero
        displacement, deck carries `*TIE`, `*SHELL SECTION` and `*SOLID SECTION`.
        A plain-geometry mixed **bulkhead** (a shell plate in a hollow hull, four
        perimeter edge ties) is also committed as
        `test_mixed_shell_solid.py::test_a_mixed_bulkhead_couples_and_solves`, so
        the geometry-only half has a regression too (**44 passed**).
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

- [x] **B3 — DONE (2026-10-11).**  An explicit write-time check in
      `write_constraint_tie.write_meshdata_constraint`: a tie whose two surfaces
      are **both shell faces** and whose loaded slave nodes are shared with a
      `*CLOAD` is refused before its `*SURFACE` is written, naming the nodes and
      the remedy (load the master side, use a `*DLOAD`, or swap master and
      slave).  It is scoped to shell-to-shell ties because a shell slave against
      a **solid** master was measured not to collide (plan §11.9), so refusing
      those would stop decks that couple correctly.  The fixture is
      `femtest/app/test_constraint_tie_shell.py` — Dhondt's two-shell-layer
      arrangement built as a hand-made `FemMesh` (lower z=0, upper z=1, t=1, so
      the upper's S1 meets the lower's S2) — and it **reproduces the hazard**:
      ccx reports the loaded nodes "already constrained".  Verified:
      `test_a_load_on_the_shell_slave_is_refused` (the check names nodes 5-8 and
      the remedy) and `test_a_load_on_the_master_side_writes_and_solves` —
      **2 passed**; `test_mixed_shell_solid.py` 43 passed and the Composites
      numerical 7 passed, so the f-family is untouched.

- [ ] **B4 — §11.11, the parked offset question and its latent bug.**  Parked,
      **not scheduled** — the research is recorded so it is not repeated.
      Extract only the one real defect from it:
  - [x] **B4.1 — DONE (2026-10-11).**  The tie names the expanded face nearest
        the master, from the slave's **own** section.  `_shell_slave_face` now
        takes the tie's resolved references and (1) finds the `ShellThickness`
        that sections the slave (`femutils.member_for_reference`, promoted from
        the body-heat-source writer's private copy), (2) measures the signed gap
        from the slave's reference surface to the master plane along the shell
        normal, and (3) picks `S1`/`S2` by the near face — which at `g = 0`
        reduces exactly to the old offset rule, so the existing offset test is
        unchanged.  The geometry is one shared definition
        (`mixedcoupling.shell_expansion_faces`, `tie_slave_side_and_tolerance`,
        `planar_face`) used by the writer and the checker alike.
        `checksanalysis` now **refuses** a tie whose `Tolerance` is below the
        chosen face's distance from the master — naming both faces, both
        numbers and the landing offset (`±0.5 − g/t`) — instead of writing a
        deck that couples nothing (the handover said "warn"; the write is
        blocked, which is what the §11.11 exit asks for).  Verified:
        `test_mixed_shell_solid.py` **43 passed** (the geometry rule, the
        per-section lookup, the refusal, and a landing-offset solve with no
        untied node), and `test_mixed_coupling_numerical.py` **6 passed**,
        which also confirms f3/f4 now couple through their near face.
  - *Not scheduled:* making the offset land an expansion node on the contact
      plane (`o = g/t − 0.5`).  The requirement is **per tie pair, not per
      shell**, and it moves material through the thickness — it can at most be
      *reported*.

- [ ] **B5 — §11.3 residual.**  All four face families solve with zero untied
      nodes, but:
  - [x] **B5.1 — DONE (2026-10-11).**  Decided: the offset and bag families get
        **no** compared pair, and the reason is recorded.  A compared pair needs
        an *independent* reference, and only F1/F2 have one — their interface is
        a coincident bond, so the all-solid rebuild (a slab resting on the spar)
        is a separate structure.  F3/F4 are 50 mm stand-offs; an all-solid
        "equivalent" would have to span the same deliberate gap with the same
        `*TIE`, so it would hang on the comparison's own tie rather than on an
        independent bond.  Their detector stays the coupling count
        (`not_coupled == 0`) plus a new non-zero-displacement assertion — a
        coupled-but-degenerate solve (load never reached the mesh) is now caught
        for all four families.  Recorded in
        `test_mixed_coupling_numerical.py`'s docstring and the fixture's.
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

- [x] **B7 — §12, assign the ties from the references the model already
      carries.**  **Status: DONE (2026-10-11)** — implemented as the headless
      helper `Composites.fem.auto_tie.auto_tie`.  The proposal below is kept as
      the reasoning; the outcome, the decisions and two findings follow it.
      The original proposal: a pass that (1) collects solids from dimension-3
      material references, (2) collects the
      composite shells that declare one of those solids — as `SupportReference`
      or `Support` — and (3) creates one `Fem::ConstraintTie` per shell, shell
      reference first, with a **derived** tolerance.  It must be an explicit
      command/helper that creates tie objects — **not** something the writer or
      `meshsetsgetter` invents, which would be coupling no object records.
      **Pairing is object identity, not geometry:** no parallel normals, no
      planes, no coincidence tolerance.
      *Preconditions:* an opt-out and a report (a shell declared on a solid that
      is deliberately not bonded); a derived tolerance; B4.1 (per-shell slave
      lookup) — **landed**; the mesh-disjointness rule (`mesh_parts_separately`,
      Trap A) **checked and refused**, not assumed; and **B7.1** below, which
      carries the face names.
      *Exit:* on a model that follows the convention, the pass produces the same
      `*TIE` set as the hand-written `add_tie`, up to names, and a second run
      creates nothing new.  **The wing and the plate do not follow it** (they
      declare separate support objects), so they keep their hand-written ties
      and are not the exit's subject.
  - [x] **B7.1 — DONE (2026-10-11).**  `Composite::Shell` gains an optional
        `App::PropertyLinkSubGlobal` `SupportReference` holding
        `(solid, ["FaceN", ...])`; `Support` is untouched, so existing documents
        load unchanged.  Three resolvers — `support_object`, `support_shape`,
        `support_placement` — prefer the reference when set; the ~14 CompositeShell
        read sites and `TexturePlan` go through them.  `StiffenerCompositeShell`
        needed no change: it re-points the panel *object*, and the panel's own
        `.Shape` is already the resolved surface.  `getSubObject` returns a
        *list* of shapes, which the resolver unwraps (a compound for several
        faces) — recorded here because it is not obvious from the API.
        Verified: `test_composite_shell.py` `TestCompositeShellSupportReference`
        **4 passed** (whole-object support unchanged; the named face resolves;
        the reference wins over `Support`; the shell's own shape follows it).
      **Outcome (2026-10-11).**  `Composites.fem.auto_tie.auto_tie(analysis)`
      collects the bonded solids from the analysis' dimension-3 material
      references, collects the `Composite::Shell` objects whose
      `SupportReference[0]` is one of them, and creates one
      `Fem::ConstraintTie` per shell through `femtools.mixedcoupling.add_tie` —
      slave first, tolerance derived, nothing invented by the writer or
      `meshsetsgetter`.  Pairing is **object identity**
      (`support_object(shell) is solid`); no geometry, no picked tolerance.
      - **Decisions taken** (from the six open questions): a headless helper
        only, in Composites — no command yet; the opt-out is a per-shell
        `AutoCouple` bool (default True) on `Composite::Shell`; a new small
        convention-following example plus tests is the exit model; an empty
        pass returns `[]`.
      - **Mesh rule checked and refused** before anything is created: the pass
        requires a mesh, refuses a non-mixed one, and refuses one whose shell
        shares a solid's nodes (`FacesOnly` empty, or overlapping node sets) —
        Trap A, and why it runs after meshing.
      - **Exit met.**
        `compositeexamples/examples/mixed_shell_solid_auto_tie.py` declares the
        skin on the spar's own face; the pass creates the tie and the model
        solves with no uncoupled node, and a second run creates nothing
        (`test_auto_tie.py`, **4 passed**).  The wing and the plate keep their
        hand-written ties and are not touched.
      - **Finding 1 — the slave reference is the shell, not the solid.**  A face
        whose object is a solid resolves to a *volume* sub-element
        (`meshtools.get_elements_by_reference_dimension`,
        `_reference_object_is_solid`), so `(solid, "FaceN")` as the slave would
        name the same surface as the master and couple nothing.  The slave is
        `(shell, "Face1")`, which is also the reference the section carries, so
        `member_for_reference` finds the section.  The examples pass a separate
        support object as the slave and so never exercised B4.1's per-shell
        lookup.
      - **Finding 2 — the expansion thickness is the laminate's total, not the
        FEM section's `Thickness`.**  `_add_shell_section_and_material` makes a
        0.8 mm placeholder; the composite provider replaces the `*SHELL SECTION`
        geometry with the laminate's merged `FEMLayers` (1.6 mm for the QI
        example) at write time.  Deriving from the placeholder wrote 0.4 mm
        where CalculiX expands at ±0.8 mm, leaving the four corner nodes
        uncoupled (the plate's hand-picked 1.0 hid it).  The pass reads the
        laminate total and writes `required * (1 + 1e-3)`, because CalculiX's
        gate drops a node whose distance *reaches* the tolerance.
      - **Follow-up — fixed the same day.**  `checksanalysis._tie_tolerance_message`
        and `write_constraint_tie._shell_slave_face` read the section's
        placeholder `Thickness` (and an `Offset` routed only at write time), so
        B4.1's guard under-estimated the requirement for laminate sections.  Both
        now call `femtools.mixedcoupling.shell_section_dimensions`, which asks a
        new registry seam (`register_shell_section_dimension_provider`) for the
        values the deck writes — the composite provider registers the laminate
        total and the shell's offset — and falls back to the object's own
        properties for a plain section.  The B7 pass uses the same helper.  The
        face *choice* stays thickness-independent.  Verified:
        `test_auto_tie.py::test_the_tolerance_refusal_reads_the_laminate_the_deck_expands`
        refuses a 0.5 mm tie where the placeholder computed only 0.4 mm required.
      - **Limit of the first cut:** one face per shell.  A `SupportReference`
        naming several faces raises rather than guess a slave face per master.

      Verified: `test_auto_tie.py` 5 passed; `test_mixed_coupling_numerical.py`
      7 passed; `test_mixed_shell_solid_stiffener.py` 1 passed; Fem
      `test_mixed_shell_solid.py` 44 passed; `test_constraint_tie_shell.py`
      2 passed; `test_fem_extension_registry.py` 5 passed;
      `test_drape_laminate_provider.py` green; `test_composite_shell.py` green
      (19 passed, the B9.6 errors fixed).

- [x] **B8 — DONE (2026-10-11).**  The feature had already landed
      (`0542b6ba22`, 2026-10-09): `CompositeShell.Offset` is the per-skin
      property and `drape_laminate_provider.route_shell_offset` writes it into
      `ShellThickness.Offset` before the section card is built, with unit tests
      for the default, the deck routing and two skins taking opposite signs.
      The note here had gone stale — its grep looked in `objects/` and
      `util/fem_util.py`, and the code is in `features/` and `fem/`.  **What was
      actually missing is the exit criterion**, the stiffness check that pins
      the sign: the cantilever probe now also builds the same mixed model with
      the section on its **mid-surface** (`offset = 0`) and
      `test_the_section_offset_stiffens_the_skin` asserts the offsetted one is
      stiffer.  Measured: offsetted **6.422333e-02 mm**, mid-surface
      **9.179597e-02 mm** (1.43x softer), all-solid **6.416312e-02 mm**
      (0.09 %, inside the stated 5 %).  A reversed sign would come out softer
      than the mid-surface model, and that is the assertion.

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
  - [x] **B9.6 — DONE (2026-10-11).** `TestCompositeShellOffset`'s three deck
        tests errored in `write_femelement_geometry.py:198`, which reads
        `ccxwriter.mesh_object.FemMesh` for a composite section, while the
        test's `_StubCcxWriter` never had a `mesh_object`.  **The stub was
        wrong, not the guard.**  It also passed `ccx_elset=True`, which the
        writer never produces — the field is a list of element ids or a set
        name (`meshsetsgetter`) — and the guard's job, refusing a layered
        section on a linear shell, is real and needs a mesh to count nodes.  The
        stub now carries a one-quad8 `FemMesh` (`_quadratic_shell_mesh`) and
        `ccx_elset=[1]`, so the card the tests assert is written through the
        same path the writer takes.  The guard is untouched; its refusing
        branch stays covered in Fem's `test_mixed_shell_solid.py`.  Verified:
        `test_composite_shell` **19 passed, 0 errors**.

---

## Dependencies, in one place

| item | blocked by | blocks |
|---|---|---|
| ~~A2.1–A2.8~~ done | — | — |
| B1.1, B9.2, B9.3 | — | — |

**Closed 2026-10-11, blocking nothing now:** `A1`, `A2`, `B1`, `B9.1`,
`B9.1b`, `B9.4`, `B9.6`, `B5.1`, `B5.2`, `B5.3`, `B2.1`, `B2.2`, `B3`,
`B6`, `B4.1`, `B7`, `B7.1`, `B8`.  `B9.5` is deferred to the bottom of this
list, and `B5` / `B4` / `B9` stay unticked only because a sibling inside them is
open.

Tracks A and B do not touch each other: different repos, different branches, no
shared file.

## Ordering, if worked straight through

1. ~~**A1** (commit the docs), then **B9.1**, **B5.2**, **B5.3**, **B2.2** — the
   small, self-contained cleanups.~~ **Done 2026-10-11**, together with `B9.1b`
   and `B9.4`, which the B9.1 investigation turned up.
2. ~~**B6** (the E family)~~ and ~~**B4.1**~~ **both done 2026-10-11** — the
   two real defects reachable without a rebuild.
3. ~~**B3**, **B2.1**, **B5.1**, **B8**~~ — the ones needing a fixture:
   **all four done 2026-10-11**.
4. ~~**B1** — the C++ change, last because it needs a rebuild.~~ **Done
   2026-10-11** on the mesh view; the VTK pipeline result view is `B1.1`.
5. ~~**A2** — the study-side donation tail, whose gate is the lc03
   reproduction.~~ **Done 2026-10-11** (FreeCAD `c396c90ea8`, study `5692de7`).
6. ~~**B7** — the tie pass, implemented as the headless `auto_tie` helper with
   its own example and tests.~~ **Done 2026-10-11**, with the B4.1 follow-up
   (the checks read the section the deck writes).

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

      **Read first:** `handoff-2026-10-11-b95-rim-birth-law.md` (this
      directory) — a full handover for B9.5, measured on nextdrape `e708584`.
      It corrects the note above in one way that matters: the two red tests are
      **two different defects**.  `BentPlateDiagnosticsPopulate`
      (`gapFraction` 0.5) is the **pitch-resonance fold stall** (the march
      lands a node exactly on the crease at `20 + 14×5 = 90`; the seam trace
      and the mixed-cell route both bail), not a boundary link at all.
      `BoundaryLinksLieOnTheDevelopedTrim` is the rim-link class, and it is
      measured in the **flat channel** (`DetectBoundaryLinksOffTrim`,
      `QualityMetrics.cpp:1711`) — a node can sit on the 3D edge and still
      develop off the outline.  Only 3 of 17 baseline shapes fail it today:
      cyl-closed **23**/198 (worst 36 mm), cubic **2**/133 (6.73 mm), web_band
      **52**/351 (40 mm).
