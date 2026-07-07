# Mould Feature Design

**Date:** 2026-07-07  
**Status:** Draft  
**Related:** `features/Mould.py`, `features/MouldAnalysis.py`, `tools/mould.py`, `tools/part_plane.py`, `features/PartPlane.py`, `docs/mould-terminology-map.md`

## Overview

Mould creates a split mould volume around a source shape. The current target is a two-part mould, though the design may later generalize to more than two parts. The mould is intended as a machining stock / toolpath volume, not a finished composite part.

The terminology in this design follows the research grounding for composite moulds and multipart mould CAD:
- **PartLine** / parting line: the boundary curve where the mould halves meet the source surface
- **parting surface**: the surface extended from that curve
- **draw direction**: the candidate direction used to choose the split
- **mould halves**: the resulting split tooling

See `docs/mould-terminology-map.md` for the full term map.

## Problem Statement

The current implementation is a work in progress and needs clearer intent and structure:
- It should produce a two-part split mould for now
- The split direction should usually be auto-selected, but user hinting should be possible
- The source shape should be removed or hidden after mould creation
- The result should be suitable for machining stock / toolpath generation

## Solution: Mould

### Core Concept

Given a source shape, Mould should:
1. Determine a parting direction, usually automatically
2. Derive the PartLine / parting line on the source surface
3. Extend that curve into a parting surface
4. Split the mould into two halves around the source shape
5. Add clearance / overhang around the part
6. Hide or remove the source shape from the final view
7. Produce a mould volume suitable for downstream machining or toolpath use

### User Interface

**Command:** `Composites_Mould`

**Inputs:**
- `Source` (`Part::Feature`) - the shape to build the mould around
- `XOverhang` (`App::PropertyLength`) - X clearance / stock extension
- `YOverhang` (`App::PropertyLength`) - Y clearance / stock extension
- `ZOverhang` (`App::PropertyLength`) - Z clearance / stock extension

**Behavior:**
- User selects the source shape
- The feature computes a split mould around it
- The source shape is hidden or removed from the working view

### Design Intent

#### Two-Part Split Mould
The primary target is a two-part mould. This is the default and expected mode.

#### Future Extensibility
The design should not prevent more than two parts later, but that is not the current goal.

#### Parting Direction
The parting direction should usually be auto-selected by the feature. A user hint may help guide the result when needed.

#### Clearance / Overhang
The overhang values define how much stock is added around the source shape to create the mould volume.

### Output Structure

**Output Type:**
- `Part::FeaturePython` or equivalent mould feature output

**Expected Result:**
- A mould volume split into two parts
- Suitable for machining stock / toolpath generation

### Source Shape Handling

The source shape should not remain as the primary visible object after mould generation. It should be hidden or removed so the mould is the focus of the document.

### Geometry Notes

The current helper code suggests the mould is derived from cross-sections and lofting around a bounding box with buffer values. That general approach fits the intent, but the implementation should be organized around the split-mould concept rather than a generic loft.

The research notes reinforce that this is a normal composite-tooling pattern: parting lines, split directions, stock allowance, alignment features, and machinability are all part of the same problem, not separate concerns.

### Implementation Phases

#### Phase 1: Clarify split-mould behavior
- [ ] Confirm the two-part split workflow
- [ ] Make the parting direction selection explicit
- [ ] Ensure source visibility is handled correctly

#### Phase 2: Geometry hardening
- [ ] Build stable overhang/clearance handling
- [ ] Make mould split generation robust
- [ ] Validate the output as machining stock

#### Phase 3: UI polish
- [ ] Support user hints for parting direction
- [ ] Improve failure messages and diagnostics
- [ ] Keep the command workflow simple

#### Phase 4: Testing
- [ ] Test auto-selected split direction
- [ ] Test user-hinted split direction
- [ ] Test source hiding/removal behavior
- [ ] Test output suitability as mould stock

### Success Criteria

1. **Correctness**: Mould produces a valid split mould
2. **Practicality**: Output is usable as machining stock / toolpath volume
3. **Usability**: Direction is usually auto-selected, with hinting when needed
4. **Clean document state**: Source shape is hidden or removed
5. **Extensibility**: The design can later support more than two parts

### Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Auto-selected parting direction is wrong | High | Allow user hinting and add diagnostics |
| Split mould geometry becomes invalid | High | Add validation and conservative geometry rules |
| Source visibility handling confuses users | Medium | Hide/remove source consistently and document the behavior |
| Future multi-part support complicates the design | Medium | Keep the first implementation focused on two parts |

### Related Files

- `features/Mould.py` - feature definition
- `tools/mould.py` - mould geometry helper
- `tools/part_plane.py` - parting / plane helper functions
- `features/PartPlane.py` - related feature

### Open Questions

1. What should the user hint for parting direction look like in the UI?
2. Should source removal be destructive or just hidden by default?
3. Should the mould halves be created as separate named objects or as a grouped feature?
4. Should the PartLine be exposed as its own object or remain an internal step inside parting-surface generation?

---

**Next Steps:**
1. Clarify parting direction selection behavior
2. Hard-code the two-part workflow first
3. Add tests for source hiding and split validity