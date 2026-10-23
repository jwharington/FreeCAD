// Composites_parting.cpp — pybind11 binding for the non-planar parting solver.
//
// Mirrors CompositesDrape.cpp's conventions where possible, except that shapes
// are returned to Python directly as live Part.Shape objects (constructing a
// Part::TopoShapePy in C++) rather than as BREP bytes. This avoids the
// serialize-to-bytes / temp-file / Part.read round-trip entirely — both sides
// already speak OCCT, so the pybind boundary hands over the Python object.
//
// The Python side (_propose_non_planar_parting in tools/mould_analysis.py)
// calls compute_non_planar_parting(), maps the result dict to the Phase 0
// contract, and degrades to planar on any non-"ready" status.
//
// Module name: Composites_parting (importable as `import Composites_parting`),
// matching Composites_drape's underscore convention.

#include <Python.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

// FreeCAD Part module — provides TopoShapePy, TopoShape
#include <Mod/Part/App/TopoShapePy.h>
#include <Mod/Part/App/TopoShape.h>

// OpenCASCADE
#include <TopoDS_Shape.hxx>
#include <TopoDS_Compound.hxx>
#include <gp_Dir.hxx>
#include <gp_XY.hxx>
#include <stdexcept>
#include <string>
#include <vector>

// nextdrape
#include <nextdrape/partline/FaceSegment.hpp>
#include <nextdrape/partline/PartingSolver.hpp>
#include <nextdrape/mould/MouldHelper.hpp>

namespace py = pybind11;

// Standard FreeCAD pattern: the PyObject IS the TopoShapePy. Same extractor as
// CompositesDrape.cpp — unwrap Part::Feature -> .Shape if needed, then
// static_cast (zero copy).
static TopoDS_Shape extract_topods_shape(PyObject* obj) {
    PyObject* shape_obj = obj;
    if (PyObject_HasAttrString(obj, "Shape")) {
        PyObject* attr = PyObject_GetAttrString(obj, "Shape");
        if (attr) shape_obj = attr;
    }
    if (!PyObject_TypeCheck(shape_obj, &(Part::TopoShapePy::Type))) {
        throw std::runtime_error("Expected a Part.Shape object");
    }
    auto* topo_py = static_cast<Part::TopoShapePy*>(shape_obj);
    Part::TopoShape* topo = topo_py->getTopoShapePtr();
    if (!topo) throw std::runtime_error("TopoShape pointer is null");
    return topo->getShape();
}

// Hand a TopoDS_Shape to Python directly as a live Part.Shape object (None if
// empty). Builds the FreeCAD Python wrapper in C++ — the same object
// Py::asObject(new TopoShapePy(...)) produces — and transfers ONE owned
// reference to pybind. The PyCXX PythonExtensionBase starts at refcount 0, so
// the pointer must be bumped to 1 (_XINCREF, as Py::new_reference_to does)
// before reinterpret_steal hands ownership to Python. Without that increment
// the object is handed over at refcount 0 and the dict fill corrupts/frees it.
static py::object wrap_shape(const TopoDS_Shape& occ_shape) {
    if (occ_shape.IsNull()) return py::none();
    // `new` already yields refcount 1 (FreeCAD's Base::PyObjectBase
    // re-initializes it after PyCXX's base sets 0), so reinterpret_steal hands
    // that one owned reference to pybind directly. A manual incref here would
    // over-reference by 1 and free the object while Python still holds it.
    PyObject* obj = new Part::TopoShapePy(new Part::TopoShape(occ_shape));
    return py::reinterpret_steal<py::object>(obj);
}

static py::list wrap_points3d(const std::vector<gp_Pnt>& points) {
    py::list result;
    for (const auto& p : points) {
        result.append(py::make_tuple(p.X(), p.Y(), p.Z()));
    }
    return result;
}

