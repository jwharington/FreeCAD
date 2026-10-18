# Work order: a new stack model that reduces a stack to 4 layers (5 with a core)

**Repo:** `~/opt/FreeCAD` (branch `fem-mixmesh`), module `src/Mod/Composites`.
**Requested by:** the LS8e propeller work in `~/Desktop/Projects/RTOA/LS8e/Design/ls8e-design-tools/propeller`.
**Deliverable:** one new `StackModelType` (proposed name `SmearedGroups`), wired through the
existing machinery, with tests.

## Why this is needed (measured, not assumed)

The propeller's blade root carries a **49-ply laminate** (6.93 mm). Both existing extremes
fail it:

- **`Discrete`** - CalculiX cannot expand the stack. ccx stops with

  ```
  *ERROR in gen3dnor: increase nk_
     layers per element:  98
  ```

  It had already failed at a 34-ply stack, so the root the blade's load path needs **cannot be
  written as ply cards at all**.

- **`Smeared`** - one equivalent layer. It runs, but its **bending stiffness is not the
  laminate's**, so the nodal strain it reports is the equivalent layer's, not the plies'. On the
  same case: mount laminate **0.36** smeared against **1.39** discrete. Moving the section's
  reference plane to the outer face (`OFFSET=0.5`, already available) does **not** recover it -
  0.36 either way - because the error is the single layer's stiffness, not where it sits.

So neither end is usable: we need a middle. Four layers keeps the through-thickness stiffness
distribution (which is what the outer-fibre strain depends on) while staying far below ccx's
layer limit.

**Target:** reduce a stack to **4 merged layers**, or **5 when the stack contains a core** (the
core stays its own unmerged layer).

## Where the change goes (verified against the tree)

| file | what it does now |
| --- | --- |
| `mechanics/stack_model_type.py` | the enum: `Discrete`, `SmearedFabric`, `SmearedCore`, `Smeared`; `merged_name(item)` returns the label used in the material name (`Fabric` / `Sublaminate` / `Laminate`) |
| `mechanics/stack_expansion.py` | `calc_stack_model(prefix, model_type, layers)` dispatches: `Discrete` -> `flatten_nested(-1)`; `SmearedFabric` -> depth 1; `SmearedCore` -> depth 0, `exclude_core=True`; `Smeared` -> depth 0. `merge_layers(prefix, layers, exclude_core)` merges a list into one lamina via `merge_clt`, and with `exclude_core=True` merges each non-core run between cores |
| `mechanics/stack_model.py` | `merge_clt(prefix, layers, sandwich=False)` - the equivalent-lamina merge to reuse; **do not write a second one** |
| `util/fem_util.py` | `get_layers_ccx(laminate, model_type)` calls `laminate.get_layers(model_type=...)` |
| `features/Laminate.py` | `execute()` sets `FEMLayers = get_layers_ccx(laminate, StackModelType[obj.StackModelType])`. The property's enum list is built automatically: `obj.StackModelType = [item.name for item in StackModelType]` (line ~78), **so adding the enum member is all the UI/property work needed** |
| `fem/drape_laminate_provider.py` | writes `COMPOSITE` when `len(layers) != 1`, else the `MATERIAL=` form. **No change needed** - 4 layers writes a 4-line card |

## Required behaviour

1. Add `SmearedGroups = auto()` to `StackModelType` and a `merged_name` case returning a short
   unique label (proposed `"Groups"`), so the section's material name stays distinct.
