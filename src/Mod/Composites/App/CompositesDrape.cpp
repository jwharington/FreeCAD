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

// FreeCAD Part module — provides TopoShapePy, TopoShape, and FeaturePy
#include <Mod/Part/App/TopoShapePy.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/PartFeaturePy.h>

// OpenCASCADE
#include <TopoDS_Shape.hxx>
#include <gp_Pnt.hxx>
#include <gp_Dir.hxx>
#include <BRepTools.hxx>
#include <sstream>

// nextdrape
#include <nextdrape/DrapeEngine.hpp>
#include <nextdrape/Types.hpp>
#include <nextdrape/Utilities.hpp>
#include <nextdrape/SeamOverlapSolver.hpp>

// KDTreeLocator — exposed for unit-testing the spatial index in isolation
// (test_kd_tree_locator.py builds synthetic meshes without an OCC shape, so
// it cannot go through DrapeEngine). Production UV lookup goes through
// DrapeEngine::LookupUV; this binding is a test/profiling seam only.
#include <nextdrape/KDTreeLocator.hpp>

namespace py = pybind11;

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

// ── Shared helpers (used by both the solve() free function and the
//    DrapeEngine.compute() method, so the dict shape stays identical) ──

static nextdrape::DrapeParams build_params(const py::dict& params_dict) {
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

    return params;
}

static nextdrape::SeedInput build_seed(const py::dict& seed_dict) {
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
    return seed;
}

static py::dict pack_result(const nextdrape::DrapeResult& result) {
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
}

// Run a full drape on the engine and pack the result. Shared by the solve()
// free function (temporary engine) and DrapeEngine.compute() (persistent
// engine, retained so LookupUV() can query the last result).
static py::dict engine_compute(nextdrape::DrapeEngine& engine,
                               py::object shape_obj,
                               const py::dict& seed_dict,
                               const py::dict& params_dict) {
    TopoDS_Shape shape;
    try {
        shape = extract_topods_shape(shape_obj.ptr());
    } catch (const std::exception& e) {
        return py::dict(py::arg("success") = false,
                        py::arg("error") = std::string(e.what()));
    }

    auto params = build_params(params_dict);
    auto seed = build_seed(seed_dict);

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

    return pack_result(result);
}

