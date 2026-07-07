# Composites Workbench — Test & Example Coverage Gaps

**Date:** 2026-07-07
**Source root:** `src/Mod/Composites/`
**Test dir:** `compositestests/` · **Example dir:** `compositeexamples/examples/`

## Methodology

Every source module under `src/Mod/Composites/` was cross-referenced against the
test files in `compositestests/` and the example files in `compositeexamples/examples/`.
For each source file, the primary class/function name and distinctive identifiers were
grepped across both directories. "Loaded only" (a test `_load_module`s a file but never
calls its functions) is marked **partial**. Import-by-another-source does **not** count
as coverage — only direct exercise by a test or example file counts.

All "zero-coverage" verdicts in Section B were verified by grep spot-checks.

## A. Coverage matrix

### `mechanics/`

| Source module | Test coverage | Example coverage |
|---|---|---|
| `stack_model_type.py` | YES (`test_mechanics.py` TestStackModelType; also `test_freecad_fp.py`, `test.py`) | NO |
| `shell_model.py` | YES (`test_mechanics.py` — rotation_matrix_zaxis, compliance_matrix, material_shell_properties, material_stiffness_matrix, material_rotate, stiffness_matrix_to_engineering_properties; `test.py`) | NO |
| `stack_expansion.py` | YES (`test_mechanics.py` — calc_stack_model) | NO |
| `fibre_composite_model.py` | YES (`test_mechanics.py`, `test.py` — calc_fibre_composite_model) | NO |
| `stack_model.py` | YES (`test_mechanics.py` — merge_clt, merge_single, calc_z) | NO |
| `material_properties.py` | YES (`test_mechanics.py`, `example_materials.py`) | NO |

### `objects/`

| Source module | Test coverage | Example coverage |
|---|---|---|
| `fibre_composite_lamina.py` | YES (`test_mechanics.py` TestFibreCompositeLaminaObject) | YES (`ud_plate_basic.py`, `quasi_iso_laminate_plate.py`, `_shell_example_common.py`) |
| `simple_fabric.py` | YES (`test_mechanics.py` TestSimpleFabricPlyOrientations) | YES (`ud_plate_basic.py`, `quasi_iso_laminate_plate.py`, `_shell_example_common.py`) |
| `symmetry_type.py` | YES (`test_mechanics.py`, `test_freecad_fp.py`) | YES (`ud_plate_basic.py`, `quasi_iso_laminate_plate.py`, `_shell_example_common.py`) |
| `fabric.py` | YES (`test_mechanics.py` — `Fabric` imported; exercised via `SimpleFabric` subclass) | NO (`Fabric` base not directly referenced; only `SimpleFabric` subclass used) |
| `composite_lamina.py` | partial (`test_freecad_fp.py` — module loaded via `_load_module`; `CompositeLamina` base only exercised transitively via `CompositeLaminate`/`FibreCompositeLamina` subclasses) | NO |
| `ply.py` | YES (`test_mechanics.py` — `Ply` imported; exercised via subclasses) | NO (subclasses only; `Ply` not referenced in examples) |
| `weave_type.py` | YES (`test_mechanics.py` TestWeaveType, `test_freecad_fp.py`) | YES (`ud_plate_basic.py`, `quasi_iso_laminate_plate.py`, `_shell_example_common.py`) |
| `homogeneous_lamina.py` | YES (`test_mechanics.py` TestHomogeneousLamina/TestCalcZ/TestMergeClt) | NO (used in `compositestests/examples.py` only, not in `compositeexamples/examples/`) |
| `lamina.py` | YES (`test_mechanics.py` TestLamina — direct) | NO (subclasses only) |
| `laminate.py` | YES (`test_mechanics.py` — `Laminate` imported; exercised via `CompositeLaminate` subclass) | NO (`CompositeLaminate` subclass used, `Laminate` not directly referenced) |
| `composite_laminate.py` | YES (`test_mechanics.py`, `test_freecad_fp.py`) | YES (`ud_plate_basic.py`, `quasi_iso_laminate_plate.py`, `_shell_example_common.py`) |

