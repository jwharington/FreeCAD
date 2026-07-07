# Seam Feature Design

**Date:** 2026-07-07  
**Status:** Draft  
**Related:** `features/Seam.py`, `tools/seam.py`, `features/CompositeShell.py`

## Overview

Seam is a GUI command that creates an overlap joint between two CompositeShells (master and attachment), similar to a lap joint in composite manufacturing. It extends the attachment edge along the master surface to create a constant-width overlap strip.

## Problem Statement

The current `Seam` command is broken and misaligned with the intended use case:
- Implements subtractive geometry (cutting away material) instead of additive overlap
- Does not handle two-shell joining workflow
- Lacks proper edge detection and tolerance handling

## Solution: Seam

### Core Concept

Given two CompositeShells that share a common edge:
1. Detect the common edge between master and attachment
2. Project the attachment edge onto the master surface
3. Create an overlap strip of constant width along the master surface
4. Generate two new shells: overlap shell and modified attachment shell

### User Interface

**Command:** `Composites_Seam`

**Inputs:**
- `Master` (PropertyLinkGlobal) - primary shell
- `Attachment` (PropertyLinkGlobal) - secondary shell to be joined
- `OverlapWidth` (PropertyLength) - width of overlap strip

**Properties:**
- `Tolerance` (PropertyFloat) - edge matching tolerance

**Behavior:**
- When activated, user selects master and attachment shells
- Validates they share a common edge within tolerance
- Creates overlap geometry and two new CompositeShells

### Data Model

**New Objects Created:**
1. `OverlapShell` - the overlapping region
2. `ModifiedAttachment` - the attachment shell with reduced footprint

**SeamFP Class:**
```python
class SeamFP(CompositePartFP):
    def __init__(self, obj, master, attachment):
        obj.addProperty("App::PropertyLinkGlobal", "Master", ...)
        obj.addProperty("App::PropertyLinkGlobal", "Attachment", ...)
        obj.addProperty("App::PropertyLength", "OverlapWidth", ...)
        obj.addProperty("App::PropertyFloat", "Tolerance", ...)
        
    def execute(self, fp):
        # Validate edge sharing
        # Project attachment edge onto master
        # Create overlap strip
        # Generate new shells
```

### Geometry Operations

**Step 1: Edge Detection**
```python
def find_common_edge(master_shell, attachment_shell, tolerance):
    """Find edges that are within tolerance of each other."""
    master_edges = master_shell.Shape.Edges
    attachment_edges = attachment_shell.Shape.Edges
    
    for me in master_edges:
        for ae in attachment_edges:
            if me.distanceToShape(ae) < tolerance:
                return me, ae
    return None, None
```

**Step 2: Projection**
```python
def project_edge_to_surface(edge, surface, direction):
    """Project edge onto surface along normal direction."""
    # Use makeParallelProjection or similar
    projected = surface.makeParallelProjection(edge, direction)
    return projected
```

**Step 3: Overlap Creation**
```python
def create_overlap_strip(projected_edge, width, master_surface):
    """Create constant-width strip along projected edge."""
    # Offset the projected edge by width/2 on each side
    # Extrude along surface normal
    # Boolean union with master surface
```

### Output Structure

**Created Objects:**
1. **OverlapShell** - Contains the overlapping region
   - Inherits properties from both master and attachment
   - May have combined laminate definition
   
2. **ModifiedAttachment** - Attachment shell with cutback
   - Original attachment minus the overlap region
   - Maintains original properties

**Parent Relationship:**
```
SeamFP
├── OverlapShell (new)
└── ModifiedAttachment (new)
```

### Workflow

1. User selects master and attachment shells
2. Seam command validates edge sharing
3. Computes overlap geometry
4. Creates OverlapShell and ModifiedAttachment
5. Hides or removes original shells (optional)

### Error Handling

**Validation Errors:**
- No common edge found (exceeds tolerance)
- Multiple common edges detected (ambiguous)
- Invalid geometry (non-manifold, self-intersecting)

**Recovery Options:**
- Adjust tolerance and retry
- Manual edge selection
- Abort operation

### Visualization

**Default Display:**
- OverlapShell shown with distinct color/pattern
- ModifiedAttachment shown normally
- Original shells hidden (configurable)

**Selection:**
- SeamFP remains selected after creation
- Child shells can be individually selected

### Implementation Phases

#### Phase 1: Core Geometry
- [ ] Implement edge detection with tolerance
- [ ] Develop edge projection algorithm
- [ ] Create overlap strip generation
- [ ] Handle boolean operations safely

#### Phase 2: Feature Integration
- [ ] Extend SeamFP with proper properties
- [ ] Integrate with CompositeShell creation
- [ ] Handle laminate property inheritance
- [ ] Implement error handling and validation

#### Phase 3: GUI Command
- [ ] Update CompositeSeamCommand
- [ ] Implement proper selection handling
- [ ] Add resource definitions
- [ ] Create undo/redo support

#### Phase 4: Testing
- [ ] Unit tests for edge detection
- [ ] Integration tests for geometry operations
- [ ] GUI tests for command workflow
- [ ] Edge case tests (no common edge, multiple edges, etc.)

### Success Criteria

1. **Correctness**: Seam creates valid overlap joint geometry
2. **Robustness**: Handles various edge configurations gracefully
3. **Performance**: Completes geometry operations efficiently
4. **Usability**: Clear error messages and recovery options
5. **Integration**: Works seamlessly with CompositeShell ecosystem

### Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Edge detection is unreliable | High | Use robust geometric comparison, provide tolerance controls |
| Boolean operations fail on complex geometry | High | Implement fallback strategies, validate geometry beforehand |
| Overlap geometry creates invalid shells | High | Extensive validation, error recovery |
| Performance degradation on large models | Medium | Optimize algorithms, provide progress indicators |

### Related Files

- `features/Seam.py` - To be rewritten
- `tools/seam.py` - To be rewritten
- `features/CompositeShell.py` - May need extensions
- `features/VPCompositePart.py` - View provider considerations

### Open Questions

1. Should the overlap region inherit properties from master or attachment?
2. How to handle cases where the attachment edge doesn't align perfectly with master edge?
3. Should there be an option for asymmetric overlap (different widths on each side)?
4. How to handle multiple common edges (e.g., L-shaped joints)?

---

**Next Steps:**
1. Prototype edge detection and projection algorithms
2. Design overlap strip generation method
3. Determine laminate property inheritance rules
4. Create test cases for various joint configurations