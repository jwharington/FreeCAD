// CompositesDrape.cpp — nextdrape solver integrated with FreeCAD Part module.
//
// Uses the standard FreeCAD pattern (same as FemMeshPyImp.cpp):
//   static_cast<Part::TopoShapePy*>(pyobj)->getTopoShapePtr()->getShape()
//
// Zero conversion overhead — no BREP, no array marshalling, no dlsym hacks.

#include <Python.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

// FreeCAD Part module — provides TopoShapePy and TopoShape
#include <Mod/Part/App/TopoShapePy.h>
#include <Mod/Part/App/TopoShape.h>

// OpenCASCADE
#include <TopoDS_Shape.hxx>
#include <gp_Pnt.hxx>
#include <gp_Dir.hxx>

// nextdrape
#include <nextdrape/DrapeEngine.hpp>
#include <nextdrape/Types.hpp>
#include <nextdrape/Utilities.hpp>

namespace py = pybind11;

// ── Extract TopoDS_Shape from a Part.Shape PyObject* ───────────
// Standard FreeCAD pattern: the PyObject IS the TopoShapePy.
static TopoDS_Shape extract_topods_shape(PyObject* obj) {
    // Unwrap Part::Feature → .Shape if needed
    PyObject* shape_obj = obj;
    if (PyObject_HasAttrString(obj, "Shape")) {
        PyObject* attr = PyObject_GetAttrString(obj, "Shape");
        if (attr) {
            shape_obj = attr;
        }
    }

    // Verify it's a TopoShapePy (Part.Shape derivative)
    if (!PyObject_TypeCheck(shape_obj, &(Part::TopoShapePy::Type))) {
        throw std::runtime_error("Expected a Part.Shape object");
    }

    // Direct static_cast — the PyObject's memory IS the TopoShapePy
    Part::TopoShapePy* topo_py = static_cast<Part::TopoShapePy*>(shape_obj);
    Part::TopoShape* topo = topo_py->getTopoShapePtr();
    if (!topo) {
        throw std::runtime_error("TopoShape pointer is null");
    }

    return topo->getShape();
}

