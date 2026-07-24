// NonPlanarPartingSolver.hpp — marching-equator parting-surface + mould-half solver.
//
// DRAFT ARCHITECTURE — not yet compiled, not yet wired into the build.
// Lays out the class structure and OCCT call sites for the non-planar parting
// solver specified in docs/non-planar-parting-requirements.md and phased in
// docs/non-planar-parting-implementation-plan.md (Phase 1).
//
// The solver lives in nextdrape (direct OCCT BREP traversal is too slow in
// Python). This header mirrors the nextdrape convention: a single solver
// class that takes TopoDS_Shape inputs and exposes result accessors, like
// SeamOverlapSolver. The FreeCAD pybind binding (CompositesParting.cpp) wraps
// it with the same zero-copy TopoShapePy pattern as CompositesDrape.cpp.
//
// ALGORITHM (see the requirements doc for full detail):
//   1. Local frame: gp_Ax3 with Z = draw direction D, origin at bbox center.
//   2. Start point: a point where the body touches the local AABB; if its
//      surface is perpendicular to D, apply the z-midpoint rule.
//   3. Equator march: trace normal·D = 0 clockwise (viewed from -Z) across
//      surface boundaries, in each face's (u,v) space. At each point shoot a
//      surface-normal ray to the block boundary (the skirt). The recurring
//      z-midpoint rule fires on any tangent-surface degenerate range.
//   4. Output: part line as per-surface (u,v) spline chain; the source split
//      exactly along that line into upper/lower shells; skirt + block caps
//      closing each half into a valid solid.
//
// reflectLines / Contap_Contour are deliberately NOT used (unreliable on
// freeforms — documented in the investigation). The part line is marched.

#pragma once

#include <string>
#include <utility>
#include <vector>

#include <TopoDS_Compound.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Solid.hxx>
#include <Geom2d_Curve.hxx>
#include <gp_Ax3.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
#include <gp_XY.hxx>
#include <gp_Pnt2d.hxx>
#include <Bnd_Box.hxx>

#include "nextdrape/SurfaceNavigator.hpp"
#include "nextdrape/SurfaceProjection.hpp"
#include "nextdrape/Types.hpp"  // FaceMapComparator, UvPnt2d

namespace nextdrape {

/// Solver status. "ready" is the only success value; everything else is a
/// recoverable error that the Python side degrades to planar on.
enum class PartingStatus {
    Ready,
    NotImplemented,        // stub / pre-Phase-1
    NoBboxTouchPoint,      // step 2: no deterministic start point found
    ForkDegenerate,        // step 3: the equator forks — invalid mould
    MarchDidNotClose,      // step 3: failed to return to start within tol
    SplitFailed,           // step 6: BRepFeat_SplitShape could not split
    InvalidSolidResult     // step 7: a mould half is not a valid solid
};

std::string PartingStatusToString(PartingStatus status);

/// Inputs to the non-planar parting solver. Mirrors the Phase 0 Python
/// contract in analyse_source_shape (parting_land_width, parting_stock_margin,
/// parting_stock_footprint). The footprint override is (0,0) ⇒ auto.
struct PartingParams {
    double landWidth{25.0};        // minimum skirt projection (mm)
    double stockMargin{0.1};      // auto block margin (fraction of bbox)
    gp_XY  stockFootprint{0, 0};   // explicit block (dx,dy) override; (0,0)=auto
    double angularTolDeg{1.0};     // normal·D == 0 march tolerance
    double linearTolMm{1.0e-4};    // closure / projection tolerance (mm)
};

/// A per-surface segment of the part line: the face it lies on and the
/// (u,v) spline chain traced in that face's parametric space.
struct PartLineSegment {
    TopoDS_Face                          face;
    Handle(Geom2d_Curve)                 uvCurve;     // the on-surface pcurve
    std::vector<gp_Pnt>                  points3d;    // 3D image, for diagnostics
    std::vector<std::pair<double,double>> uvSamples;  // raw marched (u,v) samples
};

/// Diagnostics for a tangent-surface degenerate face: a face where normal·D
/// holds over a z-range, and the z-midpoint chosen as the part-line location.
struct TangentFaceMidpoint {
    TopoDS_Face face;
    double      zMidpoint;
};

/// Output of the non-planar parting solver. The Python binding maps this to
/// the result-dict shape consumed by _propose_non_planar_parting.
struct PartingResult {
    // (a) the part line
    std::vector<PartLineSegment>      partLine;          // per-face chain, in march order
    TopoDS_Compound                  partLine3d;        // 3D image, for visualisation

