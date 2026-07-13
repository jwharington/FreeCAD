# Seam Overlap Geometry by Surface Marching

## Summary

The seam overlap zone should be computed with a **surface-marching** approach on the attachment face.

Key clarification:
- **Lap** and **scarf** joints use the **same geometry generation**.
- The difference between lap and scarf is **only how material properties are assigned afterward**.
- Geometry generation should produce the thin overlap surface `C` by marching away from the joint edge on the attachment face.

## Why surface marching

Surface marching is the best primary approach because it:
- stays on the attachment face instead of relying on volume/surface booleans
- handles curved surfaces more naturally than swept-volume intersection
- allows a true overlap width construction on the surface, approximated numerically
- keeps the geometry solver independent from lap/scarf semantics

## OCCT helper APIs to use

### Surface evaluation and projection
- `BRepAdaptor_Surface`
- `GeomLProp_SLProps`
- `BRepLProp_SLProps`
- `GeomAPI_ProjectPointOnSurf`
- `BRepClass_FaceClassifier`
- `BRepTopAdaptor_FClass2d`

### Curve / wire / trim construction
- `BRepBuilderAPI_MakeEdge`
- `BRepBuilderAPI_MakeWire`
- `BRepBuilderAPI_MakeFace`
- `BRep_Tool::CurveOnSurface`
- `BRepTools_WireExplorer`

### Fallback / validation helpers
- `BRepAlgoAPI_Section`
- `GeomAPI_IntCS`
- `GeomAPI_IntSS`
- `BRepExtrema_DistShapeShape`

## Surface-marching concept

1. Start from the joint edge on the attachment face.
2. Compute a local frame at a seed point:
   - edge tangent
   - face normal
   - in-surface march direction
3. Step across the surface in small increments.
4. Reproject each step onto the face.
5. Accumulate arc length until the requested overlap width is reached.
6. Use the marched front as the far boundary of the overlap zone.
7. Build the overlap strip as a trimmed face or compound of faces.

## What the seam solver should return

The geometry solver should return:
- the overlap zone geometry `C`
- ordered boundary samples
- sampled 3D points
- sampled UV points if available
- achieved width / progress
- diagnostic information

The solver should **not** encode lap/scarf property semantics.
That mapping happens afterward.

## Geometry vs properties

### Geometry layer
Shared by both lap and scarf:
- same marched overlap surface
- same boundary construction
- same trim / clipping behavior

### Property layer
Differs by joint type:
- **Lap**: discrete stacking order, e.g. A over B or B over A
- **Scarf**: linear property gradient from A to B

---

# Seam Test Matrix

The seam tests must exercise **pairs of shapes**, not single fixtures.  Each scenario defines a master face set and an attachment face set.

| Scenario | Master fixture | Attachment fixture | Joint-edge condition | What it validates |
|---|---|---|---|---|
| Flat → Flat | `MakeRectangularPanel(...)` | `MakeRectangularPanel(...)` | Straight edge | Baseline marching, width control, simple trim |
| Folded Master → Flat | `MakeBentPlate(...)` or `MakeJoinedRectanglesTwentyDegrees(...)` | `MakeRectangularPanel(...)` | Straight / kinked transition | Master with multiple faces, face selection, inward march on a nontrivial master |
| Flat → Folded Attachment | `MakeRectangularPanel(...)` | `MakeBentPlate(...)` or `MakeJoinedRectanglesTwentyDegrees(...)` | Straight / kinked transition | Attachment spanning multiple faces, marching across a bend |
| Curved → Curved | `MakeCylindricalSegment(...)` | compatible curved face | Curved edge | Tangent/normal stability, projection on curved geometry |
| Corner Crossing | `MakeJoinedRectanglesTwentyDegrees(...)` | `MakeRectangularPanel(...)` or another folded pair | Edge goes around a corner | Boundary propagation through changing edge direction |
| Hole / Multi-wire | `MakeRectangularPanelWithRoundHole(...)` or `MakeDartPlate()` | `MakeRectangularPanel(...)` | Multiple wires / hole interaction | Trim interruption, multi-wire handling, local clipping |

## Seam coverage completed

The remaining shared-joint seam coverage now lives in the shared fixture matrix and test suite.

For the failure modes that still need explicit detection or solver work, see:
- `src/3rdParty/nextdrape/docs/seam-failure-detection-plan.md`

Implemented scenarios:

- Mirrored lateral offset rectangle
- Trapezoidal / tapered panels, taper along seam direction
- Trapezoidal / tapered panels, taper across seam direction
- Rectangle → L-shaped joint
- Hole-adjacent successful seam case
- Non-symmetric doubly curved surfaces
- Adaptive joint-edge sampling with bounded error rather than fixed 3-point sampling

The broader seam matrix also continues to cover:

- Flat → Flat
- Folded Master → Flat
- Flat → Folded Attachment
- Curved → Curved
- Corner Crossing
- Hole / Multi-wire
- Curvature aligned with seam direction
- Curvature across seam direction
- Mixed curvature master/attachment mismatch

## Suggested initial test set

Start with these four scenarios first:

1. **Flat → Flat**
2. **Folded Master → Flat**
3. **Curved → Curved**
4. **Hole / Multi-wire**

That gives coverage of:
- baseline marching
- multi-face master handling
- curved edge / curved surface stability
- trim / hole interruptions

## Expected behavior by scenario

### Flat → Flat
- march cleanly by the requested overlap width
- produce a single bounded overlap strip
- no clipping needed

