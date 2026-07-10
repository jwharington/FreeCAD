# Seam Transition Algorithm Implementation - Unified Model

## Overview

This document details the geometric algorithm for creating seam transitions between composite faces, supporting both lap and scarf joint types through a **unified geometry model** with **distinct property mapping**.

---

## Core Principle

### Geometry vs Properties
- **Geometry**: The physical shape of the overlap zone (C) - **identical for both lap and scarf**
- **Properties**: Material characteristics assigned across the overlap zone - **differs by type**

```
     Master (A)          Attachment (B)
         │                   │
    ┌────┴───────────────┴───┐ C (Overlap Zone - Same Geometry!)
    │                        │
    └────────────────────────┘
```

The overlap zone geometry is generated once. Then:
- **Lap**: Assign discrete stacking order (A over B or B over A)
- **Scarf**: Map continuous property gradient across the zone

---

## Geometric Algorithm

### Step 1: Partner Edge Detection
Find shared edges between master (A) and attachment (B).

```cpp
std::vector<TopoDS_Edge> FindPartnerEdges(const TopoDS_Face& A, 
                                          const TopoDS_Face& B) {
    std::vector<TopoDS_Edge> partners;
    
    // Check each edge of faceB against edges of faceA
    TopExp_Explorer expA(A, TopAbs_EDGE);
    while (expA.More()) {
        TopoDS_Edge edgeA = TopoDS::Edge(expA.Current());
        
        TopExp_Explorer expB(B, TopAbs_EDGE);
        while (expB.More()) {
            TopoDS_Edge edgeB = TopoDS::Edge(expB.Current());
            
            if (edgeA.IsPartner(edgeB)) {
                partners.push_back(edgeA);
                break;
            }
            expB.Next();
        }
        expA.Next();
    }
    return partners;
}
```

### Step 2: Define Overlap Boundaries
Create reference planes at overlap boundaries.

```cpp
// For overlap width W along edge direction
gp_Dir edgeDir = GetEdgeDirection(partnerEdge);
gp_Pnt startPoint = GetEdgeStart(partnerEdge);

// Plane at start of overlap (boundary A-C)
gp_Vec normal = GetFaceNormal(A);
gp_Pnt planePoint = startPoint + edgeDir * (-overlapWidth/2);
Handle(Geom_Plane) planeAC = new Geom_Plane(gp_Ax3(planePoint, normal));

// Plane at end of overlap (boundary C-B)
gp_Pnt planePointEnd = startPoint + edgeDir * (overlapWidth/2);
Handle(Geom_Plane) planeCB = new Geom_Plane(gp_Ax3(planePointEnd, normal));
```

### Step 3: Generate Pipe Shells Along Edges
Create solid tubes along each partner edge.

```cpp
TopoDS_Shape CreatePipeShell(const TopoDS_Edge& edge, double radius) {
    // Convert edge to wire
    TopoDS_Wire wire = BRepBuilderAPI_MakeWire(edge).Wire();
    
    // Create circular cross-section profile
    gp_Dir axis = GetEdgeDirection(edge);
    Handle(Geom_Circle) circle = new Geom_Circle(
        gp_Ax2(gp_Pnt(), gp_Dir(0, 1, 0), axis), 
        radius
    );
    TopoDS_Wire profile = BRepBuilderAPI_MakeWire(circle->Create3d()).Wire();
    
    // Build pipe shell
    BRepOffsetAPI_MakePipeShell pipe(wire);
    pipe.Add(profile);
    pipe.Build();
    
    return pipe.Shape();
}
```

### Step 4: Boolean Cut Operations
Cut master face with pipe shells to define overlap zone.

```cpp
TopoDS_Shape CutFaceWithTubes(const TopoDS_Face& face,
                              const std::vector<TopoDS_Shape>& tubes) {
    TopoDS_Shape result = face;
    
    for (const auto& tube : tubes) {
        BRepAlgoAPI_Cut cutter(result, tube);
        cutter.SetTolerance(1e-6);
        cutter.Build();
        
        if (!cutter.IsDone()) {
            throw std::runtime_error("Boolean cut failed");
        }
        result = cutter.Shape();
    }
    
    return result;
}
```

