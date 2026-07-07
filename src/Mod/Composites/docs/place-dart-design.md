# PlaceDart Feature Design

**Date:** 2026-07-07  
**Status:** Draft  
**Related:** `features/CompositeShell.py`, future `PlaceDart` command

## Overview

PlaceDart is a GUI command that allows users to specify additional cut lines (darts) on a draped composite shell. Unlike the current broken implementation that manipulates mesh topology, PlaceDart integrates with the draping algorithm's native cut line system to create precise, parametric darts.

## Problem Statement

The legacy `Dart` command was broken and has been removed. Its issues were:
- depended on removed `shape2Mesh()` function
- attempted mesh topology manipulation instead of parametric cuts
- did not integrate with the draping algorithm's cut system
- produced unpredictable results

## Solution: PlaceDart

### Core Concept

Instead of manipulating the mesh after draping, PlaceDart:
1. Takes user-provided wires as input
2. Adds them to the CompositeShell's dart support list
3. Projects wires onto the support surface
4. Passes them to the draping algorithm as cut lines
5. Visualizes dart boundaries on the draped mesh

### User Interface

**Command:** `Composites_PlaceDart`

**Inputs:**
- `Wires` (PropertyLinkListGlobal) - one or more sketch wires
- `CompositeShell` (PropertyLinkGlobal) - the shell to place darts on

**Properties:**
- No additional parameters (all configuration via visualization settings)

**Behavior:**
- When activated, user selects wires and a CompositeShell
- Wires are added to the CompositeShell's dart list
- Upon recomputation, the drape is performed with cut lines
- Dart boundaries are visualized on the draped mesh

### Data Model

**CompositeShell Extensions:**

```python
class CompositeShellFP:
    # New property for dart wires
    obj.addProperty(
        "App::PropertyLinkListGlobal",
        "DartWires",
        "Dart",
        "Wires defining cut lines for darts"
    )
    
    # Existing dart support property (may need rename)
    # obj.DartSupports or similar
    
    def execute(self, fp):
        # Project wires onto support faces
        # Pass to draping algorithm
        # Store resulting dart boundaries for visualization
```

### Visualization

**Overlay System:**
- Dart boundaries rendered as separate overlay on draped mesh
- Configurable via ViewObject properties:
  - `DartLineColor` (Color) - RGB tuple
  - `DartLineWidth` (Float) - in pixels
  - `DartLineTransparency` (Float) - 0.0 to 1.0

**Rendering:**
- Integrated with existing Coin3D shader system
- Separate node group for dart boundaries
- Can be toggled on/off independently

### Draping Algorithm Integration

**API Contract:**
```python
# In drape_backend_nextdrape.py or similar
def solve(shape, laminates, dart_wires=[], ...):
    """
    Args:
        shape: Support shape
        laminates: Laminate definitions
        dart_wires: List of wires to use as cut lines
        ...
    """
```

**Workflow:**
1. CompositeShell.execute() collects DartWires
2. Projects each wire onto support faces (using nearest point projection)
3. Converts projected curves to draping algorithm format
4. Passes to solver via existing API
5. Receives back draped mesh with cut boundaries

### Implementation Phases

#### Phase 1: Foundation
- [ ] Add DartWires property to CompositeShell
- [ ] Implement wire projection onto support faces
- [ ] Integrate with draping algorithm's cut line API

#### Phase 2: Visualization
- [ ] Extend ViewProviderCompositeShell with dart overlay
- [ ] Add customizable line properties (color, width, transparency)
- [ ] Wire up to existing shader/rendering system

#### Phase 3: GUI Command
- [ ] Create PlaceDart command (replacing Dart)
- [ ] Implement selection handling for wires + shell
- [ ] Add proper resource definitions

#### Phase 4: Testing
- [ ] Unit tests for wire projection
- [ ] Integration tests for draping with cut lines
- [ ] GUI tests for command activation
- [ ] Visualization tests for dart overlay

### Success Criteria

1. **Functionality**: User can place darts on a CompositeShell
2. **Integration**: Darts affect draping algorithm output
3. **Visualization**: Dart boundaries are clearly visible
4. **Performance**: No significant slowdown in draping
5. **Usability**: Command is intuitive and well-documented

### Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Draping API doesn't support cut lines | High | Verify API availability before implementation |
| Wire projection is computationally expensive | Medium | Cache projections, optimize algorithms |
| Visualization causes performance issues | Medium | Use efficient Coin3D nodes, LOD techniques |
| Integration with existing CompositeShell is complex | High | Modular design, extensive testing |

### Related Files

- legacy `Dart` implementation has been removed; replace with a new `PlaceDart` command
- `features/CompositeShell.py` - Extension needed
- `tools/drape_backend_nextdrape.py` - API integration
- `shaders/MeshGridShader.py` - Visualization system
- `features/VPCompositeShell.py` - View provider extension

### Open Questions

1. Should dart wires be editable after placement?
2. How to handle wires that don't intersect the support surface?
3. Should there be a maximum number of darts?
4. How to visualize darts that are inside the mesh vs. on edges?

---

**Next Steps:**
1. Confirm draping API accepts cut lines
2. Prototype wire projection algorithm
3. Design visualization overlay system