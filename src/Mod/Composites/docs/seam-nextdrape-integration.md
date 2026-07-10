# Seam Integration into nextdrape - Unified Model

## Domain Requirements (Clarified)

### Shared Geometry Model
Both lap and scarf joints use the **same geometric approach**:
- Create a **thin surface geometry** (overlap zone C) connecting master (A) and attachment (B) along shared edges
- This surface represents the **physical transition region** between the two composite faces
- The geometry is determined by:
  - Edge partnership detection
  - Overlap width parameter
  - Geometric constraints (continuity, boundary conditions)

### Distinction: Material Property Mapping
The difference lies **only** in how material properties are assigned across the overlap zone:

| Joint Type | Property Mapping |
|------------|------------------|
| **Lap** | **Discrete stacking order**: Either A over B or B over A |
| **Scarf** | **Continuous gradient**: Linear interpolation from A → B properties |

---

## Unified Algorithm

```cpp
namespace nextdrape {

enum class SeamTransitionType { Lap, Scarf };

struct SeamParams {
    double overlapWidth;      // Width of overlap zone (C)
    SeamTransitionType type;  // Lap or Scarf
    
    // Lap-specific: stacking order
    bool masterOverAttachment = true; // A over B? (true) or B over A? (false)
    
    // Scarf-specific: gradient parameters (optional if geometry defines taper)
    double taperAngle = 5.0;        // Angle of taper (degrees) - for geometric profile
};

struct SeamResult {
    bool success;
    TopoDS_Shape geometry; // The overlap zone C (thin surface/compound)
    std::vector<TopoDS_Face> faces; // Individual transition faces
    double area;
    std::string errorMessage;
};

class SeamSolver {
public:
    static SeamResult CreateSeam(
        const TopoDS_Face& faceA,
        const TopoDS_Face& faceB,
        SeamParams params);

private:
    // === UNIFIED GEOMETRY GENERATION (Same for Lap & Scarf) ===
    static TopoDS_Shape CreateOverlapGeometry(
        const TopoDS_Face& A,
        const TopoDS_Face& B,
        double overlapWidth,
        double taperAngle); // taperAngle affects geometry profile, not properties

    // === PROPERTY MAPPING (Differs by type) ===
    static void MapLapProperties(
        const TopoDS_Shape& geometry,
        const TopoDS_Face& A,
        const TopoDS_Face& B,
        bool masterOverAttachment);
        
    static void MapScarfProperties(
        const TopoDS_Shape& geometry,
        const TopoDS_Face& A,
        const TopoDS_Face& B,
        double taperAngle);
        
    // === COMMON HELPERS ===
    static std::vector<TopoDS_Edge> FindPartnerEdges(
        const TopoDS_Face& A,
        const TopoDS_Face& B);
};

} // namespace nextdrape
```

---

## Implementation Phases (Updated)

### Phase 1: Unified Geometry Engine (Weeks 1-2)

#### Step 1.1: Foundation
- [ ] Set up C++ build environment for nextdrape
- [ ] Implement `FindPartnerEdges()` (reuse Python logic)
- [ ] Test edge partnership detection with various geometries

#### Step 1.2: Overlap Geometry Generation
- [ ] Implement `CreateOverlapGeometry()`:
  - **For lap**: Pipe shell cuts along edges
  - **For scarf**: Tapered surface extrusion (same geometric profile)
  - **Key insight**: Geometry is the same; only property mapping differs
  
#### Step 1.3: Validation & Testing
- [ ] Test geometry generation with simple shapes
- [ ] Verify continuity at boundaries
- [ ] Test edge cases (zero overlap, degenerate faces)

---

### Phase 2: Property Mapping (Weeks 3-4)

#### Step 2.1: Lap Joint Properties
- [ ] Implement `MapLapProperties()`:
  - Assign discrete stacking order (A over B or B over A)
  - Mark faces with appropriate properties
  - Store metadata for manufacturing

