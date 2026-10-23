# Assembly load states as FEM load steps

The Assembly's `FemLink` (`src/Mod/Assembly/FemLink`) drives part-level FEM from
the assembly's own solved simulation: each simulation frame is a load state, and
a part (`LinkBody`) receives one `Fem::ConstraintReaction` per joint (the
joint's reaction force and moment, at the joint's reference), one
`Fem::ConstraintVirtualForces` (the body's motion), and a
`Fem::ConstraintJig321` (the supports). Two execution modes exist for the
sequence of states.

## One multi-step deck (the default, "batch")

`LinkBody.runAnalysisBatch` collects one snapshot per state - per-constraint
`Force`/`Torque`/`Origin` for the reactions and the full virtual-forces
property set - and calls
`run_fem_solver(step_count=N, vf_snapshots, reaction_snapshots,
batch_step_states)`. The CalculiX writer then writes ONE deck containing one
`*STEP` block per state:

- The step loop is `femsolver/calculix/writer.py::write_solver_input`; each
  step writes its own step-dependent constraints.
- Per-step values: `_apply_virtualforces_snapshot` /
  `_apply_reaction_snapshot` rewrite the constraint properties from that
  state's snapshot before that step's constraints are written.
- CLOAD reset: the first load block of each step is written with `OP=NEW`
  (`_write_virtualforces_step_constraints`,
  `_write_reaction_step_constraints`), so loads do not carry across `*STEP`
  blocks.

The outcome: N states, one mesh, one solver run. `runAnalysisBatch` maps each
state to one result increment in `result_map` (and `batch_result_map`): the
solver reports `result_count` increments and state `i` bins to
`min(result_count - 1, (i + 1) * result_count / state_count - 1)` - the last
increment of its uniform bin - so the per-state value reflects that step's
final load state. When the increment count does not equal the state count the
mapping warns and still bins.

## One deck per state (the legacy loop)

`UtilsAnalysis._run_state_sequence` falls back to the per-state loop: for each
state, `state_set` + `updateFEMLinks(LOAD)` + a full `runAnalysis` - one
complete deck write and one ccx invocation per state, N result objects each
with its own DAT. This remains the fallback when the batch entrypoint
(`runAnalysisBatch`) is unavailable on the proxy.

## Choosing the mode

`UtilsAnalysis._batch_mode_enabled()` gates the pipeline entrypoints
(`run_stored_analysis`, `exercise_load_case_pipeline`) when the caller passes
no explicit `batch_mode`:

- Default: **ON** (batch, one multi-step deck).
- Debug switch: `FREECAD_FEMLINK_BATCH_ANALYSIS=0` (also `false`/`no`/`off`/
  empty) turns it off and restores the legacy one-solve-per-state loop.

Study runners that pass `batch_mode` explicitly (e.g. the pylon study's
`mechanism_fem.py --no-batch`) bypass the env var.

## Reaction delivery: face vs nodal

Reaction constraints are written by
`femsolver/calculix/write_constraint_pressure*.py` - they are routed through
`cons_pressure`. `femmesh/meshsetsgetter.py::get_constraints_pressure_faces`
splits them by reference type:

- **Face references** (`RefShapeType == "Face"`): the reaction surface is
  resolved through the element face masks into `PressureFaces` /
  `PressureFaceInfo` / `PressureNodeInfo`, and the writer delivers the wrench
  through a `*DISTRIBUTING COUPLING` over those face nodes, or - inside a
  batched step - as a per-step nodal `*CLOAD` distribution with the moment
  transferred as a zero-net-force nodal couple.
- **Vertex or edge references** (assembly ball joints reference vertices):
  the constraint is a nodal load. The references are resolved to mesh nodes
  with `meshtools.get_femnodes_by_femobj_with_references` and stored in
  `femobj["ReactionNodes"]` (the face tables stay empty); the writer delivers
  the wrench at those nodes with equal weight, excludes Jig321-support nodes,
  and applies the same per-step force + moment CLOAD distribution. The moment
  is realised as a nodal couple and therefore needs at least two nodes; a
  reaction on a single vertex carries the force only and the writer reports
  the singular-moment warning (an ideal ball joint's moment is ~0 anyway).

Force constraints (`ConstraintForce`) already had this nodal path
(`RefShapeType` Vertex/Edge/Face -> `NodeLoadTable` in
`get_constraints_force_nodeloads`); the reaction's nodal treatment mirrors it
instead of forcing vertex references through the face mask search, whose
element-edge binary search does not exist for points.
