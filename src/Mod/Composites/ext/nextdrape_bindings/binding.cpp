// binding.cpp — nextdrape pybind11 binding for FreeCAD Composites WB.
// Compatible with nextdrape master (post-API-change).

#include <Python.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

// OpenCASCADE
#include <opencascade/TopoDS_Shape.hxx>
#include <opencascade/TopoDS_Face.hxx>
#include <opencascade/TopExp.hxx>
#include <opencascade/TopExp_Explorer.hxx>
#include <opencascade/BRep_Tool.hxx>
#include <opencascade/BRepAdaptor_Surface.hxx>
#include <opencascade/gp_Pnt.hxx>
#include <opencascade/gp_Vec.hxx>
#include <opencascade/gp_Dir.hxx>
#include <opencascade/GeomPlate_BuildPlateSurface.hxx>
#include <opencascade/Standard_TypeDef.hxx>

// nextdrape
#include <nextdrape/DrapeEngine.hpp>
#include <nextdrape/Types.hpp>

// Eigen
#include <Eigen/Dense>

// Local bridge — minimal PyCXX declarations
#include "freecad_bridge.h"

namespace py = pybind11;

// ── Main solve function ──
py::dict solve(py::object shape_obj,
               py::dict seed_dict,
               py::dict params_dict = py::dict()) {
    
    TopoDS_Shape* shape = extract_topods_shape(shape_obj.ptr());
    if (!shape) {
        return py::dict(py::arg("success") = false, py::arg("error") = "Failed to extract TopoDS_Shape");
    }
    
    // Build SeedInput
    nextdrape::SeedInput seed;
    if (seed_dict.contains("point")) {
        auto pt = seed_dict["point"].cast<py::tuple>();
        seed.point = gp_Pnt(pt[0].cast<double>(), pt[1].cast<double>(), pt[2].cast<double>());
    }
    if (seed_dict.contains("warp_dir")) {
        auto wd = seed_dict["warp_dir"].cast<py::tuple>();
        seed.warpDir3D = gp_Dir(wd[0].cast<double>(), wd[1].cast<double>(), wd[2].cast<double>());
    }
    
    // Build DrapeParams
    nextdrape::DrapeParams params;
    if (params_dict.contains("pitch"))
        params.pitch = params_dict["pitch"].cast<double>();
    if (params_dict.contains("max_warp_steps"))
        params.maxWarpSteps = params_dict["max_warp_steps"].cast<int>();
    if (params_dict.contains("max_weft_steps"))
        params.maxWeftSteps = params_dict["max_weft_steps"].cast<int>();
    if (params_dict.contains("shear_warn_deg"))
        params.shearWarnDeg = params_dict["shear_warn_deg"].cast<double>();
    if (params_dict.contains("shear_fail_deg"))
        params.shearFailDeg = params_dict["shear_fail_deg"].cast<double>();
    if (params_dict.contains("shear_gate_deg"))
        params.shearGateDeg = params_dict["shear_gate_deg"].cast<double>();
    if (params_dict.contains("strain_fail"))
        params.strainFail = params_dict["strain_fail"].cast<double>();
    if (params_dict.contains("projection_tol"))
        params.projectionTol = params_dict["projection_tol"].cast<double>();
    if (params_dict.contains("boundary_tol"))
        params.boundaryTol = params_dict["boundary_tol"].cast<double>();
    if (params_dict.contains("use_geodesic"))
        params.useGeodesicPlacement = params_dict["use_geodesic"].cast<bool>();
    
    // Run the solver
    nextdrape::DrapeResult result;
    try {
        nextdrape::DrapeEngine engine;
        result = engine.Compute(*shape, seed, params);
    } catch (const std::exception& e) {
        return py::dict(py::arg("success") = false, py::arg("error") = std::string(e.what()));
    }
    
    py::dict res;
    res["success"] = (result.status == nextdrape::DrapeStatus::Ok);
    
    if (result.status != nextdrape::DrapeStatus::Ok) {
        std::string err;
        switch (result.status) {
            case nextdrape::DrapeStatus::InvalidInput: err = "Invalid input"; break;
            case nextdrape::DrapeStatus::SolverFailure: err = "Solver failed"; break;
            case nextdrape::DrapeStatus::NonDrapable: err = "Non-drappable surface"; break;
            case nextdrape::DrapeStatus::ShearLimitExceeded: err = "Shear limit exceeded"; break;
            default: err = "Unknown error"; break;
        }
        res["error"] = err;
        return res;
    }
    
    // Texture coordinates from texturePlan.flatNodes (gp_Pnt2d -> (u,v,0))
    py::list tex_coords_list;
    for (const auto& pn : result.texturePlan.flatNodes) {
        tex_coords_list.append(py::make_tuple(pn.X(), pn.Y(), 0.0));
    }
    res["tex_coords"] = tex_coords_list;
    
    // Quads from texturePlan.quads
    py::list quads_list;
    for (const auto& q : result.texturePlan.quads) {
        quads_list.append(py::make_tuple(q[0], q[1], q[2], q[3]));
    }
    res["quads"] = quads_list;
    
    // Shear angles: compute from node positions (approximation)
    py::list shear_angles;
    for (size_t i = 0; i < result.quads.size(); ++i) {
        shear_angles.append(0.0);  // Placeholder - actual shear computation needs more work
    }
    res["shear_angle"] = shear_angles;
    
    // Coverage ratio
    res["coverage_ratio"] = result.coverageRatio;
    
    // Max shear / strain
    res["max_shear_deg"] = result.maxShearDeg;
    res["max_strain"] = result.maxStrain;
    
    // Solve time
    res["solve_time_ms"] = result.solveTimeMs;
    
    // Node count
    res["total_nodes"] = static_cast<int>(result.nodes.size());
    
    return res;
}

// ── Module definition ──
PYBIND11_MODULE(Composites_drape, m) {
    m.doc() = "nextdrape C++ solver for FreeCAD Composites";
    m.def("solve", &solve, "Run nextdrape solver",
          py::arg("shape"), py::arg("seed"), py::arg("params") = py::dict());
}
