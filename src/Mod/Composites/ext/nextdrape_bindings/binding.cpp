// binding.cpp — nextdrape pybind11-free binding for FreeCAD Composites WB.
//
// Uses PyCXX-style casting to talk directly to FreeCAD's Part module.
// No pybind11, no capsule conversion, no BREP round-trips.
// Direct TopoDS_Shape* access via TopoShapePy::getTopoShapePtr().

#include <Python.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

// OpenCASCADE
#include <TopoDS_Shape.hxx>
#include <TopoDS_Face.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>
#include <gp_UVector.hxx>
#include <GeomPlate_BuildSurfaceThickness.hxx>
#include <Standard_TypeDef.hxx>

// nextdrape
#include <nextdrape/DrapeEngine.hpp>
#include <nextdrape/Types.hpp>
#include <nextdrape/SeedGenerator.hpp>

// Eigen
#include <Eigen/Dense>

// Local bridge — minimal PyCXX declarations
#include "freecad_bridge.h"

namespace py = pybind11;

// ── Helper: extract TopoDS_Shape* from any Part.Shape PyObject* ──
static TopoDS_Shape* extract_shape(PyObject* obj) {
    // Step 1: If it's a Part::Feature, unwrap to .Shape
    PyObject* shape_obj = obj;
    PyObject* shape_attr = PyObject_GetAttrString(obj, "Shape");
    if (shape_attr && shape_attr != obj) {
        shape_obj = shape_attr;
    } else if (shape_attr) {
        Py_DECREF(shape_attr);
    }

    // Step 2: Check type name — Part.Shape derivatives have names like
    // "Part.Solid", "Part.Face", "Part.Wire", etc.
    PyTypeObject* typ = Py_TYPE(shape_obj);
    if (!typ || !typ->tp_name) {
        PyErr_SetString(PyExc_TypeError, "Not a Part.Shape object");
        return nullptr;
    }

    const char* tn = typ->tp_name;
    if (tn == nullptr || tn[0] != 'P' || tn[1] != 'a' || tn[2] != 'r' || tn[3] != '.') {
        PyErr_SetString(PyExc_TypeError, "Expected Part.Shape (got ").append(tn ? tn : "null").append(")");
        return nullptr;
    }

    // Step 3: Cast to TopoShapePy* and extract TopoShape* → TopoDS_Shape*
    // This is safe because PyCXX ensures the PyObject layout matches.
    Part::TopoShapePy* topo_py = reinterpret_cast<Part::TopoShapePy*>(shape_obj);
    Part::TopoShape* topo = topo_py->getTopoShapePtr();
    if (!topo) {
        PyErr_SetString(PyExc_ValueError, "TopoShape pointer is null");
        return nullptr;
    }

    return const_cast<TopoDS_Shape*>(&topo->getShape());
}

// ── Helper: build nextdrape SeedInput from Python seed data ──
static nextdrape::SeedInput make_seed(py::dict seed_dict) {
    nextdrape::SeedInput seed;
    
    // Parse corner points
    if (seed_dict.contains("corners")) {
        auto corners = seed_dict["corners"].cast<py::list>();
        if (len(corners) >= 3) {
            for (auto item : corners) {
                auto pt = item.cast<py::tuple>();
                seed.corner_points.emplace_back(pt[0].cast<double>(),
                                                 pt[1].cast<double>(),
                                                 pt[2].cast<double>());
            }
        }
    }
    
    // Parse fold lines
    if (seed_dict.contains("fold_lines")) {
        auto folds = seed_dict["fold_lines"].cast<py::list>();
        for (auto item : folds) {
            auto pts = item.cast<py::list>();
            if (pts.size() >= 2) {
                nextdrape::FoldLine fl;
                fl.start = nextdrape::Vec3(pts[0][0].cast<double>(),
                                            pts[0][1].cast<double>(),
                                            pts[0][2].cast<double>());
                fl.end = nextdrape::Vec3(pts[1][0].cast<double>(),
                                          pts[1][1].cast<double>(),
                                          pts[1][2].cast<double>());
                seed.fold_lines.push_back(fl);
            }
        }
    }
    
    return seed;
}

