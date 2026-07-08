# Composites Integration Roadmap

**Date:** 2026-07-07  
**Scope:** `src/Mod/Composites/`  
**Focus:** real FreeCADCmd integration coverage and remaining functionality gaps

## Status Summary

The core mould, rosette, seam, and PlaceDart workflows now have real FreeCAD integration coverage. The legacy `RunCompositeExample` command has been removed, and the legacy `Dart` command has been removed as a broken path awaiting its replacement workflow.

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
- seam geometry and seam-shell behavior
- `PlaceDart` cut-wire plumbing through `CompositeShell.DrapeCuts`

## Current Priority Order

### 1. Seam hardening

`Seam` is the highest-value user-facing workflow that still has room to mature outside the taskpanel layer.

Goals:

- keep the part/shape seam path stable
- keep the CompositeShell seam path stable
- exercise `make_edge_seam()` and `make_join_seam()` with real geometry
- harden edge-case behavior for:
  - missing edges
  - multiple edges
  - joined faces without partner edges
  - partial overlap / near-match cases

Why this comes first:

- it is a core modeling workflow
- it already has real geometry tests, so the next gains are in robustness rather than UI plumbing
- it is more important than taskpanels

### 2. PlaceDart projection polish

The new PlaceDart workflow is implemented at the integration level, but the projection pipeline can still be hardened.

Goals:

- tighten wire projection onto the support surface
- verify closed wires and multi-edge wires behave consistently
- add/keep integration tests for projection onto real shell geometry
- ensure stored cut wires continue to invalidate drape correctly

Why this comes next:

- it restores missing layup functionality
- it belongs to the draping workflow itself
- it is more important than taskpanels

### 3. Seam-shell stability cleanup

The seam-shell path is working, but it should stay quiet and predictable as the seam implementation evolves.

Goals:

- keep helper objects stable and hidden
- make `LapSide` updates deterministic
- ensure seam support + virtual laminate stay in sync cleanly
- avoid accidental recompute loops

### 4. Drape cleanup, if needed

This is separate from seam and PlaceDart, but worth a cleanup pass if it keeps surfacing during seam-shell work.

Goals:

- fix the `CompositeShell` persistence `tolist` issue
- reduce unrelated recompute noise
- keep this isolated from seam behavior changes

### 5. Documentation refresh

Only after the behavior is settled.

Goals:

- keep `seam-design.md` aligned with the real command behavior
- keep `place-dart-design.md` aligned with the current cut-wire implementation
- fold final decisions back into this roadmap

### 6. Taskpanel coverage

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

These items are lower priority than the main work above, but still worth tracking.

### Direct integration gaps

- `compositetools/drape_task.py` is still only exercised transitively through `CompositeShell.execute()`.
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
- real FreeCADCmd tests for seam geometry and seam-shell output behavior
- real FreeCADCmd tests for PlaceDart cut-wire invalidation and solver-input shaping
- example runner support for multiple integration test modules

### Commands removed

- `RunCompositeExample`
- legacy `Dart`

## Notes

- The current seam and PlaceDart priorities are about functionality and robustness, not just taskpanels.
- Seam now has a real implementation and should continue to be exercised with actual geometry.
- PlaceDart is intentionally a replacement design, not a continuation of the removed legacy `Dart` path.
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

Current integration coverage already exercises the practical seam cases above: single-edge baseline, connected and disconnected multi-edge inputs, edge-order independence, partial-overlap face joins in both orders, angled cylinder joins, annulus/toroidal seams, tapered cone seams, and thin-geometry seams, plus explicit empty-input and no-partner failures.

## Suggested Next Slice

### Working checklist

#### Seam hardening

- [ ] add or refine the highest-value scenario tests from the matrix above
- [ ] keep the direct tool tests and the `SeamFP` integration test aligned
- [ ] confirm the command and tool behavior stay consistent under real FreeCAD recompute cycles
- [ ] close the remaining non-common-edge fallback gap in `tools/seam.py`

#### PlaceDart projection polish

- [ ] tighten wire projection behavior for closed and multi-edge wires
- [ ] keep the cut-wire invalidation tests aligned with the shell integration path
- [ ] add any missing projection edge-case coverage on real shell geometry

#### Seam-shell stability cleanup

- [ ] keep helper objects hidden and stable
- [ ] make `LapSide` updates deterministic
- [ ] avoid accidental recompute loops

#### Defer to taskpanels last

- [ ] only after the geometry and command layers are stable
- [ ] use the smallest GUI/taskpanel slices that still prove the workflow

After that, move to taskpanels.