### `features/`

| Source module | Test coverage | Example coverage |
|---|---|---|
| `Laminate.py` | partial (`test_freecad_fp.py` — `LaminateFP` tested; `LaminateCommand`/`ViewProviderLaminate`/`is_laminate` not exercised) | NO |
| `TransferRosette.py` | YES (`test_transfer_rosette.py` — `TransferRosetteFP`, `is_transfer_rosette`) | NO |
| `coin_geometry.py` | NO (functions only run transitively inside `CompositeShell.execute`; no direct import) | NO |
| `AlignFibreRosette.py` | YES (`test_rosette_integration.py` — `AlignFibreRosetteFP`, `is_align_fibre_rosette`, `ViewProviderAlignFibreRosette`) | NO |
| `FibreCompositeLamina.py` | YES (`test_freecad_fp.py`, `test_integration_freecad.py` — `FibreCompositeLaminaFP`) | YES (`_shell_example_common.py`) |
| `Container.py` | partial (`test_freecad_fp.py` — module loaded; `CompositesContainerFP`/`getCompositesContainer` not called) | NO |
| `VPCompositePart.py` | NO (not loaded by any test) | NO |
| `RunCompositeExample.py` | NO | NO |
| `Mould.py` | NO | NO |
| `MouldAnalysis.py` | NO | NO |
| `CompositeShell.py` | YES (`test_freecad_fp.py` TestCompositeShellFPRosetteProperty; integration in `test_rosette_integration.py`/`test_transfer_rosette.py`/`test_integration_freecad.py`) | YES (`_shell_example_common.py`) |
| `ToolbarGroup.py` | NO | NO |
| `VPCompositeBase.py` | partial (`test_freecad_fp.py` — module loaded; `CompositeBaseFP` exercised transitively via FP subclasses; `VPCompositeBase` view-provider untested) | NO |
| `VPCompositeShell.py` | YES (`test_vp_composite_shell_shader_reload.py` — `ViewProviderCompositeShell.get_offset_angle`/`onChanged`) | YES (`_shell_example_common.py`) |
| `HomogeneousLamina.py` | YES (`test_freecad_fp.py` TestHomogeneousLaminaFP) | NO (examples create `FibreCompositeLamina` features, not `HomogeneousLamina` features) |
| `TexturePlan.py` | NO | NO |
| `Stiffener.py` | NO | NO |
| `RosetteSymbol.py` | NO (only imported by `VPCompositeShell`/`Rosette` view providers; no direct test) | NO |
| `CompositeLaminate.py` | YES (`test_freecad_fp.py` TestCompositeLaminateFP) | YES (`_shell_example_common.py`) |
| `Rosette.py` | YES (`test_freecad_fp.py` TestRosetteFP/TestIsRosette; `test_integration_freecad.py`; `test_rosette_integration.py`; `test_transfer_rosette.py`) | YES (`_shell_example_common.py`) |
| `PartPlane.py` | NO | NO |
| `Seam.py` | NO | NO |
| `Lamina.py` | partial (`test_freecad_fp.py` — `BaseLaminaFP` exercised via `HomogeneousLaminaFP`/`FibreCompositeLaminaFP` subclasses; `is_lamina` not exercised) | NO |
| `Dart.py` | NO | NO |
| `Command.py` | partial (`test_freecad_fp.py` — module loaded; `BaseCommand.check_sel`/`Activated` not exercised) | NO |
| `Composite.py` | partial (`test_freecad_fp.py` — module loaded; `add_composite_props` runs transitively during FP construction, not directly called) | NO |

### `compositetools/`

| Source module | Test coverage | Example coverage |
|---|---|---|
| `drape_task.py` | NO (only called transitively from `CompositeShell.execute` draping) | NO |

### `shaders/`

