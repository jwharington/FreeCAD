# Seam C++ Prototype - Initial Investigation

## Quick OCCT Exploration

Let me explore what's available in FreeCAD's OCCT bindings for seam generation.

### Key Questions:
1. How to generate pipe shells from edges?
2. What boolean operations are available?
3. How to validate face adjacency?

### Approach:
Create a minimal C++ test that demonstrates seam generation using pure OCCT (no nextdrape).

## Prototype Plan

### Phase 1: Edge-based Pipe Shell
```cpp
// Create a tube along an edge
TopoDS_Edge edge = ...;
Handle(Geom_CylindricalSurface) cyl = new Geom_CylindricalSurface(overlap);
TopoDS_Wire wire = ...; // from edge
BRepPrimAPI_MakePipe maker(wire);
maker.SetRadius(overlap);
TopoDS_Shape tube = maker.Shape();
```

### Phase 2: Boolean Slice
```cpp
// Slice master face with tubes
BRepAlgoAPI_Split splitter(master, tube);
splitter.SetTolerance(1e-6);
splitter.Build();
if (splitter.IsDone()) {
    TopoDS_Shape result = splitter.Shape();
}
```

### Phase 3: Partner Edge Detection
```cpp
// Check if two edges are partners (share same underlying curve and orientation)
bool arePartners(const TopoDS_Edge& e1, const TopoDS_Edge& e2) {
    return e1.IsPartner(e2);
}
```

Let me write this up as a reference document.

## References

- [OCCT Boolean Operations](https://dev.opencascade.com/doc/occt-7.4.0/overview/html/occt_user_guides__boolean_operations.html)
- [BRepPrimAPI_MakePipe](https://dev.opencascade.com/doc/occt-7.4.0/reference/html/class_b_rep_prim_a_p_i___make_pipe.html)
- [BRepAlgoAPI_Split](https://dev.opencascade.com/doc/occt-7.4.0/reference/html/class_b_rep_algo_a_p_i___split.html)

---

*See `seam-nextdrape-integration.md` for complete implementation plan.*