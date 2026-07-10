# Seam Integration: Unified Geometry Model

## Key Insight

**Both lap and scarf joints share the same underlying geometric model.** The distinction is purely in how material properties are mapped across the overlap zone (C).

---

## Unified Algorithm

### Step 1: Find Shared Edges
```cpp
auto partners = FindPartnerEdges(A, B);
```

### Step 2: Generate Pipe Shells Along Edges
```cpp
for (const auto& edge : partners) {
    tubes.push_back(CreatePipeShell(edge, overlapWidth));
}
```

### Step 3: Boolean Cut Master Face
```cpp
cutMaster = CutFaceWithTubes(A, tubes);
```

### Step 4: Assemble Overlap Zone
```cpp
compound.Add(cutMaster);
return compound;
```

---

## Property Mapping (Separate Concern)

### Lap Joint
- Discrete stacking order (A over B or B over A)
- Mark faces with "top" and "bottom" designation
- Store metadata about which face is on top

### Scarf Joint
- Continuous linear gradient from A → B properties
- Interpolate thickness, fiber angle, etc.
- Sample at regular intervals along transition

---

## Benefits of Unified Model

1. **Simpler implementation**: One geometry generation code path
2. **Consistent results**: Same geometry for both joint types
3. **Easier maintenance**: Changes to geometry affect both types automatically
4. **Clean separation**: Geometry vs. property mapping concerns

---

## API Design

```cpp
struct SeamResult {
    bool success;
    TopoDS_Shape geometry; // Unified overlap zone
    std::string error;
};

SeamResult CreateSeam(const TopoDS_Face& A, 
                     const TopoDS_Face& B,
                     double overlapWidth,
                     SeamTransitionType type,
                     bool masterOverAttachment = true,
                     double taperAngle = 5.0) {
    
    // 1. Generate unified geometry
    auto result = SeamSolver::CreateOverlapGeometry(A, B, overlapWidth, taperAngle);
    
    if (!result.success) return result;
    
    // 2. Map properties based on type
    switch (type) {
        case SeamTransitionType::Lap:
            MapLapProperties(result.geometry, A, B, masterOverAttachment);
            break;
        case SeamTransitionType::Scarf:
            MapScarfProperties(result.geometry, A, B, taperAngle);
            break;
    }
    
    return result;
}
```

---

*Last updated: 2026-07-09*