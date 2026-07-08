# Seam Feature Design

**Date:** 2026-07-07  
**Status:** Active implementation slice  
**Related:** `features/Seam.py`, `tools/seam.py`, `features/CompositeShell.py`

## Overview

Seam now supports two related workflows:

1. **part/shape seam** — selecting two part-like shapes produces a seam as a `Part::FeaturePython`
2. **CompositeShell seam** — selecting two `CompositeShell`s produces a seam shell with a virtual laminate and a selectable lap order (`A+B` or `B+A`)

The geometry side still relies on the overlap-strip seam helpers in `tools/seam.py`, while the command side routes to the correct output type based on the selected inputs.

## Current Behavior

### Part/shape seam

- uses selected edges or master/attachment shapes
- builds seam geometry through `make_edge_seam()` / `make_join_seam()`
- produces a `Part::FeaturePython` seam object
- hides the source object in the edge-selection path

### CompositeShell seam

- accepts two `CompositeShell` inputs
- exposes a `LapSide` choice of `A+B` or `B+A`
- builds a virtual laminate by aggregating the source shell laminates in the selected order
- creates a seam shell object that keeps the seam support and laminate in sync

## Data Model

### Part/shape seam

**Object type:** `Part::FeaturePython`

**Properties:**
- `Edges` — optional selected sub-edges
- `Master` — selected master shape
- `Attachment` — selected attachment shape
- `Overlap` — seam overlap length
- `LapSide` — kept for API symmetry, but not meaningful for the part/shape path

### CompositeShell seam

**Object type:** `Part::FeaturePython` with `CompositeShellFP` behavior

**Properties:**
- `Master` — primary `CompositeShell`
- `Attachment` — secondary `CompositeShell`
- `Overlap` — seam overlap length
- `LapSide` — ordering selector (`A+B` / `B+A`)
- `Support` — generated seam support shape
- `Laminate` — generated virtual laminate

## Implementation Notes

### Geometry helpers

`tools/seam.py` currently provides:

- `make_edge_seam(shape, edges, overlap)`
- `get_partner_edges(face1, face2)`
- `make_join_seam(face1, face2, overlap)`

The direct geometry helpers are intentionally kept independent of the GUI command layer.

### Shell seam helper

`SeamShellFP` is the current seam-shell implementation slice. It:

- validates that both inputs are `CompositeShell`s
- builds the seam support shape from the source shell geometry
- builds a virtual laminate from the two source laminates in lap-side order
- keeps the seam object’s `Shape`, `Support`, and `Laminate` aligned

### Current limitation

`make_join_seam()` still needs a more complete fallback for faces that do not share a clean partner edge. That remains the main geometry-hardening gap for this feature.

## Testing Focus

The seam work is best tested by scenario rather than by a single happy-path example.

### Already covered

- single-edge baseline
- multiple-edge input
- reversed edge orientation
- disconnected edges
- curved surface input
- annulus / torus input
- tapered cone input
- thin geometry
- adjacent-face join
- partial overlap
- face-order sensitivity
- no-partner failure
- missing-edge failure
- CompositeShell seam output ordering

### Still worth keeping

- non-common-edge fallback behavior
- nearly coincident edges
- corner crossings
- boundary-adjacent seams
- self-intersection risk
- very thin / sliver geometry

## Open Questions

1. How aggressive should the non-common-edge fallback be when no partner edge exists?
2. Should part/shape seam and CompositeShell seam share more of their output-object setup?
3. Should the seam shell eventually expose more of the virtual laminate aggregation to the UI?

## Related Files

- `features/Seam.py`
- `tools/seam.py`
- `features/CompositeShell.py`
- `docs/integration-roadmap.md`

## Notes

This document now reflects the current implementation slice rather than the original rewrite plan.