PYBIND11_MODULE(Composites_parting, m) {
    m.doc() = "Non-planar marching-equator parting solver (nextdrape C++).";

    // The single entry point the Python side calls.
    m.def("compute_non_planar_parting",
        [](py::object shape_obj, py::tuple direction,
           double stock_margin_x, double stock_margin_y, double stock_margin_z,
           double part_line_tolerance, py::tuple footprint, bool part_line_only,
           bool run_withdrawal_clearance, const std::string& part_line_source,
           double tessellation_band_tol_deg,
           double tessellation_deflection,
           const std::string& skirt_levelling,
           const std::string& skirt_levelling_extent,
           double skirt_levelling_transition,
           double part_line_radius,
           double part_line_simplify_distance) {
            nextdrape::PartingParams params;
            params.stockMarginX = stock_margin_x;
            params.stockMarginY = stock_margin_y;
            params.stockMarginZ  = stock_margin_z;
            params.partLineToleranceMm = part_line_tolerance;
            // Part-line source (plan §10.3 B1). "tessellation" is the default:
            // HLR is kept only as the debugging reference, never the path a
            // caller falls into by not asking (a shape left on HLR gets the
            // HLR part line, however good the tessellation one is).
            if (part_line_source == "tessellation" || part_line_source == "tess") {
                params.partLineSource = nextdrape::PartLineSource::Tessellation;
            } else if (part_line_source == "hlr") {
                params.partLineSource = nextdrape::PartLineSource::Hlr;
            } else {
                throw std::runtime_error(
                    "part_line_source must be 'tessellation' or 'hlr', got: " +
                    part_line_source);
            }
            params.tessellationBandTolDeg = tessellation_band_tol_deg;
            // The scan deflection: nextdrape's own default when the caller
            // does not name one.
            params.tessellationDeflectionMm = tessellation_deflection;
            // Skirt outer-wall levelling (docs/spec-skirt-levelling.md). The
            // defaults are nextdrape's own, so a caller that does not ask gets
            // today's cast, and with it no level strip. A `fixed` extent is the
            // only one that produces a level surface to export.
            if (skirt_levelling == "off") {
                params.skirtLevelling = nextdrape::SkirtLevelling::Off;
            } else if (skirt_levelling == "direct") {
                params.skirtLevelling = nextdrape::SkirtLevelling::Direct;
            } else if (skirt_levelling == "s-curve" || skirt_levelling == "s_curve") {
                params.skirtLevelling = nextdrape::SkirtLevelling::SCurve;
            } else {
                throw std::runtime_error(
                    "skirt_levelling must be 'off', 'direct' or 's-curve', got: " +
                    skirt_levelling);
            }
            if (skirt_levelling_extent == "whole") {
                params.skirtLevellingExtent = nextdrape::SkirtLevellingExtent::Whole;
            } else if (skirt_levelling_extent == "fixed") {
                params.skirtLevellingExtent = nextdrape::SkirtLevellingExtent::Fixed;
            } else {
                throw std::runtime_error(
                    "skirt_levelling_extent must be 'whole' or 'fixed', got: " +
                    skirt_levelling_extent);
            }
            params.skirtLevellingTransitionMm = skirt_levelling_transition;
            // Rounding the skirt creases (ridge plan 12.11/12.12): the walked
            // part line's s-z profile is filleted at exactly this radius before
            // the split, so a crease is machined as a fillet rather than left
            // as a sharp step. Only the tessellation source walks a profile to
            // fillet, so it is inert on HLR; 0 leaves the part line alone.
            params.partLineRadiusMm = part_line_radius;
            // Douglas-Peucker simplification of the walked part line (ridge plan
            // 12.7). The simplified walk IS the cut, so the radius and the split
            // both run through it; 0/0 (default) leaves the walk as the mesh
            // placed it.
            params.partLineSimplifyDistanceMm = part_line_simplify_distance;
            // The incremental-withdrawal clearance scan is the most expensive
            // stage of the full pipeline and does NOT gate the mould halves
            // (they come from split/skirt/close). The caller decides whether
            // to pay for it; the default stays on so the verdict is unchanged.
            params.runWithdrawalClearance = run_withdrawal_clearance;
            if (py::len(footprint) >= 2) {
                params.stockFootprint.SetX(footprint[0].cast<double>());
                params.stockFootprint.SetY(footprint[1].cast<double>());
            }

            TopoDS_Shape source = extract_topods_shape(shape_obj.ptr());
            gp_Dir D(direction[0].cast<double>(),
                     direction[1].cast<double>(),
                     direction[2].cast<double>());

            // Source selected by `part_line_source` (default tessellation).
            auto solver = nextdrape::makePartingSolver(params);
            const auto stopAt = part_line_only
                ? nextdrape::SolveStopStage::AfterPartLine
                : nextdrape::SolveStopStage::FullPipeline;
            bool ok = solver->Solve(source, D, params, stopAt);
            const auto& r = solver->Result();
            // Marshal tangent_face_midpoints: list of (face_shape, z_mid).
            py::list midpoints;
            for (const auto& tfm : r.tangentFaceMidpoints) {
                midpoints.append(py::make_tuple(
                    wrap_shape(tfm.face), tfm.zMidpoint));
            }

            // Marshal the split faces: the cut pieces of each half with the
            // source face each was cut from (1-based, TopExp::MapShapes order =
            // FreeCAD's FaceN) and whether the part line failed to cut that
            // source face at its equator.
            const auto packSplitFaces = [](const std::vector<nextdrape::SplitFace>& pieces) {
                py::list packed;
                for (const auto& piece : pieces) {
                    packed.append(py::dict(
                        py::arg("face")              = wrap_shape(piece.face),
                        py::arg("source_face_index") = piece.sourceFaceIndex,
                        py::arg("straddles")         = piece.straddles));
                }
                return packed;
            };
            py::list upperSplitFaces = packSplitFaces(r.UpperSplitFaces());
            py::list lowerSplitFaces = packSplitFaces(r.LowerSplitFaces());

            // Derive the part-line 3D shape on demand from the canonical
            // segment chain (never a cached duplicate; partLine3d was removed).
            // Inlined in the dict so the returned shape's lifetime is owned by
            // the dict -> Python (a separate named local would be decref'd at
            // lambda exit, freeing the object the returned dict still holds).

            // Marshal the part line: one dict per marched segment. Every segment
            // kind is included (face-crossing FaceSegment and edge/silhouette
            // EdgeSegment), tagged by type, so the list is a uniform per-segment
            // contract across all shapes — not only the face segments.
            py::list segments;
            for (const auto& segment : r.partLine) {
                if (!segment) continue;
                py::list uvSamples;
                if (const auto* fs = dynamic_cast<const nextdrape::FaceSegment*>(segment.get())) {
                    for (const auto& sample : fs->uvSamples()) {
                        uvSamples.append(py::make_tuple(sample.X(), sample.Y()));
                    }
                    segments.append(py::dict(
                        py::arg("type") = "face",
                        py::arg("face") = wrap_shape(fs->face_),
                        py::arg("uv_samples") = uvSamples,
                        py::arg("points_3d") = wrap_points3d(fs->points3d())
                    ));
                } else {
                    // Edge segment (silhouette / boundary edge). No face UV:
                    // carry the 3D points and leave face/uv_samples unset.
                    segments.append(py::dict(
                        py::arg("type") = "edge",
                        py::arg("face") = py::none(),
                        py::arg("uv_samples") = uvSamples,
                        py::arg("points_3d") = wrap_points3d(segment->points3d())
                    ));
                }
            }

            // Marshal the native withdrawal-clearance result so the Python
            // layer can consume it instead of re-running the (Python) check.
            py::list wcHalfChecks;
            for (const auto& hc : r.withdrawalClearance.halfChecks) {
                wcHalfChecks.append(py::dict(
                    py::arg("half")            = hc.half,
                    py::arg("status")          = hc.status,
                    py::arg("sample_count")    = hc.sampleCount,
                    py::arg("clearance_steps") = hc.clearanceSteps,
                    py::arg("collision_volume")= hc.collisionVolume,
                    py::arg("failure_region")  = hc.failureRegion));
            }
            py::list wcFailureRegions;
            for (const auto& r_ : r.withdrawalClearance.failureRegions) {
                wcFailureRegions.append(r_);
            }
            py::dict withdrawalClearance = py::dict(
                py::arg("status")        = r.withdrawalClearance.status,
                py::arg("summary")       = r.withdrawalClearance.summary,
                py::arg("sample_count")  = r.withdrawalClearance.sampleCount,
                py::arg("failure_count") = r.withdrawalClearance.failureCount,
                py::arg("failure_regions") = wcFailureRegions,
                py::arg("half_checks")   = wcHalfChecks,
                py::arg("step_mm")       = r.withdrawalClearance.stepMm);

            // The level strips (spec A14): per wall, the inboard boundary of
            // the flat strip (`P_level_in`, at plan = t) and the wall base
            // (`P_out`). Points, station for station, so a consumer can pair
            // the two chains and close the ring across the walls. `present`
            // and `note` say why they are absent, rather than leaving an empty
            // list to be mistaken for a strip that is legitimately there.
            py::list levelStripWalls;
            for (const auto& wall : r.skirtLevelStrips.wall) {
                levelStripWalls.append(py::dict(
                    py::arg("wall")            = wall.wall,
                    py::arg("level_in_points") = wrap_points3d(wall.levelInPoint),
                    py::arg("outer_points")    = wrap_points3d(wall.outerPoint),
                    py::arg("level_in_edges")  = wall.levelInEdge.size(),
                    py::arg("outer_edges")     = wall.outerEdge.size()));
            }
            py::dict levelStrips = py::dict(
                py::arg("present") = r.skirtLevelStrips.present,
                py::arg("note")    = r.skirtLevelStrips.note,
                py::arg("walls")   = levelStripWalls);

            return py::dict(
                py::arg("success")               = ok,
                py::arg("status")                = nextdrape::PartingStatusToString(r.status),
                py::arg("summary")               = r.summary,
                py::arg("part_line_3d")           = wrap_shape(nextdrape::BuildSegmentCurveCompound(
                    r.partLine, params.linearTolMm)),
                py::arg("part_line_segments")     = segments,
                py::arg("upper_shell")           = wrap_shape(r.upperShell),
                py::arg("lower_shell")           = wrap_shape(r.lowerShell),
                py::arg("upper_split_faces")     = upperSplitFaces,
                py::arg("lower_split_faces")     = lowerSplitFaces,
                py::arg("mould_half_upper")      = wrap_shape(r.mouldHalfUpper),
                py::arg("mould_half_lower")      = wrap_shape(r.mouldHalfLower),
                py::arg("skirt")                 = wrap_shape(r.skirt),
                py::arg("withdrawal_clearance")  = withdrawalClearance,
                py::arg("tangent_face_midpoints") = midpoints,
                py::arg("part_line_source")       = part_line_source,
                py::arg("level_strips")           = levelStrips
            );
        },
        py::arg("shape"), py::arg("draw_direction"),
        py::arg("stock_margin_x") = 5.0,
        py::arg("stock_margin_y") = 5.0,
        py::arg("stock_margin_z") = 5.0,
        py::arg("part_line_tolerance") = 0.1,
        py::arg("stock_footprint") = py::make_tuple(0.0, 0.0),
        py::arg("part_line_only") = false,
        py::arg("run_withdrawal_clearance") = false,
        py::arg("part_line_source") = "tessellation",
        py::arg("tessellation_band_tol_deg") = 2.0,
        py::arg("tessellation_deflection") = 0.05,
        py::arg("skirt_levelling") = "off",
        py::arg("skirt_levelling_extent") = "whole",
        py::arg("skirt_levelling_transition") = 1.0,
        py::arg("part_line_radius") = 0.0,
        py::arg("part_line_simplify_distance") = 0.0,
        "Compute a non-planar parting surface + mould halves for a FreeCAD "
        "Part.Shape along a user-specified draw direction. Returns a dict; "
        "success=True iff the pipeline reached `ready` (full mould) or the "
        "part line only (part_line_only=True, solver stops at AfterPartLine). "
        "stock_margin_x/y/z set the independent mould block margins. "
        "part_line_source selects the part-line solver: 'tessellation' "
        "(default, the drafted-path solver) or 'hlr' (the projected-outline "
        "debugging reference). tessellation_band_tol_deg is the equator-band "
        "half-width the tessellation source treats as the veil: faces within "
        "it carry no draft opinion and the part line may cross them anywhere. "
        "It must be at least the shallowest face's |n.d| that the part line "
        "has to cross, and as small as possible, since every face inside it "
        "loses its own opinion. "
        "part_line_radius fillets the walked part line's s-z profile at that "
        "radius before the split, rounding the skirt creases (ridge plan "
        "12.11/12.12); 0 (default) leaves the part line alone, and it is inert "
        "on the HLR source, which walks no profile. "
        "part_line_simplify_distance applies Douglas-Peucker to the walked part "
        "line before the split (ridge plan 12.7): a node survives when its span's "
        "worst chord deviation exceeds that distance, at a carrier junction, or "
        "when it is alone on its face. 0 (default) = off. "
        "Skirt levelling (docs/spec-skirt-levelling.md) shapes the skirt's "
        "outer wall: 'off' (default), 'direct' or 's-curve'. Only a 'fixed' "
        "extent, whose transition spans the first skirt_levelling_transition "
        "mm outboard of the cutline and then holds the outer z flat, produces "
        "a level strip, exported as level_strips: {present, note, "
        "walls:[{wall, level_in_points, outer_points, level_in_edges, "
        "outer_edges}]}. 'off' and 'whole' export nothing and say so in the "
        "note, since neither has a level surface for the strip to bound. "
        "Shapes are returned as live Part.Shape objects directly.");
}