| Source module | Test coverage | Example coverage |
|---|---|---|
| `MeshGridShader.py` | YES (`test_meshgrid_shader_binding.py`; loaded by `test_freecad_fp.py`) | YES (`test_shader_gui.py`) |

### `util/`

| Source module | Test coverage | Example coverage |
|---|---|---|
| `fem_util.py` | partial (`test_freecad_fp.py` — module loaded; `get_layers_ccx`/`write_lamina_materials_ccx`/`write_shell_section_ccx`/`format_material_name` not called) | NO |
| `bom_util.py` | partial (`test_freecad_fp.py` — module loaded; `get_layers_bom`/`get_layers_fibre` not called) | NO |
| `geometry_util.py` | YES (`test_mechanics.py` — expand_symmetry, normalise_orientation, format_orientation, format_layer; `test_freecad_fp.py`) | NO (`tex_coord_nearest_quad_fallback` not exercised anywhere) |
| `mesh_util.py` | partial (`test_freecad_fp.py` — module loaded; `triangle_distance`/`calc_lambda`/`proj`/`perp` not called) | NO |
| `selection_utils.py` | NO (only a commented-out import in `features/Command.py`) | NO |
| `plot_util.py` | YES (`test.py` — `illustrateLayup`) | NO |

### `fem/`

| Source module | Test coverage | Example coverage |
|---|---|---|
| `drape_laminate_provider.py` | partial (`test_drape_laminate_provider.py` — `register_drape_laminate_providers` tested; `get_compshell_obj`/`get_drape_lcs`/`get_laminate`/`get_laminate_materials` not exercised) | NO (only a comment reference in `_shell_example_common.py`) |
| `failure_models_composites.py` | YES (`test_failure_provider.py` — `calc_failure_tsai_wu`, `calc_failure_hashin`, `register_composite_failure_models`) | YES (`_shell_example_common.py` `evaluate_failure_criteria`) |

### `taskpanels/` (all GUI/Qt — every one is stubbed or mocked in tests)

| Source module | Test coverage | Example coverage |
|---|---|---|
| `task_homogeneous_lamina.py` | NO (mocked in `test_freecad_fp.py`) | NO (stubbed in `_shell_example_common.py`) |
| `task_composite_laminate.py` | NO (mocked/stubbed) | NO (stubbed) |
| `base_taskpanel.py` | NO (not referenced) | NO |
| `task_fibre_composite_lamina.py` | NO (mocked in `test_freecad_fp.py`/`test_integration_freecad.py`) | NO (stubbed) |
| `base_material.py` | NO (not referenced) | NO |

### `ext/`

| Source module | Test coverage | Example coverage |
|---|---|---|
| `drape_nextdrape.py` | NO (not referenced; may load transitively via draper backend) | NO |
| `_native/__init__.py` | NO (not directly imported; the loaded `Composites_drape.so` is exercised transitively by integration draping) | NO |

### `App/`

| Source module | Test coverage | Example coverage |
|---|---|---|
| `CompositesDrape.cpp` | partial (integration tests `test_rosette_integration.py`/`test_transfer_rosette.py`/`test_integration_freecad.py` exercise the compiled solver via the Python draper API; no direct C++ unit test) | partial (`_shell_example_common.py` drapes via the solver; indirect) |

### top-level

| Source module | Test coverage | Example coverage |
|---|---|---|
| `InitGui.py` | NO | NO |
| `__init__.py` | YES (`test_integration_freecad.py` — `is_comp_type`; `test_freecad_fp.py`/`test_mechanics.py` `import Composites`) | NO (icon constants / `is_comp_type` not directly used by examples) |
| `version.py` | NO (only imported by `__init__.py`, a source module) | NO |

## B. Priority gaps — zero coverage in both tests and examples

GUI-wired = user-facing command wired in `InitGui.py`/`features/ToolbarGroup.py`.

### Recommended remediation order

This ordering reflects user impact, coupling, and how central the feature is to the current mould workflow.

