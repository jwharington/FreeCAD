# Stiffener Feature Design

**Date:** 2026-07-07  
**Status:** Draft  
**Related:** `features/Stiffener.py`, `tools/stiffener.py`, `features/VPCompositePart.py`

## Overview

Stiffener creates a structural stiffener, such as a rib or stringer, on top of a composite shell or other support surface. The intended workflow is to sweep a 2D cross-section profile along a plan path projected onto the support geometry.

This feature is intended for composite shells, but the resulting geometry should remain a general Part feature so it can also be used for metal structures and other applications.

## Problem Statement

The current implementation is close to the intended behavior, but it needs cleanup and hardening:
- Geometry handling is complex and fragile
- Alignment logic needs clearer intent and stronger validation
- The feature lacks sufficient tests
- Output handling should remain generic as a Part feature

## Solution: Stiffener

### Core Concept

Stiffener should:
1. Take a 2D plan sketch as the sweep path
2. Take a profile sketch as the cross-section
3. Project the plan onto a support face or shape
4. Sweep the profile along the projected path
5. Produce a Part feature representing the stiffener geometry

### User Interface

**Command:** `Composites_Stiffener`

**Inputs:**
- `Plan` (`Sketcher::SketchObject`) - 2D sweep path
- `Support` (`Part::Feature`) - support geometry, may be a face
- `Profile` (`Sketcher::SketchObject`) - stiffener cross-section
- `Direction` (`App::PropertyVector`) - projection direction
- `MirrorX` (`App::PropertyBool`) - mirror profile in X
- `MirrorY` (`App::PropertyBool`) - mirror profile in Y

**Behavior:**
- User selects plan, support, and profile
- The plan is projected onto the support along `Direction`
- The profile is aligned and swept along the resulting path
- The resulting geometry is created as a Part feature

### Data Model

**FeaturePython Object:**
- `StiffenerFP` remains a `Part::FeaturePython`
- The output should stay generic and not be tied only to composites

**Properties:**
- `Support` - linked support geometry
- `Plan` - linked sketch path
- `Profile` - linked sketch profile
- `Direction` - projection direction
- `MirrorX`, `MirrorY` - profile orientation modifiers

### Geometry Intent

#### Plan
The plan is the 2D cross-section path that gets swept. It defines the route of the stiffener over the support.

#### Support
The support may be a face or other Part geometry. The plan is projected onto it to obtain the actual stiffener path.

#### Profile
The profile is the 2D cross-section of the stiffener. It is swept along the projected path to create the final solid or shell geometry.

#### Alignment
The current alignment logic uses local axes and Frenet-like behavior. That appears to be close to the intended behavior, but it should be made more robust and easier to reason about.

### Output Structure

**Output Type:**
- `Part::FeaturePython`

**Why:**
- The feature should remain usable outside composites workflows
- It may be applied to metal structures as well as composite shells

**Expected Result:**
- A stiffener body or compound geometry
- Possibly supporting auxiliary tool geometry internally, but the public result should be a Part feature

### Existing Behavior to Preserve

The following should remain part of the design:
- `MirrorX` control
- `MirrorY` control
- `Direction` as the projection direction

### Implementation Notes

The current implementation already has the right broad shape:
- project plan to support
- compute local alignment
- generate stiffener geometry
- split or fragment the support as needed

The main work is to improve robustness and maintainability rather than redesign the concept.

### Implementation Phases

#### Phase 1: Cleanup
- [ ] Simplify the geometry pipeline where possible
- [ ] Make alignment logic easier to follow
- [ ] Reduce fragile assumptions in vector/frame handling

#### Phase 2: Robustness
- [ ] Validate input sketches and support geometry
- [ ] Handle edge cases cleanly
- [ ] Improve error reporting for invalid geometry

#### Phase 3: Output Discipline
- [ ] Ensure the command consistently produces a Part feature
- [ ] Keep internal helper output separate from public result
- [ ] Verify compatibility with non-composite use cases

#### Phase 4: Testing
- [ ] Unit tests for alignment and projection helpers
- [ ] Geometry tests for sweep behavior
- [ ] Integration tests for command execution
- [ ] Regression tests for mirror and direction handling

### Success Criteria

1. **Correctness**: The stiffener is placed and swept as intended
2. **Robustness**: Works reliably on valid support geometries
3. **Generality**: Remains usable outside the composites domain
4. **Maintainability**: Geometry logic is understandable and testable
5. **Coverage**: Core behavior is backed by tests

### Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Projection or alignment fails on complex surfaces | High | Validate support geometry and improve fallback handling |
| Local axis logic becomes hard to reason about | Medium | Factor out axis generation and add tests |
| Output shape is unstable across recompute | Medium | Keep output deterministic and persist only stable properties |
| Feature becomes too composite-specific | Medium | Preserve Part feature output and avoid composites-only assumptions |

### Related Files

- `features/Stiffener.py` - feature definition
- `tools/stiffener.py` - geometry logic
- `features/VPCompositePart.py` - shared view-provider base

### Open Questions

1. Should stiffener output always be a solid, or may it also be a shell/compound?
2. Should the plan path support multiple edges or only a single continuous wire?
3. Should projection direction be editable after creation?

---

**Next Steps:**
1. Clean up the geometry pipeline
2. Add tests for projection and alignment
3. Verify behavior on both composite shells and generic Part support geometry