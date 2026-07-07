# TexturePlan Feature Design

**Date:** 2026-07-07  
**Status:** Draft  
**Related:** `features/TexturePlan.py`, `features/CompositeShell.py`, `tools/drape_backend_nextdrape.py`

## Overview

TexturePlan is a convenience command that exposes the existing CompositeShell boundary data as editable 2D sketch geometry. It does not introduce new draping logic; instead, it presents the boundary loops already available from the CompositeShell API in a form that is easier to inspect, edit, and export.

## Problem Statement

The current `TexturePlan` feature is an imperfect 3D wire generator:
- It projects UV boundaries back into 3D
- It mixes boundary extraction with surface projection
- It creates wires instead of editable sketches
- It contains fallback logic that flattens some points to the XY plane
- It does not clearly structure output per shell or per layer

## Solution: TexturePlan

### Core Concept

TexturePlan should:
1. Read boundary loops from one or more CompositeShells
2. Convert those loops into editable 2D sketch geometry
3. Optionally create one output sketch per shell or per layer
4. Serve as a convenience wrapper around existing CompositeShell data

### User Interface

**Command:** `Composites_TexturePlan`

**Inputs:**
- `CompositeShell` (PropertyLinkListGlobal) - one or more shells to unwrap

**Behavior:**
- When activated, the command gathers boundary loops from each selected CompositeShell
- Boundary data is converted into 2D sketch entities
- Output objects are editable sketches rather than raw wires
- Multiple shells are supported optionally

### Data Model

**Input Source:**
- `CompositeShell.Proxy.get_boundaries(offset_angle_deg)`
- Existing API already provides the boundary loops needed for texture plan generation

**Output Objects:**
- `Sketcher::SketchObject` instances containing boundary loops
- Optionally grouped by shell and/or by laminate layer

### Geometry Handling

#### Boundary Extraction
The feature should rely on the existing CompositeShell boundary API instead of recomputing geometry.

```python
boundaries = shell.Proxy.get_boundaries(offset_angle_deg=orientation)
```

#### Sketch Generation
Boundary loops should be converted into editable 2D sketch geometry:
- lines or polylines in sketch space
- no 3D back-projection required
- no XY-plane fallback behavior

#### Layer Awareness
The current code hints at stack assembly iteration. That should be retained only if it produces meaningful per-layer outputs.

Possible output layouts:
- one sketch per shell
- one sketch per layer
- one sketch per boundary group

### Output Structure

**Recommended structure:**
- `TexturePlanFP` remains a FeaturePython object
- It creates one or more `Sketcher::SketchObject` outputs
- Each sketch is editable and can be used downstream

**Suggested naming:**
- `TexturePlan_<ShellName>`
- `TexturePlan_<ShellName>_<LayerName>` when layer separation is available

### Implementation Phases

#### Phase 1: Simplify the current command
- [ ] Remove 3D projection logic
- [ ] Consume `get_boundaries()` output directly
- [ ] Generate 2D sketch entities instead of wires

#### Phase 2: Structure outputs
- [ ] Support multiple shells
- [ ] Decide on per-shell vs per-layer sketch grouping
- [ ] Generate stable, editable object names

#### Phase 3: GUI integration
- [ ] Keep the command as a convenience tool
- [ ] Ensure command selection supports multiple shells
- [ ] Add proper resource definitions

#### Phase 4: Testing
- [ ] Unit tests for boundary-to-sketch conversion
- [ ] Integration tests for multi-shell input
- [ ] Tests that verify editable sketch output

### Success Criteria

1. **Convenience**: The command exposes existing CompositeShell boundary data easily
2. **Editability**: Output is a sketch, not just a wire compound
3. **Stability**: No brittle UV-to-3D fallback behavior
4. **Flexibility**: Supports multiple shells optionally
5. **Clarity**: Output structure is easy to understand and use

### Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Boundary loops are not suitable for sketch geometry | Medium | Normalize and validate loops before sketch creation |
| Multiple shells create confusing outputs | Medium | Use consistent naming and grouping |
| Layer semantics are unclear | Medium | Keep layer handling optional until clarified |
| Editable sketch creation is more complex than wires | Medium | Start with simple line segments, then refine |

### Related Files

- `features/TexturePlan.py` - to be simplified/reworked
- `features/CompositeShell.py` - source of boundary data
- `tools/drape_backend_nextdrape.py` - boundary provider implementation

### Open Questions

1. Should each shell create one sketch or multiple sketches by layer?
2. Should the output sketch preserve the original boundary ordering exactly?
3. Should there be a separate option for exporting texture plans instead of creating sketches?

---

**Next Steps:**
1. Replace 3D projection logic with direct sketch generation
2. Decide on grouping strategy for multiple shells and layers
3. Add tests for editable sketch output