### Folded Master → Flat
- choose the correct attachment-side direction even if the master spans multiple faces
- keep the seam geometry on the attachment face
- report if the march crosses a face boundary

### Flat → Folded Attachment
- march across the attachment bend without losing local frame consistency
- preserve continuity across the joint region
- expose diagnostics if the front needs local repair

### Curved → Curved
- respect curvature while marching
- keep reprojecting onto the surface
- avoid drifting off-face

### Corner Crossing
- update the local frame as the edge direction changes
- keep boundary samples ordered
- handle polyline-like seam edges

### Hole / Multi-wire
- recognize multiple wires in the joining region
- clip or stop the march at holes / trims
- preserve partial overlap geometry instead of failing the whole seam

---

# Implementation Plan

## 1. Create a seam-specific nextdrape solver

Add a new seam module under nextdrape, separate from the drape solver:

- `src/3rdParty/nextdrape/include/nextdrape/SeamOverlapSolver.hpp`
- `src/3rdParty/nextdrape/include/nextdrape/SeamOverlapTypes.hpp`

If the result/diagnostic structures are small, they can live in `Types.hpp` instead.

### Responsibilities
- accept a face, seed edge, and overlap width
- march across the attachment face
- return the overlap zone geometry
- produce diagnostics for fallback and clipping

## 2. Reuse existing nextdrape helpers

The plan should reuse existing surface utilities where possible:
- `SurfaceNavigator` for projection / frame evaluation / in-face checks
- `SurfaceProjection` for step advancement and projection logic

This keeps seam logic aligned with the rest of nextdrape’s geometry style.

## 3. Implement the marching core

The marching algorithm should:
1. validate the input face and edge
2. find a seed point on the joint edge
3. evaluate local tangents and normals
4. choose the inward march direction
5. step by a small distance
6. project the stepped point back onto the surface
7. classify the point against the face boundary
8. continue until the overlap width is reached

### Important behavior
- use small, configurable steps
- reduce step size on local failure
- keep the path on the surface by reprojection
- stop cleanly at trim boundaries or holes

## 4. Add fallback strategies

If marching becomes unstable locally:

1. **Reduce step size** and retry
2. **Switch to UV-guided stepping** on the same face
3. **Clip locally** if the march reaches a trim boundary
4. **Recover a local boundary segment** using section/intersection helpers
5. Keep legacy seam generation only as a last-resort fallback

## 5. Expose the solver to Python

Keep `src/Mod/Composites/tools/seam.py` as a thin adapter.

The Python layer should:
- call the C++ seam overlap solver
- receive the overlap zone geometry and samples
- apply lap/scarf property mapping afterward

This preserves the current FreeCAD-facing API while moving the geometry work into C++.

## 6. Add tests before broad integration

Write focused tests for the seam solver first.

### Minimum tests
- flat → flat
- folded master → flat
- flat → folded attachment
- curved → curved
- hole / multi-wire seam
- corner-crossing seam
- regression against the current Python seam behavior on simple geometry

### What to validate
- overlap width reached
- strip stays on the face
- strip respects trim boundaries
- diagnostics are useful when marching fails

---

## Suggested development sequence

### Phase 1: Solver skeleton
- add seam-specific result and diagnostic types
- create the seam solver class
- wire in the existing nextdrape projection/frame helpers

### Phase 2: Marching implementation
- implement seed selection
- implement local frame evaluation
- implement step/projection/classification loop
- emit the overlap strip geometry

### Phase 3: Fallbacks and validation
- add local retry logic
- add trim/boundary clipping
- add section-based recovery helpers

### Phase 4: Python integration
- expose the new solver through the Composites binding
- keep the Python seam module as a thin adapter
- separate geometry generation from lap/scarf property mapping

### Phase 5: Tests and polish
- add C++ tests for planar, curved, corner, and hole cases
- add regression tests against existing seam behavior
- refine diagnostics and failure messages

---

## Recommended file layout

```text
src/3rdParty/nextdrape/include/nextdrape/
  SeamOverlapSolver.hpp
  SeamOverlapTypes.hpp

src/Mod/Composites/tools/
  seam.py

src/Mod/Composites/App/
  CompositesDrape.cpp
```

## Build and test instructions

These instructions are for the **nextdrape** codebase only.

### Configure
From the `src/3rdParty/nextdrape` directory:

```bash
cmake -S . -B build -DBUILD_TESTING=ON
```

### Build

```bash
cmake --build build -j8
```

This builds:
- `nextdrape_core`
- `nextdrape_cli`
- `nextdrape_tests` when `BUILD_TESTING=ON`

### Run the test suite

```bash
ctest --test-dir build -V
```

### Run only seam-related tests

Once seam tests exist, run them directly with a gtest filter:

```bash
./build/nextdrape_tests --gtest_filter='*Seam*'
```

If the seam tests are split into a dedicated test translation unit, add a narrower filter for the new test case names.

### Run the CLI smoke test

```bash
./build/nextdrape_cli --shape rect --out out/seam-smoke/
```

Use this as a quick regression check that the build is healthy before and after seam changes.

### Failure expectations

- Start with the smallest seam test subset first.
- Fix build or test failures before broadening to the full suite.
- If marching fails on a specific surface class, keep the fallback path enabled and capture diagnostics rather than weakening the test.

---

## Success criteria

- overlap geometry is generated by surface marching
- lap and scarf share the same geometry path
- property mapping is separated from geometry generation
- trimmed, curved, cornering, and multi-wire faces behave robustly
- tests cover planar, curved, corner, and hole cases

---

*Last updated: 2026-07-09*