2. Add the dispatch branch in `calc_stack_model` for `SmearedGroups`.
3. New merge function beside `merge_layers`, e.g.

   ```python
   def merge_layers_grouped(prefix, layers, groups=4):
       """Merge a flat stack into `groups` layers, a core staying its own layer."""
   ```

   Rules:
   - Flatten the stack first (the nested `list` structure is what `flatten_nested` exists for).
   - **Partition by position, not by angle.** Contiguous bands of roughly equal thickness,
     outermost first. Grouping all the 0 deg plies into one lump would move stiffness through
     the thickness and make `D` worse, which is the whole point of not using `Smeared`.
   - Merge each band with the existing `merge_clt` - one call per band.
   - A core layer is emitted as its own layer and does not count against `groups`, hence
     5 layers for a cored stack.
   - **Keep the partition symmetric** when the input stack is palindromic (the propeller's are):
     choose boundaries so group *i* mirrors group *n-1-i*, which keeps `B` ~ 0 as the discrete
     stack has it.

## Acceptance tests (all must pass before commit)

1. **Layer count.** On a 49-ply stack with no core: exactly 4 layers; with a core: 5. Assert the
   count in a compositetests test.
2. **It is much closer than `Smeared`, and it is the reason to exist.** Build the laminate from a
   representative stack (the repo's quasi-isotropic example, and a 49-ply one), compute `A` and
   `D` for `Discrete`, `Smeared` and `SmearedGroups`, and report
   `|A-A_d|/|A_d|` and `|D-D_d|/|D_d|`. **`SmearedGroups`' `D` error must be a small fraction of
   `Smeared`'s.** Record the numbers in the test (and in this file) - a claim without them is not
   a result. Do not invent a tolerance; measure what the algorithm gives and state it.
3. **ccx accepts it.** Write a deck with `SmearedGroups` on a 49-ply section, confirm the
   `*SHELL SECTION` carries 4 (or 5) layer lines and **no** `gen3dnor: increase nk_`. The
   propeller case is: `cad/PropellerFem.py --solve --blade-geometry smooth --zones --mesh-max 12.5
   --stack SmearedGroups` in the LS8e repo, whose mount zone is the 49-ply stack.
4. **Nothing existing moves.** `Discrete`, `Smeared`, `SmearedFabric`, `SmearedCore` must produce
   byte-identical layers to before. Run the module's tests and the examples that exercise them.
5. **Symmetry.** On a palindromic input stack, assert the merged stack is palindromic too.

## Guardrails

- **Do not change** `Discrete`/`Smeared`/`SmearedFabric`/`Smeared` behaviour, the `merged_name`
  values they return, or `merge_clt`'s arithmetic.
- **Do not write a second smearing.** `merge_clt` is the one equivalent-lamina merge; call it.
- **No config knobs beyond the group count.** `groups=4` as a default parameter is enough; do not
  add a document property or a settings dialog.
- Build and test through the repo's own flow (`build-install-freecad.sh`, then the FreeCAD test
  targets via `run-fem-tests.sh`). **Do not copy files into `build/` or `.pixi/` by hand.**
- Commit incrementally, with the measured `A`/`D` numbers in the commit message.
- If the 4-layer reduction cannot beat `Smeared` on `D` materially, **stop and report that** with
  the numbers rather than tuning until something passes.

## Context from the consuming side (read-only; do not edit that repo)

- `~/Desktop/Projects/RTOA/LS8e/Design/ls8e-design-tools/propeller/cad/propeller/schedule.py`
  - `STACK_MODEL = "Smeared"` is what the propeller sets by default, with the ccx reason
    recorded there. `SKIN_OUTER_OFFSET = {"upper": 0.5, "lower": -0.5}` places each section's
    reference surface on its outer face.
- `cad/PropellerFem.py` has `--stack <name>`, which is passed straight to
  `shell.Laminate.StackModelType`, so **no propeller-side change is needed** to try the new model.
- The propeller's exposure check reads the frd's `TOSTRAIN` block and is what will judge this
  work: `cad/check-strain-exposure.py DECK FRD --detail`.

## Results (measured 2026-10-07)

Implemented: `StackModelType.SmearedGroups` (`merged_name` → `Groups`),
`merge_layers_grouped(prefix, layers, groups=4)` in `stack_expansion.py`,
dispatched from `calc_stack_model`. Bands are contiguous and roughly equal
in thickness; a core is emitted unmerged and does not count against
`groups`; a palindromic stack gets mirrored band boundaries.

### Criterion 1 — layer count (PASS)

49-ply stack: 4 layers. 49-ply with a core mid ply: 5 layers, one of them
the core. Asserted in `test_mechanics.TestSmearedGroups`.

### Criterion 2 — stiffness vs Discrete (PASS on the thin stacks, NOT on the 49-ply)

Relative error against `Discrete`, glass plies of 0.141 mm, plane-stress
reduction of the stiffness the deck exports. `D` is the Frobenius norm of
the full 3x3 bending matrix, not one entry — `D11` is shown where it was
quoted, and it tells the same story, so the comparison is not an artefact
of picking a single entry. Reproduced by
`compositestests/inspect_stack_model_errors.py`.

| stack | model | layers | A err | B err | D err | D11 err |
| --- | --- | --- | --- | --- | --- | --- |
| 4 identical plies (control) | SmearedGroups | 4 | 1.4e-17 | 0.0 | 1.2e-16 | 1.2e-16 |
| 4 identical plies (control) | Smeared | 1 | 1.4e-17 | 0.0 | 3.5e-16 | 3.5e-16 |
| 8-ply QI `[0/45/-45/90]s` | SmearedGroups | 4 | 2.3e-04 | ~0 | **2.06e-01** | 1.52e-01 |
| 8-ply QI `[0/45/-45/90]s` | Smeared | 1 | 3.4e-04 | ~0 | 4.97e-01 | 3.97e-01 |
| 48-ply `[6x(0/45/-45/90)]s` | SmearedGroups | 4 | 3.4e-04 | ~0 | 9.64e-02 | 9.30e-02 |
| 48-ply `[6x(0/45/-45/90)]s` | Smeared | 1 | 3.4e-04 | ~0 | 9.64e-02 | 9.30e-02 |
| 49-ply `[6x(0/45/-45/90)]+0` | SmearedGroups | 4 | 3.4e-04 | 1.9e-02 | 8.95e-02 | 8.50e-02 |
| 49-ply `[6x(0/45/-45/90)]+0` | Smeared | 1 | 3.4e-04 | ~0 | **7.49e-02** | **6.63e-02** |
| 49-ply, mid ply a core | SmearedGroups | 5 | 2.2e-04 | — | — | 9.12e-02 |
| 49-ply, mid ply a core | Smeared | 1 | 3.4e-04 | — | — | 6.63e-02 |
| `[0x4/90x4]s` (gradient) | SmearedGroups | 4 | 3.9e-16 | ~0 | **3.9e-16** | 3.9e-16 |
| `[0x4/90x4]s` (gradient) | Smeared | 1 | 5.1e-04 | ~0 | 5.40e-01 | 3.91e-01 |

The control rows validate the estimator: with one ply per band both models
must reproduce `Discrete` exactly, and they do. (A first version of this
measurement omitted the `t` factor in Barbero's D and read the uniform
control as 75% wrong — impossible; the control is what caught it.)

`A` is preserved by both merges to the merge's own numerical error
(~3e-4).

**Where grouping wins.** When a band is thin or homogeneous relative to the
stack's stiffness variation it is a real improvement: 2.4x better than
`Smeared` on the 8-ply QI plate, and on `[0x4/90x4]s` — where 4 bands of 4
makes every band a single angle — it is **exact** (3.9e-16 against a
`Smeared` error of 5.4e-1).

**Where it does not.** On thick, near-uniform stacks it is a tie or worse.
The 48-ply case is an *exact* tie (9.64e-02 both, agreeing to 10 digits),
and on the 49-ply stack `Smeared` is ~20% closer to `Discrete`.

Two structural reasons, both verified:

1. A band is a **centroid quadrature** of the through-thickness stiffness
   integral, `D = Σ Q_k t_k (z_k² + t_k²/12)`. When every band has the same
   thickness and the same equivalent stiffness this sum equals `Q h³/12`
   for one layer **exactly** — hence the 48-ply tie. Grouping only helps
   where `Q` actually varies through the thickness at band scale.
2. A 12-ply band averages that variation away, so more groups does not
   monotonically help: what matters is plies *per band*, not groups per
   stack. The 49-ply stack gets 12-ply bands — too coarse to represent its
   (near-uniform) stiffness profile, while a single layer integrates a
   near-constant `Q` exactly.

So the honest reading is not "grouping is useless" but "grouping pays when
the group count is comparable to the stack's block structure" — 8-ply and
blocky stacks benefit, 48+ ply near-uniform stacks do not.

A second, unavoidable cost: with 4 bands over an odd ply count, mirror
symmetry is arithmetically impossible (2a + 2b = 49 has no integer
solution), so the mid ply rides with one inner band and the merged stack
carries `B/A11 = 2.26e-2` where `Discrete` has exactly zero.

Per the guardrail this is a **stop-and-report** result, not something to
tune: the 4-layer reduction does not beat `Smeared` on `D` for the stack it
was built for.

**Disposition (decided):** keep the model. It is wired, tested and solves
in ccx, and it is measurably the right choice for thin or blocky stacks
(2.4x better on the 8-ply QI plate, exact when bands are homogeneous). It
is not the answer for the 49-ply propeller mount laminate, and the
propeller should stay on whatever its measurements support there.

### Criterion 3 — ccx accepts it (PASS)

`test_quasi_iso_fem.TestQuasiIsoFemCrossValidation` and
`test_stack_model_ccx.TestStackModelCcxRoundTrip` now iterate every
`StackModelType`, so `SmearedGroups` is solved through the real writer →
deck → ccx path on the §7.6 plate: it solves, its deck is self-consistent,
and its response agrees with `Discrete` within the 5% §7.6 tolerance. A
49-ply section writes 4 `*SHELL SECTION` layer lines with 4 defined
materials and no `gen3dnor: increase nk_`.

### Criterion 4 — nothing existing moves (PASS)

`test_mechanics`: 218 tests, 0 failures. `Discrete`/`Smeared`/
`SmearedFabric`/`SmearedCore` behaviour and their `merged_name` values are
untouched.

### Criterion 5 — symmetry (partial)

Even-count palindromic stacks get exactly mirrored bands, with `B/A11` at
round-off. Odd counts cannot; measured residual `B/A11 = 2.26e-2` (one ply
thickness out of a 6.9 mm stack).
