# Feature request: assembly load states as FEM load steps, end to end

**Date:** 2026-10-23 · **Raised by:** the LS8e pylon design work
**Where the machinery lives:** `src/Mod/Assembly/FemLink/LinkBody.py`
(`runAnalysisBatch`, `_collect_batch_step_states` — load states from the
assembly's own solved frames) → `src/Mod/Assembly/FemLink/UtilsAnalysis.py`
(`_run_state_sequence`, `_batch_mode_enabled`) →
`src/Mod/Fem/femsolver/run.py` (`run_fem_solver`, threading per-step
snapshots) → `src/Mod/Fem/femsolver/calculix/writer.py` (the per-step
`*STEP` loop, `_apply_virtualforces_snapshot`,
`_write_reaction_step_constraints`) →
`src/Mod/Fem/femmesh/meshsetsgetter.py` (per-constraint node/face sets).

## The finding (measured, LS8e pylon bellcrank)

The workflow we need: a mechanism solved through its stroke (114 frames),
each frame's joint reactions becoming one FEM load state, the whole set
integrated as load steps in ONE CalculiX deck — part-level stress across
the entire load history without N separate solves. The machinery for this
**already exists and is designed correctly**:

1. `runAnalysisBatch` collects per-state virtual-force and reaction
   snapshots and calls `run_fem_solver(step_count=len(states), ...)`.
2. The CalculiX writer loops `for step_index in range(step_count)`, writes
   one `*STEP` block per state, applies that state's virtual-forces
   snapshot, and writes that state's reaction loads — with an explicit
   `CLOAD` reset per step so loads do not carry across `*STEP` blocks.
3. The state set comes from the assembly's own frames, optionally
   SVD+convex-hull reduced (8 states from 114 on our bellcrank).

Measured on the bellcrank study (7-body assembly, 114-frame sweep,
~8 000-element second-order mesh): the writer reached the per-step deck
with the material group carried correctly. **Two defects then block the
path, and one configuration choice hides the whole facility:**

1. **`constraint_jig321.find_largest_triangle` is O(h³) in pure Python,
   and worse before it.** The jig's three support points are found by an
   exhaustive triple loop over convex-hull vertices with a numpy
   `cross/norm` per triple — and the hull of a volumetric node cloud can
   carry thousands of vertices. Before that loop even starts, the node
   array is built as `np.array([femmesh.Nodes[i] for i in ...])`, where
   `femmesh.Nodes` is a *property that rebuilds the whole node map on every
   access* — a 13 k-entry dict rebuilt ~13 k times. Measured cost of one
   deck write: **12+ minutes of CPU at 190 %** before a single byte of the
   `.inp` was written (found with a `faulthandler.register(SIGUSR1)` stack
   dump; py-spy could not attach, yama ptrace_scope). Fixed locally: hoist
   the node map once, cap the hull-vertex candidate set at 128 (a
   near-largest triangle is all a 3-2-1 jig placement needs) — the search
   drops from hours to well under a second.
2. **Vertex-referenced reaction constraints crash the face collector.**
   The LinkBody reaction constraints inherit their `References` from the
   assembly joints themselves, and *ball* joints reference **vertices**.
   `meshsetsgetter.get_constraints_pressure_faces` (where the writer routes
   every reaction constraint) resolves them with the face-based
   `meshtools.get_elements` path, whose binary search then descends into
   edges and dies:
   `KeyError: 10` at `meshtools.get_element_edges_from_binary_search`
   (`vol_dict[bit_pattern_dict[ele][0]]`). Any mechanism with ball joints —
   i.e. most of them — cannot write the batch deck.
3. **Batch mode is not the default.** `_batch_mode_enabled` gates the whole
   multistep path behind `FREECAD_FEMLINK_BATCH_ANALYSIS`; without it the
   pipeline takes the legacy one-solve-per-state loop (a full deck write
   and a ccx invocation per state), and the facility is undiscoverable.

## The requests

1. **Make the batch/multistep path the default for assembly-driven load
   states** (flip the gate, or drop it), so N solved frames become one
   deck with N `*STEP` blocks and one solver run. The legacy per-state
   loop remains as the fallback, not the default.
2. **Support vertex- and edge-referenced reaction constraints in the
   mesh-set collectors** — route them through the nodal path the force
   constraints already use, instead of assuming faces. This is what makes
   the facility usable on real mechanisms (ball joints everywhere).
3. **Accept the jig321 fix** (node-map hoist + candidate cap, included in
   the study's patch), or fix the search properly — the largest-area
   triangle among hull vertices has sub-cubic algorithms, but the cap alone
   bounds the worst case to under a second.
4. **Document the load-step facility** (`FREECAD_FEMLINK_BATCH_ANALYSIS`,
   what one deck per state vs one multistep deck means for results objects
   and for the per-step mapping in `runAnalysisBatch`'s
   `result_map`/binning).

## What we would use it for

Part-level FEM straight from the mechanism's own load history: bellcranks,
link rods, mount lugs and anchors analysed across the whole stroke with the
mesh built once and the loads stepped — plus the discrete static cases
(thrust, crash) dropped in as additional states on the same deck. The LS8e
pylon bellcrank (6061-T6, joints J002/J003/J005, 114-frame sweep + two
static cases at 4.6× the sweep peak) is the driving case; its study files
and the two defect traces are in the session record
(`cad/pylon/mechanism_fem.py`, `/tmp/bellcrank_fem_traceback.txt`).
