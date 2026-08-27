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
#include <vector>

// nextdrape
#include <nextdrape/partline/FaceSegment.hpp>
#include <nextdrape/partline/HLRPartingSolver.hpp>
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
           double part_line_tolerance, py::tuple footprint, bool part_line_only) {
            nextdrape::PartingParams params;
            params.stockMarginX = stock_margin_x;
            params.stockMarginY = stock_margin_y;
            params.stockMarginZ  = stock_margin_z;
            params.partLineToleranceMm = part_line_tolerance;
            if (py::len(footprint) >= 2) {
                params.stockFootprint.SetX(footprint[0].cast<double>());
                params.stockFootprint.SetY(footprint[1].cast<double>());
            }

            TopoDS_Shape source = extract_topods_shape(shape_obj.ptr());
            gp_Dir D(direction[0].cast<double>(),
                     direction[1].cast<double>(),
                     direction[2].cast<double>());

            nextdrape::HLRPartingSolver solver;
            const auto stopAt = part_line_only
                ? nextdrape::SolveStopStage::AfterPartLine
                : nextdrape::SolveStopStage::FullPipeline;
            bool ok = solver.Solve(source, D, params, stopAt);
            const auto& r = solver.Result();

            // Marshal tangent_face_midpoints: list of (face_shape, z_mid).
            py::list midpoints;
            for (const auto& tfm : r.tangentFaceMidpoints) {
                midpoints.append(py::make_tuple(
                    wrap_shape(tfm.face), tfm.zMidpoint));
            }

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

            return py::dict(
                py::arg("success")               = ok,
                py::arg("status")                = nextdrape::PartingStatusToString(r.status),
                py::arg("summary")               = r.summary,
                py::arg("part_line_3d")           = wrap_shape(nextdrape::BuildSegmentCurveCompound(
                    r.partLine, params.linearTolMm)),
                py::arg("part_line_segments")     = segments,
                py::arg("upper_shell")           = wrap_shape(r.upperShell),
                py::arg("lower_shell")           = wrap_shape(r.lowerShell),
                py::arg("mould_half_upper")      = wrap_shape(r.mouldHalfUpper),
                py::arg("mould_half_lower")      = wrap_shape(r.mouldHalfLower),
                py::arg("skirt")                 = wrap_shape(r.skirt),
                py::arg("tangent_face_midpoints") = midpoints
            );
        },
        py::arg("shape"), py::arg("draw_direction"),
        py::arg("stock_margin_x") = 5.0,
        py::arg("stock_margin_y") = 5.0,
        py::arg("stock_margin_z") = 5.0,
        py::arg("part_line_tolerance") = 0.1,
        py::arg("stock_footprint") = py::make_tuple(0.0, 0.0),
        py::arg("part_line_only") = false,
        "Compute a non-planar parting surface + mould halves for a FreeCAD "
        "Part.Shape along a user-specified draw direction. Returns a dict; "
        "success=True iff the pipeline reached `ready` (full mould) or the "
        "part line only (part_line_only=True, solver stops at AfterPartLine). "
        "stock_margin_x/y/z set the independent mould block margins. "
        "Shapes are returned as live Part.Shape objects directly.");
}
