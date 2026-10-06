# Plan: Mixed shell + solid elements in one FEM analysis

**Date:** 2026-10-02 · **Status:** proposed, not started
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
volume's own skin.** `FemMesh::getFacesOnly` (`FemMesh.cpp:841-863`)
classifies a face as "shell" when its node set is **not** a subset of
any volume's node set. So a shell meshed conformally *on* a solid's
boundary, or a midsurface that gmsh turns into an internal volume
boundary after `Coherence Mesh;`, is silently **not** a shell and is
dropped by mesh-write mode 2. The mesh strategy (Stage 0) exists to
establish, by experiment, which geometry arrangement survives this test.

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
| Where the fix lives | **FreeCAD FEM core** (`src/Mod/Fem`), flag-gated and upstreamable. Composites consumes it and owns only the mesh-merge helper + example. | Stage 8 |
| Shell↔solid coupling | **`*TIE` with position tolerance**, non-conformal meshes. Chosen because Trap A makes conformal shells on a solid boundary undetectable. Conformal coupling stays out of scope. | Stage 0 |
| Safety gate while incomplete | **Hidden dev parameter** `AllowMixedShellSolid` in `User parameter:BaseApp/Preferences/Mod/Fem/General`, default `False`, read through one getter in `femsolver/settings.py` (next to `get_write_comments`). Deleted in the final stage. | Stage 8 |

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
default is overturned → **write `docs/adr/0004-shell-solid-element-dimensionality.md`**
recording the replacement before continuing.

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
Transform and RigidBody. In `write_step_output.py:33-44`, a mixed model
always writes `*NODE FILE, OUTPUT=3d`, never `2d`.

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

### Stage 8 — Composites-facing finish, and delete the flag

- Promote the mesh-merge helper into `Composites/util/fem_util.py`
  (shell meshes + solid meshes → one `FemMesh`) if Stage 7 validated the
  merge route.
- Add a Composites example under `compositeexamples/examples/` per the
  `_shell_example_common.py` pattern.
- Flip the default to on, keep the flag one release, then delete the
  getter and the flag branches.

---

## 4. Verification

```bash
# Composites side (unchanged harness)
~/.pi/agent/skills/freecad-dev/scripts/run-tests.sh test_laminate

# FEM app tests, including the golden-deck comparison
~/.pixi/envs/default/bin/FreeCADCmd -t Fem.test_ccxtools
```

Confirm the exact `-t` module spelling before first use rather than
guessing flags — `src/Mod/Fem/TestFemApp.py` shows the test modules the
FEM suite registers.

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
- Conformal shared-node shell↔solid coupling (see Trap A).
- Multiple mesh objects per analysis
  (`membertools.get_mesh_to_solve` still raises). Mixing happens inside
  one `FemMesh`, not across two.
- Any change to Z88, Elmer, CalculiX-objects, MyStran or OOFEM writers.
  The flag path is CalculiX-only.
- Layered/composite shell sections beyond what
  `fem_extension_registry` already provides.

---

## 6. Findings (filled in by Stage 0)

| Candidate | `VolumeCount` | `FaceCount` | `len(FacesOnly)` | `Efaces` written? | Verdict |
|---|---|---|---|---|---|
| a. compound, Gmsh | | | | | |
| b. separate meshes, merged | | | | | |
| c. coincident sheet, Gmsh | | | | | |

Coupling route confirmed by Stage 0: *not yet recorded.*

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| `*TIE` to a shell surface behaves differently in ccx than assumed | Stage 0 spike + Stage 7 numerical check, both before any behaviour is user-visible |
| Node-count inference lurking in code paths not yet read (Stage 4 is the wide one) | Stage 1 ships dimension-tagged tables and Stage 4 asserts on element **types**, not counts |
| A mixed model silently double-sections elements | Stage 5's explicit no-element-in-two-sections assertion |
| Flag leaks into normal paths and changes existing decks | Golden-file comparison over the whole `femtest/data/calculix/` set at every stage; the flag is read in exactly one function |
| Work stalls half-done, leaving an unusable combination | The flag makes "half-done" a supported state: off = today's behaviour, including today's error message |
