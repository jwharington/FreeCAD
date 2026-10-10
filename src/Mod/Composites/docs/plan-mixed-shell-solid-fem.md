# Plan: Mixed shell + solid elements in one FEM analysis

**Date:** 2026-10-02 (revision 2026-10-10) · **Status:** Stages 1–9 done and verified. The
mixed path is **on by default**, a Composites example drives it end to end, the
merge routine is published, and a mixed result now displays without freezing the
GUI. Stage 7's coupling check passes at **0.09 %** against an all-solid rebuild;
Stage 8 makes a mixed result displayable; Stage 9 promotes the path and hardens
the checks the promotion would have weakened.
**The motivating case now runs.** `mixed_shell_solid_wing.py` — a NACA 2412 wing
with a solid Rohacell core and a real `[+/-45]s` carbon laminate on each lateral
surface — meshes, writes and **solves** in one deck, coupled by two `*TIE`s
(§11.5). Getting it to run took three FEM defects and a mesh-sizing bug, none of
which was visible until the one in front of it was fixed; they are written up
with their numbers in [`fem-mesh-query-cost.md`](fem-mesh-query-cost.md).
**Remaining:** the full list is **§11**. Fixed since the last revision: §11.1 (the
silent wrong deck on an edge-shaped connection), §11.2 (a composite section on a
linear shell, now refused by the writer), §11.3's F1 solve, §11.5's motivating
laminate, §11.6's GUI freeze — traced to the layered `COMPOSITE` section expanding
the frd to **8x** the mesh (289,241 nodes against 35,385) and fixed in the frd
reader — and §11.7, which turned out not to be a defect at all: the wing's tie
warnings are ccx reporting DOFs that are already constrained, and the run has
**zero** of the ones that mean an uncoupled node. Also fixed: §11.12, where a
force's axis was coming from the referenced face's normal instead of the
direction asked for, which is what the wing's load case was silently doing.
Also fixed: §11.13, where the mixed-coupling shape lookups and tie/load
helpers existed in a separate copy per mixed file; they now live in one Fem
module (`femtools/mixedcoupling.py`).
Open: the results-viewer toggle
(§11.4), the coverage and cleanup tail (§11.8, §11.10), a tie hazard the
tolerance research turned up (§11.9), and the question of landing a shell's
expansion node on the contact plane (§11.11), which is written up and
deliberately **parked**. All four face families are solved as of `6fc22a9334`;
what only F1 has is a compared-pair displacement check, because the offset and
bag families have no natural all-solid equivalent (§11.3).
**Owner context:** LS8e fuselage FEM work — a composite skin modelled as
shells wants to coexist with locally solid features in the *same*
analysis. Today it cannot: FreeCAD's FEM pipeline is built around
**one element dimension per analysis**.

This plan is staged so that **every stage leaves the tree green**. No
stage depends on a later one, and each stage's exit criterion is a
command, not an intention.

---

## 1. Why it is blocked today (verified in source, not folklore)

Four independent layers each assume a single element dimension. Any one
of them alone keeps mixing broken, which is why previous attempts ended
up working on `.inp` text after the fact.

| # | Layer | Evidence |
|---|---|---|
| 1 | Validation forbids it | `femtools/checksanalysis.py:305-320` — *"Shell thicknesses defined but FEM mesh has volume elements."* Beams⊕shells and beams⊕fluid likewise (`:267-280`). Reached from both entry points: `femtools/ccxtools.py:267`, `femsolver/calculix/calculixtools.py:66`. Run aborts before anything is written. |
| 2 | The mesh writer drops the shells | `femsolver/calculix/write_mesh.py:37` hard-codes `element_param = 1`; `FemMesh::writeABAQUS` (`src/Mod/Fem/App/FemMesh.cpp:1987`, `:2028`) only collects faces/edges when `elementsMapVol` is empty. With volumes present, **no shell `*Element` block and no `Efaces` elset ever reaches the deck** (`FemMesh.cpp:2138-2204`). Mode 2 (*"FEM elements only"*, volumes + `getFacesOnly()` + `getEdgesOnly()`) is exactly what mixing needs and **no writer uses it**. |
| 3 | The mesh abstraction is dimension-exclusive | `meshtools.is_solid_femmesh / is_face_femmesh / is_edge_femmesh` (`:1951-1976`) are mutually exclusive over the whole mesh; `get_femelement_table` (`:142-156`) returns only the highest dimension; `get_elements` (`:1543-1600`) derives one `model_dim` for the entire model and routes every geometry reference through it — including Tie and Contact (`meshsetsgetter.py:794-815`). |
| 4 | The material × geometry product is per-dimension | `meshsetsgetter.get_material_elements` (`:950-976`) fills one `"FEMElements"` slot per material, first from the volume table then **overwritten** by the face table; `get_element_sets_material_and_femelement_geometry` (`:978-1040`) calls both matgeoset families. The code says it outright: *"it does not work for mixed meshes and multiple materials, this is checked in check_prerequisites."* Materials must additionally share one reference shape type (`checksanalysis.py:97-113`). |

### Two traps that are not obvious from the layer list

**Trap A — `getFacesOnly()` cannot distinguish a deliberate shell from a
volume's own skin.** `FemMesh::getFacesOnly` (`FemMesh.cpp:841-875`)
classifies a face as "shell" when its node set is **not** a subset of
any volume's node set. So a shell meshed conformally *on* a solid's
boundary, or a midsurface that gmsh turns into an internal volume
boundary after `Coherence Mesh;`, is silently **not** a shell and is
dropped by mesh-write mode 2. The mesh strategy (Stage 0) exists to
establish, by experiment, which geometry arrangement survives this test.

The test is on **node ids, not coordinates** — a distinction that decides
the whole "solid covered by a shell" family and is pinned down in §8.3.

**Trap B — element dimension is inferred from node count.** The
reference→element machinery keys off `len(element_nodes)`:
`get_element_faces_elements_from_binary_search`
(`meshtools.py:278-296`) looks up `vol_dict[len]`, so tetra4 ≡ quad4,
penta6 ≡ tria6, hexa8 ≡ quad8. A naive "merge all elements into one
table" therefore misclassifies a tetra mesh as a shell mesh. The mixed
path must carry **explicit dimension tags**, sourced from
`FemMesh.Volumes` / `FacesOnly` / `EdgesOnly`, never from node counts.

### What already exists, and should be reused

- `meshsetsgetter.get_constraints_fixed_nodes:288-307` +
  `write_constraint_fixed.py:56-98` already split a fixed constraint
  into `NodesSolid` (DOF 1-3) and `NodesFaceEdge` (DOF 1-6) for a mixed
  mesh. The intent is already in the tree — generalise it, don't
  reinvent it.
- `write_constraint_tie.py:96-103` writes `*TIE, POSITION TOLERANCE=…,
  ADJUST=…` — shell↔solid coupling needs **no writer change**.
- `FemMesh.FacesOnly` / `EdgesOnly`, `FemMesh.getElementType`,
  `meshtools.compact_mesh` (`:2180`, which already renumbers ids across
  all three dimensions and documents the id-collision hazard),
  `Composites/util/fem_util.py` for laminate material/section writing.
- `femtest/app/test_ccxtools.py:340 input_file_writing_test` +
  `testtools.compare_inp_files` against golden decks in
  `femtest/data/calculix/*.inp` — the regression guard for
  "nothing changed".

---

## 2. Locked defaults (chosen in planning, revisit at the named stage)

| Decision | Default | Revisit |
|---|---|---|
| Where the fix lives | **FreeCAD FEM core** (`src/Mod/Fem`), flag-gated and upstreamable, and **general**: a mixed model's shell need not be a composite shell — a plain steel shell over a solid feature wants exactly the same path — so nothing here, the mesh-merge routine included, is Composites-specific. Composites is one consumer, not the owner. | Stage 9 |
| Shell↔solid coupling | **`*TIE` with position tolerance**, non-conformal meshes, on **node-disjoint** meshes. Chosen primarily because **Trap A** makes a node-merged shell on a solid boundary undetectable — it is dropped from the written mesh, silently, before any coupling question arises. For an **edge** interface a shared node is additionally a hinge (`solidshell1`, §8.3); for a **face patch** it is not (`solidshell2`), so Trap A is what decides there. `*TIE` covers **face interfaces only** — edge-connected shapes (§8.4, family E) have no mechanism in the tree and are a scope decision for ADR 0004. | Stage 0 |
| Safety gate | **Hidden dev parameter** `AllowMixedShellSolid` in `User parameter:BaseApp/Preferences/Mod/Fem/General`, read through one getter in `femsolver/settings.py` (next to `get_write_comments`). **Stage 9 flipped the default to `True`** — setting it to `False` is the rollback, not the other way round. Getter and branches deleted after a release ships with the default on. | Stage 9 (done) |

**Invariant for the whole plan:** with the flag off, every generated
`.inp` is **byte-identical** to today's. Every existing golden file in
`femtest/data/calculix/` stays untouched — they are pure-dimension
meshes, so they must not move. If one moves, the flag is leaking.

---

## 3. Stages

Each stage: *change → exit criterion → verify → back out*.

### Stage 0 — Mesh-behaviour spike (no production code)

Write a throwaway script that builds three candidate mixed meshes and
records what the pipeline actually sees. This stage decides whether the
Tie default in §2 holds; it must not be skipped.

| Candidate | Question answered |
|---|---|
| a. Compound(solid + separate sheet), Gmsh | Does the mesh keep faces that `getFacesOnly()` reports? Do nodes merge under `CoherenceMesh`? |
| b. Solid meshed alone + sheet meshed alone, merged in Python | Same questions, with structurally disjoint node sets (the intended production route). |
| c. Sheet exactly coincident with a solid face, Gmsh | Confirms Trap A fires (expected: `FacesOnly` reports nothing → shell vanishes). |

*Exit criterion:* a findings table appended to §6 of this document —
per candidate: `VolumeCount`, `FaceCount`, `len(FacesOnly)`, and
whether `writeABAQUS(elemParam=2)` emits an `Efaces` block.
*Back out:* delete the script. Nothing in the tree changed.

If candidate (c) is the only one that works, or none does, the coupling
default is overturned.

**Stage 0 also always writes one ADR** —
`docs/adr/0004-shell-solid-coupling-and-interface-dimension.md` — because
the spike raises a second, independent question the candidates cannot
answer: an **edge-connected** shell↔solid shape has no coupling mechanism
in the tree at all (§8.4.1), and whether to build one (`*EQUATION`) or to
declare it out of scope changes the size of this work. The ADR records the
chosen interface-dimension policy and, if the candidate spike overturns the
Tie default, the replacement coupling as well. §8.5 G10/G11 enforce whatever
it decides.

**Stage −1 (§9) runs first and gates everything below it.** It validates the
plan's premises — does ccx accept a mixed deck, does `*TIE` carry moment,
does the mode-2 writer emit what §8.3 assumes — using probes that touch no
production file. If P1 or P2 fails, the stages below are re-shaped before any
of them is started. Do not begin Stage 0 until §9 has an answer for P1.

**Stage 0 additionally settles the coupling question the manual leaves open.**
The manual calls a shared-node 3D↔2D connection hinged, which CalculiX's own
`solidshell2` contradicts for a face patch (§8.3), and it says nothing about
whether `*TIE`'s MPCs carry a shell slave node's rotations. Probe **D2**
(§9.4) answers that with a tip-deflection ratio before any F-family stage
depends on it, and the measured ratio is the number the ADR records.

### Stage 1 — New primitives, zero call sites

Add, do not wire in:

- `settings.get_allow_mixed_elements()` — the flag getter.
- `meshtools.is_mixed_femmesh(femmesh)` — volumes **and**
  (`FacesOnly` or `EdgesOnly`) non-empty. Existing
  `is_solid_femmesh` / `is_face_femmesh` / `is_edge_femmesh` stay
  unchanged for all current callers.
- `meshtools.get_femelement_tables_by_dim(femmesh)` → `{3: table,
  2: table, 1: table}` built from `Volumes` / `FacesOnly` / `EdgesOnly`
  — the dimension-tagged table Trap B demands.
- `meshtools.merge_femmeshes(base, extra)` — disjoint node/element
  renumbering, factored out of the `compact_mesh` id discipline.

*Exit criterion:* unit tests cover (i) a hand-built mixed mesh classifies
as mixed and pure meshes do not, (ii) the by-dim tables have no id in
two tables and never use node counts, (iii) merge preserves
`FacesOnly` for the merged mesh. **No existing file besides the new
tests changes behaviour.**
*Verify:* FEM app tests + `run-tests.sh test_laminate` as a canary.

### Stage 2 — Write the shell elements into the deck

In `write_mesh.py`, choose `element_param = 2` **only** when
`get_allow_mixed_elements()` and `is_mixed_femmesh()`; otherwise keep
`1`. That is the entire stage.

*Exit criterion:* the whole existing `femtest/data/calculix/` golden set
still compares equal — proving pure-dimension output is untouched.
*Add:* one golden mixed deck (volumes + `Efaces` block, one
`*ELSET,ELSET=Efaces`) written from a fixture, not from a solver run.

### Stage 3 — Stop refusing to run

In `checksanalysis.py`, move the shell-vs-volume and beam-vs-shell rules
behind the flag: flag off → today's error text verbatim; flag on → the
combination is allowed, and combinations the pipeline genuinely cannot
express yet (beams, fluids) stay errors regardless. Also allow mixed
reference shape types on materials only under the flag.

*Exit criterion:* an analysis with volumes + a `ShellThickness` object
now reaches `write_inp_file` and produces the Stage 2 golden deck; a
beam+shell analysis still fails with the unchanged message.

### Stage 4 — Resolve references by the reference's own dimension

Dispatch `meshtools.get_elements` on the **referenced sub-shape's**
`ShapeType` (Solid → dim 3, Face → dim 2 with a zero-match fallback to
the sub-element path, Edge → dim 1, Vertex → nodes) instead of one
`model_dim` for the whole mesh, when the flag is on. `MeshSetsGetter`
holds the by-dim tables from Stage 1.

*Exit criterion:* with volumes and shells present, a Fixed constraint on
a solid face and a Pressure on a shell face each resolve to elements of
their own dimension — asserted in a new test by element counts and by
`getElementType`, not by node counts.

### Stage 5 — One matgeoset per (material, dimension)

Give material members a `"FEMElementsByDim"` map alongside
`"FEMElements"` (populated per dimension by `get_material_elements`),
and have the solid family read `[3]` and the shell family read `[2]`.
`get_element_sets_material_and_femelement_geometry` calls both families
when the mesh is mixed — no rewrite of the eight existing builders.

*Exit criterion:* the mixed golden deck contains exactly one
`*SOLID SECTION` and N `*SHELL SECTION` cards; a test asserts **no
element id appears in two section elsets** (this is the failure mode
that would otherwise pass silently).

### Stage 6 — DOF correctness

Extract the `NodesSolid` / `NodesFaceEdge` split from
`get_constraints_fixed_nodes` into one helper and use it in Displacement
(`write_constraint_displacement.py:86` currently emits DOF 4-6 to the
whole nset — a hard error for solid-only nodes), PlaneRotation,
Transform and RigidBody. `write_step_output.py:33-44` is deliberately
left alone here: the `OUTPUT=2d`/`3d` choice shown there is a
visualisation decision rather than a DOF one, and Stage 8 owns it.

*Exit criterion:* per-constraint golden diffs showing DOF 4-6 applied
only to shell/edge nodes; a ccx run (if a binary is configured) that
produces no *"node set has no rotational dof"*-class warning.

### Stage 7 — Coupling and results, end to end

Validate the Stage-0 coupling route against a real ccx run:
skin-as-shell ⊕ spar-as-solid, Tie'd, loaded in bending. Confirm the
interface transfers shear and does **not** transmit a spurious moment —
the classic shell-solid failure is a hinge that is quietly too
flexible. Then fix result plumbing only where it is actually wrong:
check `task_result_mechanical.py:796` (its `not VolumeCount` test
becomes meaningless on a mixed mesh) and the result object type
selection.

*Exit criterion:* tip deflection within a stated tolerance of an
independent reference — the same model built fully solid, or an
analytic estimate. The tolerance is **stated before the run** and is
never relaxed afterwards to make the test pass.

*Measured:* `compositestests/inspect_mixed_cantilever.py` (a spar with a
skin on top, joined by `*TIE`, loaded at the spar tip). The tolerance was
5 % against the all-solid rebuild **stated before the run**, and it is met:
the mixed model gives 6.4223e-02 mm against 6.4163e-02 mm, a difference of
**0.09 %**. The tied skin carries the section.

Getting there found and fixed two defects:

