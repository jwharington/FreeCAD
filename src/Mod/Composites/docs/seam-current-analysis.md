# Current Seam Implementation Analysis

## Existing Python Code (`tools/seam.py`)

### Core Functions

```python
def make_join_seam(face1, face2, overlap):
    """Main entry point."""
    edges = get_partner_edges(face1, face2)  # Find shared edges
    if not edges:
        edges = _fallback_join_edges(...)  # Try common/section/intersect
    return make_edge_seam(face1, edges, overlap)
```

```python
def make_edge_seam(shape, edges, overlap):
    """Create pipe shells along edges, then slice shape."""
    tools = []
    for e in edges:
        tube = generate_seam_tube(Part.Wire(e), overlap)  # Pipe shell
        tools.append(tube)
    return splitAPI.slice(shape, tools, "Split", 1e-6)  # Boolean cut
```

```python
def generate_seam_tube(wire, overlap):
    """Create solid pipe shell along wire."""
    c = Part.Circle()  # Circular cross-section
    c.Radius = overlap
    return wire.makePipeShell([c], makeSolid=True, isFrenet=True)
```

```python
def get_partner_edges(face1, face2):
    """Find edges where one is partner of other."""
    return [e2 for e2 in face2.Edges for e1 in face1.Edges if e2.isPartner(e1)]
```

---

## Algorithmic Understanding

### What It Does
1. **Find shared edges** between two faces
2. **Generate pipe shells** (tubes) along those edges with radius = overlap
3. **Boolean cut** the master face (face1) with the tubes
4. **Return** the modified master face as a compound

### Geometric Result
- The master face is **cut along its edges** that are adjacent to the attachment face
- The pipe shells remove material from the master face, creating a **stepped transition**
- Effectively creates a **lap joint** where the master face overlaps onto the attachment face

### Current Behavior
- **Master**: face1 (the first face passed)
- **Attachment**: face2 (the second face passed)
- **Overlap**: radius of pipe shell
- **Stacking order**: Implicit - master face sits on top of attachment face
- **Transition**: Stepped (discrete) - not smooth

---

## Mapping to New Requirements

### Lap Joint (Current Implementation)
✅ **Matches current behavior:**
- Creates stepped transition (A over B)
- Uses pipe shells to define cut boundaries
- Boolean cut removes material from master

**Required Change:**
- Add explicit `masterOverAttachment` parameter
- When `False` (B over A), need different geometry: cut attachment face instead, or create compound of both cuts

### Scarf Joint (New Feature)
❌ **Not supported currently**
- Need tapered transition instead of pipe shells
- Need continuous property gradient mapping
- Need G1 continuity at boundaries

**Implementation Approach:**
- Replace pipe shell generation with tapered surface extrusion
- Use blending surfaces for smooth transitions
- Add property interpolation logic

---

## Key Observations

### 1. Overlap Parameter Meaning
- In current code: `overlap` = **pipe shell radius**
- In lap joint: `overlap` = **width of overlap zone**
- In scarf joint: `overlap` = **length of taper**

### 2. Edge Partnership Detection
- Uses `Edge.isPartner()` which checks if edges are identical (same underlying curve, orientation)
- This is correct for finding shared seam boundaries
- Fallback methods exist for cases where partnership fails

### 3. Boolean Operation
- Uses `splitAPI.slice()` which appears to be a custom wrapper around OCCT boolean operations
- Need to understand this API before migrating to pure C++

### 4. Error Handling
- Comprehensive validation (null faces, invalid faces, null edges)
- Fallback chain for edge detection
- Clear error messages

---

## Migration Strategy

### Phase 1: Lap Joint (Minimal Changes)
1. Keep edge partnership detection (already correct)
2. Modify `make_edge_seam()` to support stacking order:
   - If `masterOverAttachment=True`: Cut master face (current behavior)
   - If `masterOverAttachment=False`: Cut attachment face OR create compound of both cuts
3. Return appropriate geometry

### Phase 2: Scarf Joint (New Implementation)
1. Create separate function `make_scarf_seam()`
2. Generate tapered surface using OCCT extrusion
3. Blend with parent faces using `GeomFill` or similar
4. Map material properties along transition

### Phase 3: Unified Interface
```python
def make_join_seam(face1, face2, overlap, type="lap", **params):
    """Unified seam generator."""
    if type == "lap":
        return create_lap_seam(face1, face2, overlap, **params)
    elif type == "scarf":
        return create_scarf_seam(face1, face2, overlap, **params)
```

---

## Testing Implications

### Existing Tests
- All current tests assume lap joint behavior (A over B)
- May need to update assertions for new stacking order option

### New Tests Needed
- Lap joint with B over A
- Scarf joint geometry validation
- Property gradient verification for scarf

---

*Analysis completed: 2026-07-09*