# PlaceDart Feature Design

**Date:** 2026-07-07  
**Status:** Active implementation slice  
**Related:** `features/CompositeShell.py`, `features/PlaceDart.py`

## Overview

PlaceDart records wire-like cut paths on a composite shell by projecting them onto the shell support surface and storing the projected cut objects in `CompositeShell.DrapeCuts`. This replaces the removed legacy `Dart` workflow, which attempted mesh-topology manipulation.

## Current Behavior

The current command path:

1. accepts a shell plus one or more wire-like sources
2. projects each wire onto the shell support surface
3. stores the projected cut objects in `CompositeShell.DrapeCuts`
4. invalidates persisted drape state when the cut set changes
5. recomputes the shell so the draping pipeline consumes the new cuts

## Data Model

`CompositeShell` already owns the relevant cut-line state:

- `DrapeCuts` — list of projected cut objects used by draping
- persisted drape payload fields — invalidated when the cut list changes

`PlaceDart` does **not** introduce a second parallel dart property. The command works with the existing `DrapeCuts` state and keeps the projection objects hidden from normal view.

## Geometry Behavior

The command currently uses a nearest-point projection approach onto the shell support surface.

### Current slice

- wire-like selection is filtered from the current FreeCAD selection
- each wire is discretized into sample points
- each sample point is projected to the shell support shape
- a hidden `Part::Feature` object is created or updated for the projected cut wire
- the projected cut objects are merged into `DrapeCuts`

### Current focus

The main remaining geometry work is to keep that projection behavior robust for more wire shapes and support geometries, especially:

- closed wires
- multi-edge wire sources
- awkward support curvature
- wires that only partially intersect the support region

## Implementation Status

### Foundation

- [x] Reuse the shell’s existing `DrapeCuts` property
- [x] Implement wire projection onto support faces
- [x] Integrate with the draping workflow’s cut-line path

### GUI command

- [x] Create the PlaceDart command
- [x] Implement selection handling for shell + wires
- [x] Add command resource definitions

### Testing

- [x] Integration tests for `DrapeCuts` invalidation and solver input shaping
- [x] Integration coverage for projected cut objects being merged into the shell cut set
- [ ] Visualization tests for dart overlay
- [ ] Broader geometry coverage for unusual wire/support combinations

### Visualization

- [ ] Extend `ViewProviderCompositeShell` with a dedicated dart overlay if needed
- [ ] Add customizable line properties if we want the overlay exposed in the UI
- [ ] Wire the overlay into the existing Coin3D/shader path only if that becomes necessary

## Success Criteria

1. **Functionality**: users can place darts on a `CompositeShell`
2. **Integration**: dart cut lines affect draping results through `DrapeCuts`
3. **Robustness**: projection stays stable across common wire shapes
4. **Usability**: the command is understandable and repeatable

## Open Questions

1. Should dart wires remain editable after placement?
2. How should the command behave when a wire fails to project cleanly onto the support?
3. Do we need a visible dart overlay, or is the stored cut geometry enough for now?

## Related Files

- `features/PlaceDart.py`
- `features/CompositeShell.py`
- `compositetools/drape_task.py`
- `docs/integration-roadmap.md`

## Notes

This document now tracks the current implementation slice rather than the removed legacy `Dart` workflow.
