# Review: reusable FEM/Composites code in LS8e `propeller/cad`

**Date:** 2026-10-10 · **Status:** read-only review; no code written or changed.
**Source under review:** `~/Desktop/Projects/RTOA/LS8e/Design/ls8e-design-tools/propeller/cad`
· **Reviewed by request for:** code reusable across analyses, to be considered
for inclusion in Composites or the Fem module. It must be
**application-neutral** to be included.

---

## 1. Scope

The review was requested for three files — `run_fem_cases.py`, `FuselageV2.py`,
`FuselageFem.py` — "etc there". Scope is therefore those three files **and their
transitive import closure**, computed from the source rather than chosen by hand:

```
run_fem_cases ──▶ runpaths
FuselageV2    ──▶ matlib
FuselageFem   ──▶ FuselageV2, femstudy
femstudy      ──▶ bucklingdat, deckaudit, frequencydat, geomhash,
                  meshcache, model_mass, partexposure, runpaths
bucklingdat, frequencydat ──▶ ccxdat
model_mass, decknodes      ──▶ deckaudit
partexposure               ──▶ decknodes
```

**Local closure: 15 modules.**

```
run_fem_cases  FuselageV2  FuselageFem  femstudy  runpaths  matlib
bucklingdat  deckaudit  frequencydat  geomhash  meshcache  model_mass
partexposure  ccxdat  decknodes
```

Everything else in that directory is **not reachable** from the three named
files and is out of scope here: `CompositeFEM.py`, `BladeCompositeFEM.py`,
`failure.py`, `check_mesh_connectivity.py`, `femutil.py`, `util.py`,
`probe_args.py`, `frdnodes.py`, `layup.py`, `hub.py`, `motor.py`, `blade*.py`,
`Fuselage.py`, `Propeller.py`, the `plot_*`/`summarize_*`/`bench_*`/`check_*`
scripts, and the airframe geometry modules.

## 2. The neutrality test applied

A module is a donation candidate only if:

1. no LS8e nouns, part names or paths appear in its logic;
2. it takes the document / objects / mesh / deck as arguments rather than
   reading module state;
3. it reads no environment variable and writes to no fixed location;
4. it calls no private API of the Composites example package.

## 3. Rules for any donation (project policy)

- **New files only**, so upstream's own copies of anything similar stay where
  they are and the merge has no conflict to resolve.
- **No environment variables** in the code; run-time options are arguments.
- **DRY / clean code**: reuse an existing helper rather than adding a second
  copy; factor out the common piece first if the nearest existing code is too
  specific.
- **No inline imports** — every import at the top of the module.
- **Must work GUI and headless** (no unconditional `import FreeCADGui`, no
  `FreeCAD.ActiveDocument` assumption where a document can be passed in).

---

## 4. Tier A — neutral, self-contained, genuine donation candidates

### 4.1 CalculiX `.dat` readers — `ccxdat.py`, `bucklingdat.py`, `frequencydat.py`

- `ccxdat.tables_by_step(path, head, row_of)` (`ccxdat.py:20`) — one step-titled
  table scan shared by the two readers; pure `re`/stdlib. Refuses a gap in the
  mode numbering and aborts on a missing/surplus step rather than mis-assigning
  a value to the wrong case (`:41-58`).
- `bucklingdat.factors_by_step` / `factors_for_cases` (`bucklingdat.py:31,42`) —
  λ per step, with the one-step-per-case pairing asserted.
- `frequencydat.frequencies_by_step` / `modes_for_run` / `lowest`
  (`frequencydat.py:57,68,91`) — keeps **both** the real and imaginary parts and
  calls a mode `imaginary` when `hz == 0` and the imaginary part is not
  (`:47-51`).

**Upstream gap, verified in `src/Mod/Fem`:**

- `feminout/importCcxDatResults.readResult` reads only the
  `EIGENVALUE OUTPUT` table, by fixed columns `line[39:55]`; no step tracking,
  and the imaginary part is dropped.
- **Nothing upstream reads the buckling `.dat` at all.** The factor is taken
  from the frd `100CL` amplitude, `round(step_time, 2)`, and baked into the
  result object name: `importCcxFrdResults.py:744` and the
  `"{}BucklingFactor_{}_Results"` format at `:247-249`.

So `bucklingdat` is new capability, and `frequencydat` fixes a real reporting
defect. **Home:** `src/Mod/Fem/feminout/`.

### 4.2 Mesh signature + cache — `geomhash.py` + `meshcache.py`