### Step 5: Assemble Overlap Zone
Create compound geometry representing the overlap zone.

```cpp
TopoDS_Shape CreateOverlapGeometry(const TopoDS_Face& A,
                                   const TopoDS_Face& B,
                                   double overlapWidth,
                                   double taperAngle) {
    
    // 1. Find shared edges
    auto partners = FindPartnerEdges(A, B);
    if (partners.empty()) {
        return TopoDS_Shape(); // No seam possible
    }
    
    // 2. Generate pipe shells along edges
    std::vector<TopoDS_Shape> tubes;
    for (const auto& edge : partners) {
        TopoDS_Shape tube = CreatePipeShell(edge, overlapWidth);
        tubes.push_back(tube);
    }
    
    // 3. Cut master face with tubes (creates step-like geometry)
    TopoDS_Shape cutMaster = CutFaceWithTubes(A, tubes);
    
    // 4. Return as compound (includes both cut pieces)
    BRep_Builder builder;
    TopoDS_Compound compound;
    builder.MakeCompound(compound);
    builder.Add(compound, cutMaster);
    
    return compound;
}
```

---

## Property Mapping

### Lap Joint Properties

```cpp
void MapLapProperties(const TopoDS_Shape& geometry,
                      const TopoDS_Face& A,
                      const TopoDS_Face& B,
                      bool masterOverAttachment) {
    
    // Identify which face sits on top
    TopoDS_Face topFace, bottomFace;
    
    if (masterOverAttachment) {
        topFace = A;   // Master on top
        bottomFace = B; // Attachment on bottom
    } else {
        topFace = B;   // Attachment on top
        bottomFace = A; // Master on bottom
    }
    
    // Mark faces with stacking order
    SetProperty(topFace, "seam_order", "top");
    SetProperty(bottomFace, "seam_order", "bottom");
    
    // Store metadata
    geometry.SetProperty("seam_type", "lap");
    geometry.SetProperty("stacking_order", masterOverAttachment ? "master_over_attachment" : "attachment_over_master");
}
```

### Scarf Joint Properties

```cpp
void MapScarfProperties(const TopoDS_Shape& geometry,
                        const TopoDS_Face& A,
                        const TopoDS_Face& B,
                        double taperAngle) {
    
    // Interpolate properties across transition
    double thicknessA = GetThickness(A);
    double thicknessB = GetThickness(B);
    double angleA = GetFiberAngle(A);
    double angleB = GetFiberAngle(B);
    
    // Linear interpolation functions
    auto ThicknessFunc = [thicknessA, thicknessB](double t) {
        return thicknessA + t * (thicknessB - thicknessA);
    };
    
    auto AngleFunc = [angleA, angleB](double t) {
        return angleA + t * (angleB - angleA);
    };
    
    // Sample at regular intervals
    int samples = 10;
    std::vector<double> thicknesses, angles;
    for (int i = 0; i < samples; i++) {
        double t = static_cast<double>(i) / (samples - 1);
        thicknesses.push_back(ThicknessFunc(t));
        angles.push_back(AngleFunc(t));
    }
    
    // Store as JSON or dictionary
    std::string props = FormatProperties(thicknesses, angles);
    geometry.SetProperty("seam_type", "scarf");
    geometry.SetProperty("gradient_properties", props);
}
```

---

## Helper Functions

### Edge Direction and Point Extraction
```cpp
gp_Dir GetEdgeDirection(const TopoDS_Edge& edge) {
    BRep_Tool tool;
    Handle(Geom_Curve) curve = tool.Curve(edge);
    // Extract direction from curve parameterization
    // Simplified: return normalized tangent at midpoint
    gp_Pnt midPoint = curve->Value(0.5);
    gp_Vec dir = curve->LinearizedOrientation();
    return gp_Dir(dir.X(), dir.Y(), dir.Z());
}

gp_Pnt GetEdgeStart(const TopoDS_Edge& edge) {
    TopoDS_Vertex startV = TopExp_Explorer(edge, TopAbs_VERTEX).Current();
    gp_Pnt p = BRep_Tool::Pnt(startV);
    return p;
}
```

