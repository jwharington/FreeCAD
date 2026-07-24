// NonPlanarPartingSolver.cpp — marching-equator parting solver implementation.
//
// DRAFT ARCHITECTURE — not yet compiled. Each pipeline stage is laid out
// with its OCCT call sites and TODO markers at the four verify-items from the
// implementation plan (§1.3). The structure mirrors SeamOverlapSolver.cpp:
// a single Solve() driving private stage methods, results on the instance.
//
// CONVENTIONS (match nextdrape):
//   - OCCT headers fully qualified (<BRepBuilderAPI_Transform.hxx> etc.)
//   - one stage per private method, each returns bool + sets status on failure
//   - diagnostics accumulate on m_result so a failed march still explains why

#include "NonPlanarPartingSolver.hpp"
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepFeat_SplitShape.hxx>
#include <BRep_Tool.hxx>
#include <GeomProjLib.hxx>                    // Curve2d: 3D->on-surface pcurve (preferred, verified OCCT 8)
#include <Geom2dAPI_PointsToBSpline.hxx>     // fallback: least-squares 2D BSpline through UV points (verified OCCT 8)
#include <BRepFill.hxx>                      // ruled surface between two wires (skirt; verified OCCT 8)
#include <BRepOffsetAPI_MakeOffset.hxx>     // planar wire offset (Path 1 outset; verified OCCT 8)
#include <gp_Ax3.hxx>
#include <gp_Trsf.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>
#include <gp_Dir.hxx>
#include <Bnd_Box.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <map>
#include <cmath>

