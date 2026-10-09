# Plan: Mixed shell + solid elements in one FEM analysis

**Date:** 2026-10-02 (revision 2026-10-09) · **Status:** in progress — Stages 1–8 done and
verified and the mixed path is **on by default** (Stage 9's promotion). Remaining:
publishing the mesh-merge routine from Fem (general, not Composites') and a consumer
example. Stage 7's coupling check passes at
**0.09 %** against an all-solid rebuild, after fixing two defects it found; Stage 8
makes a mixed result displayable (`OUTPUT=2d` on both file cards). See §3.
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
| Shell↔solid coupling | **`*TIE` with position tolerance**, non-conformal meshes, on **node-disjoint** meshes. Chosen because (a) Trap A makes node-merged shells on a solid boundary undetectable, and (b) the CalculiX manual (§8.3) states that a shared 3D↔2D node is a **hinge by design**, so node sharing is not a coupling mechanism at all. `*TIE` covers **face interfaces only** — edge-connected shapes (§8.4, family E) have no mechanism in the tree and are a scope decision for ADR 0004. | Stage 0 |
| Safety gate while incomplete | **Hidden dev parameter** `AllowMixedShellSolid` in `User parameter:BaseApp/Preferences/Mod/Fem/General`, default `False`, read through one getter in `femsolver/settings.py` (next to `get_write_comments`). Deleted in the final stage. | Stage 9 |

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
The manual says a *shared-node* 3D↔2D connection is a hinge; it says nothing
about whether `*TIE`'s MPCs carry a shell slave node's rotations. Probe **D2**
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
- Publish the mesh-merge routine from **Fem**, publicly and generically:
  "mesh each part alone, then merge them node-disjoint" (§8.3), for **any** 2D
  shell and 3D solid, composite or not. It is not Composites' to own — a
  non-composite shell wants it just as much — and it is not a Composites
  convenience. It exists as
  `femexamples/_mixed_coupling_common.mesh_parts_separately`, which is private
  and lives under the *examples*. Layering note: the routine calls
  `femexamples.meshes.generate_mesh`, which imports `gmshtools`, and
  `gmshtools` already imports `meshtools`, so the routine cannot move down into
  `meshtools` without a cycle. "Publishing" it therefore means either promoting
  `generate_mesh` to a public Fem module too, and putting the routine above
  `gmshtools`, or exposing the routine from the examples package without the
  underscore. Decide that when the first non-example caller appears; do not add
  a Composites copy. **Not started.**
- Add a Composites example under `compositeexamples/examples/` per the
  `_shell_example_common.py` pattern — a laminate shell skin and a solid
  feature in one analysis, which is the motivating case for the whole plan.
  **Not started.**
- Delete the getter and the flag branches after one release.

---

## 4. Verification

```bash
# Composites side (unchanged harness)
~/.pi/agent/skills/freecad-dev/scripts/run-tests.sh test_laminate

# FEM app tests, including the golden-deck comparison
~/.pixi/envs/default/bin/FreeCADCmd -t femtest.app.test_ccxtools

# The mixed-mesh geometry matrix of §8
~/.pixi/envs/default/bin/FreeCADCmd -t femtest.app.test_mixed_shell_solid

# The GUI half of §8 (needs a display; see §8.8)
build/debug/bin/FreeCAD --run-test TestFemGui
```

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
- Conformal shared-node shell↔solid coupling (see Trap A). This is not a
  preference: the CalculiX manual (§8.3) states that the 3D↔2D connection is
  **always hinged** when nodes are shared, so a conformal shared-node
  connection cannot be used as a coupling mechanism at all. The merge route
  is node-disjoint by construction and couples through `*TIE`.
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
| **A shell↔solid connection is attempted by sharing nodes and becomes a silent hinge.** The Manual (§8.3): *"The connection between 3D elements and all other elements (1D or 2D) is always hinged."* Shared 3D↔2D nodes are knots, whose rotations the solid cannot resist | The merge route is node-disjoint by construction (§8.3); coupling is declared by `*TIE` only; G5 asserts the `*TIE` cards exist, G10/G11 make an uncouplable edge connection a loud error, and G13's numerical check would expose a hinge as excess tip deflection |
| ~~Whether `*TIE` carries a shell slave node's rotational DOF~~ — **resolved, and it does** | Probes D1/D2/D3 ran before any production code existed; results in §9.8. A tied shell root is within **1.7 %** of a clamped root, and Stage 7 shows a tied **flange** within **0.09 %** of an all-solid rebuild. G13 remains the regression guard. |
| **A tie with the wrong shell side fails silently.** The writer must pick the side of the expanded shell that meets the master (`write_constraint_tie._shell_slave_face`). Stage 7 measured the failure: the joint was one thickness out, ccx printed `WARNING in gentiedmpc: no tied MPC` to stdout only, the job finished, and the deflection was exactly the uncoupled one — the deck text was indistinguishable from a working one | Fixed and regression-tested (`test_tie_slave_side_follows_the_shell_offset`). G13's numerical check is the guard that makes a silent uncoupling impossible to ship, which is why a text-only deck test is not enough |
| **A hinged mixed model fails silently, not loudly.** D2's hinge variant returned a ~2.5e12 deflection magnification with **no `*ERROR` and no warning** from ccx | The "loud error, not a silent hinge" requirement stands, and G13's numerical check is **load-bearing** — a hinge will not announce itself and cannot be caught by a deck-text test |
| **Composite `*SHELL SECTION` accepts only S8R and S6.** Measured in D3: an `S4` shell with a composite section is rejected outright — `Element 2 is not a S8R nor a S6 shell element.` | Stage 2/5 must emit S8R or S6 for the shell side of a mixed model when the section is composite; asserted in §8.5 via `getElementType`, never assumed. This is not optional for the plan's motivating Composites case. |
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

**Node-disjointness is required for a second, independent reason: shared
nodes cannot couple a shell to a solid at all.** The CalculiX manual, S8/S8R
section (identical wording in the 2.7 and 2.18 manuals):

> *"Beam and shell elements are always connected in a stiff way if they share
> common nodes. This, however, does not apply to plane stress, plane strain and
> axisymmetric elements."* — the stiff-by-shared-nodes rule is for 1D↔2D only.
>
> *"For an internal hinge between 1D or 2D elements the nodes must be doubled
> and connected with MPC's. The connection between 3D elements and all other
> elements (1D or 2D) is always hinged."*

The mechanism: shells are *"automatically expanded into 20-node brick
elements"*, and a shared shell node becomes a **knot** — a rigid body with
seven DOF (3 translations, 3 rotations, uniform expansion) at the reference
node. A solid element can see only that node's three translations, so the
shell's rotations have no counterpart on the solid side and nothing resists
them. A hinge, by design.

Consequence for the whole plan: **a shell↔solid connection must be declared
by MPCs (`*TIE` or `*EQUATION`), never by node sharing.** Node sharing does
not merely couple weakly — it silently produces the hinge §7 warns about.
That is why the merge route in §2 is node-disjoint by construction: it is a
requirement of the coupling, not a limitation of it.

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

| File | Purpose |
|---|---|
| `femtest/app/test_mixed_shell_solid.py` | headless half of G0-G13 |
| `femtest/gui/test_mixed_shell_solid.py` | GUI half of G0-G12 |
| `femexamples/constraint_mixed_face_coupling.py` | F-family geometry + analysis; `setup(doc, variant="f1"|"f2"|"f3"|"f4")`, default `f1` |
| `femexamples/constraint_mixed_edge_coupling.py` | E-family geometry + analysis; `setup(doc, variant="e1"|"e2"|"e3")`, default `e2` |
| `femexamples/meshes/mesh_mixed_face_coupling_f*.py` | frozen merged meshes for G4-G7, G12, G13 |
| `femexamples/meshes/mesh_mixed_edge_coupling_e*.py` | frozen meshes for G10, G11 |
| `femtest/data/calculix/constraint_mixed_*.inp` | the mixed goldens |
| `femtest/data/mesh/mixed_*.npy`-or-text snapshots | structural baselines for the R1 half of G4-G7 |

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
  §8.9.

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

### 8.10 Invoke Composites modules fully qualified, and check the count

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

### 8.9 Visualisation cases (V1-V3)

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

