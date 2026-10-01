# Plan: Mixed shell + solid elements in one FEM analysis

**Date:** 2026-09-02 → *use 2026-10-02 in the document header* · **Status:** proposed

## Summary

FreeCAD's FEM pipeline assumes **one element dimension per analysis**. That assumption is enforced independently at four layers, so no single change unlocks mixed shell+solid models. This plan removes them in eight increments, ordered so that **the shipped behaviour is never worse at the end of any stage than at the start**, and the new path stays behind one off-by-default switch until it is complete.

The deliverable is a plan document at `src/Mod/Composites/docs/plan-mixed-shell-solid-fem.md`, followed by the code work it stages.

**Step 0 of implementation:** write this plan to `src/Mod/Composites/docs/plan-mixed-shell-solid-fem.md`, in the house style of `docs/fem-shell-mesh-continuity.md` (dated `**Date:** 2026-10-02 · **Status:** proposed` header, `##` sections, inline `path:line` code references, summary table at the end).

---

## Why it is blocked today (verified in source)

| # | Layer | Location | Effect |
|---|---|---|---|
| 1 | Validation | `src/Mod/Fem/femtools/checksanalysis.py:305-320` (also `:267-280`, `:97-113`) | `"Shell thicknesses defined but FEM mesh has volume elements."` aborts the run in `check_prerequisites` (`femtools/ccxtools.py:267`, `femsolver/calculix/calculixtools.py:66`) before any deck is written |
| 2 | Mesh writer | `femsolver/calculix/write_mesh.py:37` (`element_param = 1`) + `src/Mod/Fem/App/FemMesh.cpp:1987`, `:2028` | With volumes present, face/edge elements are never written — no `*Element,TYPE=S8R`, no `Efaces`/`Eedges` elsets |
| 3 | Element tables | `femmesh/meshtools.py:142-156` (`get_femelement_table` → highest dim only), `:1543-1600` (`get_elements` computes one `model_dim` for the whole mesh), `:1951-1976` (`is_*_femmesh` mutually exclusive), `:229-296` (bit-pattern classification keys on **node count**) | All geometry-reference → element resolution uses one dimension table; a mixed node-count table is ambiguous (tetra4 vs quad4, penta6 vs tria6, hexa8 vs quad8) |
| 4 | Material × geometry | `femmesh/meshsetsgetter.py:950-976`, `:978-1040` | Each material member has one `"FEMElements"` slot; with volumes present the solid branch and the shell branch overwrite each other. Self-documented: *"does not work for mixed meshes and multiple materials, this is checked in check_prerequisites"* |

Already half-built: `meshsetsgetter.get_constraints_fixed_nodes:288-307` and `write_constraint_fixed.py:56-98` split nodes into `NodesSolid` (DOF 1-3) / `NodesFaceEdge` (DOF 1-6) under the comment *"if mixed mesh with solids the node set needs to split"*. Displacement (`write_constraint_displacement.py:86`), PlaneRotation, Transform and RigidBody have **no** such split. `write_step_output.py:33-44` picks `*NODE FILE OUTPUT=2d/3d` for the whole model.

CalculiX itself is not the constraint. `meshsetsgetter.py:950-953` and `membertools.get_mesh_to_solve` (*"multiple meshes in analysis are not supported yet"*) are.

## Locked decisions (defaults recorded; user was offered the choice and declined)

1. **Fix lands in `src/Mod/Fem`** (core pipeline), not in a Composites-side `.inp` post-processor. Composites contributes the mesh-merge helper, an example, and the docs. *If this is wrong, Stages 2-6 are discarded and replaced by a deck-merge in `src/Mod/Composites/util/fem_util.py`; Stage 0 and Stage 7 are unaffected.*
2. **Coupling is `*TIE`-based on non-conformal meshes.** `write_constraint_tie.py:96-103` already emits `*TIE, POSITION TOLERANCE=…, ADJUST=…`, so no writer change is needed. Conformal/shared-node coupling is explicitly rejected as the primary route: `FemMesh::getFacesOnly()` (`FemMesh.cpp:841-862`) defines shells as *faces whose nodes are not a subset of any volume*, so a shell placed on a solid's skin is invisible to the pipeline, and shell rotations at solid-only nodes are unconstrained (a hinge) without `*EQUATION`.
3. **Safety gate is a hidden Bool** at `User parameter:BaseApp/Preferences/Mod/Fem/General` → `AllowMixedElements`, default `False`, read through **one** helper added to the existing param wrapper in `femsolver/settings.py` (which already wraps `_GENERAL_PARAM`, so no new param plumbing). One call-site set, deleted in the final commit. No new document-visible API.

## Behaviour changes