- `geomhash`: `shape_digest`, `parts_digest`, `geometry_arguments_digest`,
  `versions_digest`, `builder_digest`, `mesh_parameters_*`, `explain`
  (`geomhash.py:107,124,139,168,194,205,221,246`). Keys a mesh on the geometry
  it was cut from *and* the mesh parameters, and can say which component moved.
- `meshcache`: `store` / `load` / `note` / `latest` / `components_of`
  (`meshcache.py:80,118,148,166,171`).

Upstream meshes unconditionally. There are hashing primitives (`TopoShape.hashCode`,
`femmesh/transfinitetools.py`) but **no mesh-validity signature**.

**Blockers to strip (both are single defaults, not logic):**
`geomhash.BUILDER` defaults to the LS8e builder file (`geomhash.py:57`), and
`meshcache.ROOT` is `~/.cache/ls8e/meshes` (`meshcache.py:31`). The
`configured=None` seam in `meshcache.root` and `builder_digest(path=BUILDER)`
are exactly where they come out. **Home:** `src/Mod/Fem/femmesh/` or `femtools/`.

### 4.3 Deck text audit — `deckaudit.py`

- Neutral: `parse_deck` (`:36`), `_material_problems` (`:245` — catches
  duplicate `*MATERIAL` names, which ccx stops on silently), `_coverage_problems`
  (`:262` — elements with no section or two sections).
- **Not neutral:** `section_of_elset` (`:29`) hard-codes the
  `Material<Section>_<id>` naming, and `audit()` (`:180`) requires
  `doc.Objects` named `*_Section` and calls `laminate.Proxy.deck_layers`.

Donation = the parser plus the card/coverage checks. The model-vs-deck
comparison is Composites-specific.

### 4.4 Mass from the deck — `model_mass.py`

- `densities_by_card` (`:34`), `plies_by_section` (`:60`), `_stack_of` (`:85`),
  and the arithmetic in `masses` (`:139`) / `layups` (`:176`): mass = member
  area × Σ(ρ·t), read from the deck's own `*SHELL SECTION` plies and `*DENSITY`
  cards; raises when one laminate is written two ways.

Fem has **no mass facility** (only `Fem::ConstraintSelfWeight`; nothing that
reports mass), so this is new capability.

**Blockers:** `member_areas` requires `doc.getObject("StructureFemCompound")`
(`:104`); `owners` requires `doc.getObject("Analysis")` (`:112`) and
`*_Section` names.

### 4.5 Per-part result accounting — `partexposure.py` + `decknodes.py`

- `partexposure.assign` (`:98`) / `maxima` (`:123`) — every result node assigned
  to the member(s) whose deck nodes it is nearest (bondline nodes claimed by
  both), unclaimed nodes counted rather than dropped.
- `decknodes.node_at` / `nearest_part` / `zone_of_node` (`:210,190,215`) and the
  one-pass `_blocks` parser (`:70`).

**Real blocker — a bug, not styling:** `decknodes.zones_by_node(path, known={})`
(`:158`) and `position_index(path, known={})` (`:185`) use **mutable default
arguments as caches**, so they persist across documents and a second model can
be answered from the first's geography. Also `partexposure.TIE_MM` and
`_UNREACHED_MM` are module constants that must become arguments. Needs
numpy/scipy.

### 4.6 Deck parse + load-resultant verification — functions in `femstudy.py`

- `_parse_inp_load_blocks` (`:77`), `_parse_inp_cload` (`:120`),
  `_verify_inp_loads` (`:133`), `_check_case_resultant` (`:189`),
  `_cload_positions` (`:219`), `_resultant` (`:243`), `_parse_inp` (`:464`),
  `_append_to_elsets` (`:537`).

These read the written deck per step and prove the applied resultant equals the
study's target, refusing `OP=NEW` inheritance mistakes. Upstream lacks this:
`ccxtools.has_missed_ties` / `has_no_material_assigned` are whole-deck flags,
not per-step load verification.

**Do not port** `_repair_inp_uncovered` (`:366`): it hard-codes
`doc.getObject("FEMMeshGmsh")` (`:383`), and its node recovery duplicates
`meshtools.get_nodes_by_face_with_fallback` (`src/Mod/Fem/femmesh/meshtools.py:2635`),
which the same function already calls at `:400`.

### 4.7 Constraint read-back idiom — `FuselageFem._add_fixed` / `_add_reaction` / `_verify_reaction`

