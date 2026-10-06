# Plan — Stack models must survive the CalculiX deck round trip

**Date:** 2026-10-07
**Status:** Fixes implemented — both defects closed, 217 tests green
**Origin:** LS8e fuselage laminate-representation study (design-tools TODO 5)
hit solver failures when the `--stack-model` flag was exercised for the first
time; user direction: *"the error is not in CalculiX, it is you"* — the defect
is in the Composites deck-writing path, and the missing coverage is tests that
run CalculiX.

---

## 1. Background

The workbench's existing stack-model tests (`compositestests/test_mechanics.py`,
`test.py`) pin the **laminate representation** layer: enum membership,
`merged_name`, `calc_stack_model` merge behaviour, `get_layers` round trips.
None of them invoke CalculiX, so nothing verified that a merged stack survives
the provider → `write_shell_section_ccx` → deck → ccx expansion path.

The first real model to walk that leg (LS8e fuselage, 4 stack models × 6 load
cases) produced one solver failure (SmearedFabric, `gen3dnor` abort) and
suspicious exposures for the merged models — with no test to separate deck bugs
from solver behaviour.

## 2. New coverage

`compositestests/test_stack_model_ccx.py` (added 2026-10-07) runs the §7.6 QI
plate — the smallest deck on which the ccx round trip is already known-good
(`test_quasi_iso_fem.py`) — once per `StackModelType` member, through the real
provider path, asserting:

1. **the solve succeeds** — a deck ccx cannot expand aborts before any step;
2. **deck self-consistency, before any solver opinion** — every material named
   on a COMPOSITE layer line has a matching `*MATERIAL,NAME=` card, and each
   section's layer thicknesses sum to the laminate thickness (a merge that
   loses material hides here);
3. **physical parity** — every model's mean free-edge ux agrees with the
   Discrete export within the §7.6 cross-validation tolerance (5 %,
   `QI_CROSS_VALIDATION_TOLERANCE`); the models are presentations of one
   physical stack.

Supporting change: `TestQuasiIsoFemCrossValidation._build_and_solve` gained a
`stack_model=None` parameter (sets `laminate.StackModelType` before recompute;
`None` keeps the Discrete default; no behaviour change for existing callers).

## 3. Findings — one solve per member on the §7.6 plate

| model | solves | response vs Discrete |
|---|---|---|
| Discrete | yes | reference |
| SmearedFabric | yes | **+12.0 % — fails the §7.6 5 % gate** |
| SmearedCore | **no — ccx aborts** | — |
| Smeared | (run stops at SmearedCore) | — |

On the LS8e fuselage (6 cases, 1.08 M-node deck) the same pair manifests
differently — SmearedFabric aborts (`gen3dnor`), SmearedCore solves — so the
defects are geometry-dependent in manifestation but the same two root causes.

## 4. Defect 1 — merged off-axis layers lose normal–shear coupling

**Symptom.** SmearedFabric solves but its response is 12 % off the same
physical laminate solved Discrete.

**Evidence (deck diff, §7.6 plate).** Discrete's `[-45]` ply is written
`*ELASTIC,TYPE=ANISOTROPIC` with the ±16 109 MPa normal–shear (A16/A26-type)
coupling terms. The merged `FABRIC00k` layer for the same pair of plies is
written with those terms **zero** — an orthotropic presentation of a material
that is not orthotropic in-plane.

**Root cause.** `mechanics/stack_model.py`:

- `merge_single` (used by Discrete after rotation) keeps the full rotated 6×6
  stiffness on the `HomogeneousLamina` (`stiffness=...`), and
  `write_lamina_material_ccx` (`util/fem_util.py`) then emits `TYPE=ANISO`,
  precisely because *"for an off-axis ply the engineering constants below lose
  the normal–shear coupling"* — the comment is already there;
- `merge_clt` (used by all merged models) builds an equivalent layer from ABD
  but attaches **no stiffness tensor**, so the writer falls back to `TYPE=
  ENGINEERING CONSTANTS`, which cannot represent coupling. The A16/A26 terms
  are dropped silently — no warning, no residual recorded.

The fuselage corroborates: Smeared/SmearedCore exposures ran 0.834/0.809
against Discrete 0.786/0.751 at lc01/lc02 — ~6 % scatter that is the same lost
coupling, not mesh noise.

**Proposed fix.** `merge_clt` attaches an equivalent single-layer 6×6
stiffness to its result: in-plane block from the smeared membrane stiffness
(A / total thickness), transverse block from the existing C/H accumulation.
The writer's existing ANISO path then picks it up unchanged (it already
reorders shear components for ccx via `_CCX_FROM_CODE_INDEX`). Known
limitation to document: an asymmetric merged stack has non-zero B, which no
single layer can represent — Smeared models are symmetric-stack presentations
by construction; assert/refuse rather than silently lose B.

**Regression gate.** `test_merged_models_match_discrete_response` (the 5 %
gate) goes green only when the coupling is preserved.

## 5. Defect 2 — SmearedCore deck drives ccx into heap corruption

**Symptom.** The SmearedCore plate deck aborts ccx in <1 s with
`realloc(): invalid next size` (SIGABRT), empty `.sta`, no steps started.

**Evidence.**

- gdb backtrace: SIGABRT in `u_realloc(ptr=orab, CalculiX.c:887)` — ccx
  reallocating its orientation array; the overrun happened earlier during
  input/expansion.