// ── Main solve function ────────────────────────────────────────
PYBIND11_MODULE(Composites_drape, m) {
    m.doc() = "Composites draping solver — nextdrape integrated with FreeCAD";

    m.def("solve", [](py::object shape_obj, py::dict seed_dict, py::dict params_dict) {
        TopoDS_Shape shape;
        try {
            shape = extract_topods_shape(shape_obj.ptr());
        } catch (const std::exception& e) {
            return py::dict(py::arg("success") = false,
                          py::arg("error") = std::string(e.what()));
        }

        nextdrape::DrapeParams params;
        if (params_dict.contains("pitch"))
            params.pitch = params_dict["pitch"].cast<double>();
        if (params_dict.contains("shear_warn_deg"))
            params.shearWarnDeg = params_dict["shear_warn_deg"].cast<double>();
        if (params_dict.contains("shear_fail_deg"))
            params.shearFailDeg = params_dict["shear_fail_deg"].cast<double>();
        if (params_dict.contains("projection_tol"))
            params.projectionTol = params_dict["projection_tol"].cast<double>();
        if (params_dict.contains("boundary_tol"))
            params.boundaryTol = params_dict["boundary_tol"].cast<double>();
        if (params_dict.contains("strain_fail"))
            params.strainFail = params_dict["strain_fail"].cast<double>();

        // === CUT-WIRE CONFIG ===
        params.cutWires.enabled = false;
        if (params_dict.contains("cut_wires_enabled"))
            params.cutWires.enabled = pybind11::cast<bool>(
                params_dict["cut_wires_enabled"]);
        if (params_dict.contains("cut_wires_proximity_tol"))
            params.cutWires.proximityTol =
                params_dict["cut_wires_proximity_tol"].cast<double>();
        if (params_dict.contains("cut_wires_block_nodes"))
            params.cutWires.blockNodesOnWire =
                pybind11::cast<bool>(
                    params_dict["cut_wires_block_nodes"]);
        if (params_dict.contains(
                "cut_wires_block_quads"))
            params.cutWires.blockQuadsCrossingWire =
                pybind11::cast<bool>(
                    params_dict["cut_wires_block_quads"]);

        nextdrape::SeedInput seed;
        if (seed_dict.contains("point")) {
            auto pt = seed_dict["point"].cast<py::tuple>();
            seed.point = gp_Pnt(pt[0].cast<double>(),
                               pt[1].cast<double>(),
                               pt[2].cast<double>());
        } else {
            seed.point = gp_Pnt(0, 0, 0);
        }
        if (seed_dict.contains("warp_direction")) {
            auto wd = seed_dict["warp_direction"].cast<py::tuple>();
            seed.warpDir3D = gp_Dir(wd[0].cast<double>(),
                                    wd[1].cast<double>(),
                                    wd[2].cast<double>());
        } else {
            seed.warpDir3D = gp_Dir(1, 0, 0);
        }

        nextdrape::DrapeEngine engine;
        nextdrape::DrapeResult result;
        try {
            result = engine.Compute(shape, seed, params);
        } catch (const std::exception& e) {
            return py::dict(py::arg("success") = false,
                          py::arg("error") = std::string(e.what()));
        }

        if (result.status != nextdrape::DrapeStatus::Ok) {
            std::string status_str = nextdrape::StatusToString(result.status);
            return py::dict(py::arg("success") = false,
                          py::arg("error") = std::string("Drape status: ") + status_str);
        }

        py::dict res;
        res["success"] = true;

        ssize_t n_nodes = static_cast<ssize_t>(result.nodes.size());
        py::array_t<double> node_pos({n_nodes, py::ssize_t(3)});
        auto np = node_pos.mutable_unchecked<2>();
        for (ssize_t i = 0; i < n_nodes; ++i) {
            np(i, 0) = result.nodes[i].p3d.X();
            np(i, 1) = result.nodes[i].p3d.Y();
            np(i, 2) = result.nodes[i].p3d.Z();
        }
        res["node_positions"] = node_pos;

        ssize_t n_flat = static_cast<ssize_t>(result.texturePlan.flatNodes.size());
        py::array_t<double> tex_coords({n_flat, py::ssize_t(2)});
        auto tc = tex_coords.mutable_unchecked<2>();
        for (ssize_t i = 0; i < n_flat; ++i) {
            tc(i, 0) = result.texturePlan.flatNodes[i].X();
            tc(i, 1) = result.texturePlan.flatNodes[i].Y();
        }
        res["tex_coords"] = tex_coords;

        py::list quad_list;
        for (const auto& q : result.texturePlan.quads) {
            py::list q_list;
            for (auto idx : q) q_list.append(static_cast<py::ssize_t>(idx));
            quad_list.append(q_list);
        }
        res["quads"] = quad_list;

        // Export strains only for the seed-connected quads (texturePlan.quads)
        // so they align with the mesh geometry.
        const auto& connected = nextdrape::SeedConnectedQuadIndices(result.quads);
        ssize_t n_mesh_quads = static_cast<ssize_t>(connected.size());
        py::array_t<double> warp_strain(n_mesh_quads);
        py::array_t<double> weft_strain(n_mesh_quads);
        py::array_t<double> shear_deg_arr(n_mesh_quads);
        auto ws = warp_strain.mutable_unchecked<1>();
        auto wf = weft_strain.mutable_unchecked<1>();
        auto sd = shear_deg_arr.mutable_unchecked<1>();
        for (ssize_t i = 0; i < n_mesh_quads; ++i) {
            const auto& q = result.quads[connected[static_cast<std::size_t>(i)]];
            ws(i) = q.warpStrain;
            wf(i) = q.weftStrain;
            sd(i) = q.shearDeg;
        }
        res["warp_strain"] = warp_strain;
        res["weft_strain"] = weft_strain;
        res["shear_angle"] = shear_deg_arr;

        py::list boundary_list;
        for (const auto& bl : result.texturePlan.boundaries) {
            py::list bl_list;
            for (const auto& pt : bl) {
                py::list pt_list;
                pt_list.append(pt.X());
                pt_list.append(pt.Y());
                bl_list.append(pt_list);
            }
            boundary_list.append(bl_list);
        }
        res["boundaries"] = boundary_list;

        py::dict diag;
        diag["status"] = static_cast<int>(result.status);
        diag["coverage_ratio"] = result.coverageRatio;
        diag["max_shear_deg"] = result.maxShearDeg;
        diag["max_strain"] = result.maxStrain;
        diag["solve_time_ms"] = result.solveTimeMs;
        diag["accepted_nodes"] = static_cast<int>(result.nodes.size());
        diag["total_nodes"] = static_cast<int>(result.nodes.size());
        res["diagnostics"] = diag;

        // Quality result — forward from C++ CheckQuality
        py::dict qual;
        qual["overall_pass"] = result.qualityResult.overallPass;
        py::list qual_failures;
        for (const auto& f : result.qualityResult.failures) {
            qual_failures.append(f);
        }
        qual["failures"] = qual_failures;
        res["quality"] = qual;

        // === CUT-WIRE DIAGNOSTICS ===
        py::dict cut_diag;
        cut_diag["nodes_blocked"] = result.cutWireDiagnostics.nodesBlocked;
        cut_diag["quads_blocked"] = result.cutWireDiagnostics.quadsBlocked;
        cut_diag["edges_crossing_wire"] = result.cutWireDiagnostics.edgesDetectedCrossing;
        py::list blocked_descs;
        for (const auto& desc : result.cutWireDiagnostics.blockedWireDescriptions) {
            blocked_descs.append(desc);
        }
        cut_diag["blocked_wire_descriptions"] = blocked_descs;
        res["cut_wire_diagnostics"] = cut_diag;

        return res;
    },
    py::arg("shape"), py::arg("seed"), py::arg("params") = py::dict(),
    "Run nextdrape solver on a FreeCAD Part.Shape — zero-copy TopoDS_Shape access.");
}