#### Step 2.2: Scarf Joint Properties
- [ ] Implement `MapScarfProperties()`:
  - Define interpolation functions
  - Map thickness, fiber angle, etc. across transition
  - Store as attributes on faces

#### Step 2.3: Integration & Optimization
- [ ] Optimize property mapping performance
- [ ] Add diagnostics and logging
- [ ] Finalize unified interface

---

### Phase 3: Python Binding & Validation (Week 5)

#### Step 3.1: Python Interface
- [ ] Extend `Composites_drape.cpp` with seam binding
- [ ] Serialize `SeamResult` to Python dict
- [ ] Error handling and exception propagation

#### Step 3.2: Test Suite
- [ ] Run all existing seam tests
- [ ] Add new tests for both lap and scarf
- [ ] Performance benchmarking

#### Step 3.3: Documentation & Release
- [ ] Update API documentation
- [ ] Add usage examples
- [ ] Clean up temporary code

---

## Key Technical Decisions

### Decision 1: Geometry Representation
**Chosen Approach**: Unified thin surface/solid representing overlap zone C.

**Why Unified?**
- Simplifies implementation (single geometry engine)
- Consistent behavior across joint types
- Easier maintenance and testing

**Implementation**:
- Use pipe shells for edge-based transitions (like current Python)
- For scarf: same pipe shell geometry + property gradient
- Geometry stored as compound of faces/solids

### Decision 2: Property Mapping Separation
**Chosen Approach**: Keep property mapping separate from geometry generation.

**Benefits**:
- Clear separation of concerns
- Easy to add new joint types
- Reusable geometry engine

### Decision 3: Parameter Handling
**Chosen Approach**: Both joint types accept `taperAngle`, but use differently.
- **Lap**: `taperAngle` may affect edge rounding/fillet
- **Scarf**: `taperAngle` defines the geometric profile

---

## Testing Strategy (Updated)

### Unit Tests (C++)

```cpp
// Unified geometry test - same for both types
TEST(SeamSolver, OverlapGeometry_Planes) {
    auto A = CreatePlane(20, 10);
    auto B = CreatePlane(10, 10, Vector(5, 0, 0));
    SeamParams params{1.0, SeamTransitionType::Lap, true};
    
    auto result = SeamSolver::CreateSeam(A, B, params);
    EXPECT_TRUE(result.success);
    EXPECT_GT(result.area, 0.0);
    // Verify geometry exists
}

TEST(SeamSolver, OverlapGeometry_Scarf) {
    SeamParams params{1.0, SeamTransitionType::Scarf, 5.0};
    auto result = SeamSolver::CreateSeam(A, B, params);
    // Verify geometry exists (same as lap!)
}

// Property mapping tests
TEST(SeamSolver, LapProperties_AOverB) {
    auto result = SeamSolver::CreateSeam(A, B, params{1.0, SeamTransitionType::Lap, true});
    // Verify A over B property assignment
}

TEST(SeamSolver, ScarfPropertyGradient) {
    auto result = SeamSolver::CreateSeam(A, B, params{1.0, SeamTransitionType::Scarf, 5.0});
    // Verify continuous property gradient
}
```

---

## Success Criteria (Updated)

1. **Correctness**: Unified geometry works for both lap and scarf
2. **Flexibility**: All parameter combinations work correctly
3. **Performance**: Comparable or better than Python version
4. **Robustness**: Handles edge cases gracefully
5. **Maintainability**: Clean separation between geometry and properties

---

## Risk Mitigation (Updated)

| Risk | Impact | Mitigation |
|------|--------|------------|
| Geometry too complex for both types | High | Start with simple geometry, refine |
| Property mapping confusion | Medium | Keep clear separation, document thoroughly |
| Performance issues | Medium | Profile early, optimize geometry engine |
| Test failures | High | Keep Python implementation initially |

---

*Last updated: 2026-07-09*
*Unified geometry model for lap and scarf joints*