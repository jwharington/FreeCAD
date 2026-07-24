# Non-Planar Parting Solver — Draft Architecture

**Status:** Draft. Not compiled, not wired into the build. Lays out the
architecture for the Phase 1 C++ marching-equator solver so it slots in
cleanly once nextdrape stabilises.

**Spec:** `docs/non-planar-parting-requirements.md`
**Plan:** `docs/non-planar-parting-implementation-plan.md` (Phase 1)
**Live interface (Phase 0, already merged):** `_propose_non_planar_parting`
stub + `PartingModel` FP property in `tools/mould_analysis.py` /
`features/MouldAnalysis.py`, with `TestNonPlanarPartingInterface` green.

## Files in this draft

| File | Role | Lands at (when wired) |
|---|---|---|
| `NonPlanarPartingSolver.hpp` | Solver class, result structs, status enum | `src/3rdParty/nextdrape/include/nextdrape/NonPlanarPartingSolver.hpp` |
| `NonPlanarPartingSolver.cpp` | Pipeline stages with OCCT call sites + TODO markers | `src/3rdParty/nextdrape/src/NonPlanarPartingSolver.cpp` |
| `CompositesParting.cpp` | pybind11 binding (mirrors `CompositesDrape.cpp`) | `src/Mod/Composites/App/CompositesParting.cpp` |
| `python_wiring.py` | Python `_propose_non_planar_parting` binding-call draft | body replaces the stub in `tools/mould_analysis.py` |
| `CMake-registration.txt` | The two CMake registration sites | appended to the real CMakeLists |

## Architecture

```
Python (tools/mould_analysis.py)
  _propose_non_planar_parting(shape, D, land, margin, footprint)
        │  py.dict
        ▼
CompositesParting.compute_non_planar_parting(shape, D, land, margin, fp)
        │  pybind11 (zero-copy TopoShapePy → TopoDS_Shape)
        ▼
nextdrape::NonPlanarPartingSolver::Solve(source, D, params)
        │  7-stage pipeline, each stage bool + sets status on failure
        ▼
PartingResult { partLine, upperShell, lowerShell, mouldHalfUpper/Lower,
                skirt, tangentFaceMidpoints, status, summary }
        │  BRepTools::Write → bytes → Python Part.readBytes
        ▼
Python result dict (Phase 0 contract) → _evaluate_split_strategy_attempt
        │
        ▼
validate_mould_result (WC authoritative) → verdict
```

## Conventions mirrored from the existing code

- **nextdrape solver shape:** single `Solve()` entry, results via const
  accessor (`Result()`), stateless apart from the result — matches
  `SeamOverlapSolver`.
- **FreeCAD binding:** zero-copy `extract_topods_shape` via
  `static_cast<Part::TopoShapePy*>`; BREP-serialize return — matches
  `CompositesDrape.cpp` / `extract_seam`.
- **Header layout:** `include/nextdrape/` + `src/` — matches nextdrape.
- **Result-dict contract:** superset of the live Phase 0 stub keys (adds the
  closed mould-half shapes; the stub leaves them `None`).

## Reusable nextdrape utilities (do NOT reimplement)

Studied the nextdrape headers; these already provide the BREP-traversal
plumbing the solver needs. The solver composes them rather than calling raw
OCCT for the same operations:

| Utility | Reused for |
|---|---|
| `SurfaceNavigator` | `ProjectPointOnShape`/`ProjectPointOnFace` (start point), `EvaluateFrame(face,uv,du,dv,normal)` (the `D1` eval behind `normal·D=0`), `IsInsideFace` (march boundary check), `DiscoverSharedEdges` (the cross-face handoff map, pre-computed once) |
| `SurfaceProjection` | `CrossFaceAdvance` (face-to-face handoff with chirality preservation), `GeodesicStep`/`CanAdvance` (on-surface stepping pattern) |
| `GeodesicStepper` | `ProjectTangentToUV` + `GeodesicRK4Step` — the template for the `(u,v)` integrator (adapted: the equator is a 1D zero-set trace of `N(u,v)·D=0`, not a free geodesic, but the UV-frame plumbing is identical) |
| `Types.hpp` | `FaceMapComparator` (face-keyed maps), `UvPnt2d` |