| Priority | Scope | Why this comes first |
|---|---|---|
| P0 | `MouldAnalysis`, `Mould`, `PartPlane` | Core split-mould workflow; these are now tightly coupled through parting-line / parting-surface / mould-half semantics. |
| P1 | `TexturePlan`, `Stiffener` | User-facing geometry conveniences with direct manufacturing value and moderate coupling. |
| P2 | `Seam`, `Dart` / `PlaceDart`, `RunCompositeExample` | Important, but either more specialized, currently being redefined, or simpler wrapper behavior. |
| P3 | `taskpanels/` package | Large GUI surface area; important, but can be tested after the core command flow is stabilized. |

### Notes on the priority bands

- **P0** should get the first integration tests because it defines the mould-analysis pipeline and the terminology the rest of the tooling depends on.
- **P1** should follow once the core split workflow is stable.
- **P2** contains useful but less central user actions, including the future `PlaceDart` workflow.
- **P3** is broad GUI coverage that benefits from the core object model being stable first.

### GUI feature commands (highest priority — user-facing, untested, no example)

| Feature | Purpose | Toolbar group |
|---|---|---|
| `features/RunCompositeExample.py` | Runs the default `ud_plate_basic` example | `Composites_RunCompositeExample` |
| `features/MouldAnalysis.py` | Proposes a split direction, parting surface, and mould halves | `Composites_MouldTools` |
| `features/Mould.py` | Builds a split mould stock / toolpath volume from a source | `Composites_MouldTools` |
| `features/PartPlane.py` | Parting surface from a source shape | `Composites_MouldTools` |
| `features/TexturePlan.py` | Unwraps composite shells to a flat texture plan | `Composites_TexturePlan` |
| `features/Stiffener.py` | Projects a profile stiffener onto a plan | `Composites_StructureTools` |
| `features/Seam.py` | Overlap seam between composite shells | `Composites_StructureTools` |
| `features/Dart.py` | Planned PlaceDart cut-line placement for draping | `Composites_Dart` |

### GUI task panels (entire `taskpanels/` package untested)

- `taskpanels/task_homogeneous_lamina.py` — material-selection task panel for `HomogeneousLamina`. **GUI-wired** (edit panel).
- `taskpanels/task_composite_laminate.py` — resin-material task panel for `CompositeLaminate`. **GUI-wired**.
- `taskpanels/base_taskpanel.py` — base task panel (UI load, accept/reject). **GUI-wired** (base).
- `taskpanels/task_fibre_composite_lamina.py` — resin+fibre material task panel. **GUI-wired**.
- `taskpanels/base_material.py` — base material task panel (`Materials.MaterialManager` tree). **GUI-wired** (base).

### Internal support modules (not GUI-wired, run only transitively)

- `features/coin_geometry.py` — Coin3D scene-graph helpers for draped-mesh injection (consumed by `CompositeShell`).
- `features/VPCompositePart.py` — base FP/VP for part-like composite features (base class for MouldAnalysis/Mould/PartPlane/Seam/Stiffener/TexturePlan/Dart).
- `features/RosetteSymbol.py` — Coin3D X/Y rosette axis symbol (consumed by `VPCompositeShell`/`Rosette` view providers).
- `compositetools/drape_task.py` — runs the C++ draping solve synchronously (invoked by `CompositeShell.execute`).
- `util/selection_utils.py` — find first face in a `Gui.SelectionObject` (only a commented-out import in `Command.py`).

### Other

- `features/ToolbarGroup.py` — registers the workbench command groups/toolbars. **GUI-wired** (it is the wiring).
- `ext/drape_nextdrape.py` — lazy proxy loader for the `drape_nextdrape` C++ extension. Not GUI-wired (native loader).
- `ext/_native/__init__.py` — loads `Composites_drape.so` and exposes `solve()`. Not GUI-wired (loader; required by workbench init, exercised indirectly by integration draping).
- `InitGui.py` — `CompositesWorkbench` registration (loads solver, imports features, builds toolbar). **GUI-wired** (the workbench itself).
- `version.py` — `__version__` string. Not GUI-wired (metadata, low priority).