`FuselageFem.py:355,369,401`. Create a constraint idempotently (re-point, never
duplicate) and read Force/Torque back from the object before the write, failing
loudly on a sign flip. This is the same silent-direction failure class as the
`DirectionVector` defect, and the idiom is absent upstream. The function bodies
are neutral; only the surrounding `LOAD_CASE` global state is LS8e.

---

## 5. Tier B — in scope, but not donation candidates

- **`run_fem_cases.py`** — thin subprocess/ThreadPool fan-out. `runner_args`
  (`:72`), forwarding `--out-dir` rather than naming files, is a good pattern,
  but the module hard-codes `FREECAD_RUN_SCRIPT`, the
  `~/.pi/.../run-script.sh` path and a home-path timeout (`:29-32`), which
  violates the project guardrails. Not portable as written.
- **`runpaths.py`** — neutral but trivial (`directory`/`stem`/`paths`/
  `artifact_for`). The idea — one place names a run's files — is worth copying;
  the code is small.
- **`matlib.py`** — a materials table plus `mat2calculix` (`:23`). Composites
  already owns material-card writing, so a second materials library would be
  duplication.
- **`FuselageV2.py`** — 2806 lines, overwhelmingly LS8e geometry (rings, bays,
  engine box, bands). The portable helpers are small: `_attach_vp` (`:497`,
  guards against double-installing a view provider), `_shape_object` (`:515`),
  `_largest_face` (`:521`), `_new_document` (`:533`),
  `_split_at_symmetry_plane` (`:955`), `_is_composite_geometry` (`:1745`),
  `_silence_occt_chatter` (`:1935`), `_timed` (`:1958`). Candidate utility
  additions at best, not a module.
- **`FuselageFem.py`** beyond §4.7 — LS8e load-case table (`CASES_ULTIMATE`,
  `lc01`–`lc06`), constraints named `SkinFwdFem*`/`Frame_5`, module-level
  globals mutated by `configure` (`:209-213`), and an import-time
  `LOAD_CASE = _build_load_case()`.

---

## 6. Recurring blockers to strip before any donation

- Hard-coded object names: `"FEMMeshGmsh"` (`femstudy.py:383`),
  `"Analysis"` / `"SolverCcxTools"` (`femstudy.py:1257-1258`),
  `"StructureFemCompound"` (`model_mass.py:104`; `FuselageFem._model_parts`).
- Deck naming conventions baked into logic: `Material<Section>_<id>`
  (`deckaudit.py:29`), `*_Section` (`model_mass.py:112`, `deckaudit.py:189`).
- `sys.path.insert(CAD_DIR)` plus sibling imports (`femstudy.py:51`,
  `run_fem_cases.py:24`, `FuselageFem.py`), which is why the whole set is one
  directory.
- Mutable default arguments as caches (`decknodes.py:158,185`).
- Environment variables and home paths (`run_fem_cases.py:29-32`,
  `meshcache.py:31`).
- Import of the **private** Composites example helper
  `Composites.compositeexamples.examples._shell_example_common`
  (`femstudy.py:46`, `FuselageFem.py`) — the same layering smell already
  flagged in this tree's own helpers.
- Import-time global state (`FuselageFem.LOAD_CASE`, `RUNNER`).

---

## 7. Suggested order, if any of it is wanted

1. `.dat` readers (`ccxdat` + `bucklingdat` + `frequencydat`) — stdlib-only,
   testable with no solver, fixes the unread buckling factor.
2. Mesh signature/cache (`geomhash` + `meshcache`) — biggest user value;
   generalise the two defaults.
3. Deck parser + load-resultant verifier (the `femstudy` functions) and the
   deck text audit (`deckaudit.parse_deck` + card/coverage checks).
4. Mass report (`model_mass`), then per-part accounting (`partexposure` +
   `decknodes`, fixing the caches), then the read-back idiom.

Each as a **new file** per the policy in §3, with the Fem CMake source-list
line, and the deck snapshot plus the four existing checks as the safety net.

---

## 8. Method and evidence

Files read in full: `run_fem_cases.py`, `runpaths.py`, `matlib.py`,
`ccxdat.py`, `bucklingdat.py`, `frequencydat.py`, `geomhash.py`, `meshcache.py`,
`deckaudit.py`, `model_mass.py`, `partexposure.py`, `decknodes.py`,
`FuselageFem.py`. `femstudy.py` lines 1–580 plus the named functions elsewhere;
`FuselageV2.py` helper bodies. The upstream-overlap claims in §4 were each
checked against `src/Mod/Fem` by reading/grepping, not assumed. No file in the
LS8e project or the FreeCAD tree was modified by this review.