Not reused (different domain): the lattice/quad/drape layer
(`LatticeBuilder`, `QuadBuilder`, `ChebyshevNetSolver`, `DrapeEngine`, etc.).

## Pipeline stages (NonPlanarPartingSolver.cpp)

1. `buildLocalFrame` — `gp_Ax3` Z=D origin=bbox-center; transform source in.
2. `findStartPoint` — AABB-touch point; project to surface for (u,v).
3. `applyStartMidpointRule` — perpendicular-to-D start → z-midpoint (recurring).
4. `marchEquator` — `normal·D=0` clockwise from −Z; skirt rays; surface handoffs.
5. `buildPartLineSplines` — per-face `(u,v)` BSpline + 3D image.
6. `splitShells` — `BRepFeat_SplitShape::SplitByWire`; side-select +D/−D.
7. `buildSkirtAndCloseHalves` — sweep skirt, cap, cavity-cut, validity check.
8. `mapBackToOriginalFrame` — inverse transform on all result shapes.

## OCCT 8 APIs (verified via context7 / OCCTSwift, OCCT 8.0.0p1)

All four open verify items from the implementation plan are now resolved.
The draft's stage comments cite the verified API:

| # | Stage | Verified API |
|---|---|---|
| 1 | buildPartLineSplines | `GeomProjLib::Curve2d` (3D curve → on-surface pcurve, preferred) / `Geom2dAPI_PointsToBSpline` (least-squares through UV points, fallback) |
| 2 | splitShells | `BRepFeat_SplitShape::SplitByWire(wire, face)`; `LocOpe_Spliter` for batch. Wire must lie on face — the on-surface pcurve from #1 satisfies this. Partial-wire behaviour at face boundaries to confirm empirically on blade/loft bring-up. |
| 3 | buildSkirtAndCloseHalves | `BRepFill` ruled surface between two wires (`Shape.ruled(profile1, profile2)`); alt `bsplineFill(.coons)` |
| 4 | buildSkirtAndCloseHalves (Path 2) | `BRepOffsetAPI_MakeOffset` (planar wire offset, Path 1) / `projectOnSurface` + iso-curves (`bsplineUIso`/`VIso`) for on-surface extension (Path 2) |

## What is NOT here (deliberately)

- No algorithm bodies — each stage is a skeleton with verified OCCT call-site
  comments and a TODO. The marching integrator (stage 4) is the real research
  item; it's sketched (1D zero-set trace of `N(u,v)·D=0` with cross-face
  handoff via `SurfaceProjection::CrossFaceAdvance`) but not coded.
- No Phase 1 unit tests (the plan describes box/cylinder/cone/sphere; those
  land in nextdrape's test suite when the solver compiles).
- No Phase 2 acceptance tests (Python, skipped, flipping on when the binding
  lands — still to draft).
- No build integration — the draft stays in `_draft/` until nextdrape is
  stable, then moves to the locations in the table above.

## Coordination with the nextdrape agent (2026-07-25)

Heads-up sent and acknowledged (`/tmp/nextdrape-parting-solver-reply.md`).
Outcome:

- **Unblocked.** nextdrape's recent rip-out (`okish2`, `b64c32e`) was the
  lattice fallback chain + trim-clipping — none of the utilities I depend on
  were touched. `SurfaceNavigator`, `SurfaceProjection`, `GeodesicStepper`,
  `Types.hpp` are intact and stable; no `include/nextdrape/` reorg planned
  during their Phase 3.
- **Action item (mine): add a `CrossFaceAdvance` unit test.** The lattice
  fallback was its only integration caller; removing it left
  `SurfaceProjection::CrossFaceAdvance` with zero coverage. When I wire it
  into the equator march, I'll add a focused nextdrape-side unit test for the
  face-to-face handoff + chirality check (two adjacent faces of a known
  compound, advance across their shared edge, assert the target point/face
  + chirality). This is now part of the Phase 1 test list.
- **`SplitByWire` partial-wire behaviour:** unconfirmed (nextdrape never does
  shell splitting). Verify empirically on blade/loft bring-up as planned.
- **`IntersectWireLeg`** in `SurfaceNavigator`: the nextdrape agent may add/
  reuse it for their own wire-snapping ray-cast, keeping the signature
  backward-compatible. Watch for it — it could also serve the skirt-ray step
  (stage 4) if it lands before I code that stage.
