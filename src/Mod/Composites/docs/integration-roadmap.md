# Composites Integration Roadmap

**Date:** 2026-07-07  
**Scope:** `src/Mod/Composites/`  
**Focus:** real FreeCADCmd integration coverage and remaining functionality gaps

## Status Summary

The core mould and rosette workflows now have real FreeCAD integration coverage. The legacy `RunCompositeExample` command has been removed, and the legacy `Dart` command has been removed as a broken path awaiting a future replacement.

Current integration coverage includes:

- `MouldAnalysis`
- `Mould`
- `PartPlane`
- `TexturePlan`
- `Stiffener` smoke coverage
- `Rosette`
- `AlignFibreRosette`
- `TransferRosette`
- `CompositeShell` behavior through real example and rosette flows

## Current Priority Order

### 1. Seam maturity

`Seam` is the next highest-value user-facing workflow.

Goals:

- exercise `make_edge_seam()` and `make_join_seam()` with real geometry
- cover the `SeamFP` command path with actual selected edges
- verify recompute behavior in a real FreeCAD document
- tighten edge-case behavior for:
  - missing edges
  - multiple edges
  - joined faces without partner edges

Why this comes first:

- `Seam` is still a real feature with non-GUI helpers available
- it is more important than taskpanels or the future `PlaceDart` workflow
- it is a direct modeling operation, not just UI plumbing

### 2. PlaceDart replacement

The old `Dart` feature was removed because the implementation was broken and based on an obsolete mesh workflow.

Goals for the replacement:

- create a new `PlaceDart` command
- attach dart cut-line data to `CompositeShell`
- project wires onto the support surface
- pass dart cut lines into the draping workflow
- visualize dart boundaries on the draped result

Why this comes next:

- it restores missing layup functionality
- it belongs to the draping workflow itself
- it is more important than taskpanels

### 3. Taskpanel coverage

The `taskpanels/` package remains largely untested and unexercised in end-to-end use.

Goals:

- identify the smallest reliable GUI/taskpanel slices
- exercise accept/reject behavior where possible
- cover material-editing and feature-editing panels through real FreeCAD sessions

Why this comes last:

- it is broader and more UI-centric
- it is less urgent than core modeling features
- it benefits from the feature and command layers being stable first

## Remaining Functional and Integration Gaps

These items came from the coverage-gap audit and are still worth tracking, but they are lower priority than the three main items above.

### Direct integration gaps

- `compositetools/drape_task.py` is only exercised transitively through `CompositeShell.execute()`.
- `App/CompositesDrape.cpp` is only exercised indirectly through Python integration flows; it has no direct C++ unit test.
- `fem/drape_laminate_provider.py` still lacks direct coverage of the provider functions (`get_compshell_obj`, `get_drape_lcs`, `get_laminate`, `get_laminate_materials`).

### Partial feature/runtime gaps

- `features/Command.py` is loaded but its command-selection logic is not directly exercised.
- `features/Composite.py` is only hit transitively through FeaturePython construction.
- `features/Container.py` is only loaded; `getCompositesContainer()` is not called in tests.
- `features/Laminate.py` has partial FP coverage, but `LaminateCommand`, `ViewProviderLaminate`, and `is_laminate()` remain untouched.
- `features/Lamina.py` has subclass coverage, but `is_lamina()` is untested.
- `features/VPCompositeBase.py` has its FP path exercised transitively, but the base view provider is untested.
- `features/VPCompositePart.py`, `features/RosetteSymbol.py`, `features/coin_geometry.py`, and `util/selection_utils.py` remain indirect-only support code.

### Utility and FEM helper gaps

- `util/fem_util.py` still lacks direct tests for its layer/material helpers.
- `util/bom_util.py` still lacks direct tests for BOM/fibre helpers.
- `util/mesh_util.py` still lacks direct tests for `triangle_distance`, `calc_lambda`, `proj`, and `perp`.
- `util/geometry_util.py` still has an unexercised `tex_coord_nearest_quad_fallback()` path.
- `ext/drape_nextdrape.py` and `ext/_native/__init__.py` remain loader paths rather than direct test targets.

## Completed Work

### Integration coverage added

- real FreeCADCmd tests for the mould workflow
- real FreeCADCmd tests for layout and rosette-related features
- example runner support for multiple integration test modules

### Commands removed

- `RunCompositeExample`
- legacy `Dart`

## Notes

- The current `Seam` and `PlaceDart` priorities are about functionality, not just test coverage.
- `Seam` has a real implementation and should be exercised with actual geometry.
- `PlaceDart` is intentionally a replacement design, not a continuation of the removed legacy `Dart` path.
- GUI-only polish and toolbar/button conveniences are not being prioritized here.

## Seam Test Matrix

The seam work should be tested by scenario rather than by one-off examples.

### Core contract

For each seam case, verify:

- result is valid
- result has the expected broad shape type
- master area before/after is sensible
- attached area before/after is sensible
- overlap area is non-zero and bounded
- overlap lies entirely on the attached surface
- there is no overhang into free space
- geometry failures raise exceptions rather than returning garbage

### Primary scenarios

| Scenario | Geometry idea | Main assertions |
|---|---|---|
| Single edge baseline | One edge on a simple planar master and matching attached edge | seam succeeds, shape type is stable, overlap is contained |
| Multiple edges | Several connected edges in one call | edge ordering does not matter, result remains valid |
| Long master / short attached | Master edge is longer than the attached edge | overlap is limited by the shorter attached side |
| Short master / long attached | Attached edge is longer than the master edge | overlap still respects the master limitation |
| Tapered master | Master expands or contracts along the seam path | overlap area changes smoothly, no detached fragments |
| Angled master / attached | Faces are not coplanar | seam remains contained and does not leak into free space |
| Looped seam / annulus | Closed seam path on a ring-like shape | cyclic topology stays closed and continuous |
| No partner edges | Faces do not share matching edges | the join path raises an exception |
| Bad edge input | Empty list or invalid subshape reference | the seam path raises an exception |

### Secondary scenarios

| Scenario | Geometry idea | Main assertions |
|---|---|---|
| Partial overlap only | Edges overlap only on part of their length | no assumption of full-length coincidence |
| Reversed orientation | Same geometry with reversed edge direction | orientation normalization holds |
| Nearly coincident edges | Edges are very close but not identical | tolerance handling stays stable |
| Seam across a corner | Seam crosses a sharp kink or corner | continuity survives a normal discontinuity |
| Hole-boundary seam | Seam follows an inner hole boundary | closed-loop topology remains valid |
| Disconnected multi-edge input | Multiple edges are not mutually connected | input validation or predictable grouping |
| Mixed curvature | One side flat, the other curved | containment and area checks still hold |
| Boundary-adjacent seam | Seam sits close to the outer boundary | no overhang beyond the attached surface |
| Self-intersection risk | Geometry could cause the split volume to intersect itself | failure is explicit, not silent |
| Thin or sliver geometry | Very small features or near-zero widths | robustness against CAD precision limits |

## Suggested Next Slice

Start with `Seam`:

1. add the highest-value scenario tests from the matrix above
2. keep the direct tool tests and the `SeamFP` integration test aligned
3. verify the command and tool behavior stay consistent under real FreeCAD recompute cycles

After that, design and implement `PlaceDart`.