- Flag `False` (default, and every existing document): **byte-identical** decks. Every existing code path in `meshtools`, `meshsetsgetter` and the writers is unchanged.
- Flag `True`: the shell-thickness/volume conflict becomes a warning; face and edge elements are written alongside volumes; references resolve per referenced sub-shape rather than per whole mesh; materials yield one element set per dimension; node sets carrying rotational DOF are split by dimension.
- Still errors, regardless of the flag: beams with shells, beams with fluids, fluid sections in a static analysis, and >1 mesh per analysis.

---

## Stages

Each stage is one mergeable unit. Exit criteria are checked before the next stage starts.

### Stage 0 — Mesh-strategy spike (no production code)
Answer, with real output, how a FemMesh containing volumes **and** shell elements that survive `FacesOnly` is produced. Probe three candidates in a throwaway script under `compositeexamples/examples/` (deleted before merge, findings kept in the doc):

- **(a)** two separate Gmsh meshes (solid body; skins) merged in Python with renumbered nodes → expected to pass
- **(b)** Gmsh on a compound of solid + sheet (internal surface) → expected to fail: coherence makes the sheet a volume face
- **(c)** Gmsh on a compound of solid + sheet coincident with the solid's skin → expected to fail: excluded by `getFacesOnly()`

For each: `VolumeCount`, `FaceCount`, `FacesOnly`, and the deck produced by `writeABAQUS(elemParam=2)`. Also run one CalculiX job of the (a) mesh coupled with `*TIE` and confirm no zero-pivot/warning about unconstrained rotational DOF; confirm a CalculiX binary is configured, and if none exists record that and defer the numerical check to Stage 7.

**Exit:** the doc's *Findings* section states which strategy the plan adopts, and either (a) confirms `*TIE` works or triggers ADR `docs/adr/0004-shell-solid-coupling.md` recording the alternative. **This is the only permitted ADR.**

### Stage 1 — Additive infrastructure, zero call sites
New code only, so nothing can break:
- `femutils`/`settings.py`: `allow_mixed_elements()` reading the flag.
- `meshtools`: `is_mixed_femmesh(femmesh)` (volumes present **and** `FacesOnly`/`EdgesOnly` non-empty) — deliberately *not* a redefinition of `is_solid_femmesh`/`is_face_femmesh`, which stay as-is for all 15 existing call sites.
- `meshtools`: `get_femelement_tables_by_dim(femmesh)` returning dimension-tagged tables from `femmesh.Volumes`, `FacesOnly`, `EdgesOnly`. This is the answer to the node-count ambiguity in `:229-296`: **dimension is taken from mesh membership, never from node count.**
- `meshtools`: `merge_femmeshes(base, extra)` — renumbering merge, factored out of the pattern already in `compact_mesh` (`meshtools.py:2180-2203`), whose comment documents the shared id namespace.
- Unit tests for all four (`femtest/app/test_mesh.py`).

**Exit:** full FEM app suite green with no golden file touched.

### Stage 2 — Write the missing elements
`write_mesh.py`: choose `element_param = 2` **only** when the flag is on and `is_mixed_femmesh`; otherwise keep `1`. Mode 2 writes volumes + `getFacesOnly()` + `getEdgesOnly()`, and therefore also emits the `Efaces`/`Eedges` elsets (`FemMesh.cpp:2138-2204`) that `meshsetsgetter` already references as `ccx_efaces`.

**Exit:** every file in `femtest/data/calculix/*.inp` reproduces exactly (no golden edits); a new mixed example produces a deck containing both `*Element,TYPE=C3D8…` and `*Element,TYPE=S8R…` blocks and an `Efaces` elset. No C++ change is expected — verify before assuming one is needed.

### Stage 3 — Let it through validation
`check_member_for_solver_calculix`: when the flag is on and the mesh is mixed, replace the two shell/solid conflict messages with warnings, and skip the "same reference shape type" requirement for materials. All other checks unchanged.

**Exit:** a mixed analysis reaches the writer instead of failing in `check_prerequisites`; a beam+shell analysis still fails with the existing message; a new `test_ccxtools` case asserts warning-not-error.

### Stage 4 — Resolve references by dimension
`meshtools.get_elements` (`:1543`): when flag on and mixed, dispatch on the **referenced sub-shape's** `ShapeType` — Solid → volumes table, Face → `FacesOnly` table with fallback to the existing sub-element search on a zero match, Edge → `EdgesOnly` with the same fallback, Vertex → nodes. Flag off: existing `model_dim` path untouched. This single function serves materials, constraints, sections and ties (`_get_elements` → `meshsetsgetter.py:516`), including the Tie faces path (`:809-815`) used for coupling.

**Exit:** new unit test shows a material referencing a solid and a shell thickness referencing a face each get disjoint, correct element ids from one mixed mesh.