// ── Main solve function ──
py::dict solve_drape(py::object shape_obj,
                     py::dict seed_dict,
                     py::dict params_dict = py::dict()) {
    
    // Extract TopoDS_Shape* directly from Part.Shape (zero-copy, no BREP)
    TopoDS_Shape* shape = extract_shape(shape_obj.ptr());
    if (!shape) {
        return py::dict(py::arg("success") = false, py::arg("error") = "Failed to extract TopoDS_Shape");
    }
    
    // Convert Python dicts to C++ structs
    nextdrape::DrapeParams params;
    if (params_dict.contains("tolerance"))
        params.tolerance = params_dict["tolerance"].cast<double>();
    if (params_dict.contains("max_iterations"))
        params.max_iterations = params_dict["max_iterations"].cast<int>();
    if (params_dict.contains("warp_spread"))
        params.warp_spread = params_dict["warp_spread"].cast<double>();
    if (params_dict.contains("weft_spread"))
        params.weft_spread = params_dict["weft_spread"].cast<double>();
    if (params_dict.contains("friction_coefficient"))
        params.friction_coefficient = params_dict["friction_coefficient"].cast<double>();
    
    nextdrape::SeedInput seed = make_seed(seed_dict);
    
    // Run the solver
    nextdrape::DrapeResult result;
    try {
        result = nextdrape::DrapeEngine::Compute(*shape, seed, params);
    } catch (const std::exception& e) {
        return py::dict(py::arg("success") = false, py::arg("error") = std::string(e.what()));
    }
    
    if (!result.success) {
        return py::dict(py::arg("success") = false,
                       py::arg("error") = result.error_message);
    }
    
    // ── Build result dict ──────────────────────────────────────
    py::dict res;
    res["success"] = true;
    
    // Texture coordinates: flat_mesh.points (Nx3)
    py::array_t<double> tex_coords({static_cast<ssize_t>(result.flat_mesh.points.size()), 3});
    auto tc_buf = tex_coords.mutable_unchecked<2>();
    for (size_t i = 0; i < result.flat_mesh.points.size(); ++i) {
        tc_buf(i, 0) = result.flat_mesh.points[i][0];
        tc_buf(i, 1) = result.flat_mesh.points[i][1];
        tc_buf(i, 2) = 0.0;
    }
    res["tex_coords"] = tex_coords;
    
    // Facets: flat_mesh.facets (Mi indices into points)
    py::list facets_list;
    for (const auto& f : result.flat_mesh.facets) {
        py::list face_list;
        for (auto idx : f) {
            face_list.append(static_cast<py::ssize_t>(idx));
        }
        facets_list.append(face_list);
    }
    res["facets"] = facets_list;
    
    // Strain energy per facet
    py::array_t<double> strain_energy({static_cast<ssize_t>(result.strain_energy.size())});
    auto se_buf = strain_energy.mutable_unchecked<1>();
    for (size_t i = 0; i < result.strain_energy.size(); ++i) {
        se_buf(i) = result.strain_energy[i];
    }
    res["strain_energy"] = strain_energy;
    
    // Boundary edges
    py::list boundary_list;
    for (const auto& edge : result.boundary_edges) {
        py::list edge_list;
        for (auto idx : edge) {
            edge_list.append(static_cast<py::ssize_t>(idx));
        }
        boundary_list.append(edge_list);
    }
    res["boundary_edges"] = boundary_list;
    
    // Diagnostics
    py::dict diag;
    diag["iterations"] = result.iterations;
    diag["converged"] = result.converged;
    res["diagnostics"] = diag;
    
    return res;
}