## C. Partially-covered modules

Covered by tests OR examples but not both, or only partially exercised.

### Test-only (no example coverage)

- `mechanics/stack_model_type.py`, `shell_model.py`, `stack_expansion.py`, `fibre_composite_model.py`, `stack_model.py`, `material_properties.py` — fully unit-tested; not directly imported by any example (used via `objects`).
- `objects/fabric.py`, `ply.py`, `lamina.py`, `laminate.py`, `homogeneous_lamina.py`, `composite_lamina.py` — tested (directly or via subclass); examples use only the leaf subclasses (`SimpleFabric`/`FibreCompositeLamina`/`CompositeLaminate`), never these bases directly.
- `features/HomogeneousLamina.py` — FP tested in `test_freecad_fp.py`; no example creates a `HomogeneousLamina` feature.
- `features/TransferRosette.py`, `features/AlignFibreRosette.py` — integration-tested; not used by any example.
- `util/geometry_util.py` — symmetry/orientation helpers tested; `tex_coord_nearest_quad_fallback` untested.
- `util/plot_util.py` — `illustrateLayup` called only by `compositestests/test.py` (a scratch script that runs at import, not a unittest).
- `__init__.py` — `is_comp_type` tested; icon-path constants and FEM-registration side effects not asserted.

### Partial (loaded but not directly exercised)

- `features/Laminate.py` — `LaminateFP` tested; `LaminateCommand`, `ViewProviderLaminate`, `is_laminate` untouched.
- `features/Container.py` — module loaded; `CompositesContainerFP`/`getCompositesContainer` never called.
- `features/VPCompositeBase.py` — `CompositeBaseFP` runs transitively via FP subclasses; `VPCompositeBase` view-provider untested.
- `features/Lamina.py` — `BaseLaminaFP` exercised via subclasses; `is_lamina` untested.
- `features/Command.py` — module loaded; `BaseCommand.check_sel`/`Activated`/`GetResources` untested.
- `features/Composite.py` — `add_composite_props` runs transitively during FP construction; no direct call/assertion.
- `util/fem_util.py` — module loaded; `get_layers_ccx`/`write_lamina_materials_ccx`/`write_shell_section_ccx`/`format_material_name` never called.
- `util/bom_util.py` — module loaded; `get_layers_bom`/`get_layers_fibre` never called.
- `util/mesh_util.py` — module loaded; `triangle_distance`/`calc_lambda`/`proj`/`perp` never called.
- `fem/drape_laminate_provider.py` — only `register_drape_laminate_providers` tested; the provider functions (`get_compshell_obj`/`get_drape_lcs`/`get_laminate`/`get_laminate_materials`) untested.
- `App/CompositesDrape.cpp` — exercised only indirectly through the Python draper API in integration tests/examples; no direct C++ test.

No source module is example-covered but test-uncovered.

## D. Fully covered (both test and example)

`mechanics/material_properties.py`, `objects/fibre_composite_lamina.py`, `objects/simple_fabric.py`, `objects/symmetry_type.py`, `objects/weave_type.py`, `objects/composite_laminate.py`, `features/CompositeShell.py`, `features/VPCompositeShell.py`, `features/CompositeLaminate.py`, `features/Rosette.py`, `features/FibreCompositeLamina.py`, `shaders/MeshGridShader.py`, `fem/failure_models_composites.py`.

## Bottom line

The biggest practical exposure is the **eight GUI feature commands** (`MouldAnalysis`, `Mould`, `PartPlane`, `TexturePlan`, `Stiffener`, `Seam`, `Dart`, `RunCompositeExample`) plus the **entire `taskpanels/` package** — all are user-facing, none has any test or example. The drape solver path (`CompositesDrape.cpp`, `drape_task.py`, `ext/`) is only indirectly exercised through integration draping and would benefit from a direct test.