- ccx's own budget (`allocation.f`): for `*SHELL SECTION, COMPOSITE`,
  `nk_ += 20*nlayer*meminset(elset)` and `norien_ += nesr*mi(3)` (one local
  orientation per layer of each shell element, plus explicit cards). Same
  4-card plate deck: Discrete is budgeted **68** orientations, SmearedCore
  only **8** — the budget scales with the deck's layer counts, and the merged
  deck's 1-layer sections shrink it.
- The deck audits clean: materials all defined, thicknesses sum to the
  laminate (1.6 mm), names within ccx's 80-char limits, no zero-thickness
  layers.

**Working hypothesis.** The deck ccx is given is legal by every check we
control, but the *1-layer COMPOSITE with a full ANISO material* pattern (every
merged layer is a whole sublaminate) is the unusual input; whether the overrun
is in ccx's budget arithmetic interacting with this pattern or in something the
writer should never emit is **not settled**. The failing deck is preserved for
bisecting at `/tmp/fcfem_3iqnxe46/StackModelSmearedCore_FEMMesh.inp`.

**Plan.**
1. Bisect by sed-editing the preserved deck copy (rename/move keywords, drop
   `*ORIENTATION`, split the 1-layer section) — find the minimal trigger.
2. Depending on the trigger: change the writer (e.g. never emit a 1-layer
   COMPOSITE — use the plain isotropic path or ≥2 layers), or, if the deck is
   provably legal and minimal, record it as a ccx defect with the minimal
   deck attached (do not route around a solver failure silently).

## 6. Consequences for the fuselage study

The LS8e laminate-representation study numbers collected on 2026-10-07
(`fem-results/stack-study/*/`) are **suspect for the merged models**: the
~6 % exposure shifts read as this lost-coupling bug, not as a physical effect
of smearing. The study must be re-run after the fixes; until then only the
Discrete row is trustworthy. TODO 5 conclusions drawn from merged-model rows
are withdrawn.

## 7. Acceptance criteria

1. `test_stack_model_ccx` passes all four members: solve success, deck
   round-trip consistency, ≤5 % response parity.
2. No change to Discrete decks (byte-identical material/section blocks).
3. Fuselage sweep re-run; handover TODO 5 updated with trustworthy numbers.
4. If defect 2 turns out to be a genuine ccx bug: minimal deck committed to
   the docs/evidence trail, module-side presentation adjusted only if it is
   the correct fix — never a silent workaround.

## 8. Resolution log (2026-10-07)

### Defect 1 — fixed; root cause one layer deeper than first read

`merge_clt` now attaches the accumulated thickness-averaged 6×6 as the merged
layer's `stiffness` (`merge_single`'s channel), but that alone did **not**
change the deck: `get_layers_ccx` wraps every merged layer through
`merge_single` *again*, and `merge_single` recomputed `stiffness` from the
merged material's engineering-constant dict — which cannot carry coupling —
silently overwriting the true merged tensor. That double-wrap was the actual
coupling-destroying step; the old deck's ANISO-with-zeros was
`merge_single`'s recomputation, not merge_clt's output. `merge_single` now
preserves an existing stiffness and only computes one when there is none.
Verified: the SmearedFabric deck's 45°-pair layers carry ±16 109 MPa coupling
(matching Discrete) and the parity gate passes.

### Defect 2 — fixed; the deck's single-layer COMPOSITE was ours to fix

Deck bisection on the preserved copy isolated the trigger precisely:

| deck variant | result |
|---|---|
| 1-layer COMPOSITE + `ORIENTATION=` reference | **heap corruption** |
| 1-layer COMPOSITE, orientation reference removed | solves |
| same deck, layer split in two (0.8 + 0.8) + orientation | solves |
| shorter material name / known-good ANISO constants / no `OFFSET` | still crashes |
| plain `MATERIAL=`+`ORIENTATION=` form (no COMPOSITE) | still crashes |

So a **single-layer presentation carrying a section frame reference** is the
degenerate input, in both COMPOSITE and plain forms; the frame-preserving form
that works is ≥2 layers. `shell_section_provider` now emits a single merged
(orthotropic) layer as a COMPOSITE section of two stacked half-thickness
layers of the same material — identical ABD by construction, drape frame kept.
The declared-isotropic single layer keeps its plain `MATERIAL=` path (D5, no
orientation), unchanged.

### Premise corrected — no B refusal

The plan proposed refusing asymmetric merged groups (§4). The workbench's own
unit tests pin the opposite: `test_smeared_core_with_core_separates_layers`
and friends exercise merged models on **asymmetric** sandwiches (unequal
skins/core), i.e. losing B is the merged models' accepted semantics, part of
the specification. An interim B refusal raised against 14 pinned tests and was
withdrawn — the tests are the spec. Defect 1's fix (coupling preserved in the
tensor) stands; B loss remains documented model behaviour.

### Verification

`run-tests.sh test_stack_model_ccx test_mechanics test_quasi_iso_fem
test_drape_laminate_provider`: **217 PASS, 0 FAIL, 0 ERROR** (read from the
timings file — FreeCAD's console spam corrupts live stdout counts). Includes
all four stack models solving, deck round-trip consistency, ≤5 % response
parity, and the 200 pre-existing mechanics tests unchanged.

Remaining from §7: re-run the LS8e fuselage stack study on the fixed module
(merged-model rows withdrawn, §6) — design-tools side.