    // (b) the split base geometry
    TopoDS_Shape                     upperShell;        // +D side faces
    TopoDS_Shape                     lowerShell;        // -D side faces

    // (c) the closed mould halves
    TopoDS_Solid                     mouldHalfUpper;    // upperShell + skirt + cap, cavity cut
    TopoDS_Solid                     mouldHalfLower;

    // (d) the skirt (surface-normal rays to the block boundary)
    TopoDS_Shape                     skirt;

    // (e) diagnostics
    std::vector<TangentFaceMidpoint> tangentFaceMidpoints;
    PartingStatus                    status{PartingStatus::NotImplemented};
    std::string                      summary;
};

/// The solver. Single Solve() entry point; results via accessors, mirroring
/// SeamOverlapSolver. Stateless apart from the result (one Solve per instance,
/// like SeamOverlapSolver).
class NonPlanarPartingSolver {
public:
    NonPlanarPartingSolver() = default;

    /// Run the marching-equator parting construction.
    /// Returns true iff status == Ready (a usable mould half pair).
    /// On any non-Ready status the result is still populated with diagnostics
    /// (partLine so far, tangentFaceMidpoints, status/summary) so the Python
    /// side can surface the failure reason.
    bool Solve(const TopoDS_Shape& source,
               const gp_Dir&       drawDirection,
               const PartingParams& params);

    const PartingResult& Result() const { return m_result; }

private:
    PartingResult m_result;

    // ── reusable nextdrape utilities (composition, not inheritance) ──
    // SurfaceNavigator is the BREP-traversal core (project, evaluate frame,
    // discover shared edges, inside-face test). SurfaceProjection adds
    // cross-face advance + on-surface stepping. Both already exist in
    // nextdrape; the solver reuses them rather than calling raw OCCT.
    SurfaceNavigator m_navigator;
    SurfaceProjection m_projection;

    // ── internal pipeline stages (implementation in the .cpp) ──
    // Each stage returns false and sets m_result.status/summary on failure.

    bool buildLocalFrame(const TopoDS_Shape& source, const gp_Dir& D);
    bool findStartPoint();
    bool applyStartMidpointRule();
    bool marchEquator();
    bool buildPartLineSplines();
    bool splitShells();
    bool buildSkirtAndCloseHalves();
    bool mapBackToOriginalFrame();

    // ── local-frame state (set by buildLocalFrame, consumed by the rest) ──
    TopoDS_Shape m_localShape;          // source transformed into the D frame
    gp_Ax3       m_localFrame;          // Z = D, origin = bbox center
    gp_Trsf      m_forwardTrsf;         // original → local
    gp_Trsf      m_inverseTrsf;         // local → original
    Bnd_Box      m_localBbox;           // AABB of m_localShape

    // shared-edge map: sourceFace → [{neighborFace, sharedEdge3DMidpoint}]
    std::map<TopoDS_Face, std::vector<std::pair<TopoDS_Face, gp_Pnt>>,
             FaceMapComparator> m_sharedEdges;

    // march state (set by findStartPoint / marchEquator)
    TopoDS_Face m_startFace;
    gp_Pnt2d    m_startUV;
    gp_Pnt      m_startPoint3d;

    // solve inputs (stored by Solve for the stage methods)
    PartingParams m_params;
    gp_Dir       m_drawDirection;
};

} // namespace nextdrape
