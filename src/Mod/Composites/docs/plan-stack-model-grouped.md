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
