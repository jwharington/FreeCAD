// CompositesParting.cpp — pybind11 binding for the non-planar parting solver.
//
// DRAFT ARCHITECTURE — not yet compiled, not yet registered in CMakeLists.txt.
// Mirrors CompositesDrape.cpp's conventions:
//   - zero-copy TopoDS_Shape extraction via static_cast<Part::TopoShapePy*>
//   - BREP-serialize (BRepTools::Write) for returning shapes to Python
//   - a thin solve() free function over a temporary solver instance
//
// The Python side (_propose_non_planar_parting in mould_analysis.py) calls
// this binding's compute_non_planar_parting(), maps the result dict to the
// Phase 0 contract, and degrades to planar on any non-"ready" status.
//
// REGISTER: add to src/Mod/Composites/CMakeLists.txt alongside
// CompositesDrape.cpp. The PYBIND11_MODULE name is "CompositesParting"
// (importable as `import CompositesParting`), matching CompositesDrape.

#include <Python.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <Mod/Part/App/TopoShapePy.h>
#include <Mod/Part/App/TopoShape.h>

#include <BRepTools.hxx>
#include <TopoDS_Shape.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <sstream>

#include "NonPlanarPartingSolver.hpp"

namespace py = pybind11;

// Reuse the exact zero-copy extractor from CompositesDrape.cpp.
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

// BREP-serialize a TopoDS_Shape back to Python as bytes (Python decodes via
// Part.readBytes()). Same pattern as CompositesDrape::extract_seam.
static py::object wrap_shape(const TopoDS_Shape& shape) {
    if (shape.IsNull()) return py::none();
    std::ostringstream stream;
    BRepTools::Write(shape, stream);
    return py::bytes(stream.str());
}

PYBIND11_MODULE(CompositesParting, m) {
    m.doc() = "Non-planar marching-equator parting solver (nextdrape C++).";

    py::class_<nextdrape::PartingParams>(m, "PartingParams")
        .def(py::init<>())
        .def_readwrite("land_width",   &nextdrape::PartingParams::landWidth)
        .def_readwrite("stock_margin", &nextdrape::PartingParams::stockMargin)
        // stockFootprint (gp_XY) + tolerances exposed via property helpers
        // when the binding is wired (gp_XY ↔ (x,y) tuple).
        ;

    // The single entry point the Python side calls.
    m.def("compute_non_planar_parting",
        [](py::object shape_obj, py::tuple direction,
           double land_width, double stock_margin, py::tuple footprint) {
            nextdrape::PartingParams params;
            params.landWidth   = land_width;
            params.stockMargin  = stock_margin;
            // TODO: unpack footprint tuple → params.stockFootprint (gp_XY).

            TopoDS_Shape source = extract_topods_shape(shape_obj.ptr());
            gp_Dir D(direction[0].cast<double>(),
                     direction[1].cast<double>(),
                     direction[2].cast<double>());

            nextdrape::NonPlanarPartingSolver solver;
            bool ok = solver.Solve(source, D, params);
            const auto& r = solver.Result();

            return py::dict(
                py::arg("success")           = ok,
                py::arg("status")            = nextdrape::PartingStatusToString(r.status),
                py::arg("summary")           = r.summary,
                py::arg("part_line_3d")       = wrap_shape(r.partLine3d),
                py::arg("upper_shell")       = wrap_shape(r.upperShell),
                py::arg("lower_shell")       = wrap_shape(r.lowerShell),
                py::arg("mould_half_upper")  = wrap_shape(r.mouldHalfUpper),
                py::arg("mould_half_lower")  = wrap_shape(r.mouldHalfLower),
                py::arg("skirt")             = wrap_shape(r.skirt),
                // tangentFaceMidpoints → list of (face_brep_bytes, z_midpoint)
                // TODO: marshal when the diagnostics list is populated.
                py::arg("tangent_face_midpoints") = py::list()
            );
        },
        py::arg("shape"), py::arg("draw_direction"),
        py::arg("land_width") = 25.0, py::arg("stock_margin") = 0.1,
        py::arg("stock_footprint") = py::make_tuple(0.0, 0.0),
        "Compute a non-planar parting surface + mould halves for a FreeCAD "
        "Part.Shape along a user-specified draw direction. Returns a dict; "
        "success=True iff the mould halves are valid and releasable.");
}