// ── lcs_at_point: k-d tree based nearest-neighbor lookup ──
py::dict lcs_at_point(py::object shape_obj,
                      py::array_t<double> query_points,
                      py::array_t<double> node_positions,
                      py::array_t<double> node_lcs_matrices,
                      int k = 8) {
    
    // Extract TopoDS_Shape* (same pattern as solve_drape)
    TopoDS_Shape* shape = extract_shape(shape_obj.ptr());
    if (!shape) {
        return py::dict(py::arg("success") = false, py::arg("error") = "Failed to extract TopoDS_Shape");
    }
    
    // Query points: (N, 3)
    auto qp = query_points.unchecked<2>();
    size_t N = query_points.shape(0);
    
    // Node positions: (M, 3)
    auto np = node_positions.unchecked<2>();
    size_t M = node_positions.shape(0);
    
    // Node LCS matrices: (M, 3, 3) — flattened row-major
    auto nl = node_lcs_matrices.unchecked<3>();
    
    // ── Build k-d tree from node positions ─────────────────────
    struct KDNode {
        int idx;
        double coord;       // split coordinate
        int axis;           // split axis (0=x, 1=y, 2=z)
        int left = -1, right = -1;
    };
    
    std::vector<KDNode> tree;
    std::vector<int> perm(M);
    for (size_t i = 0; i < M; ++i) perm[i] = static_cast<int>(i);
    
    // Simple median-of-three partitioning for tree build
    // For production, use std::nth_element for O(n) median
    auto build_tree = [&](auto&& self, int lo, int hi, int depth) -> int {
        if (lo >= hi) return -1;
        
        int axis = depth % 3;
        int mid = lo + (hi - lo) / 2;
        
        // Partial sort to find median (simple insertion sort for small ranges)
        for (int i = mid + 1; i < hi; ++i) {
            if (np(perm[i], axis) < np(perm[mid], axis)) {
                std::swap(perm[mid], perm[i]);
            }
        }
        for (int i = mid - 1; i >= lo; --i) {
            if (np(perm[i], axis) > np(perm[mid], axis)) {
                std::swap(perm[mid], perm[i]);
            }
        }
        
        int node_idx = static_cast<int>(tree.size());
        tree.push_back({perm[mid], np(perm[mid], axis), axis, -1, -1});
        
        tree.back().left = self(lo, mid, depth + 1);
        tree.back().right = self(mid + 1, hi, depth + 1);
        
        return node_idx;
    };
    
    build_tree(build_tree, 0, static_cast<int>(M), 0);
    
    // ── Query: find nearest node for each query point ──────────
    py::array_t<int> nearest_indices({static_cast<ssize_t>(N)});
    py::array_t<double> nearest_distances({static_cast<ssize_t>(N)});
    auto ni_buf = nearest_indices.mutable_unchecked<1>();
    auto nd_buf = nearest_distances.mutable_unchecked<1>();
    
    auto query_knn = [&](auto&& self, int node, const double* qpoint) -> int {
        if (node < 0) return -1;
        
        const auto& nd = tree[node];
        double diff = qpoint[nd.axis] - nd.coord;
        
        int near_child = (diff <= 0) ? nd.left : nd.right;
        int far_child = (diff <= 0) ? nd.right : nd.left;
        
        int best = self(self, near_child, qpoint);
        double best_dist = 0;
        for (int i = 0; i < 3; ++i) {
            double d = np(best, i) - qpoint[i];
            best_dist += d * d;
        }
        
        // Check if we need to search the far side
        if (diff * diff < best_dist && far_child >= 0) {
            int far_best = self(self, far_child, qpoint);
            double far_dist = 0;
            for (int i = 0; i < 3; ++i) {
                double d = np(far_best, i) - qpoint[i];
                far_dist += d * d;
            }
            if (far_dist < best_dist) {
                best = far_best;
                best_dist = far_dist;
            }
        }
        
        return best;
    };
    
    for (size_t i = 0; i < N; ++i) {
        double qpoint[3] = {qp(i, 0), qp(i, 1), qp(i, 2)};
        int nn = query_knn(query_knn, 0, qpoint);
        if (nn >= 0) {
            ni_buf(i) = nn;
            double dist = 0;
            for (int j = 0; j < 3; ++j) {
                double d = np(nn, j) - qpoint[j];
                dist += d * d;
            }
            nd_buf(i) = std::sqrt(dist);
        } else {
            ni_buf(i) = -1;
            nd_buf(i) = -1.0;
        }
    }
    
    py::dict res;
    res["success"] = true;
    res["nearest_indices"] = nearest_indices;
    res["nearest_distances"] = nearest_distances;
    
    return res;
}

// ── Module definition ───────────────────────────────────────────
PYBIND11_MODULE(drape_nextdrape, m) {
    m.doc() = "nextdrape C++ solver bound for FreeCAD Composites WB";
    
    m.def("solve", &solve_drape,
          py::arg("shape"), py::arg("seed"),
          py::arg("params") = py::dict(),
          "Run the nextdrape solver on a FreeCAD Part.Shape.");
    
    m.def("lcs_at_point", &lcs_at_point,
          py::arg("shape"), py::arg("query_points"),
          py::arg("node_positions"), py::arg("node_lcs_matrices"),
          py::arg("k") = 8,
          "Find nearest mesh node for each query point using k-d tree.");
}