// ── Module ────────────────────────────────────────────────────
PYBIND11_MODULE(Composites_drape, m) {
    m.doc() = "Composites draping solver — nextdrape integrated with FreeCAD";

    // ── DrapeEngine: the clean frontend ─────────────────────────
    // FreeCAD holds a persistent DrapeEngine, calls compute() once (which
    // builds the UV-query index internally), then lookup_uv() for any
    // number of point queries. This keeps the k-d tree / brute-force
    // algorithm choice and the flat-data round-trip inside nextdrape.
    py::class_<nextdrape::DrapeEngine>(m, "DrapeEngine")
        .def(py::init<>())
        .def("compute",
             [](nextdrape::DrapeEngine& self,
                py::object shape_obj,
                py::dict seed_dict,
                py::dict params_dict) {
                 return engine_compute(self, shape_obj, seed_dict, params_dict);
             },
             py::arg("shape"), py::arg("seed"), py::arg("params") = py::dict(),
             "Run the drape solve; returns the same result dict as solve(). "
             "The engine retains a UV-query index for subsequent lookup_uv() calls.")
        .def("lookup_uv",
             [](const nextdrape::DrapeEngine& self, py::object point_obj) -> py::object {
                 nextdrape::Vec3 p{0.0, 0.0, 0.0};
                 try {
                     py::sequence seq(point_obj);
                     if (py::len(seq) < 3) {
                         return py::none();
                     }
                     p.x = py::cast<double>(seq[0]);
                     p.y = py::cast<double>(seq[1]);
                     p.z = py::cast<double>(seq[2]);
                 } catch (const std::exception&) {
                     return py::none();
                 }
                 const auto uv = self.LookupUV(p);
                 if (!uv) {
                     return py::none();
                 }
                 return py::make_tuple(uv->u, uv->v);
             },
             py::arg("point"),
             "Return (u, v) texture coordinate at a 3D point on the last "
             "compute() result, or None if no quad is reachable.");

    // ── solve(): thin wrapper over a temporary DrapeEngine ──────
    // Retained for backward compatibility / one-shot use. Holding a
    // persistent DrapeEngine (compute + lookup_uv) is preferred so the
    // UV-query index survives across lookups.
    m.def("solve", [](py::object shape_obj, py::dict seed_dict, py::dict params_dict) {
        nextdrape::DrapeEngine engine;
        return engine_compute(engine, shape_obj, seed_dict, params_dict);
    },
    py::arg("shape"), py::arg("seed"), py::arg("params") = py::dict(),
    "Run nextdrape solver on a FreeCAD Part.Shape — zero-copy TopoDS_Shape access.");

    // ── Seam extraction ──────────────────────────────────────────
    m.def("extract_seam", [](py::object master_obj, py::object attachment_obj, double seam_width) {
        TopoDS_Shape master_shape;
        TopoDS_Shape attachment_shape;
        try {
            master_shape = extract_topods_shape(master_obj.ptr());
            attachment_shape = extract_topods_shape(attachment_obj.ptr());
        } catch (const std::exception& e) {
            return py::dict(py::arg("success") = false,
                          py::arg("error") = std::string(e.what()),
                          py::arg("seam") = py::none(),
                          py::arg("remainder") = py::none());
        }

        nextdrape::SeamOverlapSolver solver;
        bool ok = false;
        try {
            ok = solver.Solve(master_shape, attachment_shape, seam_width);
        } catch (const std::exception& e) {
            return py::dict(py::arg("success") = false,
                          py::arg("error") = std::string(e.what()),
                          py::arg("seam") = py::none(),
                          py::arg("remainder") = py::none());
        }

        if (!ok) {
            return py::dict(py::arg("success") = false,
                          py::arg("error") = std::string("SeamOverlapSolver::Solve returned false"),
                          py::arg("seam") = py::none(),
                          py::arg("remainder") = py::none());
        }

        const TopoDS_Shape& seam_shape = solver.Seam();
        const TopoDS_Shape& remainder_shape = solver.AttachmentRemainder();

        // Wrap TopoDS_Shape back into Part.Shape PyObjects.
        // Serialize the TopoDS_Shape to BREP bytes via BRepTools, then
        // let Python decode it via Part.readBytes(). This preserves the
        // full BRep topology without lossy conversion.
        auto wrap_shape = [](const TopoDS_Shape& occ_shape) -> py::object {
            if (occ_shape.IsNull()) {
                return py::none();
            }
            std::ostringstream stream;
            BRepTools::Write(occ_shape, stream);
            std::string brep_str = stream.str();
            return py::bytes(brep_str);
        };

        return py::dict(py::arg("success") = true,
                      py::arg("error") = std::string(""),
                      py::arg("seam") = wrap_shape(seam_shape),
                      py::arg("remainder") = wrap_shape(remainder_shape));
    },
    py::arg("master"), py::arg("attachment"), py::arg("seam_width") = 10.0,
    "Extract seam geometry between master and attachment surfaces.");

    // ── KDTreeLocator bindings (TEST/PROFILING SEAM ONLY) ───────
    // Production UV lookup goes through DrapeEngine::lookup_uv. This
    // binding exists so test_kd_tree_locator.py can exercise the spatial
    // index in isolation on synthetic meshes that have no OCC shape (and
    // therefore cannot go through DrapeEngine::Compute). Keeping it does
    // not couple production code to the k-d tree implementation.
    py::class_<nextdrape::KDTreeLocator>(m, "KDTreeLocator")
        .def(py::init([](py::list node_positions,
                         py::list quads) {
            std::vector<nextdrape::Vec3> positions;
            for (auto item : node_positions) {
                py::tuple t = item.cast<py::tuple>();
                positions.push_back({t[0].cast<double>(), t[1].cast<double>(), t[2].cast<double>()});
            }
            std::vector<std::array<std::uint32_t, 4>> q;
            for (auto item : quads) {
                py::tuple t = item.cast<py::tuple>();
                q.push_back({
                    static_cast<std::uint32_t>(t[0].cast<int>()),
                    static_cast<std::uint32_t>(t[1].cast<int>()),
                    static_cast<std::uint32_t>(t[2].cast<int>()),
                    static_cast<std::uint32_t>(t[3].cast<int>())
                });
            }
            return new nextdrape::KDTreeLocator(positions, q);
        }))
        .def("lookup",
             [](nextdrape::KDTreeLocator& self, py::list point, py::list tex_coords) {
                 nextdrape::Vec3 p;
                 if (py::len(point) == 3) {
                     p.x = point[0].cast<double>();
                     p.y = point[1].cast<double>();
                     p.z = point[2].cast<double>();
                 } else {
                     return std::vector<double>();
                 }
                 std::vector<nextdrape::Vec2> tc;
                 for (auto item : tex_coords) {
                     py::list row = item.cast<py::list>();
                     if (py::len(row) >= 2) {
                         tc.push_back({row[0].cast<double>(), row[1].cast<double>()});
                     }
                 }
                 return self.lookup(p, tc);
             },
             py::arg("point"), py::arg("tex_coords"),
             "Find UV coordinate for a 3D point.")
        .def_static("min_quads_for_kdtree",
            &nextdrape::KDTreeLocator::min_quads_for_kdtree,
            "Minimum number of quads before k-d tree is worth building.")
        .def("last_lookup_us",
             &nextdrape::KDTreeLocator::last_lookup_us,
             "Last lookup duration in microseconds (for profiling).");
}