namespace nextdrape {

std::string PartingStatusToString(PartingStatus status) {
    switch (status) {
        case PartingStatus::Ready:             return "ready";
        case PartingStatus::NotImplemented:    return "not_implemented";
        case PartingStatus::NoBboxTouchPoint:   return "no_bbox_touch_point";
        case PartingStatus::ForkDegenerate:     return "fork_degenerate";
        case PartingStatus::MarchDidNotClose:   return "march_did_not_close";
        case PartingStatus::SplitFailed:        return "split_failed";
        case PartingStatus::InvalidSolidResult: return "invalid_solid_result";
    }
    return "unknown";
}

// ── public entry point ───────────────────────────────────────────────────

NonPlanarPartingSolver::NonPlanarPartingSolver()
    : m_projection(m_navigator) {}

bool NonPlanarPartingSolver::Solve(const TopoDS_Shape& source,
                                   const gp_Dir&       drawDirection,
                                   const PartingParams& params) {
    m_result = {};  // fresh per Solve

    if (source.IsNull()) {
        m_result.status = PartingStatus::NotImplemented;
        m_result.summary = "null source shape";
        return false;
    }

    m_params = params;
    m_drawDirection = drawDirection;

    // Pipeline. Each stage sets status/summary on failure and returns false.
    if (!buildLocalFrame(source, drawDirection))         return false;
    if (!findStartPoint())                               return false;
    if (!applyStartMidpointRule())                       return false;
    if (!marchEquator())                                 return false;
    if (!buildPartLineSplines())                         return false;
    if (!splitShells())                                  return false;
    if (!buildSkirtAndCloseHalves())                     return false;
    if (!mapBackToOriginalFrame())                       return false;

    m_result.status = PartingStatus::Ready;
    m_result.summary = "non-planar parting constructed";
    return true;
}

// ── stage 1: local frame ─────────────────────────────────────────────────
// gp_Ax3 with Z = D, origin at bbox center. Transform the source into this
// frame; keep the inverse to map results back at the end.

bool NonPlanarPartingSolver::buildLocalFrame(const TopoDS_Shape& source,
                                             const gp_Dir&       D) {
    // bbox of the original shape → origin at its centre.
    Bnd_Box bbox;
    BRepBndLib::Add(source, bbox);
    if (bbox.IsVoid()) {
        m_result.status = PartingStatus::NoBboxTouchPoint;
        m_result.summary = "buildLocalFrame: source has no bounding box";
        return false;
    }
    const gp_Pnt centre((bbox.CornerMin().X() + bbox.CornerMax().X()) / 2.0,
                        (bbox.CornerMin().Y() + bbox.CornerMax().Y()) / 2.0,
                        (bbox.CornerMin().Z() + bbox.CornerMax().Z()) / 2.0);

    // gp_Ax3 with Z = D, origin at centre. OCCT picks X deterministically
    // (createFromNormal); if global X ∥ D it falls back to Y.
    m_localFrame = gp_Ax3(centre, D);

    // forward: original → local; inverse: local → original.
    m_forwardTrsf.SetTransformation(m_localFrame, gp_Ax3());
    m_inverseTrsf = m_forwardTrsf.Inverted();

    BRepBuilderAPI_Transform xform(source, m_forwardTrsf, /*Copy=*/true);
    m_localShape = xform.Shape();

    // local AABB of the transformed shape (NOT the OBB).
    BRepBndLib::Add(m_localShape, m_localBbox);

    // Pre-compute the shared-edge map once; the march hands off across faces
    // via this map (SurfaceNavigator::DiscoverSharedEdges).
    m_navigator.DiscoverSharedEdges(m_localShape, m_sharedEdges);
    return true;
}

// ── stage 2: start point ────────────────────────────────────────────────
// Pick a point where the body touches the local AABB (a vertex on an extreme
// x/y face, chosen deterministically). Project to its surface for (u,v).

bool NonPlanarPartingSolver::findStartPoint() {
    // Pick a vertex on an extreme x/y face of the local AABB (deterministic:
    // first such vertex in TopExp_Explorer order).
    TopExp_Explorer ex(m_localShape, TopAbs_VERTEX);
    for (; ex.More(); ex.Next()) {
        const gp_Pnt p = BRep_Tool::Pnt(TopoDS::Vertex(ex.Current()));
        if (std::abs(p.X() - m_localBbox.CornerMin().X()) < 1e-6 ||
            std::abs(p.X() - m_localBbox.CornerMax().X()) < 1e-6 ||
            std::abs(p.Y() - m_localBbox.CornerMin().Y()) < 1e-6 ||
            std::abs(p.Y() - m_localBbox.CornerMax().Y()) < 1e-6) {
            m_startPoint3d = p;
            // Project onto the owning face for (u,v). Reuse SurfaceNavigator.
            if (!m_navigator.ProjectPointOnShape(m_localShape, p, /*tol=*/1e-4,
                                                 m_startFace, m_startUV, /*proj=*/p)) {
                m_result.status = PartingStatus::NoBboxTouchPoint;
                m_result.summary = "findStartPoint: start point did not project onto a face";
                return false;
            }
            return true;
        }
    }
    m_result.status = PartingStatus::NoBboxTouchPoint;
    m_result.summary = "findStartPoint: no vertex touches an x/y AABB extreme";
    return false;
}

// ── stage 3a: start z-midpoint rule ─────────────────────────────────────
// If the start face is perpendicular to D (normal ∥ D), the equator is
// ambiguous there. Scan ±Z to find z_max/z_min; start z = their midpoint.
// This is the recurring rule — factored here, re-entered from the march.

bool NonPlanarPartingSolver::applyStartMidpointRule() {
    // If the start face is perpendicular to D (normal ∥ D), the equator is
    // ambiguous there → scan ±Z for z_max/z_min, set z = midpoint.
    gp_Vec du, dv; gp_Dir normal;
    if (!m_navigator.EvaluateFrame(m_startFace, m_startUV, du, dv, normal)) {
        m_result.status = PartingStatus::NotImplemented;
        m_result.summary = "applyStartMidpointRule: frame evaluation failed at start";
        return false;
    }
    const double align = std::abs(normal.Dot(m_drawDirection));
    if (align > 1.0 - m_params.angularTolDeg * M_PI / 180.0) {
        // perpendicular face → recurring midpoint rule.
        // TODO: intersectLine(start, ±D) → z_max, z_min; zMid = (z_max+z_min)/2.
        //   Record TangentFaceMidpoint{m_startFace, zMid}.
        // (intersectLine is the BRepIntCurveSurface-style OCCT call; reused
        //  via the navigator or a direct IntCurvesFace_Inter object.)
    }
    return true;
}

// ── stage 3b: equator march ─────────────────────────────────────────────
// The core. Trace normal·D = 0 clockwise (viewed from -Z) across face
// boundaries, in each face's (u,v). At each step: surface-normal ray → skirt.
// Re-enter the midpoint rule on any tangent-surface degenerate range.

bool NonPlanarPartingSolver::marchEquator() {
    // The core: trace normal·D = 0 clockwise (viewed from -Z) across face
    // boundaries, in each face's (u,v).
    //
    // REUSED nextdrape machinery:
    //  - SurfaceNavigator::EvaluateFrame(face, uv, du, dv, normal) for N(u,v)
    //    (the D1 evaluation underlying normal·D=0).
    //  - SurfaceNavigator::IsInsideFace(face, uv, tol) for the boundary check.
    //  - SurfaceNavigator::DiscoverSharedEdges map (pre-computed) +
    //    SurfaceProjection::CrossFaceAdvance for face-to-face handoff with
    //    chirality preservation.
    //  - GeodesicStepper::ProjectTangentToUV + GeodesicRK4Step as the
    //    template for the (u,v) integrator (adapted: the equator is a 1D
    //    implicit curve N(u,v)·D = 0, not a free geodesic, so the step is a
    //    zero-set trace, not RK4 along an arbitrary tangent — but the
    //    UV-frame plumbing is identical).
    //
    // TODO: contour-following integrator on the 1D zero-set of N(u,v)·m_drawDirection in
    //   the current face's (u,v). Step in (u,v) along the zero-set; record
    //   (u,v) + 3D point (navigator.EvaluatePoint). At each step, shoot the
    //   skirt ray along the surface normal to the block boundary.
    // TODO: recurring midpoint rule — re-entered when a face satisfies
    //   normal·D = 0 over a z-range (detected during the march).
    // TODO: closure (return to start within params_.linearTolMm) or fork /
    //   no-close → ForkDegenerate / MarchDidNotClose.
    // TODO: recurring midpoint rule — re-entered when a face satisfies
    //   normal·m_drawDirection = 0 over a z-range (detected during the march).
    // TODO: closure (return to start within m_params.linearTolMm) or fork /
    //   no-close → ForkDegenerate / MarchDidNotClose.
    m_result.status = PartingStatus::NotImplemented;
    m_result.summary = "marchEquator: contour integrator not yet implemented (the real research item)";
    return false;
}

// ── stage 4: part line as (u,v) splines ────────────────────────────────
// Per traversed face, fit a Geom2d_BSplineCurve through the marched (u,v)
// samples. Build the 3D image compound for visualisation.

bool NonPlanarPartingSolver::buildPartLineSplines() {
    // Per traversed face, build the (u,v) part-line spline.
    //
    // PREFERRED: GeomProjLib::Curve2d — project the marched 3D curve onto
    //   the face's surface → a native on-surface pcurve (exactly the form
    //   BRepFeat_SplitShape::SplitByWire consumes). Verified on OCCT 8.
    //
    // FALLBACK: Geom2dAPI_PointsToBSpline — least-squares fit a 2D BSpline
    //   through the marched (u,v) samples (does not pass through every
    //   point; smoother for noisy marches). Verified on OCCT 8.
    //
    // TODO: for each face in march order, build its 3D curve from points3d,
    //   attempt GeomProjLib::Curve2d; on failure fall back to
    //   Geom2dAPI_PointsToBSpline over the (u,v) samples. Append a
    //   PartLineSegment{face, uvCurve, points3d, uvSamples} to m_result.partLine.
    // TODO: assemble partLine3d as a TopoDS_Compound of the 3D edges.
    m_result.status = PartingStatus::NotImplemented;
    m_result.summary = "buildPartLineSplines: spline fit not yet implemented";
    return false;
}

// ── stage 5: exact shell split ─────────────────────────────────────────
// Split each source face along its (u,v) part-line spline, keep the +D / -D
// sub-faces, assemble upper/lower shells.

bool NonPlanarPartingSolver::splitShells() {
    // Split each source face along its (u,v) part-line spline.
    //
    // BRepFeat_SplitShape::SplitByWire(wire, face) — verified on OCCT 8.
    //   The wire must lie on the face; the on-surface pcurve from
    //   GeomProjLib::Curve2d (buildPartLineSplines) satisfies this directly.
    //   Batch alternative: LocOpe_Spliter / locOpeSplit(wiresOnFaces:) for
    //   splitting many faces in one call.
    //
    // Partial-wire edge case (wire only partially on the face, at face
    // boundaries): not explicitly documented — confirm empirically on the
    // freeform blade/loft fixtures during Phase 1 bring-up. If SplitByWire
    // rejects partial wires, trim the part-line wire to the face boundary
    // first (it already is, by construction — the march hands off at edges).
    //
    // Side selection: keep the +D / -D sub-face by centroid side, or via
    //   BRepBuilderAPI_MakeFace(surface, wire, inside:) .
    //
    // TODO: for each PartLineSegment, build a wire from uvCurve, split its
    //   face, select the +D/-D sub-faces, assemble upperShell / lowerShell.
    // Failure → SplitFailed.
    m_result.status = PartingStatus::SplitFailed;
    m_result.summary = "splitShells: BRepFeat_SplitShape wiring not yet implemented";
    return false;
}

// ── stage 6: skirt + closure ───────────────────────────────────────────
// Sweep the skirt surface from the retained normal rays; cap with the
// rectangular block faces; cut the source cavity; form valid solids.

bool NonPlanarPartingSolver::buildSkirtAndCloseHalves() {
    // Skirt: ruled surface between the part line (inner wire) and the
    //   block-boundary outer wire. Verified on OCCT 8: the ruled-surface
    //   builder between two wires is `Shape.ruled(profile1, profile2)` /
    //   `BRepFill::face` (OCCT C++: BRepFill or GeomFill::Bezier ruled).
    //   Alt: Surface.bsplineFill(curve1, curve2, .coons) for a smoother fill.
    //
    // Per-face boundary extension to the block edge (Path 2 step 4):
    //   planar case → Shape.offsetWire / multiOffsetWires (BRepOffsetAPI_
    //   MakeOffset, planar-only — that's why Path 1 projects to ⊥D first).
    //   On-surface case → projectOnSurface + iso-curves (bsplineUIso/VIso).
    //
    // TODO: build the outer block-boundary wire (local AABB ± margin in ⊥D).
    // TODO: ruled surface between part line + outer wire → skirt.
    // TODO: cap with the rectangular block faces; cut the source cavity.
    // TODO: assert each result .IsValid() and is a Solid; else InvalidSolidResult.
    m_result.status = PartingStatus::InvalidSolidResult;
    m_result.summary = "buildSkirtAndCloseHalves: skirt + closure not yet implemented";
    return false;
}

// ── stage 7: map back ──────────────────────────────────────────────────
// Apply the inverse transform to all result shapes so they're in the
// original frame.

bool NonPlanarPartingSolver::mapBackToOriginalFrame() {
    // Apply m_inverseTrsf to every result shape so they return in the
    //   original frame. The PartLineSegment uvCurve is parametric on its
    //   (transformed) face — the face is also remapped, so the pcurve is
    //   unchanged; points3d remap with the shape.
    // TODO: BRepBuilderAPI_Transform with m_inverseTrsf on partLine3d,
    //   upperShell, lowerShell, mouldHalfUpper, mouldHalfLower, skirt.
    m_result.status = PartingStatus::NotImplemented;
    m_result.summary = "mapBackToOriginalFrame: inverse transform not yet applied";
    return false;
}

} // namespace nextdrape