1. **A solid's face resolved to a coincident shell.** In a mixed mesh a face
   reference tried the shell table first, so a `*TIE`'s master surface came out
   identical to its slave and ccx cascaded through an under-determined
   constraint set without ever solving. Fixed by deciding on the referenced
   *object* (`meshtools.get_elements_by_reference_dimension`); regression test
   `test_mixed_shell_solid.py::test_tie_master_surface_is_the_solid_not_the_shell`.
2. **The tie wrote the wrong shell side.** CalculiX numbers a shell's faces 1
   and 2 as the two sides of its 3D expansion (`*SURFACE`, manual), and the
   section offset decides which of those meets the master. The writer wrote
   face 2 on every shell. With the skin on top, face 2 is a whole thickness
   away from the spar, so **no tied MPC was generated at all** and the skin
   floated — the mixed model then returned bit-for-bit the bare spar, 1.90× the
   all-solid. Fixed by `write_constraint_tie._shell_slave_face`; regression test
   `test_mixed_shell_solid.py::test_tie_slave_side_follows_the_shell_offset`.

Defect 2 is worth remembering for how it failed: a joint one thickness out of
position is **silent**. ccx prints `WARNING in gentiedmpc: no tied MPC` to
stdout only, the job finishes normally, and the deflection is exactly the
uncoupled one. That is the silent-hinge risk this stage exists to catch, and
G13's numerical check is what caught it — the deck text looked fine.

### Stage 8 — Visualisation of mixed results

The plan used to carry one unjustified prescription here — *"a mixed model
always writes `*NODE FILE, OUTPUT=3d`, never `2d`"* — which is the **opposite**
of what visualisation needs. This stage replaces the prescription with a
measured decision.

The gate is exact. `task_result_mechanical.py:790-801` shows a result only when
`FemMesh.NodeCount == len(result_obj.NodeNumbers)`; anything else raises a
dialog. The `not VolumeCount` test at `:796` only chooses *which* message — on a
mixed mesh it is always false, so a mismatch reports the generic *"Result node
numbers are not equal to FEM Mesh NodeCount."*

Which way that gate falls is decided by the deck:

| `*NODE FILE` | where results land | node-count gate | cost |
|---|---|---|---|
| `OUTPUT=2d` | the original shell nodes | **passes** | shell results are averaged through the thickness — *"averaging removes the bending stresses in beams and shells"* |
| `OUTPUT=3d` | the expanded brick nodes, whose *"nodal numbering is different from the shell nodes"* | **fails** | full 3D shell stresses, and nothing displays them |

`write_step_output.py:33-44` already writes `OUTPUT=2d` whenever a
`ShellThickness` object exists, unless the solver's existing `Output3d` flag is
set. For a mixed model the working configuration is therefore the **default**,
and no new flag is needed. The decision is whether to keep that default or
invest in reading expanded results back onto the mesh.

A quieter hazard sits beside it: FreeCAD writes `*NODE FILE, OUTPUT=2d` but
`*EL FILE, GLOBAL=NO` with no `OUTPUT`, which defaults to 3D. One frd can
hold nodal results at original nodes and element results at expanded nodes. That
is the shape of fault that colours a model wrongly without ever erroring.

Steps, and what came of them:

1. **Measured.** The frd node numbering against the `FemMesh` node set, on the
   same mixed model, by `compositestests/inspect_mixed_cantilever.py`:

   | solver `Output3d` | `*NODE FILE` | frd nodes | mesh nodes | panel gate |
   |---|---|---|---|---|
   | off | `OUTPUT=2d` | 3910 | 3910 | **PASS** |
   | on | `OUTPUT=3d` | 4519 | 3910 | **FAIL** |

   The plan's premise was wrong on one point: `Output3d` defaults to **True**
   (`femobjects/solver_calculix.py`), so a mixed model does **not** get `2d` by
   default — it gets `3d` and fails the gate.