### Face Normal Calculation
```cpp
gp_Dir GetFaceNormal(const TopoDS_Face& face) {
    BRepGProp_Face prop(face);
    gp_Vec normal = prop.Normal();
    return gp_Dir(normal.X(), normal.Y(), normal.Z());
}
```

### Tapered Surface Generation (Optional for Scarf)
If a tapered profile is desired for the overlap zone geometry:

```cpp
TopoDS_Shape CreateTaperedSurface(const TopoDS_Edge& edge,
                                  double overlapWidth,
                                  double taperAngle) {
    
    // Get edge direction and start point
    gp_Dir edgeDir = GetEdgeDirection(edge);
    gp_Pnt startPoint = GetEdgeStart(edge);
    
    // Create 2D profile in local coordinate system
    std::array<double, 3> points = {
        {-overlapWidth/2, 0.0, 0.0},
        {0.0, tan(taperAngle), 0.0},
        {overlapWidth/2, 0.0, 0.0}
    };
    
    Handle(Geom_BSplineCurve) curve = CreateBSpline(points);
    
    // Extrude along edge direction
    BRepPrimAPI_MakeExtrude maker(curve, edgeDir, 0);
    maker.SetMode(ExtMode_Shape);
    maker.Build();
    
    return maker.Shape();
}
```

---

## Error Handling

### Validation
```cpp
void ValidateFaces(const TopoDS_Face& A, const TopoDS_Face& B) {
    if (!A.IsValid() || !B.IsValid()) {
        throw std::invalid_argument("Input faces are invalid");
    }
    
    if (A.Area() < 1e-6 || B.Area() < 1e-6) {
        throw std::invalid_argument("Faces have zero area");
    }
}
```

### Boolean Operation Failures
```cpp
bool TryBooleanOperation(TopoDS_Shape& result, 
                         const TopoDS_Shape& arg,
                         const TopoDS_Shape& tool,
                         bool isCut) {
    try {
        if (isCut) {
            BRepAlgoAPI_Cut cutter(arg, tool);
            cutter.SetTolerance(1e-6);
            cutter.Build();
            if (cutter.IsDone()) {
                result = cutter.Shape();
                return true;
            }
        } else {
            BRepAlgoAPI_Fuse fuser(arg, tool);
            fuser.SetTolerance(1e-6);
            fuser.Build();
            if (fuser.IsDone()) {
                result = fuser.Shape();
                return true;
            }
        }
    } catch (...) {
        // Log error, return false
    }
    return false;
}
```

---

## Performance Optimization

### Parallel Processing
```cpp
#pragma omp parallel for
for (int i = 0; i < static_cast<int>(partners.size()); i++) {
    auto tube = CreatePipeShell(partners[i], overlapWidth);
    tubes.push_back(tube);
}
```

### Early Validation
```cpp
if (!ValidateFace(A) || !ValidateFace(B)) {
    return SeamResult{false, "", "Invalid input faces"};
}
```

### Tolerance Tuning
```cpp
double tol = std::max(A.Area, B.Area) * 1e-6;
splitter.SetTolerance(tol);
```

---

## References

- [OCCT Boolean Operations](https://dev.opencascade.com/doc/occt-7.4.0/overview/html/occt_user_guides__boolean_operations.html)
- [BRepOffsetAPI_MakePipeShell](https://dev.opencascade.com/doc/occt-7.4.0/reference/html/class_b_rep_offset_a_p_i___make_pipe_shell.html)
- [BRepAlgoAPI_Cut](https://dev.opencascade.com/doc/occt-7.4.0/reference/html/class_b_rep_algo_a_p_i___cut.html)
- [GeomBSplineCurve](https://dev.opencascade.com/doc/occt-7.4.0/reference/html/class_geom_b_spline_curve.html)

---

*Last updated: 2026-07-09*
*Unified geometry model with separate property mapping*