// Composites_parting.cpp — pybind11 binding for the non-planar parting solver.
//
// Mirrors CompositesDrape.cpp's conventions:
//   - zero-copy TopoDS_Shape extraction via static_cast<Part::TopoShapePy*>
//   - BREP-serialize (BRepTools::Write) for returning shapes to Python
//   - a thin free function over a temporary solver instance
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
#include <BRepTools.hxx>
#include <TopoDS_Shape.hxx>
#include <gp_Dir.hxx>
#include <gp_XY.hxx>
#include <sstream>
#include <vector>

// nextdrape
#include <nextdrape/partline/FaceSegment.hpp>
#include <nextdrape/partline/NonPlanarPartingSolver.hpp>

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

// BREP-serialize a TopoDS_Shape back to Python as bytes. Python decodes via
// Part.read (temp file) — same pattern as CompositesDrape::extract_seam and
// tools/seam_extraction.py::_decode_brep.
static py::object wrap_shape(const TopoDS_Shape& occ_shape) {
    if (occ_shape.IsNull()) return py::none();
    std::ostringstream stream;
    BRepTools::Write(occ_shape, stream);
    return py::bytes(stream.str());
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
           double stock_margin_xy, double stock_margin_z,
           double part_line_sample_spacing, py::tuple footprint) {
            nextdrape::PartingParams params;
            params.stockMarginXY = stock_margin_xy;
            params.stockMarginZ  = stock_margin_z;
            params.partLineSampleSpacingMm = part_line_sample_spacing;
            if (py::len(footprint) >= 2) {
                params.stockFootprint.SetX(footprint[0].cast<double>());
                params.stockFootprint.SetY(footprint[1].cast<double>());
            }

            TopoDS_Shape source = extract_topods_shape(shape_obj.ptr());
            gp_Dir D(direction[0].cast<double>(),
                     direction[1].cast<double>(),
                     direction[2].cast<double>());

            nextdrape::NonPlanarPartingSolver solver;
            bool ok = solver.Solve(source, D, params);
            const auto& r = solver.Result();

            // Marshal tangent_face_midpoints: list of (face_brep_bytes, z_mid).
            py::list midpoints;
            for (const auto& tfm : r.tangentFaceMidpoints) {
                midpoints.append(py::make_tuple(
                    wrap_shape(tfm.face), tfm.zMidpoint));
            }

            // Marshal the UV chain directly: one dict per marched segment.
            py::list segments;
            for (const auto& segment : r.partLine) {
                const auto* faceSegment = dynamic_cast<const nextdrape::FaceSegment*>(segment.get());
                if (!faceSegment) continue;
                py::list uvSamples;
                for (const auto& sample : faceSegment->uvSamples()) {
                    uvSamples.append(py::make_tuple(sample.X(), sample.Y()));
                }
                segments.append(py::dict(
                    py::arg("face") = wrap_shape(faceSegment->face_),
                    py::arg("uv_samples") = uvSamples,
                    py::arg("points_3d") = wrap_points3d(faceSegment->points3d())
                ));
            }

            const py::object partLine3d = wrap_shape(r.partLine3d);
            const py::list partLineSegments = segments;
            return py::dict(
                py::arg("success")               = ok,
                py::arg("status")                = nextdrape::PartingStatusToString(r.status),
                py::arg("summary")               = r.summary,
                py::arg("part_line_3d")           = partLine3d,
                py::arg("part_line_segments")     = partLineSegments,
                py::arg("upper_shell")           = wrap_shape(r.upperShell),
                py::arg("lower_shell")           = wrap_shape(r.lowerShell),
                py::arg("mould_half_upper")      = wrap_shape(r.mouldHalfUpper),
                py::arg("mould_half_lower")      = wrap_shape(r.mouldHalfLower),
                py::arg("skirt")                 = wrap_shape(r.skirt),
                py::arg("tangent_face_midpoints") = midpoints
            );
        },
        py::arg("shape"), py::arg("draw_direction"),
        py::arg("stock_margin_xy") = 5.0,
        py::arg("stock_margin_z") = 5.0,
        py::arg("part_line_sample_spacing") = 0.5,
        py::arg("stock_footprint") = py::make_tuple(0.0, 0.0),
        "Compute a non-planar parting surface + mould halves for a FreeCAD "
        "Part.Shape along a user-specified draw direction. Returns a dict; "
        "success=True iff the mould halves are valid (status == ready). "
        "Shapes are returned as BREP bytes; decode via Part.read.");
}