2. **Decided: keep `OUTPUT=2d`.** It passes the gate on node count, which is
   the exit criterion; making the gate dimension-aware and mapping expanded
   nodes back onto the `FemMesh` is a much larger change for a result the panel
   cannot show anyway. The loss of through-thickness shell stresses is
   **documented, not hidden**: 2d averages them (manual, *"averaging removes
   the bending stresses in beams and shells"*).
3. **`*EL FILE` now agrees.** The manual is explicit that the default is
   expanded nodes for **both** cards (*"Default storage for quantities
   requested by the \*NODE FILE and \*EL FILE is in the expanded nodes"*), so a
   deck that set only the nodal card to 2d would put element results on a
   second, larger node set inside one frd. `write_step_output.py` now writes
   `OUTPUT=2d` on both, and ignores `Output3d` **only for a mixed mesh**, so no
   other deck changes — proven by the §4 snapshot reporting *no deck changed*.
   Regression test `test_mixed_deck_agrees_on_output_dimension`.
4. **`task_result_mechanical.py:796` needs no change.** The branch is reached
   only when the node counts differ, and on a mixed mesh `VolumeCount` is
   non-zero, so the *"beam or shell not yet supported"* message is correctly
   never produced for a mixed model: it falls through to the honest generic
   message. With step 3 the gate passes for mixed meshes, so neither message is
   reached at all. Left as is, deliberately.

*Exit criterion: met.* A mixed result displays both parts — shell and solid —
with the gate passing on node count rather than on a special case:

  * **V1** (gate): frd nodes 3910 == mesh nodes 3910 → **PASS**.
  * **V2** (both parts visible in the result, by node id against the mesh's own
    by-dimension tables): shell 477/477 nodes moving, solid 3433/3433 → **PASS**.
  * **V3** (cards agree): `*NODE FILE, OUTPUT=2d` and
    `*EL FILE, OUTPUT=2d, GLOBAL=NO` → asserted in CI without ccx.

V1/V2 need a CalculiX binary, so they are probe assertions (`--phase run`),
not CI tests; V3 is in the FEM suite as
`test_mixed_deck_agrees_on_output_dimension`.

*Back out:* additive to the result panel. Reverting leaves the deck unchanged,
since nothing here writes the deck.

**This is the cleanest cut in the plan.** If the deliverable is reduced to *"runs
headless and writes a correct, runnable mixed deck"*, Stage 8 drops whole — and
Stage 6 must then not touch `write_step_output.py` at all, because leaving the
existing `ShellThickness` behaviour alone is already the more displayable
choice. §8's GUI column then shrinks to "`setup()` completes and the deck
matches the headless golden". Decide this before Stage 4, not after.

### Stage 9 — Promotion, publishing the general merge routine, and deleting the flag

- ~~Flip the default to on~~ — **done.** `settings.get_allow_mixed_elements()`
  now returns `True` when `General/AllowMixedShellSolid` is unset, so the mixed
  path is what everyone gets and setting the parameter to `False` is the
  rollback. Doing it safely needed `checksanalysis` to gate its two relaxations
  on the mesh actually being mixed rather than on the flag alone: otherwise a
  shell thickness on a mesh with volumes but no shells would have been quietly
  accepted once the flag was on by default. The deck snapshot now sets the flag
  off explicitly, because its invariant is about flag-off decks, and it still
  reports *no deck changed*. Tests: `test_mixed_flag_defaults_on`,
  `test_flag_on_still_refuses_a_shell_thickness_on_a_solid_mesh`.
- ~~Publish the mesh-merge routine from Fem~~ — **done.**
  `femexamples/meshes/merged_mesh.py` holds `mesh_parts_separately`, and the
  mixed coupling examples import it from there. The layering note above still
  holds: it could not move down into `meshtools` without a cycle through
  `gmshtools`, so it sits in the examples package, public, above
  `generate_mesh`. A Composites example was the first non-example caller, which
  is what triggered the move.
- ~~Add a Composites example~~ — **done.**
  `compositeexamples/examples/mixed_shell_solid_plate.py`: a `Composite::Shell`
  laminate skin over a solid spar, meshed apart, merged node-disjoint, `*TIE`'d
  and solved. Test `test_mixed_shell_solid_plate_solves` asserts the mesh holds
  volumes *and* its own shell elements, and that the deck carries a
  `*SOLID SECTION`, a `*SHELL SECTION` and a `*TIE`. The skin is
  `IsotropicEquivalent`, deliberately, so the example stays off the drape
  backend. A second, `mixed_shell_solid_wing.py`, carries a **real** per-ply
  laminate over a solid foam core — the motivating case of §11.5, and the one
  that exposed the cost defects listed there. **`Stiffener` and `Bulkhead`
  still have no mixed coverage.**
- Delete the getter and the flag branches after one release.

**Fixes that came after the stages, from *using* the path rather than building
it.** Each was silent in the same way — a deck that looks well-formed and an
answer that is wrong — and each has a regression test:

- **A solid's face resolved to a coincident shell**, so a `*TIE`'s master
  surface came out identical to its slave and ccx cascaded without solving
  (`meshtools.get_elements_by_reference_dimension`; §7).
- **The tie wrote the wrong shell side** — `elem,S2` on every shell, when the
  section offset decides which expanded face meets the master. One thickness
  out is inside no tolerance, so **no tied MPC was generated at all** and the
  model returned the uncoupled answer (`write_constraint_tie._shell_slave_face`;
  §3, Stage 7).
- **Material→element assignment was not dimension-aware**, so a material on a
  solid claimed shell faces lying on it, and two solids with a material each had
  no working form (`get_material_elements`; §7).
- **A reference resolving to a `Compound` matched no dispatch branch**, so a
  `*TIE` slave that was a compound of faces — a multi-patch skin — resolved to
  an empty surface (`meshtools.get_shape_dimension`; §7). Taking a compound
  apart also uncovered a latent bug in the bit pattern, which counts one bit per
  node *occurrence*, so a node listed twice never matches its mask.
- **Reaction forces were requested on a set that no longer exists** —
  `*NODE PRINT, NSET=Fixed`, after Stage 6 split the fixed nodes into
  `FixedSolid` and `FixedFaceEdge`. No reaction forces, silently.
- **The bulkhead example returned a Document** where every other example returns
  a mapping, so `test_all_examples_build` failed on it before reaching any other
  example.

---

## 4. Verification

```bash
# Composites side (unchanged harness)
~/.pi/agent/skills/freecad-dev/scripts/run-tests.sh test_laminate

# The Composites example that drives the mixed path end to end
~/.pi/agent/skills/freecad-dev/scripts/run-tests.sh test_compositeexamples
~/.pi/agent/skills/freecad-dev/scripts/run-tests.sh test_bulkhead

# FEM app tests, including the golden-deck comparison
~/.pixi/envs/default/bin/FreeCADCmd -t femtest.app.test_ccxtools

# The mixed-mesh matrix of §8 plus the post-stage fixes
~/.pixi/envs/default/bin/FreeCADCmd -t femtest.app.test_mixed_shell_solid

# The result-size fix of §11.6: the frd reader maps expanded results onto the
# model mesh, so a composite model's result is not 8x the mesh
~/.pi/agent/skills/freecad-dev/scripts/run-fem-tests.sh test_result_mesh_mapping.py
~/.pi/agent/skills/freecad-dev/scripts/run-fem-tests.sh test_reaction_multistep_delivery.py

# The flag-off deck invariant (this tool sets the flag off itself)
~/.pi/agent/skills/freecad-dev/scripts/run-script.sh \
    src/Mod/Composites/compositestests/run_inspect_deck_snapshot.py \
    --check --snapshot src/Mod/Composites/compositestests/deck_snapshot.json

# The GUI half of §8 (needs a display; see §8.8)
build/debug/bin/FreeCAD --run-test TestFemGui
```

**The diagnostics behind §11.6** — how the GUI freeze was measured, and where it
went. All four are committed tools, not ad-hoc loops, because each answers a
question that had already been guessed wrong once:

- `inspect_document_load_cost.py <file.FCStd> ...` — opens documents and reports
  the two numbers that answer different questions (time to create the objects,
  and whether the load left anything to recompute), plus a marker tap counting
  drape solves, so "something re-executed" is measured rather than inferred.
- `inspect_wing_pipeline_cost.py [--stop-after geometry|drape|mesh|deck|solve]
  [--save <file.FCStd>] [--drape-pitch <mm>]` — the wing's per-stage wall time;
  `--stop-after` and `--save` together produce a document per stage.
- `inspect_result_mesh_mapping.py --document <file> --frd <file> --analysis <name>`
  — re-imports an frd into a model analysis and reports the result mesh size,
  row count and max |u| against the expanded import.
- `inspect_shell_section_expansion.py` — isolates the frd expansion trigger by
  re-running the same deck with a homogeneous shell section.

A trap worth keeping: the Composites harness **truncates stdout on success**
(it prints a `tail` of the log) and only prints everything on failure. `exit 0`
next to a handful of `PASS` lines is therefore a full pass, not a near-empty
run — count from the timings file the harness names, not from stdout. `27`
recorded for `test_mixed_shell_solid`, `26` for `test_compositeexamples`, `20`
for `test_bulkhead` at the time of writing.

**The golden set is not currently a usable reference, and that is a problem
for this plan specifically.** Six of the 33 cases in
`femtest.app.test_ccxtools` fail, all pre-existing: confirmed by stashing every
change this branch has made and reproducing the identical six.

| Failing case |
|---|
| `test_box_static` |
| `test_ccx_cantilever_ele_hexa20` |
| `test_ccx_cantilever_faceload` |
| `test_ccx_cantilever_nodeload` |
| `test_constraint_transform_torque` |
| `test_material_multiple_bendingbeam_fiveboxes` |

The cause is staleness, not a regression: the checked-in decks expect
`** ConstraintFixed` and a `ConstraintFixed` nset where the current examples
emit `Fixed`, and the meshes differ too (228 nodes against 235 in the faceload
case). Commits such as `dac401961b` and `059d01a519` updated `femexamples`
without refreshing the corresponding decks. **Do not regenerate them from this
plan** — that would bless whatever those commits did, including any real fault
in the constraint rename, and it is someone else's in-flight work. Note it and
leave it.

**Consequence: change this plan's flag-inert proof.** The invariant was
"flag off ⇒ every generated `.inp` is byte-identical, proven by comparing the
whole golden set". That comparison conflates two different claims — *my change
altered nothing* and *the output has not changed since the goldens were
written* — and the second is currently false for reasons unrelated to this
work. It therefore cannot be used as written.

Replace it with a **before/after deck snapshot**, which isolates exactly the
claim the plan needs and does not depend on golden currency: generate every
example deck with the tree as it stands, hash them into a committed snapshot
file, then after each stage regenerate and require the hashes to be unchanged
with the flag off. A stage that leaks changes a hash and names the deck; a stale
golden cannot mask it and a fresh golden is not required. This wants to be one
committed tool beside the §9.9 probes, not an ad-hoc loop — and it becomes the
mechanism every stage from 2 onward is verified against.

**The snapshot is now a proof, and the invariant survives as a byte hash.** The
tool is `compositestests/inspect_deck_snapshot.py` (runner
`run_inspect_deck_snapshot.py`), with its snapshot committed at
`compositestests/deck_snapshot.json`. Two runs of the same tree with the mesher
at its default thread count differed in **11 of 42 decks** and dropped one
intermittently, which is why byte-identical first read as unachievable. The
cause is not the writer: `MeshGmsh.ParallelProcessing` defaults on
(`femobjects/mesh_gmsh.py`) and `gmshtools` writes `General.NumThreads =
idealThreadCount()` into every `.geo`, and multithreaded Gmsh is not
order-stable — element node lists permute and coordinates move. Pin it to one
thread, which `--threads` defaults to and restores afterwards, and two runs
produce 42 decks with **none changed**. So the §2 invariant stands as stated,
proven by `--check`; a structural restatement becomes a fallback for a Gmsh
version bump rather than a necessity.

**The same cause makes part of the existing golden set flaky.** `test_ccxtools`
meshes live for every example it does not pass `test_mode=True`, so a golden for
a threading-affected shape can fail for no reason. Two of the six currently
failing goldens (`ccx_cantilever_faceload`, `ccx_cantilever_nodeload`) are in
that set, which is consistent with the earlier finding that at least part of the
six is nondeterminism rather than staleness. Do not regenerate them; if anyone
takes the fix, it is to mesh deterministically in that harness too.

**Known pre-existing canary failure.** `run-tests.sh test_laminate` exits 1 on
`TestQuasiIsotropicEntryGuards.test_texture_plan_activation_creates_nothing`
(`AttributeError: module 'FreeCADGui' has no attribute 'Selection'`, raised
through `Composites/mechanics/stack_model.py:303`). Confirmed pre-existing by
stashing every change this plan has made and re-running: the same single error
appears, 18 tests pass, with nothing in the plan's files on the traceback. Do
not read it as a regression from any stage here, and do not chase it from this
plan — it belongs to the quasi-isotropic stack-model work.

Confirm the exact `-t` module spelling before first use rather than
guessing flags — `src/Mod/Fem/TestFemApp.py` shows the test modules the
FEM suite registers, and `src/Mod/Fem/CMakeLists.txt` shows which files
are installed under `Mod/Fem/` at all.

Run the FEM app tests after **every** stage, not only after Stages 2
and 3. They are the only mechanism that proves the off-flag is inert.

Where a stage's claim is about solver behaviour rather than deck text
(Stage 0 candidate (a), Stage 7), it needs a ccx binary. If none is
configured, say so in the findings rather than substituting a
deck-text test for a physics result.

---

## 5. Out of scope

- Beams (`ElementGeometry1D`) and fluid networks in mixed models. They
  share the same single-dimension assumption and are blocked by the same
  code; Stage 4's by-dimension dispatch is what makes them reachable
  later, but nothing here unblocks them.
- Conformal shared-node shell↔solid coupling (see Trap A). Rejected because a
  shell sharing a solid's nodes is dropped from the written mesh — Trap A —
  before any coupling question arises. For an **edge** interface a shared-node
  connection is additionally hinged (`solidshell1`); for a **face patch** it is
  not (`solidshell2`), so Trap A alone decides that case. The merge route is
  node-disjoint by construction and couples through `*TIE`.
- Merging interface nodes as a cheap E-family coupling. Eliminated in §8.4.1:
  it is a documented hinge, not a weak joint.
- **Edge-connected shell↔solid coupling is out of scope by default — but
  the reason is narrower than first stated.** Probe D2 (§9.8) showed ccx
  couples a shell-edge `*TIE` with full moment transfer, so the blocker is
  FreeCAD's reference→surface mapping, not CalculiX, and not a missing
  `*EQUATION` capability. The default is a loud error, not a silent hinge;
  ADR 0004 may promote this to in-scope, in which case the cheap fix is to let
  an Edge selection on a shell yield its edge face (S3-S6). An `*EQUATION`
  writer remains the fallback.
- Multiple mesh objects per analysis
  (`membertools.get_mesh_to_solve` still raises). Mixing happens inside
  one `FemMesh`, not across two.
- Any change to Z88, Elmer, CalculiX-objects, MyStran or OOFEM writers.
  The flag path is CalculiX-only.
- Layered/composite shell sections beyond what
  `fem_extension_registry` already provides. Note that D3 (§9.8) constrains
  the element type instead: a composite `*SHELL SECTION` is accepted only for
  **S8R and S6**, so the shell side of a mixed composite model cannot use
  linear shells.

---

## 6. Findings (measured by the §9 probes)

The Stage 0 spike asked what the pipeline sees for three candidate mesh
strategies. Two are answered by probes §9.4 and §9.9; the third is recorded as
unrun rather than guessed.

| Candidate | `VolumeCount` | `FaceCount` | `len(FacesOnly)` | `Efaces` written? | Verdict |
|---|---|---|---|---|---|
| a. compound (solid + sheet), Gmsh | — | — | — | — | **not run** — see below |
| b. solid and sheet meshed separately, merged in Python | 1 | 1 | 1 | **yes** | **adopted.** The shell survives detection and reaches the deck. |
| c. sheet coincident with a solid face, Gmsh | — | — | — | — | **not run.** Same expectation as (a), same caveat. |
| c′. sheet sharing the solid's nodes, hand-built | 1 | 1 | **0** | **no** | Trap A, executed: the shell is dropped with no error and no warning. |
| b′. candidate b through `compact_mesh` | 1 | 1 | 1 | **yes** | renumbering does not break detection (ids unique, not contiguous). |

Rows b, c′ and b′ are measured on one C3D8 brick plus one quad at the same
four coordinates, so the only variable is whether the quad shares the brick's
nodes (§9.9). Rows a and c need Gmsh on a compound and are recorded as unrun.

**Coupling route confirmed, by Stage 0 and now end to end by Stage 7:** `*TIE`
on a **node-disjoint** merged mesh. A shell root tied to a solid face deflects
within **1.7 %** of a root fixed in DOF 1-6 (§9.8, D2), and a genuine hinge
magnifies deflection by ~2.5e12 with no diagnostics — so the coupling is real
and the failure mode is silent, which is why G13's numerical check is
load-bearing.

**Stage 7 carried that to a flange and it holds.** A skin tied over a solid's
face and loaded through the spar gives 6.4223e-02 mm against 6.4163e-02 mm for
the all-solid rebuild — 0.09 % (§3, Stage 7). Getting there required fixing the
shell side the tie writes (defect 2 in Stage 7); before that fix the joint sat
one thickness out of tolerance, no `*TIE` MPC was generated, and the deck
looked correct while behaving as if the skin were absent.

**Why the Gmsh candidates are unrun, and what that leaves open.** Gmsh on a
compound matters only if FreeCAD is ever to build a mixed mesh in one meshing
pass rather than by merging two. The merge route (b) is verified end to end and
is what §3 builds, so (a) and (c) cannot change the plan's shape now. Both are
*expected* to fail — `Coherence Mesh` would make the sheet's nodes a subset of
the solid's, which is exactly the mechanism row c′ measures — but that
expectation is inference, not measurement, and must not be quoted as a finding.
Close them before anyone proposes the single-pass Gmsh route.

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| **A shell↔solid connection is attempted by sharing nodes.** For a **face** interface the failure is Trap A: the shell's nodes are a subset of the solid's, so `getFacesOnly` drops it and the shell never reaches the deck. For an **edge** interface it is a silent hinge — the Manual's *"3D elements and all other elements (1D or 2D) is always hinged"*, which holds for a shared **line** (`solidshell1`) but not for a face patch (`solidshell2`) | The merge route is node-disjoint by construction (§8.3); coupling is declared by `*TIE` only; G5 asserts the `*TIE` cards exist, G10/G11 make an uncouplable edge connection a loud error, and G13's numerical check would expose a hinge as excess tip deflection |
| ~~Whether `*TIE` carries a shell slave node's rotational DOF~~ — **resolved, and it does** | Probes D1/D2/D3 ran before any production code existed; results in §9.8. A tied shell root is within **1.7 %** of a clamped root, and Stage 7 shows a tied **flange** within **0.09 %** of an all-solid rebuild. G13 remains the regression guard. |
| **A tie with the wrong shell side fails silently.** The writer must pick the side of the expanded shell that meets the master (`write_constraint_tie._shell_slave_face`). Stage 7 measured the failure: the joint was one thickness out, ccx printed `WARNING in gentiedmpc: no tied MPC` to stdout only, the job finished, and the deflection was exactly the uncoupled one — the deck text was indistinguishable from a working one | Fixed and regression-tested (`test_tie_slave_side_follows_the_shell_offset`). G13's numerical check is the guard that makes a silent uncoupling impossible to ship, which is why a text-only deck test is not enough |
| **A hinged mixed model fails silently, not loudly.** D2's hinge variant returned a ~2.5e12 deflection magnification with **no `*ERROR` and no warning** from ccx | The "loud error, not a silent hinge" requirement stands, and G13's numerical check is **load-bearing** — a hinge will not announce itself and cannot be caught by a deck-text test |
| ~~**Composite `*SHELL SECTION` accepts only S8R and S6.**~~ — **fixed, §11.2.** Measured in D3: an `S4` shell with a composite section is rejected outright — `Element 2 is not a S8R nor a S6 shell element.` | The writer now refuses a composite section whose elements are not 6- or 8-node shells, naming the offender, instead of writing a deck CalculiX will reject. Asserted in `test_mixed_shell_solid.py` on a linear quad4 and on the same quad with mid-side nodes. |
| **A mixed result is written but cannot be displayed.** The panel gate is exact node-count equality, and `OUTPUT=3d` moves shell results to expanded nodes whose numbering differs from the mesh's. The failure is an error dialog at best, wrong colours at worst | **Closed by Stage 8.** `Output3d` defaults True, which is the failing case; `write_step_output.py` now writes `OUTPUT=2d` on both `*NODE FILE` and `*EL FILE` for a mixed mesh and ignores that flag there, so the gate passes on node count. V1, V2 and V3 pass (§3, Stage 8). The cost is through-thickness shell stresses in the frd, documented rather than hidden |
| Node-count inference lurking in code paths not yet read (Stage 4 is the wide one) | Stage 1 ships dimension-tagged tables and Stage 4 asserts on element **types**, not counts |
| A mixed model silently double-sections elements | Stage 5's explicit no-element-in-two-sections assertion |
| Flag leaks into normal paths and changes existing decks | Golden-file comparison over the whole `femtest/data/calculix/` set at every stage; the flag is read in exactly one function |
| Work stalls half-done, leaving an unusable combination | The flag makes "half-done" a supported state: off = today's behaviour, including today's error message |
| **Edge-connected shell↔solid cannot be *generated* by FreeCAD.** Corrected by D2 (§9.8): ccx couples a shell-edge `*TIE` with full moment transfer, so CalculiX is not the blocker — the reference→surface mapping is | §8.4.1 revised: the first-choice fix is now to let an Edge selection on a shell yield its edge face (S3-S6), which is less work than a `*EQUATION` writer; until then G10/G11 make it a loud error |
| ~~**Material→element assignment is not dimension-aware, so it does not scale past one solid + one shell.**~~ — **fixed in Stage 9.** `get_material_elements` ran its face pass over every material and a `Solid` reference resolves by node geometry, so a material referencing a solid claimed shell faces lying on it (measured: `MaterialA`'s face set was `{3}`, the shell quad). Two solids each with a material plus a shell had no working form, because only one material may have empty references | Each pass now takes only the materials whose references belong to its dimension, judged by what the shape holds rather than by its `ShapeType` (so a compound of faces is a shell part), with empty references still the catch-all. Scoped to mixed meshes, so a non-mixed deck is unchanged (snapshot: *no deck changed*). Test: `test_two_solid_materials_do_not_claim_the_shell`. |
| ~~**A reference that resolves to a Compound matched no dispatch branch.**~~ — **fixed.** Every stage that read a reference's `ShapeType` treated `"Compound"` as "none of Solid, Face or Edge". A `*TIE` whose slave was a compound of faces — how a multi-patch skin is built — resolved to an **empty surface**, silently, and a material on a compound of faces would have gone to the volume pass. Taking a compound apart also exposed a latent bug: the bit pattern counts a bit per **occurrence**, so a node listed twice never matches its mask, which any reference naming sub-shapes that share a node would hit | Judge by contents through one shared `meshtools.get_shape_dimension`, used by `get_femnodes_by_refshape`, `get_elements_by_references`, `get_elements_by_reference_dimension` and the material dispatch. Dedup the node list before the bit pattern. Tests: `test_tie_resolves_a_compound_shell_slave`, `test_compound_references_land_in_their_own_dimension`, `test_shape_dimension_follows_a_compound_contents`, and the probe's `--model compound` end to end (tip matches the face-reference model exactly) |
| A golden deck is captured from a live Gmsh mesh and rots on a Gmsh upgrade | R1: byte-compared decks only from frozen `create_nodes`/`create_elements` meshes; live-Gmsh cases assert structure only |

---

## 8. Geometry test cases (headless + GUI)

The stages in §3 say *what to change*; this section says *how we prove it
on real geometry*, through both entry points, before anything is
user-visible. Every case here is geometry-driven: real `Part` shapes in a
`femexamples` module, not a hand-built `FemMesh` in a unit test.

**Admission rule for any case in this matrix.** A case enters the matrix
only when (i) it declares the stage that first makes it pass, and (ii) the
same `femexamples` module produces the *same deck* headless and in the
GUI. A case that passes only in one of the two modes is not finished.

**This rule is not met as built.** The GUI half was never written —
`femtest/gui/test_mixed_shell_solid.py` does not exist and nothing mixed is
registered in `TestFemGui.py` — so the matrix is **headless-only** at present.
That is an open decision, not an oversight to be glossed: either write the GUI
half, or amend this rule deliberately. Recorded in §11.8. The rule is left
standing here because it is the right rule, and the tree is what falls short of
it.

### 8.1 What already exists to build on

| Piece | Where | Why it matters here |
|---|---|---|
| Geometry + analysis builder | `femexamples/<name>.py` → `get_information()` + `setup(doc=None, solvertype="ccxtools")` | The *only* place today where a full analysis is built from real geometry. Same module is loaded by the GUI Examples browser. |
| GUI-conditional setup | `femexamples/constraint_tie.py:124-127` — `if FreeCAD.GuiUp: … ViewObject.hide()` | The existing precedent for one module serving both modes. Every branch is ViewObject-only. |
| Headless workflow test | `femtest/app/test_ccxtools.py:340` `input_file_writing_test` | Does exactly the workflow we need: `check_prerequisites()` → `write_inp_file()` → `testtools.compare_inp_files()` against `femtest/data/calculix/<base>.inp`. |
| Deck comparator | `femtest/app/support_utils.py:260` `compare_inp_files` | Already normalises the volatile `** written …` header lines, so a golden compare is stable. |
| Deterministic mesh route | `femexamples/meshes/generate_mesh.py:49` `mesh_from_existing(create_nodes, create_elements)` | Freezes a mesh as a committed node/element list — the reason every ccx golden is reproducible. |
| GUI test harness | `femtest/gui/test_open.py`, registered in `TestFemGui.py:25`, listed at `CMakeLists.txt:773` | The template for a GUI test that asserts on real `ViewObject` proxies. |
| Element dimension tags | `FemMesh.Volumes` / `FacesOnly` / `EdgesOnly`, `FemMesh.getElementType` | The only sound basis for mixed assertions (see Trap B in §1). |

### 8.2 The four safety rules

These are what make the matrix "no surprises". Each is a rule because
ignoring it has a specific failure mode.

**R1 — a golden deck is never written from a live Gmsh mesh.** Gmsh output
varies between Gmsh versions, so a byte-compared `.inp` built straight from
`mesh_from_mesher()` rots on an unrelated Gmsh upgrade. Therefore each
mixed case splits in two:

- a **structural** test over the live Gmsh mesh (element counts per
dimension, `Efaces` elset present, `getElementType` per element) — never a
byte compare;
- a **frozen** mesh, committed under `femexamples/meshes/` as a
`create_nodes`/`create_elements` pair, used by every golden comparison.

The geometry is still genuinely exercised: the structural test meshes it,
and the constraints in the frozen-mesh example reference the real
`Part::Feature` sub-shapes, exactly as `constraint_tie.py` does today.

**R2 — `setup()` may branch on `FreeCAD.GuiUp` only for `ViewObject`.** Any
branch that can change geometry, the mesh, the analysis tree, or the deck
is a bug. The GUI test asserts the deck written from the GUI-built
document is equal to the headless golden, so the two entry points cannot
drift apart silently.

**R3 — assert on dimension tags, never on node counts.** Element counts per
round-trip through `Volumes`/`FacesOnly`/`EdgesOnly` and `getElementType`.
A node-count assertion passes on a tetra mesh misread as a shell mesh
(tetra4 ≡ quad4, Trap B), which is precisely the bug this work exists to
prevent.

**R4 — an unlisted file is invisible, not failing.** `src/Mod/Fem/CMakeLists.txt`
installs Python files by explicit list (`FemTestsApp_SRCS:404`,
`FemGuiTests_SRCS:773`, `FemExamples_SRCS:50`, `FemTestsCcx_SRCS:433`). A
test file or golden that is not added there never installs; `-t` then
fails with *module not found* — or worse, compares against a *stale*
golden left behind by an earlier install. Every new file in §8.6 is
added to its list in the same commit that adds the file.

### 8.3 Trap A, precisely: it is node identity, not coincidence

`FemMesh::getFacesOnly` (`src/Mod/Fem/App/FemMesh.cpp:841-875`) states its
own algorithm:

> *"for each face … if the face nodes are a subset of the volume nodes … add
> the face to the volume faces … if face doesn't belong to a volume add it
> to faces only."*

The membership test is on **node ids**, not on coordinates. So the rule that
governs every "solid covered by a shell" case is:

| Shell nodes | `getFacesOnly()` | Survives `elemParam=2`? |
|---|---|---|
| its **own** nodes at coincident coordinates (node-disjoint) | not a subset → reported | **yes** |
| nodes **shared** with the solid (merged, or one Gmsh mesh with coherence) | subset → dropped | no — the shell silently disappears |

This is why §2's route survives. `compact_mesh` (`meshtools.py:2180-2235`)
renumbers nodes **1:1 in enumeration order and never merges coincident
ones**, so `merge_femmeshes(base, extra)` yields a node-disjoint mesh by
construction. Trap A therefore fires only for a *single* Gmsh mesh of a
compound with `CoherenceMesh` — not for the Python merge route. That is a
much narrower trap than §1's wording suggests, and it is the reason the
covered-solid cases below are testable at all.

`G8` and `G9` pin the failing condition; `G4`-`G7` pin the working one, so
a regression in either direction is caught.

**Node-disjointness is required for two independent reasons, and which one
bites depends on the interface.** The first is Trap A above, and it decides a
**face** interface on its own; the second is the hinge, and it decides an
**edge** interface.

The CalculiX manual, S8/S8R section (identical wording in the 2.7 and 2.18
manuals):

> *"Beam and shell elements are always connected in a stiff way if they share
> common nodes. This, however, does not apply to plane stress, plane strain and
> axisymmetric elements."* — the stiff-by-shared-nodes rule is for 1D↔2D only.
>
> *"For an internal hinge between 1D or 2D elements the nodes must be doubled
> and connected with MPC's. The connection between 3D elements and all other
> elements (1D or 2D) is always hinged."*

Read literally, the last sentence would make every shared-node 3D↔2D connection
a hinge. **CalculiX's own reference cases show that is too broad: what decides
it is the measure of the interface.**

| Reference case | Interface | Cards | Its own objective |
|---|---|---|---|
| `solidshell1` | shared **line** | none — shared nodes | *"hinged connection shell-solid"* |
| `solidshell2` | shared **face patch** | none — shared nodes | *"fixed connection shell-solid"* |

So a shared **face patch is not a hinge**, and for the face family the reason to
keep nodes apart is Trap A — which is sufficient by itself, because the shell
would not reach the deck.

For an **edge** interface the hinge is real. The mechanism: shells are
*"automatically expanded into 20-node brick elements"*, and a shared shell node
becomes a **knot** — a rigid body with seven DOF (3 translations, 3 rotations,
uniform expansion) at the reference node. A solid element can see only that
node's three translations, so a shared **line** leaves the shell's rotations
with no counterpart on the solid side. That is `solidshell1`'s configuration,
and it is what an E-family connection hits if its nodes are merged.

Consequence for the whole plan: **a shell↔solid connection must be declared
by MPCs (`*TIE` or `*EQUATION`), never by node sharing.** For a face interface
node sharing loses the shell outright (Trap A); for an edge interface it
silently produces the hinge §7 warns about. Either way the merge route in §2
is node-disjoint by construction.

**A second, unsigned hazard in the same helper.** `compact_mesh` advances
`ele_id` twice per face (once before `addFace`, once after) while edges and
volumes advance once, so its output **does** contain id gaps despite the
docstring claiming it *"removes all gaps in node and element ids"*.
Assertions on merged meshes must therefore test **uniqueness and
monotonicity, never contiguity**. A contiguity assertion would fail on
correct output and teach us nothing.

### 8.4 Coupling geometry taxonomy

Shapes fall into three families, distinguished by the **measure of the
interface**, because that — not the mesh — decides which CalculiX coupling
can express them.

**F — face interface (measure 2).** The shell lies on, or parallel-offset
from, a solid face. `*TIE` is the right mechanism and the writer already
supports it.

| Id | Shape | Notes |
|---|---|---|
| F1 | solid **fully covered** by a coincident, node-disjoint shell | the "solid wrapped in a shell" case; one tie per wrapped face |
| F2 | shell **patch** over one face of a larger solid (partial coverage) | tie only the patch footprint |
| F3 | shell **offset** from the solid (laminate midsurface standing off a core) | the physically honest composite model; tolerance must exceed the offset |
| F4 | solid **fully enclosed** by a closed shell (a shell "bag") | needs the shell topologically closed, tie on every solid face |

**E — edge interface (measure 1).** The shell meets the solid only along an
edge, so the connection carries a moment that a surface tie cannot express.
**No mechanism for this exists in the tree today** — see §8.4.1.

| Id | Shape | Notes |
|---|---|---|
| E1 | shell plate continuing a solid block from one of its edges | the classic "shell welded to a solid" |
| E2 | shell **web** meeting a solid plate at 90° along an edge | the stiffener-to-skin case |
| E3 | shell **bridging two** separate solids, edge-connected at both ends | two interfaces, both of the E kind |

**X — degenerate.** Kept as negative tests so the failure modes stay visible.

| Id | Shape | Expected today |
|---|---|---|
| X1 | shell coincident **and node-merged** with the solid (one Gmsh compound, coherence on) | shell vanishes → `len(FacesOnly) == 0` |
| X2 | shell passing **through** the solid interior (embedded sheet) | not a boundary face; excluded from `FacesOnly` by definition |

#### 8.4.1 The E family is blocked in the **writer**, not in CalculiX

> **Corrected by measurement — see §9.8.** Probe D2 tied a shell's root
> *edge* to a solid face in a hand-written deck and ccx coupled it with full
> moment transfer. `*TIE` therefore **can** express an edge interface, and the
> heading above was too strong. What follows is the original reasoning,
> retained because the writer-side limits it cites are still real and still
> the reason the E family is unavailable *from FreeCAD*.

`*TIE` cannot be *generated* for an edge interface. Verified, not assumed:

- `write_constraint_tie.py:63-77` writes `*SURFACE, NAME=…` entries of the
form `elem,S{n}` — a surface reference derived from a face index, with no
path that yields a shell edge face (S3-S6) from a selected Edge.
- `meshsetsgetter.get_constraints_tie_faces:809-815` feeds it from faces
only (`TieSlaveFaces` / `TieMasterFaces`).
- Searching `src/Mod/Fem` for `EQUATION` finds **no CalculiX `*EQUATION`
writer at all**. The one hit, `femsolver/elmer/sifio.py:39`, is Elmer's
unrelated SIF keyword; `write_step_equation.py` writes `*STEP`, despite the
name.

The blocker is therefore a **reference→surface mapping** (Stage 4's territory),
not a missing CalculiX capability and not necessarily new writer code. Options:

1. **Extend the reference resolution so an Edge selection on a shell yields
its edge face (S3-S6)** for `*TIE`. D2 shows ccx handles the resulting deck
with moment transfer, so this is the cheap route if Stage 4's by-dimension
dispatch can produce the face index. This *replaces* the earlier
"add a `*EQUATION` writer" option as the first choice — it is strictly less work.
2. **Add a `*EQUATION` writer** — still correct and general, but now a
fallback rather than the primary route, and only needed if option 1 turns out
to be impossible for some reference shape.
3. **~~Merge only the edge nodes, leaving the rest disjoint.~~ Eliminated.**
By the manual wording quoted in §8.3, a shared 3D↔2D node is a **hinge by
design** — a knot whose rotations the solid cannot resist. Merging edge nodes
would not produce a weak connection; it would produce exactly the
silently-hinged joint §7 warns about, with no error and no warning. Not an
option at any cost.
4. **Declare E out of scope** — keep §5's exclusion, with the taxonomy
recording why, and make the missing coupling a **loud error** rather than a
silent hinge.

This is a scope decision, not an implementation detail. Per §2's revisit rule
it belongs in the ADR written at Stage 0 —
`docs/adr/0004-shell-solid-coupling-and-interface-dimension.md` — recording
which of 1, 2 and 4 is chosen and what it costs.

**Until that ADR exists, the mixed path must fail loudly on an E-shaped
connection.** `G10` and `G11` exist to enforce exactly that.

### 8.5 The matrix

`G1` and `G2` are controls that pass today; `G0`, `G8` and `G9` are negative
tests pinning today's behaviour; `G10` and `G11` pin the *gap* in today's
behaviour. The rest are gated on the stage that makes them pass. Nothing
here is expected to go green early.

| Case | Family | Geometry | Mesh route | Assertion (headless) | Assertion (GUI) | First green at |
|---|---|---|---|---|---|---|
| **G0** | control | existing pure-solid example, **flag off**, with a `ShellThickness` object attached | frozen | `check_prerequisites()` still returns today's *"Shell thicknesses defined but FEM mesh has volume elements."* — verbatim | pressing **Run** on a mixed example in the Examples browser surfaces the same error text | today |
| **G1** | control | `femexamples/ccx_cantilever_base_face.py` (solid) | frozen | existing `input_file_writing_test` golden compare — unchanged | deck written from the GUI-built document equals the headless golden | today |
| **G2** | control | `femexamples/ccx_cantilever_ele_quad4.py` (shell) | frozen | existing golden compare — unchanged | as G1 | today |
| **G3** | control | G1 geometry, **flag on**, no shell elements present | frozen | deck byte-identical to G1's golden — the flag-inert guard | same | Stage 2 |
| **G4** | **F2** | shell **patch** over one face of a larger solid | live Gmsh (structural) + frozen merged mesh | structural: `len(Volumes)>0`, `len(FacesOnly)>0`, each element's dimension from its own table; frozen: one `*SOLID SECTION`, ≥1 `*SHELL SECTION`, an `*ELSET,ELSET=Efaces`, `*TIE, POSITION TOLERANCE` | setup completes, analysis tree builds, deck == headless golden | Stage 2 (deck) / Stage 5 (sections) |
| **G5** | **F1** | solid **fully wrapped** in a coincident, node-disjoint shell | live Gmsh + frozen | as G4, plus one `*TIE` per wrapped face and **no element id in two elsets** | as headless | Stage 3 |
| **G6** | **F3** | shell **offset** from the solid (laminate midsurface over a core) | live Gmsh + frozen | as G4; `POSITION TOLERANCE` ≥ the offset, read back from the deck | as headless | Stage 3 |
| **G7** | **F4** | solid **fully enclosed** by a closed shell bag | live Gmsh + frozen | as G5; the shell face set is topologically closed | as headless | Stage 5 |
| **G8** | **X1** | sheet coincident **and node-merged** with the solid (one Gmsh compound, coherence on) | live Gmsh | `len(FemMesh.FacesOnly) == 0` — the shell vanishes. Pins Trap A | same | today (asserts current behaviour) |
| **G9** | **X2** | sheet passing **through** the solid interior | live Gmsh | the sheet is not reported by `FacesOnly` | same | today |
| **G10** | **E2** | shell web ⊥ solid plate, edge-connected (stiffener T-joint) | live Gmsh + frozen | a Tie whose reference is an **Edge** raises a clear error instead of writing an unusable `*SURFACE`; the assertion is that the gap is *detected and reported*, never silently hinged | as headless | Stage 0 (gap detection); real coupling only if ADR 0004 selects an edge mechanism |
| **G11** | **E1/E3** | shell plate continuing a solid from one edge; shell bridging two solids | live Gmsh + frozen | as G10 | as headless | Stage 0 (gap detection) |
| **G12** | **F1** | G5 geometry with a `ConstraintDisplacement` | frozen | DOF 4-6 appear **only** on shell nodes; solid-only nodes get DOF 1-3. Grounds on `meshsetsgetter.get_constraints_fixed_nodes:288-307` and `write_constraint_displacement.py:86` | same | Stage 6 |
| **G13** | **F1** | G5 geometry, cantilever in bending | frozen | tip deflection within a tolerance **stated in the test before the run**, against the same model rebuilt fully solid | interactive only; not asserted in CI | Stage 7 |

G13 is the only case that needs a CalculiX binary. If none is configured,
the plan records that gap (§4) rather than substituting a deck-text check
for a physics result.

### 8.6 Files the matrix adds

| File | Purpose | Built? |
|---|---|---|
| `femtest/app/test_mixed_shell_solid.py` | headless matrix, 27 tests, registered as `FemTest17` | **yes** |
| `femtest/gui/test_mixed_shell_solid.py` | GUI half of G0-G12 | **no — not built** (§11.8) |
| `femexamples/constraint_mixed_face_coupling.py` | F-family geometry + analysis; `setup(doc, variant="f1"|"f2"|"f3"|"f4")`, default `f1` | yes |
| `femexamples/constraint_mixed_edge_coupling.py` | E-family geometry + analysis; `setup(doc, variant="e1"|"e2"|"e3")`, default `e2` | yes |
| `femexamples/meshes/mesh_mixed_face_coupling_f*.py` | frozen merged meshes for G4-G7, G12, G13 | **no.** R1's frozen half was met differently: `femexamples/meshes/merged_mesh.py` holds the merge routine, and one fixture golden covers the byte-compare. Structural assertions read the live mesh the examples build |
| `femexamples/meshes/mesh_mixed_edge_coupling_e*.py` | frozen meshes for G10, G11 | **no** — not needed while the E family does not solve (§11.1) |
| `femtest/data/calculix/constraint_mixed_*.inp` | the mixed goldens | **renamed** — one fixture deck, `mixed_shell_solid_fixture.inp` |
| `femtest/data/mesh/mixed_*.npy`-or-text snapshots | structural baselines for the R1 half of G4-G7 | **no** — structural assertions read the `FemMesh` by dimension tag instead |

**Case labels are not lookup keys.** The cases are delivered under descriptive
test names rather than the `G0`-`G13` / `V1`-`V3` labels used above —
`test_flag_never_changes_a_solid_deck` (G3),
`test_mixed_deck_carries_a_solid_and_a_shell_section` (G4/G5),
`test_displacement_prescribes_rotation_only_on_shell_nodes` (G12),
`test_mixed_deck_agrees_on_output_dimension` (V3). The labels stay useful for
discussing the matrix; they are not names you can grep for.

A `variant` keyword with a default is compatible with the browser: it
launches examples as `setup()` or `setup(solvertype="…")`
(`examplesgui.py:246-252`), so the default variant is what a GUI user gets
and the other variants are reachable only from the tests and the Python
console.

Registration, per R4: both test modules into `FemTestsApp_SRCS` /
`FemGuiTests_SRCS`; the imports into `TestFemApp.py` / `TestFemGui.py`
(the `FemTestNN` / `FemGuiTestNN` numbering at the end of each); the
example and mesh modules into `FemExamples_SRCS`; the goldens into
`FemTestsCcx_SRCS` / `FemTestsMesh_SRCS`.

Three of these are user-visible and must be declared as such in the stage
that lands them: the new examples appear in the FEM **Examples browser**;
**Run** on a mixed example with the flag off produces the §3 Stage-3 error
in the GUI; and `mesh_from_mesher` starts running on a compound for the F
variants. All three are intentional, and none changes an existing document
or deck.

Note the `meshtype` and `not_files` handling in
`femexamples/examplesgui.py:57-70` — the new examples get a `"meshtype":
"mixed"` entry in `get_information()` and are *not* added to `not_files`,
so they are loadable in the GUI. That is what makes the GUI half of §8.5
meaningful rather than synthetic.

### 8.7 Ordering inside the matrix

The cases are written **before** the stage that should make them pass, and
land in the tree skipped-or-failing-on-purpose until then. Concretely:

- **Stage 0** writes the controls and the negatives — G0, G1, G2 — which
must pass immediately, plus G8, G9 (Trap A and its interior variant) and
G10, G11 (the E-family gap). All of these assert *today's* behaviour,
including the two traps, so they are the yardstick for everything after. The
ADR from §8.4.1 is written in the same commit.
- **Stage 1** writes G3, the flag-inert guard, which must stay
byte-identical for the rest of the work; and the structural half of G4,
which is what actually verifies `merge_femmeshes`.
- **Stage 2** adds G4's golden half.
- **Stage 3** adds G5 and G6, and converts G10/G11 from *"reports the gap"*
to real coupling **only if** the ADR chose option 1 or 2.
- **Stage 5** adds G4's section assertion and G7.
- **Stage 6** adds G12; **Stage 7** adds G13; **Stage 8** adds the V cases of
  §8.10.

A case whose stage has not landed is registered in the test module but
kept out of `TestFemApp.py` / `TestFemGui.py` until it can pass, so the
suite is never red on purpose. Deleting that scaffolding in the final
stage is part of Stage 9.

### 8.8 Running them

```bash
# headless — the whole matrix
~/.pixi/envs/default/bin/FreeCADCmd -t femtest.app.test_mixed_shell_solid

# headless — one case (loader path, arbitrary nesting is supported)
~/.pixi/envs/default/bin/FreeCADCmd -t \
  femtest.app.test_mixed_shell_solid.TestMixedShellSolid.test_G13_bending_deflection

# GUI — needs a display, and TestFemGui is not in __unit_test__
# (`InitGui.py:59` keeps it commented out), so it is invoked explicitly
build/debug/bin/FreeCAD --run-test TestFemGui
```

Do not guess further flags: read `src/Mod/Fem/TestFemApp.py` and
`src/Mod/Fem/TestFemGui.py` for the registered module names before the
first invocation of any new case.

### 8.9 Invoke Composites modules fully qualified, and check the count

`run-tests.sh <bare-name>` resolves to `compositestests.<name>`, which is the
wrong package root for Composites. These modules do relative imports that need
`Composites.` as the root, so under the bare root those imports fail outright —
`test_composite_shell` reports *attempted relative import beyond top-level
package*, from `example_materials.py`'s `..mechanics`.

All three resolution paths in the script now use the qualified root: the
single-module path, the glob path (which passed a bare name with **no** package
at all), and the no-argument full-suite path (which hardcoded the wrong root for
every module in the list).

**How to count tests, because getting this wrong twice cost real time.** Do
**not** count them from `run-tests.sh`'s stdout. On success `run_one` prints only
`grep -E '^(PASS|FAIL|…)' "$log" | tail -6`, so a passing module appears to have
run six tests; on failure it prints the whole log. Counting test ids from that
output therefore undercounts *exactly when the run succeeds*, which is how a
healthy 19-test module was twice mistaken for one running 6.

Use the timings file the script already prints at startup — one line per test,
written from Python so FreeCAD's console spam cannot corrupt it:

```bash
tf=$(run-tests.sh test_laminate 2>&1 | sed -n 's/^timings file: //p')
grep -cE '^[0-9]' "$tf"            # number of tests actually run
grep -E '^[0-9]' "$tf" | grep -v PASS   # anything not passing
```

Cross-check against `grep -c 'def test_' <module>.py`. A count that does not
match the module is the signal, and it costs one grep.

### 8.10 Visualisation cases (V1-V3)

§8.5's matrix asserts deck text only, which leaves the two silent failure modes
of this work — a hinge, and a shell dropped by Trap A — with no end-to-end
detector at all. These three assert that a result is *displayable*, not merely
that it was written.

| Case | Builds on | Assertion | First green at |
|---|---|---|---|
| **V1** | G13's mixed run | the frd's node set matches the `FemMesh` node set exactly, so `task_result_mechanical`'s gate passes without a special case | Stage 8 |
| **V2** | V1 | a `Fem::ResultMechanical` built from that frd has **both** parts visible: shell nodes and solid nodes each carry non-zero displacement, checked by node id against the mesh's own by-dimension tables (§1 Stage 1) | Stage 8 |
| **V3** | G4 | `*NODE FILE` and `*EL FILE` agree on `OUTPUT` in the written deck, so nodal and element results cannot land on different node numbering | Stage 8 |

V2 is the one that matters. It is the only assertion anywhere in this plan that
would catch a shell missing from the **result** as opposed to missing from the
deck, and deck text cannot distinguish the two.

---

## 9. Risk-first premise validation (Stage −1)

### 9.1 Premises are not implementation

Every stage in §3 changes `src/Mod/Fem`. But the plan rests on a handful of
factual claims about code and physics that are **not ours** — CalculiX
behaviour, and the `writeABAQUS` C++ path. Those claims can be falsified
*now*, before a line of the plan is implemented, and two of them would change
the plan's shape if they turned out false.

So: validate the premises first, with **additive probes that touch no
production file**. Two rules.

- **No probe edits `src/Mod/Fem`.** Nothing lands there until the premises
  hold, so §2's byte-identical invariant is never even at risk.
- **No probe is a throwaway.** Per the repo's tooling discipline each is a
  committed inspection CLI, so a premise that must be re-checked on a new ccx
  or a new Gmsh is re-checked from the same file rather than rewritten.

### 9.2 The gate assumptions

| Id | Premise | If false | Evidence today | Probe |
|---|---|---|---|---|
| **P1** | ccx accepts one deck containing solids **and** shells (`*ELEMENT,TYPE=C3D10` + `TYPE=S6`, `*SOLID SECTION` + `*SHELL SECTION`) | The plan is dead — no amount of FreeCAD-side work yields a runnable mixed model | none; never tested | D1 |
| **P2** | `*TIE` between a **shell slave** and a **solid master** transfers moment — i.e. is not a hinge | The whole F family (§8.4) collapses; only `*EQUATION` remains, and no writer for it exists | manual is silent; §8.3's hinge statement is about *shared nodes*, a different case | D2 |
| **P3** | a **composite** `*SHELL SECTION` block coexists with `*SOLID SECTION` in one deck | the Composites use case (laminated skin over a solid core) is out of reach even if P1 holds | none | D3 |
| **P4** | `FemMesh.writeABAQUS(..., elemParam=2, ...)` emits volumes **and** `Efaces` on a *mixed* `FemMesh` | Stage 2 is not a one-line change; the C++ path needs work first | reachable from the GUI (§9.3) but **no test covers it** and it has never run on a mixed mesh | M1 |
| **P5** | `getFacesOnly()` reports a **node-disjoint** shell inside a mixed `FemMesh` — the §8.3 claim | the node-disjoint merge route is wrong and §8.3 must be rewritten | code-read only, never executed | M1 |
| **P6** | merge-by-renumbering produces a mesh that still satisfies P4 and P5 | Stage 1's `merge_femmeshes` is the wrong abstraction | `compact_mesh` is tested on pure meshes only | M2 |

All six now have measured answers — §9.8. None failed, so none of the failure
branches in §9.6 was triggered; §3 can start at Stage 0 rather than being
re-shaped.

### 9.3 A finding that changes P4's status: `elemParam=2` is not dead code

Stage 2 was recorded as "wiring up an unused mode". It is not unused — it is
**user-facing and default-on for GUI mesh export**:

- `src/Mod/Fem/App/AppFemPy.cpp:257` reads
  `Mod/Fem/Abaqus:AbaqusElementChoice` with **default 2**.
- `src/Mod/Fem/Gui/DlgSettingsFemExportAbaqus.ui:52` exposes that preference
  with the design-time selection at index 2 and a tooltip that documents the
  semantics exactly: *"FEM: Only FEM elements will be exported. This means
  only edges not belonging to faces and **faces not belonging to volumes**."*

Three consequences, all of which belong in the plan proper:

1. **P4 is lower risk than first claimed.** The C++ mode-2 path has a real
   entry point and is presumably exercised by users exporting `.inp`.
2. **Stage 2 makes the solver deck agree with the export dialog's default** —
   a consistency argument in its favour, not a novel idea.
3. **Trap A is documented, user-facing, default behaviour.** The tooltip
   describes `getFacesOnly()` verbatim. A user who exports a conformal
   shell+volume mesh gets the shell faces silently dropped *today, by
   default*. That is a fourth consequence to add to §1, and it strengthens
   node-disjoint merging from "the chosen route" to "the only route".

### 9.4 D1–D3 — deck probes (ccx only, no FreeCAD code)

One committed CLI, `compositestests/inspect_mixed_deck_premises.py`, built
like the existing `inspect_*` tools. It writes decks by hand, runs `ccx -i`,
and reads the `.dat`.

- **D1** — two-element mixed model: one C3D10 solid, one S6 shell, `*TIE`
  across the interface, one end fixed, tip load. *Pass:* ccx completes and
  writes a `.dat`. This is P1, and it gates D2 and D3.
- **D2** — the same geometry built three ways: **(a)** shell tied to solid as
  in D1, **(b)** the same model rebuilt **fully solid**, **(c)** D1 with the
  `*TIE` removed. *Pass:*
  `|u_tip(a) − u_tip(b)| / u_tip(b) < 0.10` **and** `u_tip(c) > 3·u_tip(a)`.
  (a)≈(b) with (c)≫(a) means a tie. (a)≈(c) means a hinge. Anything else
  means neither: print all three deflections and stop rather than guess.
  This single run decides §2's coupling default.
- **D3** — D1 with `*SHELL SECTION, COMPOSITE` (two layers) replacing the
  homogeneous `*SHELL SECTION`. *Pass:* ccx completes. P3.

D2's tolerance is stated before the run and is never relaxed afterwards (repo
rule). If it fails, that is the finding — not a tuning problem.

### 9.5 M1–M2 — mesh probes (pure Python)

Also outside `src/Mod/Fem`, as `compositestests/inspect_mixed_mesh_premises.py`.
These only `import Fem` and call the existing Python API; they become the
seeds of Stage 1/2's unit tests once the premises hold.

- **M1** — build a `Fem.FemMesh` with one tetra volume and one **node-disjoint**
  quad at coincident coordinates. Assert `len(Volumes) == 1` and
  `len(FacesOnly) == 1`; then `writeABAQUS(path, 2, False)` and assert the
  file contains a volume block, a shell block, and an `Efaces` elset. Then
  rebuild with the quad's nodes **shared** with the tetra and assert
  `len(FacesOnly) == 0`. M1 covers **P4 and P5** in one file, and executes
  Trap A rather than arguing it.
- **M2** — merge two separately built meshes by renumbering (the
  `compact_mesh` discipline) and re-run M1's assertions on the result.
  P6.

### 9.6 Failure branches

| Fails | Consequence for the plan |
|---|---|
| **P1** | Stop. The plan needs re-shaping around deck-level merging or a different solver; §3 is void. |
| **P2** | §8.4's F family collapses into the E family. `*EQUATION` moves from "the E-family gap" to "required for every shell↔solid connection", ADR 0004 becomes mandatory before Stage 3, and the plan roughly doubles. |
| **P3** | The Composites skin-over-core case is unreachable; §2's "Composites consumes it" is dropped and the plan's value shrinks to the FEM core alone. |
| **P4** | Stage 2 grows: the C++ mode-2 path is debugged first, with M1 as its regression test. |
| **P5** | §8.3 is wrong. Either the merge route must produce what `getFacesOnly` accepts, or the writer must stop inferring and take explicit element sets — a different Stage 2. |
| **P6** | Stage 1's `merge_femmeshes` design is revised while it still has no call sites. |

### 9.7 Cost and ordering

The order is forced rather than chosen: **D1 before D2 and D3** (no point
probing tie behaviour on a deck ccx rejects), and **D1–D3 before M1/M2 if a
ccx binary is available**, because a deck-level answer to P2 can make mesh
work pointless. M1/M2 are independent of D1–D3 and can run in parallel.

The whole stage is two new files. To retract it: delete them. Nothing in
`src/Mod/Fem` or `src/Mod/Composites` is touched, so §2's invariant is not
at risk and §4's existing test commands are unaffected.

Where ccx is unavailable, D1–D3 cannot be substituted by deck-text checks —
P1–P3 are claims about what ccx *does*. Record the gap (§4) and stop; do not
infer them from a written deck.

### 9.8 Results (measured)

Run with the committed probe
`src/Mod/Composites/compositestests/inspect_mixed_deck_premises.py`
against `/home/jmw/.local/bin/ccx` (`Version DEVELOPMENT`).

| Case | Premise | Result |
|---|---|---|
| D1 | P1 — ccx accepts a mixed solid+shell deck | **holds.** ccx exit 0, `Job finished`, no `*ERROR`. One C3D8 + one S8R, `*SOLID SECTION` + `*SHELL SECTION`, coincident-face `*TIE`. |
| D3 | P3 — composite `*SHELL SECTION` beside `*SOLID SECTION` | **holds, with a constraint** — see below. |
| D2 | P2 — `*TIE` shell↔solid carries moment | **holds, decisively.** see below. |

#### D3 carries a constraint that was not in the plan

My first D3 deck used `S4` and ccx **rejected it**:

> `Element 2 is not a S8R nor a S6 shell element.`
> `*ERROR in calinput: at least one fatal error message while reading the`
> `input deck: CalculiX stops.`

Composite shell sections are restricted to **S8R and S6** (the manual says so;
this is now measured). Consequences for the plan:

- **Stage 2 and Stage 5 must emit S8R or S6 for the shell portion of a mixed
  model when the section is composite.** A Composites laminated skin is
  exactly that case, so this is not optional for the plan's motivating use.
- The plan's existing golden decks use whatever element the existing writer
  picks; that choice is now constrained for the composite path and must be
  asserted, not assumed.
- Add this to §8.5's matrix as an assertion on G4/G5: the shell elements in a
  mixed deck are S8R or S6, checked by `getElementType`.

#### D2: the plan's coupling default is confirmed by measurement

Shell cantilever, 2 × S4, span 20, width 10, thickness 2, tip load 1.0 at
each of two tip nodes (total 2.0), E = 210000. The interface is the shell's
root **edge** — the E family, the one §8.4.1 called blocked.

| Variant | Root condition | tip `\|uz\|` | vs clamped |
|---|---|---|---|
| `clamped` | nodes 9,10 fixed in DOF **1-6** | 0.003366 | 1.0 |
| `tie` | root edge face **S3** tied to block face **S5** | 0.003422 | **1.0165** |
| `hinge` | nodes 9,10 fixed in DOF **1-3** only | 8.34e9 | 2.5e12 |

Analytic reference `δ = PL³/3EI` = **0.00381**. Both `clamped` and `tie` land
~11 % below it, which is what a two-element linear-shell mesh should give.

Readings:

1. **P2 holds.** A `*TIE` root is within **1.7 %** of a fully clamped root.
   §2's `*TIE` default is now measured, not merely argued from the manual.
   The pessimistic reading — that `*TIE` inherits the shared-node hinge — is
   **wrong**.
2. **The E family is not blocked in CalculiX.** This was an *edge* interface
   and it carried full moment. §8.4.1 has been corrected accordingly: the
   blocker is FreeCAD's reference→surface mapping, not ccx, and the cheapest
   fix is to let an Edge selection on a shell yield its edge face (S3-S6) for
   `*TIE` — which is **less work than the `*EQUATION` writer** the plan had
   ranked first.
3. **The `hinge` variant is a strong discriminator but a useless reference.**
   Fixing DOF 1-3 only is the manual's own definition of a shell hinge, and
   ccx returns a ~2.5e12 magnification with **no `*ERROR` and no warning** — a
   near-singular mode left unreported. So: a hinged model does not fail loudly.
   That independently justifies §7's "loud error, not a silent hinge"
   requirement, and it means G13's numerical check is load-bearing — a hinge
   will not announce itself.

#### Two probe bugs found and fixed

The first run reported false failures, both in the probe rather than the
premises, and both worth recording because the plan's Stage 0 spike can make
the same mistakes:

- **Success was tested by the wrong file.** `*NODE FILE` writes `.frd`;
  only `*NODE PRINT` writes `.dat`. D1 was declared a failure while ccx had in
  fact completed normally. The criterion is now `exit == 0` **and**
  `"Job finished" in stdout` **and** no `*ERROR` on either stream.
- **`S4` is invalid for a composite section** (above), which was a defect in
  my deck, not in P3.

### 9.9 Mesh-level results (measured)

Run with `src/Mod/Composites/compositestests/inspect_mixed_mesh_premises.py`
under `FreeCADCmd` — there is a `run_inspect_mixed_mesh_premises.py` wrapper,
but the verified command is the direct import, since a wrapper under
`FreeCADCmd -c` needs an explicit stdout flush before its `SystemExit` or it
exits silently. See the probe's docstring. The mesh is one C3D8 brick plus one
quad at the same four coordinates, so the only variable is whether the quad
shares the brick's nodes.

| Case | Premise | Result |
|---|---|---|
| M1 | P4 + P5 | **holds** |
| MT | Trap A, executed rather than argued | **confirmed** |
| M2 | P6 | **holds**, with a confirmed id-gap |

M1 / P4+P5, node-disjoint quad — `nodes=12 volumes=1 faces=1 faces_only=1`,
and `writeABAQUS(path, 2, False)` emits:

```
*Element, TYPE=C3D8, ELSET=Evolumes
*Element, TYPE=S4, ELSET=Efaces
*ELSET, ELSET=Eall
```

So **Stage 2's one-line `element_param = 2` change is confirmed sufficient for
the deck text**: the C++ path emits volumes and faces together, with the
`Efaces` elset the plan expected, on a mixed mesh. This was the path no caller
and no test had exercised.

MT / Trap A, shared quad — `nodes=8 faces_only=0`, and the deck loses the
shell entirely: no `*Element, TYPE=S4`, no `ELSET=Efaces`, **no error, no
warning**. This is the second silent failure mode found (the first was the
hinge in D2), and it is the executed form of the §8.3 prediction. It also
confirms the corrected §9.3 reading: a user exporting a conformal shell+volume
mesh with the GUI's default export setting loses the shell faces silently.

M2 / P6, `compact_mesh` — `faces_only` survives (1 before, 1 after) and
`ELSET=Efaces` is still written, so renumbering does not destroy detection.
Element ids are **unique but not contiguous**, confirming §8.3's recorded
hazard: `compact_mesh` advances the element id twice per face despite its
docstring promising to remove all gaps. M2 therefore asserts uniqueness and
deliberately does *not* assert contiguity, which would fail on correct output.

**A cross-finding worth carrying into Stage 2.** The face element emitted here
is `S4`, and D3 showed a composite `*SHELL SECTION` accepts only S8R or S6. So
a *composite* mixed model needs a quadratic face mesh; a linear one is
structurally valid (M1) but cannot carry a laminated section (D3). Stage 2 must
not treat "faces written" and "sections assignable" as the same condition.

#### A third probe bug, latent in both

`argparse` with a `nargs="*"` positional validates its **empty default**
against `choices` and rejects it, so an argument-less call failed with
`invalid choice: []`. Neither probe uses `choices` any more; both validate the
case names by hand. It surfaced on the mesh probe only because that one is
called programmatically as `main([])`, but the deck probe carried the same
latent fault.

---

## 10. Adjacent: a laminate OFFSET property, adoptable out of order

Not a stage of this plan. It can be built, tested and landed **before Stage 0**,
and it removes a wrong-answer risk from the plan's motivating case.

**What.** Give the Composites laminate a per-skin offset and route it into the
FEM `ShellThickness.Offset` property.

**Why it is nearly free.** The capability already exists in FEM:
`write_femelement_geometry.py:155` writes
`*SHELL SECTION, {elsetdef}{material}, OFFSET={offset:.13G}` from
`shellth_obj.Offset`, and the `ShellThickness` object already carries that
property. A grep across `src/Mod/Composites/objects/` and
`util/fem_util.py` finds no offset anywhere, so the leaf is missing but the
trunk is there.

**Why this plan needs it.** A shell-solid sandwich is two face interfaces —
the F family — and the two skins are bonded to the core's opposite faces.
The shell's reference surface lands on the core face, so each skin sits a
half-thickness inboard of its own midsurface, and sandwich bending stiffness
goes as the square of the separation between the skins. Thin skins: negligible.
Thick laminates: an answer that is quietly too soft, with nothing to signal it.
It is also what makes the tie tolerance physical rather than nominal: §11.3's
research found that an offset-0 skin whose reference surface is the interface
must be tied at `t/2`, while an offset that puts the reference surface *on* the
interface leaves an expanded node at zero distance, so §10 is load-bearing for
the tie as well as for the stiffness.

**Why it can go early.** It needs no mixed mesh at all. A pure shell model can
carry the offset, so it is verifiable against an equivalent solid model or a
closed-form sandwich solution today, independently of every stage here.

**Two design points, both cheap to get wrong.**

1. The offset must be **per skin, not per analysis**. A sandwich's two skins
offset in opposite directions, and one model-wide scalar cannot say that.
2. Confirm the sign and direction against the manual. The offset is in units of
   shell thickness, and the manual's definition is: *"OFFSET=0.5 means that the
   reference surface is the top surface of the shell"* (`*SHELL SECTION`, and
   the same paragraph defines which of the expanded faces is `S1` and which is
   `S2`). A positive offset therefore puts the section on the
   **negative-normal** side of the reference surface, and the sign is chosen per
   skin from which way that skin's core lies. Reversed signs put both skins
   inboard and make the sandwich *softer than no offset at all*, which still
   looks plausible in a fringe plot. Stage 7 fixed a silent coupling bug caused
   by exactly this definition — a `*TIE` written on the wrong shell face (§3) —
   so treat the sign as load-bearing, not cosmetic.

*Exit criterion:* a shell-only sandwich case whose bending stiffness matches an
equivalent solid model within a tolerance stated before the run, with the
offsetted model measurably stiffer than the un-offsetted one. If the offsetted
model comes out softer, the sign is wrong — and that is the check, not a
review of the code.

---

## 11. What is still missing

Written after Stages 0-9 landed, by inspecting the tree rather than reading the
stages back. Ordered by severity; each entry says what would close it. A stage
being "done" above means *its exit criterion was met*, not that the capability
is complete.

### 11.1 ~~The loud failure the ADR obliges does not exist~~ — **fixed**

ADR 0004, obligation 3: *"A connection that cannot be expressed as a surface
must raise."* It did not. `femsolver/calculix/write_constraint_tie.py` had no
`raise`, no `assert`, no `Exception`; and the tie check in `checksanalysis`
counted references while its own message said *"two needed faces"* — it never
asked whether either reference **was** a face.

So an **E-shaped** connection passed validation, and the writer then built a
`*SURFACE` whose face index came from an edge mask: a deck that means nothing,
with no error from FreeCAD and none from CalculiX — a silent wrong deck on a
path that is now on by default.

Fixed by `checksanalysis._tie_references_that_are_not_faces`: every tie
reference must resolve to dimension 2 (a face, or a compound of faces), judged
by what the shape holds rather than by its `ShapeType`. Verified: the mixed
suite is **29/29**, both new tests failing before the change and passing after,
and `test_ccxtools` shows no tie-related failure. The E-family examples now
refuse to write a deck, which is what `G10`/`G11` required.

### 11.2 ~~A composite section on a linear mixed shell is not guarded~~ — **fixed**

D3 (§9.8) measured that a composite `*SHELL SECTION` is accepted only for **S8R
and S6**. The Composites path happened to be safe — `_shell_example_common.py`
sets `ElementOrder = "2nd"` for composite examples — but that is a Composites
convenience protecting a FEM invariant, and it did not cover a user who builds a
mixed model by hand with a linear shell mesh. That case produced a deck CalculiX
refuses (`Element 2 is not a S8R nor a S6 shell element`) after FreeCAD had
already written it.

**The writer now refuses it.** `write_femelement_geometry.py` asks
`_is_composite_section` — a section provider replaces the whole MATERIAL chunk of
the card, so the card is layered exactly when that chunk's first field is
COMPOSITE — and, when it is, that the elements the section covers have 6 or 8
nodes: S6 triangles and S8R quads. Node count is the only shape test available
from Python, because `FemMesh.getElementType` reports an element's *dimension*
("Face"), not its shape, and the CalculiX names are chosen in C++ where the
`*Element` cards are written. The error names the ShellThickness, how many of the
elements it sections are linear, the first offender and the remedy.

Asserted in `femtest/app/test_mixed_shell_solid.py`, on that module's own fixture
— which is a linear quad4, so it is already the failing case: a stub provider
naming COMPOSITE makes the section layered without the test needing Composites,
the write raises, and the same model with the quad's mid-side nodes writes a
`COMPOSITE` section. The deck snapshot reports *no deck changed and no example
moved* across all **55** examples, so nothing was relying on the gap.

### 11.3 F1 is solved in CI now; the other families are not

**The mixed path is solved for real in CI.**
`compositestests/test_mixed_coupling_numerical.py` runs ccx on the probe's own
models and asserts the physics a deck-text test cannot see — that the tied skin
matches an all-solid rebuild, and that it is stiffer than the bare spar, which
is the detector for a silent uncoupling. Measured: mixed **6.422333e-02 mm**
against all-solid **6.416312e-02 mm** (**0.09 %**), bare **1.219529e-01 mm**
(**1.90x**). The models are reached through the probe rather than copied,
because this section quotes that probe's numbers and a second copy would be
free to drift from them. The tolerances (5 %, 1.2x) are stated in the test and
are not tuning knobs.

**All four face families are solved too.** f1, f2, f3 and f4 are built from
Fem's own fixtures (`constraint_mixed_face_coupling`), and each solve asserts
what CalculiX says about its tie: a slave node with no opposite master face is an
uncoupled model, which no deck-text test can see. That assertion found a defect
at once — f1 and f2 tied with `POSITION TOLERANCE=1.0` while the shell section is
10.0 thick, and CalculiX has by then expanded the shell into through-thickness
nodes half a thickness either side of the reference surface, so **30 and 5 slave
nodes** were never tied, with no failure at all: the job converges and the deck
looks right. The tolerance is now derived from the geometry instead of picked —
`SHELL_THICKNESS / 2` for the two variants whose reference surface *is* the
interface, and `COUPLING_GAP_MM + SHELL_THICKNESS / 2` for the offset and bag
variants — and all four report zero untied nodes. (f3 and f4 had been using 60.0
where 55.0 is the geometry.)

**Why the tolerance has to be that size, and the route that is not open.** `*TIE`
is 3D-only, so CalculiX expands the shell and hands the *expanded* nodes to the
master-face search; `S1`/`S2` name the two extreme faces of that expansion, half
a thickness either side of the reference surface, which is why the tolerance has
to reach that far. Tying the *reference* nodes instead — a `TYPE=NODE` slave,
which the manual permits — was implemented and measured: ccx accepts it and
reports **no** untied node, but the joint is no longer rigid, **7.722483e-02 mm**
against the all-solid rebuild's **6.416312e-02 mm** (+20 %), where the
element-face slave gives **6.422333e-02 mm** (+0.09 %). CalculiX links a
reference node to its expansion nodes by an **averaging** MPC —
`newnode + knor(indexk+3) − 2·node = 0`, so the reference node is the mean of two
expanded nodes. It is written in `gen3dsurf.f` (for a node belonging to a nodal
surface, which is why the `TYPE=NODE` slave inherited it) and in `gen3dmpc.f`
(for any node that already carries an MPC); Dhondt writes the same equation out
in the forum post cited below. The reference node is therefore not a point of
the expanded mesh, and a tie on it constrains the mean through the thickness:
the +20 % is what a reference node *is*, not a defect to be patched.

**The fine tolerance is reachable in the deck, so there is no case for touching
ccx.** That is the answer to the research this section was left holding open,
and three independent readings agree — all three of them already true of decks
FreeCAD writes:

- The tolerance has to cover the distance from the expansion face `S1`/`S2`
  names to the master face. For a lap joint that distance *is* the
  mid-surface-to-mid-surface distance; for a joint referenced to the real
  (offset) surface it is ~**0.2 mm** (PrePoMax forum, *TIE constraints for shell
  weldments*, Jirip's measured conclusion, September 2026).
- A large tolerance is not what risks a false match, which was the worry that
  started this. Only nodes of the selected slave surface are candidates, and a
  candidate must both sit within the tolerance orthogonally and project inside
  the master face (the manual's criterion, quoted by FEAnalyst in that thread).
  `t/2` is therefore the honest, exact requirement for an offset-0 shell whose
  reference surface is the interface, not a fudge that ought to be smaller.
- The way to make it smaller is the shell offset, not the tie code.
  `gen3dfrom2d.f` places the two outer expansion nodes at `ref − t·(0.5+offset)`
  and `ref + t·(0.5−offset)`, so `OFFSET=−0.5` puts the first *exactly on* the
  reference surface (and `OFFSET=+0.5` puts the second there). Set the offset so
  a skin's reference surface is the physical interface — §10's requirement on
  stiffness grounds — and the face the tie names coincides with the master face,
  and the tolerance need only cover the modelling gap. Both are `*SHELL SECTION`
  fields FreeCAD already writes.

What stands: the offset moves material through the thickness, so it changes the
model and the result, and where the meshed surface genuinely *is* the
mid-surface, `t/2` is what the geometry requires. What is now decided: **no ccx
change.** The distorted joint stresses at a tie are inherited rather than ours —
Abaqus answers that with a dedicated shell-to-solid coupling and CalculiX has
none (forum *Tie and surfaces?*, Calc_em, December 2021). One hazard the
research turned up is not about the tolerance at all: §11.9.

Sources: CalculiX forum `t/tie-and-surfaces/887`,
`t/tied-constraint-fails-if-a-forces-are-prescribed-to-slave-nodes/1660`,
`t/tie-constraint-on-the-edges-of-2d-elements/2855` (a tie on the edges of
plane-stress elements is still broken in 2.23 — that is §11.1's refused family,
and this says refusing it was right), and PrePoMax
`t/tie-constraints-for-shell-weldments-internal-edges-and-mid-surface-gaps/3568`.

What remains open, stated exactly:

- **The 31-test FEM mixed suite still never runs CalculiX.** Every call is
  `FemToolsCcx(..., test_mode=True)`, and `femtools/ccxtools.py:551` refuses
  outright: *"CalculiX can not be run if test_mode is True."* That suite asserts
  deck text and mesh structure; solving lives in the Composites suite above.
- **e1-e3 are refused, not unsolved.** The edge family cannot be generated at
  all: §5 puts edge-connected coupling out of scope and §11.1 makes it a loud
  error, so those three have no displacement number by design rather than by
  omission. Give them one only if ADR 0004 selects an edge mechanism.
- **The Composites example test can still skip.**
  `test_mixed_shell_solid_plate_solves` `skipTest`s when the FEM stack is
  unavailable, so it is weaker than the new numerical test, which skips only
  when no `ccx` binary exists.

### 11.4 A mixed result displays, but the two parts are not distinguishable

V1-V3 pass, so the panel does show a result. What is absent is any way to tell
the skin from the solid: a skin coincident with a solid face z-fights, and
`ViewProviderFemMesh.VisibleElementFaces` is a **read-only computed getter**
(`src/Mod/Fem/Gui/ViewProviderFemMeshPyImp.cpp`) with no dimension filter. The
existing knobs — `ColorMode`, `ShowInner`, `MaxFacesShowInner` — none of them
separates shells from solids. A toggle needs a C++ view-provider change and a
rebuild, which is why it is the one outstanding item with a build cost.

### 11.5 ~~The motivating case is not demonstrated with a real laminate~~ — **demonstrated**

`mixed_shell_solid_plate.py` still uses `IsotropicEquivalent` — deliberately, to
stay off the drape backend — so it was never the motivating case. The motivating
case is `mixed_shell_solid_wing.py`, and it now solves end to end:
**`test_mixed_shell_solid_wing_solves`** (`test_compositeexamples`) meshes,
writes and runs a CalculiX job on it, and asserts the deck holds one
`*SOLID SECTION`, `COMPOSITE,ORIENTATION=` shell sections, quadratic shells
(either `S8R` or `S6`) and exactly **two** `*TIE`s — one per skin. It is green,
measured at **375 s**, which is the first time it has passed: it was re-armed in
commit `7fedad03b4` with a note that the end-to-end run had not finished, and it
had never been run to green since. What it failed on was its own assertion rather
than the model — it demanded `S8R` when the mesher produces `S6` triangles and
CalculiX accepts both (see §11.2), and the assertion's own message said so.

What it is: a NACA 2412 wing, 1000 mm span, 200 mm chord, a solid Rohacell 51 WF
core and a 160 gsm biaxial carbon-epoxy `Composite::Shell` on each lateral
surface — a real per-ply `[+/-45]s` laminate with a fibre orientation, not a
smeared equivalent. The skins are meshed apart from the core and merged
node-disjoint (§8.3), then tied. The load case is a cantilever, so the tip
deflection is interpretable, and the test's bound is a factor on an estimate
**computed from the model**: the skins' in-plane stiffness `A11 = sum(C11_k t_k)`
read from the laminate's own merged layers (`FEMLayers`, the ones the writer
emits), the outline's section integrals taken from the same NACA ordinates the
core is built from, and the core's shear modulus from its own two properties.
That ideal sandwich gives **46 mm**; the solve gives **94.9 mm**, so the bound is
the estimate **x4** — the ~2x the ideal omits is the section distortion and shear
lag a sandwich beam does not have, while the bare foam core would be ~65x the
estimate. (It is a bound, not a compared pair; the compared-pair check lives in
§11.3's numerical test, on a smaller model.)

**The bound was 50 mm against a ~6 mm estimate until `b45b7fb10f`, and both were
wrong for the same reason**: the estimate used `E_skin = 135 GPa`, which is the
ply's *fibre-direction* modulus, while the skins are `[+/-45]s` and the deck's
own `A11` gives 31.5 GPa for them. The load was also not going where the code
said — it followed the tip face's **+Y** normal instead of −Z, which is a
spanwise load rather than a bending one, and that is why a bound that should have
failed passed. Both are fixed; §11.12 has the mechanism.

**It could not run until three FEM defects and a mesh-sizing bug in front of it
were fixed**, which is why it is recorded here and not only in the example:

* `FemMesh::getFacesOnly` / `getEdgesOnly` rebuilt every volume's node set once
  per face — quadratic, and **83 % of all samples** on this mesh. The deck write
  was 286.6 s against a solve of 26.6 s (10.8x the solve).
* `write_mesh` and `write_step_output` each asked `is_mixed_femmesh` about the
  same unchanged mesh: **26 % of the run** answering a yes/no question twice.
* Generated per-element `*ELSET` names reached **82 characters** against
  CalculiX's limit of **80**, so the wing had **never been solved once** and
  nothing said so. FreeCAD checked the base name; the writer then appended the
  element id to it, which is how a name that passed the check still arrived over
  the limit. The prefix is now hashed to 20 characters — **md5**, not `hash()`,
  which is salted per process and would make decks irreproducible.
* `MeshSizeFromCurvature` (12 elements per 2π) refines independently of
  `max_size`, and the NACA 2412 nose radius is only 3.2 mm, so the core meshed to
  **294,917** points instead of **21,332** — 11x finer than intended.

The full cost study — the measurements, the change that bought nothing and is
recorded anyway, and the set-name defect — is
[`fem-mesh-query-cost.md`](fem-mesh-query-cost.md). The same tool that found
those (`inspect_wing_pipeline_cost.py`) also made the two drape changes
measurable, and the drapes are now ~54 % cheaper than when first measured
(nextdrape submodule `5ccc7fd`, `aba05cc`).

What is still open on this case: per-layer results are averaged away on the
displayed mesh (§11.6's trade), and the S8R/S6 requirement is asserted by this
example but not by Fem (§11.2). The tie warning that looked like a third is
accounted for in §11.7.

### 11.6 ~~A solved mixed model makes the GUI unresponsive, and its result is
~8x the mesh~~ — fixed

- **What it was.** Opening the saved mixed wing (`/tmp/wing.FCStd`, 78 MB) in the
  GUI and viewing `CCX_Results` is very slow, and the GUI process was later found
  gone.
  Measured on that deck and its frd: the deck defines **35,385 nodes** (ids
  1..35,385, all distinct and contiguous, and no element references beyond
  them), while the frd declares **289,241** — the mesh's own nodes plus
  **253,856 expansion nodes** with ids up to 414,924. So the result spans 8x the
  mesh, the panel's exact-node-count gate cannot pass, and the GUI carries 8x the
  data it should.

  **`OUTPUT=2d` does not prevent this for this model**, which is where Stage 8
  generalised too far from a smaller case. Re-running ccx on the same deck with
  each setting: `OUTPUT=2d` → 289,241 frd nodes, `OUTPUT=3d` → 275,189. The
  manual says why: 2D output *"averages the fields in the expanded elements to
  obtain the values in the nodes of the original 1d and 2d elements"* — the
  expanded model is present either way, so the option changes where the
  *results* land, not which nodes the frd lists. The probe's own model did give
  3910 == 3910, so mixed-ness is not the trigger; the wing's shells carry a
  **composite** section, the probe's a homogeneous one. Removing the per-element
  `ORIENTATION` from every shell section and re-running still gave 289,241, so
  the orientation cards are ruled out. That leaves the layered `COMPOSITE`
  section itself as the candidate, and it has **not** been isolated from model
  size: the probe's comparison is small *and* homogeneous, the wing is large
  *and* composite. The `*NODE FILE` placement was also checked and is correct -
  it sits inside the step (`*STEP` at line 180,061, `*NODE FILE` at 180,254),
  which the manual requires for the option to apply at all.

  Consequence for the fix: for a composite mixed model it is not a deck option.
  Either the reader maps expanded results back onto the mesh, or the panel and
  the result object must cope with an frd 8x the mesh without freezing. Neither
  is small and neither has been attempted.

  **The stages have now been separated, and the cost is not where the size is.**
  Building the same wing up to each stage and opening each save in the GUI
  (`inspect_document_load_cost.py`, clean documents with the per-part meshes
  removed):

  | stage | objects | GUI open | delta | headless open |
  |---|---|---|---|---|
  | geometry | 3 | 0.15 s | — | 0.20 s |
  | + composite shells | 29 | 7.30 s | **+7.15 s (48 %)** | 0.55 s |
  | + FEM mesh | 41 | 12.46 s | +5.16 s (35 %) | 0.72 s |
  | + results | 45 | 14.84 s | +2.38 s (16 %) | 2.50 s |

  Three things follow, and two of them contradict what this section assumed.
  The cost is **GUI-only** - headless the whole lot is 2.5 s - so it is
  ViewProvider construction, not document parsing. It is **not the results**:
  the 289,241-node frd adds the *smallest* stage, while the two draped composite
  shells add the largest, at 3.6 s each for a 296 KB document. And **nothing
  re-executes on load** - measured as zero drape solves and 0.00 s of settling
  recompute at every stage - so this is not a re-solve hiding behind a load.
  Rendering is also cheap: making the mesh and result visible and fitting the
  3D view costs 0.39 s.

  So the culprit is eager per-object view geometry, worst for `CompositeShell`
  (the drape weave), next for `FemMesh`, least for the result. 3.6 s for one
  draped shell of ~8,000 lattice points is ~0.4 ms per point, which is the
  signature of building Coin objects one at a time.

  **And the freeze itself is now reproduced and explained - it is picking, and
  it is a different object again.** Reported symptom: panning and re-zoom are
  fine, but scroll-zoom with the pointer *over the body* stalls for seconds,
  and over empty space it does not. A wheel notch issues a ray pick, so a ray
  pick over the body against empty space measures it exactly:

  | configuration | pick |
  |---|---|
  | pointer over the body, everything visible | **0.44-0.48 s** |
  | pointer over empty space | 0.000 s |
  | model mesh `WingPipelineCost_FEMMesh` alone | **0.023 s** |
  | **result mesh `CCX_Results_Mesh` alone** | **0.412 s** |
  | `CCX_Results` or `Pipeline_CCX_Results` alone | 0.000 s |

  The slow object is **the results mesh** - the one FreeCAD builds from the frd -
  and it holds **289,239 nodes against the model mesh's 35,383**. So the
  oversized frd does matter after all, just not for the reason this section
  first gave: it makes a pickable 289k-node display mesh whose every hover pick
  costs 0.4 s. Display mode is irrelevant (even `Nodes` only is 0.42 s) and the
  scene graph has just 2,648 nodes, so it is neither triangle count nor
  traversal - it is the pick against that object.

  **The first mitigation** was `CCX_Results_Mesh.Selectable = False`, which takes
  the pick from 0.477 s to 0.026 s (committed, `af92dc0568`). Nothing else tried
  helps: `Selectable = False` on the *model* mesh changes nothing (its pick was
  already 0.023 s, which is why testing it there proved nothing), `ShowInner =
  True` makes it worse (0.735 s), and `SelectionStyle = "BoundBox"` does nothing
  either - it only sets `SoFCSelectionRoot::selectionStyle`
  (`Gui/ViewProviderDocumentObject.cpp:233`), which decides how a hit is
  *reported*, not whether Coin's ray pick walks the geometry. What actually
  cheapens a pick is `SoPickStyle::UNPICKABLE`, set by
  `ViewProviderGeometryObject::setSelectable`
  (`Gui/ViewProviderGeometryObject.cpp:346-373`).

  Which is why the **post pipeline** needed different treatment: its view
  provider (`ViewProviderFemPostPipeline` : `ViewProviderFemPostObject` :
  `Gui::ViewProviderDocumentObject`) does not inherit `ViewProviderGeometryObject`
  - where `Selectable` is declared - and its root holds **zero `SoPickStyle`
  nodes**, so its geometry is always walked. Introducing one took its pick from
  0.269 s to 0.024 s. Not applied, because the root fix makes it unnecessary.

  **The root cause, isolated** - same deck, nodes and elements byte-identical,
  only the sections changed:

  | deck | shell sections | frd nodes | extra |
  |---|---|---|---|
  | original | 6,822 x `COMPOSITE` | 289,241 | 253,855 |
  | homogeneous | 1 x `*SHELL SECTION` | **35,385** | **0** |

  So it is the **layered `COMPOSITE` section** - not model size, and not
  mixed-ness. The manual says why `OUTPUT=2d` could never help: *"In the .frd
  file, however, each layer is expanded independently ... (no matter whether the
  parameter OUTPUT=3D was used)."* ccx reports "layers per element: 8", and the
  extra ids sit on the shell normal at exactly the ply thickness (0.0831 mm).

  **Fixed in the reader** (`089a6fcae7`): when the frd's nodes are a strict
  superset of the model mesh's, the result mesh is the analysis's own mesh and
  the result rows are filtered to it. Measured on a real import: result mesh
  289,239 -> **35,383** nodes, max |u| 0.113354 -> 0.113326 (0.02 %), frd import
  19.5 s -> **6.5 s**, and a pick over the body with the pipeline in `Surface`
  mode showing a field **0.29-0.48 s -> 0.036 s**. The scroll lag is gone.

  **The trade**, recorded because it is a real loss: through-thickness and
  per-layer stresses are averaged away on the displayed mesh, so individual plies
  are no longer separable. The expanded mesh was the only way to see per-layer
  fields.

  Still open: the exact arithmetic of the extra-node numbering (289,240 records
  against 289,241 declared, with id gaps of 2 and 4), and per-layer stress
  fidelity after mapping.

  The `Selectable = False` mitigation is **kept**. It is no longer load-bearing -
  at 35,384 nodes a pick costs 0.063-0.073 s even when selectable, against 0.45 s
  for the expanded mesh, so it is not what makes the GUI usable any more - but it
  still nearly halves the pick (0.073 -> 0.040 s), which makes it a cheap
  optimisation rather than wasted weight.

### 11.7 ~~The wing's ties are partly uncoupled~~ — **disproved; the warning was
miscounted**

Solving the wing writes a `.nam` file listing tie slave nodes in duplicated pairs
(`35388` twice, `35415` twice, …), which was read here as the Stage 7
silent-uncoupling symptom. It is not one.

CalculiX's `gentiedmpc.f` writes `<job>_WarnNodeMissTiedContact.nam` for **two
unrelated reasons**, and only stdout tells them apart:

- **no opposite master face found**, or one found beyond the position tolerance:
  no MPC is generated and the node is genuinely not coupled — the defect, and a
  silent one;
- **the DOF already has an SPC or another MPC**, so no tie MPC is needed: the DOF
  is eliminated either way, which is bookkeeping, not a coupling failure.

Both write the node number to the same file. The wing's is entirely the second:
its run has **165 entries**, and its log has **165 x "DOF is not active"** and
**0 x "no tied MPC"** — not one slave node failed the face search. The
multiplicity is the DOF count rather than a repeated node (measured: 70 nodes with
DOFs 1-2, 7 with 1-3, 2 with 2-3), because a node is listed once per inactive DOF.

**The two causes are separable, measured on the 14-node plate deck that
`inspect_mixed_cantilever` builds** — the same probe whose numbers §11.3 quotes:

| deck | `no tied MPC` | warnings | `.nam` |
|---|---|---|---|
| as built | 0 | 4 DOFs already constrained | 17, 17, 20, 20 |
| skin-edge `*BOUNDARY` deleted | 0 | 0 | **no file written at all** |
| master covers half the tied face | 1 | 2 already constrained | 17, 20, 20 |
| shell 16 mm thick, not 1.6 | **4** | 0 | 17, 20, 23, 26 |

So the entries are slave nodes that are *also* prescribed by the fixed
constraint — delete that constraint and the file vanishes — while an over-thick
shell, whose expansion nodes fall outside the in-face tolerance, produces the
other message. The wing has the first case.

**What this changes.** The `.nam` alone is not evidence of uncoupling, which is
the trap that produced this entry, and the classification now lives where ccx's
stdout is already owned — `femtools/ccxtools.py`, beside the existing
`has_no_material_assigned` and `has_nonpositive_jacobians`:

- `tied_mpc_warning_counts(ccx_stdout)` returns the two counts;
- `FemToolsCcx.has_missed_ties()` reports the uncoupled one in the report view,
  on the success path as well as the failure path, because a missed tie does not
  make the job fail. A user's own model is therefore no longer silent either.

The probe keeps only the policy: `_check_tie_warnings` reuses that
classification and refuses a run that has an uncoupled node, so every solve the
numerical test performs also asserts that the tie coupled every slave node it was
handed.

One residual, recorded so the search is not repeated: the ids in the `.nam` are
ccx's internal expansion-node numbering and do **not** match the frd's — measured
0 of 79 present in either the `OUTPUT=2d` or the `OUTPUT=3d` frd — so a `.nam` id
cannot be located by coordinates.

And one cause that *does* mean an uncoupled node wears this same warning — a
point load on the tie's shell slave — is §11.9.

### 11.8 Coverage the plan does not reach

Two gaps in what the tests exercise, as opposed to what the code can do:

- **`Stiffener` / `Bulkhead`** — no mixed coverage at all.
  `quasi_iso_stiffener_panel` is all shells; Bulkhead has no FEM example at all.
- **The GUI half of §8** — `femtest/gui/test_mixed_shell_solid.py` does not
  exist, so §8's admission rule (*a case passes in both modes*) is unmet and the
  matrix is headless-only. Amend the rule or write the test; do not leave the
  rule standing against a tree that does not satisfy it.

### 11.9 A point load on a tie's shell slave can drop the tie, under a warning we
call benign

A tie's slave can be lost silently when the same node carries a point load, and
the warning it writes says "already constrained" — the cause §11.7 files as
bookkeeping.

A point force in a shell node is not applied to that node. `gen3dforc.f` writes
the same expansion link that `gen3dsurf`/`gen3dmpc` write, but with the
**expanded** node as the dependent term:

```
knor(indexk+1) + knor(indexk+3) − 2·node = 0
```

So whichever of the expansion's nodes the tie names as its slave can no longer be
the dependent term of the load's MPC, and `gentiedmpc` reports *"DOF n of node X
is not active; no tied constraint is generated"*. Guido Dhondt worked this case
through in the forum thread *Tied constraint fails if a forces are prescribed to
slave nodes* (`calculix.discourse.group/t/…/1660`, 3 July 2023): two shell layers
tied on the lower face of the upper one, plus a `*CLOAD` on the upper layer, and
the tie is lost at the loaded nodes; his remedy is to swap master and slave. He
notes in the same post that `*DLOAD` writes no MPC, so a pressure load cannot
cause this.

Why the existing classification cannot see it: ccx's stdout is identical for
"an SPC already prescribed this DOF" (benign) and "this DOF is dependent in the
expansion MPC a point load created" (an uncoupled node), and
`tied_mpc_warning_counts` counts both as *already constrained*. FreeCAD can tell
them apart, because it wrote both the tie's slave surface and the `*CLOAD`.
Closing action: a write-time check that reports a tie whose shell slave carries
a `*CLOAD` node, naming the nodes and the remedy (swap master and slave, or load
the master side). Not yet written — and now without a fixture that shows it, so
one would have to be built as Dhondt's arrangement rather than found in ours.

**Our own fixtures are not exposed to it, measured rather than assumed.** f1-f4
apply their 100 N force to the **shell** (`constraint_mixed_face_coupling.setup`
— `add_force(..., extreme_face_reference(shell_obj, ...))`), the tie's slave is
also the shell, and in `_covered_solid` the shell wraps the solid, so the loaded
face is a tied face. Whether the two collide was left open here, and it is now
settled: each family's own deck was run twice — as FreeCAD wrote it, and with the
`*CLOAD` block deleted and nothing else changed (`diff` shows that block and its
comment banner are the only difference) — and ccx was asked what it says about
the ties.

| variant | `POSITION TOLERANCE` | `no tied MPC` | `DOF … is not active` |
|---|---|---|---|
| f1 | 5 | 0 / 0 | 74 / 74 |
| f2 | 5 | 0 / 0 | 4 / 4 |
| f3 | 55 | 0 / 0 | 0 / 0 |
| f4 | 55 | 0 / 0 | 72 / 72 |

(with the load / without it). The counts are identical, the `.nam` files are
byte-identical, and ccx's own bookkeeping does not move either: `multiple point
constraints` is 2881 for f1 and f4 and 481 for f2 and f3 in both runs, `number of
equations` is unchanged at 74, 36, 33 and 101, while `concentrated loads` falls
from 40, 32, 20 and 20 to 0. So in these four models the force adds **loads and
no constraint at all**, and cannot take a DOF from the tie. f3 is the
discriminating case: its shell carries no SPC, so a collision could only have
appeared as a warning, and it has none either way. Re-measured after §11.12 moved
the load onto its intended axis: identical counts, identical `.nam` contents and
identical constraint totals, so the table above is the same before and after.

That is also the order the source requires, which is what makes the null result
mean something: `gen3dforc` runs at input reading (`calinput.f:1327`) and
`gentiedmpc` in the pre-run (`CalculiX.c:720`), so a collision would be reported
rather than passed over.

What this does **not** do is disprove Dhondt's case. His tie was between two
**shell layers** with the load on the slave layer; ours is a shell slave against
a **solid** master face. The hazard above stands as written — it is simply not
reproduced by the coupling this plan builds, so the write-time check has no
failing fixture in the mixed face family to be developed against.

*Exit criterion:* a fixture that puts a `*CLOAD` on a shell tie slave and asserts
the writer reports it with the nodes named, and shows the same model with the
load on the master side (or as a `*DLOAD`) still writes and solves. It has to be
the two-shell-layer arrangement Dhondt describes: the mixed face families do not
exhibit the hazard, so there is nothing in them to fail first.

### 11.10 Deliberate leftovers, and small bugs

- **`test_rosette_scenarios` SIGSEGV** on a compound of boxes — the guard covers
  top-level solids only. Unrelated to the flag.
- **Flag deletion** — the getter and branches remain, by design, until a release
  has shipped with the default on.
- **The branch is unmerged.** It is all commits on `fem-mixmesh` off
  `fem-unified`, unreviewed and unupstreamed, and **no PR is planned**: the
  branch is the working record.

### 11.11 Parked: landing a shell's expansion node on the tie's contact plane

**Parked, not scheduled.** The question was whether FreeCAD should always
arrange the shell's section offset so that an expansion node lies exactly on the
contact plane — correcting it, or warning when it does not. The research below
was done and is recorded so it is not repeated; **nothing here is being
changed**, and the entry is the record rather than a plan.

**What ccx does, in order.** The two halves of the proposal both exist already,
and the order between them is what matters:

- **Selection gate, first.** `gentiedmpc.f:283-288` compares the perpendicular
  distance from the slave node to the master triangle (`dist`) with the tie's
  position tolerance (`tietol(1,i)`), and sets `isol=0` — dropping the node, with
  *"opposite master face found but too far away; distance: …; tolerance: …"*.
  This is the only place a tie node is lost.
- **Correction, second.** `gentiedmpc.f:380-386` (and `:636`) moves the slave
  node onto the master face (`co(k,node)=p(k)`), gated by `tietol(2,i).gt.0`.
  That flag is `*TIE, ADJUST`: default `1.d0` (`ties.f:56`), set to `-1.d0` only
  by `ADJUST=NO` (`ties.f:82`). So **ccx's own default is to correct**, and
  FreeCAD switches it off — `Adjust` defaults to `False` and
  `write_constraint_tie.py:111` emits `ADJUST=NO` — which is why no FreeCAD deck
  gets the correction today.

Two things follow, and both were the reason the question was not simple:

- **Correction cannot rescue selection.** The gate runs first, so `ADJUST` only
  moves nodes that were already accepted. Landing exactly is therefore not a
  substitute for a correct tolerance; it makes a *small* tolerance sufficient.
- **On a shell, `ADJUST` moves an *expansion* node**, deforming the element's
  through-thickness geometry. Turning it on by default is a model change across
  every deck, not a bug fix.

**And `Tolerance = 0.0` is not zero.** It is FreeCAD's default
(`femobjects/constraint_tie.py`), and `gentiedmpc.f:162` replaces anything below
`1e-10` with ccx's own `tolloc`, computed at `:98-105` as
`0.025 ×` the mean over master triangles of `|n·cg + d|`. Whatever that
evaluates to for a given model, it is smaller than the `1.0` that already failed
the f1/f2 fixtures at `t = 10` (§11.3) — so the *default* is the weakest of the
three settings, and the examples' `1.0` is a workaround that holds only while
`t` stays under ~2 mm.

**Where the offset fits.** The expansion faces sit at `ref − t·(0.5+o)` and
`ref + t·(0.5−o)` (`gen3dfrom2d.f:152,159`; the composite/layer block at
`:238-293` uses the same `o`, scaled by the accumulated ply thickness). With the
master plane at signed distance `g` from the reference surface, a node lands on
it exactly when `o = g/t − 0.5`, and the tolerance the writer's chosen face needs
is

| offset | slave face | required tolerance |
|---|---|---|
| `o < 0` | `S1` | `abs(g − t·(0.5+o))` |
| `o ≥ 0` | `S2` | `g + t·(0.5−o)` |

The two constants `6fc22a9334` derived by hand come straight out of that:
`o = 0, g = 0 → t/2`, and `o = 0, g = 50 → 50 + t/2`. At `o = ∓0.5` the same
table gives `g`, which is §11.3's third reading as arithmetic rather than prose.

**Why it is parked rather than scheduled.**

- **The requirement is per tie pair, not per shell.** A skin tied to the core
  and to a stiffener has two distances; no single offset lands both, so the
  offset cannot become a shell-wide invariant, and at most can be *reported*.
- **It moves material through the thickness**, silently if applied
  automatically. §10 puts the offset where the skin physically is, per skin and
  in opposite directions for a sandwich; deriving it from the tie inverts that
  dependency, and its sign is load-bearing and invisible in a fringe plot.
- **The offset-0 case is not a defect.** Both mixed examples tie at offset 0 on
  purpose (`mixed_shell_solid_wing.py:40`: a 0.33 mm skin eccentricity against a
  24 mm core, under 1.5 %), and `t/2` is the honest tolerance for that
  idealisation. A warning keyed to *"not exact"* would fire on every correct
  mixed model. The defect is only `tolerance < required`, which is the silent
  uncoupling §11.3 found in the fixtures.

**A latent bug found while reading this — recorded, not fixed.**
`_shell_slave_face` (`write_constraint_tie.py:60-77`) takes `S1`/`S2` from the
**first non-suppressed** `geos_shellthickness` offset in the whole analysis, and
never consults where the master is. §10 requires a sandwich's two skins to offset
in *opposite* directions, so once real offsets are in use one of the two ties
will name the far face — a distance of `t` instead of 0 — which ccx reports only
as *"too far away"* and which the function's own docstring already calls silent.
It cannot bite today: every fixture and both examples use offset 0, where `S1`
and `S2` are symmetric about the reference surface and the choice cannot matter.

*If this is ever picked up, in this order:*

1. Derive the requirement before the write, in `checksanalysis`, from geometry
   only — §11.1 already requires both references to be faces, so `g` is a
   plane-to-plane distance, and `t` and `o` come from the section. Warn when
   `tolerance < required`, naming the two faces, both numbers and the remedy
   (`o = g/t − 0.5`, or raise the tolerance). No mesh query, so none of §11.6's
   view cost.
2. Choose the slave face from the master's side rather than from the offset
   sign, which is the latent bug above.
3. Only then set an offset in a fixture, as §11.3's demonstration that the
   required tolerance collapses from `t/2` to `g`.

*Exit criterion:* a fixture whose shell offset leaves its expansion face `t/2`
from the master and whose write fails with the distance and the offset that would
remove it, while the same model with that offset writes and solves with zero
uncoupled nodes.


### 11.12 ~~A force's axis came from the referenced face's normal, not from the direction asked for~~ — **fixed**

Every mixed model in this work loaded along the normal of the face its force was
attached to, whatever the code said. The wing's tip face made that a *spanwise*
load rather than the cantilever load §11.5 asserts; f1 and f4 loaded **+x** and
f2, f3, f4 **+z**.

**`DirectionVector` is not an input.** It is declared
`App::Prop_ReadOnly | App::Prop_Output`, *"Direction of arrows"*
(`FemConstraintForce.cpp:49-55`), and the input is `Direction`, a link to
*"Element giving direction of constraint"* (`:38-46`). The overwrite chain, all
of it in C++:

- `Constraint::execute()` calls `References.touch()` on **every** recompute
  (`FemConstraint.cpp:136-138`);
- that fires `Constraint::onChanged(&References)`, which recomputes
  `NormalDirection` from the first referenced **face** (`:167`, `:192`);
- that fires `ConstraintForce::onChanged(&NormalDirection)`, which overwrites
  `DirectionVector` with ±`NormalDirection` whenever `Direction.getValue()` is
  null — *"Set a default direction if no direction reference has been given"*
  (`FemConstraintForce.cpp:129-139`). The guard asks whether a `Direction` link
  exists, not whether a direction was set.

`analysis.addObject()` touches the constraint, so the overwrite happens while the
model is built and is already in place when the deck is written. A reference that
is not a face (an edge) never recomputes `NormalDirection`, which is why
`mixed_shell_solid_plate` and all five `inspect_mixed_cantilever` forces — every
one of them edge-referenced — were correct by accident, and why §11.3's F1
comparison (0.09 % and 1.90x) is unaffected and still stands.

**Measured** in a scratch document before any code changed: a face-referenced
force set to `(0,0,-1)` reads `(0,0,1)` back after build+recompute; the same on an
edge reference keeps `(0,0,-1)`. In the decks it was visible as `*CLOAD` on DOF 1
(f1, f4) or DOF 3 (f2, f3) with **positive** values, and no `*TRANSFORM` exists
in any of them to make the DOF numbering local.

**Fixed** by giving each force a `Direction` element: an `App::Line` datum whose
local Z axis is the axis wanted, which is what `Constraint::getDirection` reads
from a datum (`FemConstraint.cpp:533-535`). One in
`_mixed_coupling_common.add_force` for the f1-f4 fixtures, and a shared
`add_load_direction()` in `_shell_example_common` for the wing (the core's curved
profile offers neither a linear Z edge nor a planar Z face to point at) and the
plate. All four face-family decks now write their load on **DOF 3, negative**, and
nothing else about them changed: the tie warnings, the `.nam` contents and ccx's
constraint totals are identical to before, so the axis was the only thing wrong.
`test_compositeexamples` pins it — `_assert_loads_point_along_minus_z` asserts the
`*CLOAD` block's DOF and sign in both mixed examples — because this failure is
silent: the job converges and the deflection looks plausible either way.

### 11.13 ~~The mixed-coupling helpers were re-written in every mixed file~~ — **fixed**

The mixed path's geometry helpers had drifted into a copy per caller: five
files held their own version of the lookups (the f1-f4 fixture's shared module,
the wing, the plate, the cantilever probe, the edge fixture), with **four
different spellings of "the face whose centre is on axis = value"** between
them, and they disagreed on the details — only one checked planarity, and only
one compared plane normals rather than centres. The tie, load-direction and
result helpers had done the same: `add_tie` existed once per fixture plus a
local `_add_tie` in each example, and `_max_displacement` twice verbatim.

**One home, in Fem.** They now live in a new module,
`src/Mod/Fem/femtools/mixedcoupling.py`: the shape lookups and the fixtures'
pairing rule `paired_faces_by_plane` (commit `0592ba787a`), then `add_tie`,
`add_load_direction` and `max_displacement` (the second commit). The axis lookup
takes a `planar_only` flag so the wing keeps its stricter check. The moves are
verbatim and the call sites call the same code paths, so **nothing about the
decks changes**: the promotion is a move, not a rewrite, and the flag-off deck
snapshot is green. The module is in Fem rather than in the examples package
because the lookups are geometry, not example scaffolding — a plain Fem model
with a shell-on-solid interface needs the same code — and it is a **new file**
on purpose, so upstream's copies stay where they are and the merge has no
conflict to resolve. Fem installs Python by an explicit source list
(`FEMTools_SRCS`), so the file adds **one line** to `src/Mod/Fem/CMakeLists.txt`.

**What moved where.**

- `femtools/mixedcoupling.py` — `paired_faces_by_plane`, the axis/plane/edge
  lookups, `add_tie`, `add_load_direction`, `max_displacement`.
- `femexamples/_mixed_coupling_common.py` — lost its `add_tie`; `add_force` now
  calls `add_load_direction` instead of building the `App::Line` datum inline.
- `constraint_mixed_face_coupling.py` / `constraint_mixed_edge_coupling.py` —
  import `add_tie` from `femtools.mixedcoupling`.
- `compositeexamples/examples/_shell_example_common.py` — lost its
  `add_load_direction`.
- `mixed_shell_solid_wing.py` / `mixed_shell_solid_plate.py` — lost their local
  `_add_tie` and `_max_displacement`; the call sites use `add_tie(...)` and
  `max_displacement`. The wing's explicit tolerance `1.0` and the comment that
  explains it (the shell's expanded face sits half a skin thickness off the
  reference surface) are preserved unchanged, because the tolerance is a
  property of the section, not of where the helper is defined.

**Verified** at `0592ba787a` for the lookup move: the flag-off deck invariant
reads *no deck changed and no example moved*. The second commit's call sites
compile; its suites (`test_mixed_coupling_numerical`, the Fem mixed suite, and
the wing + plate solves) are run before it is committed.

---

## 12. Proposed: assign the ties from the references the model already carries

**Status: proposal, to be reviewed before any code.** Nothing here is
implemented, and nothing in §11 was changed to make room for it.

**Today's cost.** Coupling a skin to a core means writing the tie by hand —
`ObjectsFem.makeConstraintTie`, two face references (the shell first, because
the first reference is the slave), and a `Tolerance` nothing derives — *and*
finding the pair to reference. That search is real code: the fixtures use
`paired_faces_by_plane` (`femtools/mixedcoupling.py:115`, promoted there by
§11.13), and the
examples use `_lateral_face_names` / `_planar_face_name` / `_face_name` /
`extreme_face_reference` to name the same kind of face from the other side. A
user with a skin on a solid has to reproduce that search, per interface.

**The observation behind the proposal.** The model already declares both halves
of every interface, in objects the pipeline already walks:

- the **solid** — its material's reference, resolved dimension-aware by
  `meshsetsgetter.get_material_elements` (`:1052`), with
  `meshtools.get_shape_dimension` (`:1671`) judging dimension by contents so a
  compound is not mistaken for a solid;
- the **shell faces** — the shell-thickness object's references
  (`membertools.py:266` collects `Fem::ElementGeometry2D`), which
  `meshsetsgetter.get_shell_elements` (`:957`) already resolves to element
  faces. A Composites skin always has one: the provider routes the offset
  through `ShellThickness` (`drape_laminate_provider.route_shell_offset`), and
  the examples create one per skin.

So the interface set is derivable: **the shell-thickness references that lie on
a face of a solid the analysis declares**. The tie is then a *derived* object
rather than a searched-for one, and the search helper already written for the
fixtures is the rule to reuse.

**The proposal, stated plainly.** A pass over the analysis that (1) collects the
solids from the dimension-3 material references, (2) collects the shell faces
from the shell-thickness references, (3) pairs them with the fixture's rule —
parallel normals, planes within a tolerance — and (4) creates one
`Fem::ConstraintTie` per pair, shell reference first, with a derived tolerance.

**Review.**

*Where it lives, and when it runs.* The pairing rule has to leave
`femexamples` for Fem proper — the same promotion Stage 9 did for
`mesh_parts_separately` — so that a plain shell gets it too, with Composites
supplying only the shell-thickness objects it already creates. *When* matters
more than where. Doing it in the writer, or in `meshsetsgetter`, means coupling
that no object records: invisible in the tree, uneditable, and impossible to
switch off for one interface. ADR 0004 obliges a connection that cannot be
expressed to *raise*; silently inventing connections is that failure in reverse.
So an explicit command/helper that **creates the tie objects** keeps the writer
untouched and the coupling visible, which is also the order Stage 8/9 used
(headless helper first, GUI command later).

*Four things that have to be settled first.*

1. **Over-coupling is the default failure.** A shell face lying on a solid face
   is not always a bond: a stiffener web standing on a plate, a patch left free
   on purpose, two parts that merely touch. Pairing every coincidence would
   silently stiffen models that are correct today. The pass therefore needs an
   opt-out per interface, a report of what it created, and a stated coincidence
   tolerance (`COINCIDENT_TOLERANCE = 1e-6`, the value the fixtures use). A
   *declared gap* (the F3/F4 50 mm families) should be a later opt-in, because
   nothing in the model states that gap today.
2. **The tolerance must be derived, not typed.** §11.3 measured what happens
   when it is picked (30 and 5 untied nodes at `t = 10`), and a *default* of
   `0.0` is not even zero to ccx, which replaces it with its own `tolloc`
   (§11.11). For a coincident interface the requirement is `t·(0.5−|offset|)`
   (§11.11's table), and this pass is the natural home for that derivation,
   because it is the same geometry walk that does the pairing.
3. **It depends on fixing the slave-side lookup.** `_shell_slave_face`
   (`write_constraint_tie.py:60-77`) takes the offset from the **first**
   non-suppressed shell-thickness object in the analysis. §10 requires a
   sandwich's two skins to offset in opposite directions, so with real offsets
   one of the two ties names the far face — a whole thickness out, inside no
   tolerance, and silent. Auto-tieing a two-skin model on top of that would
   generate the very failure §3 fixed, at scale. Per-shell lookup first.
4. **The meshing rule cannot be automated here.** The tie only couples if the
   shell's nodes are disjoint from the solid's (`mesh_parts_separately`, Trap
   A), which is decided when the mesh is built and before any tie exists. The
   pass should therefore *check* it — the mesh's `FacesOnly` must hold the
   shell — and refuse rather than create a tie that couples nothing, the same
   loud-not-silent rule as §11.1's guard on non-face references.

*Out of scope for a first cut:* edge interfaces (ADR 0004 keeps those a loud
error until it decides), multi-stage and contact ties, and the task panel.
Ambiguity — a shell face lying on two solids — should be a refusal with the
candidates named, not a preference.

*Exit criterion:* on the wing and the plate, replacing their hand-written
`add_tie` calls (the local `_add_tie` helpers were already removed by §11.13)
with the pass produces the same `*TIE` set up to names, the deck snapshot still
reports *no deck changed*, and a second run creates nothing new.