### Stage 5 — One element set per material per dimension
`meshsetsgetter`: add `FEMElementsByDim` to material members alongside the existing `FEMElements` (kept, for compatibility); populate it from the dimension-tagged tables in Stage 4. `get_element_sets_material_and_femelement_geometry` then appends the solid family **and** the shell family, each reading its own dimension slot, so the eight existing builders stay recognisable rather than being rewritten. No element may appear in two sections — assert this and fail loudly.

**Exit:** a mixed deck has exactly one `*SOLID SECTION` per material-with-volumes and one `*SHELL SECTION` per (material, shell thickness), elset ids partition the element range with no duplicates.

### Stage 6 — Finish the DOF split and output
Extract the Fixed-constraint split (`meshsetsgetter.py:288-307`) into one helper and use it in Displacement (its DOF 4-6 lines at `write_constraint_displacement.py:86` must apply to face/edge nodes only), PlaneRotation, Transform and RigidBody. `write_step_output.py`: mixed models always get `*NODE FILE, OUTPUT=3d`.

**Exit:** one golden `.inp` per touched constraint, flag-off output unchanged, no `*BOUNDARY` card referencing rotational DOFs of a solids-only nset.

### Stage 7 — Coupling and results, verified end to end
Validate the Stage 0 coupling decision against a real run. Then verify the result path for a mixed model: `frd` reading in `ccxtools.load_results_ccxfrd`, and `task_result_mechanical.py:796`, whose `if not self.mesh_obj.FemMesh.VolumeCount:` guard assumes a purely-solids model. Numerical acceptance: a shell skin + solid block whose combined response is checkable against an independent model (pure-solid, same stiffness) within a tolerance agreed **before** the test is written — never tuned afterwards.

**Exit:** mixed analysis runs to completion in CalculiX with no unsupported-DOF warnings, results load in the GUI, and the numerical check passes at the agreed tolerance.

### Stage 8 — Make it usable from Composites, then drop the scaffolding
- Composites: a helper in `util/fem_util.py` (next to the existing `get_layers_ccx` / `write_shell_section_ccx`) that builds the mixed FemMesh via `merge_femmeshes` — reuse, do not re-implement; plus an example under `compositeexamples/examples/` following `_shell_example_common.py`, e.g. a skin + solid stiffener block with a Tie.
- Docs: mark this plan `delivered`, update `docs/known-issues.md`, and note the strategy in `docs/fem-shell-mesh-continuity.md`, which already covers shell mesh continuity and is where a reader will look.
- Remove the `AllowMixedElements` scaffolding: make the mixed path automatic on `is_mixed_femmesh`, delete the flag helper and its call sites in one commit.

---

## Testing and verification

- **Regression floor, every stage:** the golden `.inp` comparisons in `femtest/app/test_ccxtools.py` against `femtest/data/calculix/`. They are the load-bearing proof that flag-off output is unchanged. **No golden file is ever edited to make a stage pass.**
- Run the FEM app suite headlessly through the project's runner (`~/.pi/agent/skills/freecad-dev/scripts/run-tests.sh`, `FreeCADCmd -t …`), targeting `femtest.app.test_ccxtools`, `test_mesh`, `test_common` per stage and `TestFemApp` at Stages 6 and 8. Confirm the exact invocation with one probe run in Stage 1 — do not guess flags.
- Composites suites only where Composites files change: `run-tests.sh test_compositeexamples`.
- New mixed-model fixtures live in `femtest/data/` alongside existing ones; new writer tests assert deck text, no CalculiX binary required. Only Stage 7 needs a binary, and its absence is recorded rather than silently skipping the check.
- Per `AGENTS.md`: never relax a tolerance, threshold or assertion to get green.

## Out of scope

Beam/edge or fluid elements in a mixed model (the flag deliberately keeps those errors); multi-physics (Elmer, Z88, Mystran — `run.py:515-537` and `mystran/tasks.py:64` keep their existing checks); multiple meshes per analysis; `*SUBMODEL`; GUI affordances beyond what already exists; upstreaming to FreeCAD mainline.

## Assumptions to revisit if wrong

1. `elemParam = 2` in `writeABAQUS` is sufficient for mixed meshes with no C++ change — verified by Stage 2's spike-like check; if `getFacesOnly`'s node-subset test proves too aggressive, a C++ change to tag mesh-origin faces is the fallback and it grows Stage 2.
2. `*TIE` with `POSITION TOLERANCE` couples shells to solids correctly in the installed CalculiX version — verified in Stage 0.
3. `*NODE FILE, OUTPUT=3d` plus `S, E` gives usable results for both element kinds — verified in Stage 7.
4. A CalculiX binary is configured in this environment — checked in Stage 0; if not, numerical acceptance is deferred with the gap stated in the doc rather than substituted with a mock.
5. Element ids are unique across dimensions in one FemMesh (per `compact_mesh`'s comment) — asserted in Stage 1's merge tests.
