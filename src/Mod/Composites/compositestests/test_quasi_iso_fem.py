# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""End-to-end QI FEM tests (PRD quasi_isotropic_laminate.md §7.6).

Cross-validation gate: the same quasi-isotropic stack solved twice under
a membrane load case — (a) QI isotropic presentation, (b) the
conventional draped orthotropic per-ply export — compared on the mean
axial edge displacement (ux).  The agreement tolerance is 5%
(`QI_CROSS_VALIDATION_TOLERANCE`, user decision 2026-09-16).
"""

import os
import sys
import unittest

from pathlib import Path

import FreeCAD
import Part

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import Composites  # noqa: E402, F401
import Composites.objects  # noqa: E402, F401

from .test_base import TestFreeCADFP  # noqa: E402
from Composites.compositeexamples.examples._shell_example_common import (  # noqa: E402
    _add_analysis_member,
    _add_fixed_constraint,
    _create_fem_base,
    _mesh_support,
    _run_ccx,
    _set_constraint_refs,
)

CARBON = {
    "Name": "Carbon",
    "Density": "1750.0 kg/m^3",
    "PoissonRatioXY": "0.27",
    "PoissonRatioXZ": "0.27",
    "PoissonRatioYZ": "0.45",
    "ShearModulusXY": "5000 MPa",
    "ShearModulusXZ": "5000 MPa",
    "ShearModulusYZ": "3500 MPa",
    "YoungsModulusX": "135 GPa",
    "YoungsModulusY": "9.5 GPa",
    "YoungsModulusZ": "9.5 GPa",
}
RESIN = {
    "Name": "Epoxy",
    "Density": "1180.0 kg/m^3",
    "YoungsModulus": "3.300 GPa",
    "PoissonRatio": "0.35",
}

PLATE_LENGTH = 100.0
PLATE_WIDTH = 60.0
QI_ANGLES = (0.0, 45.0, -45.0, 90.0)
FORCE_N = 1000.0

# §7.6 membrane agreement tolerance between the QI isotropic presentation
# and the draped per-ply export, agreed at 5% (user, 2026-09-16).  Measured
# disagreement is <=1.6% at the finest mesh; do not widen without explicit
# user confirmation.
QI_CROSS_VALIDATION_TOLERANCE = 0.05


def _edge_names_by_x(support):
    min_edge, max_edge, min_x, max_x = None, None, None, None
    for idx, edge in enumerate(support.Shape.Edges, start=1):
        x = sum(v.Point.x for v in edge.Vertexes) / len(edge.Vertexes)
        if min_x is None or x < min_x:
            min_x, min_edge = x, f"Edge{idx}"
        if max_x is None or x > max_x:
            max_x, max_edge = x, f"Edge{idx}"
    return min_edge, max_edge


def _add_edge_force(doc, analysis, support, edge_name, tag):
    import ObjectsFem

    force_obj = ObjectsFem.makeConstraintForce(doc, f"{tag}_Force")
    _set_constraint_refs(force_obj, [(support, edge_name)])
    # PropertyForce stores an internal-unit quantity; a bare float is
    # interpreted as that internal unit, not Newtons (measured: 1000.0
    # wrote a 1 N *CLOAD).  Assign unit-explicit.
    force_obj.Force = f"{FORCE_N} N"
    direction_obj = doc.addObject("App::Line", f"{tag}_ForceDirection")
    direction_obj.Placement = FreeCAD.Placement(
        FreeCAD.Vector(0, 0, 0),
        FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 90),
    )
    try:
        force_obj.Direction = (direction_obj, [])
    except Exception:
        pass
    try:
        force_obj.DirectionVector = FreeCAD.Vector(1.0, 0.0, 0.0)
    except Exception:
        pass
    _add_analysis_member(analysis, force_obj)
    return force_obj


def _avg_free_edge_displacement(analysis, mesh_obj, support):
    """Mean axial displacement (ux) across the free (loaded) edge.

    The free edge is the support edge with the largest mean x (the loaded
    one); the clamped edge is excluded by construction.  The **axial
    component** is used, not the vector magnitude: at the edge corners
    the Poisson contraction adds uy, so |u| is not uniform along the edge
    and its average is weighted by the mesh's node distribution.  Mean ux
    is the well-defined edge extension (§7.6 metric, user directive
    2026-09-16).
    """
    result = next(
        obj for obj in analysis.Group
        if obj.isDerivedFrom("Fem::FemResultObject")
    )
    # The result vectors are ordered by result.NodeNumbers, NOT by mesh
    # node id (see FreeCAD's femresult.resulttools — the value lists must
    # be zipped with NodeNumbers).  Assuming node-id order misassigns
    # every node's displacement.
    disp = dict(zip(result.NodeNumbers, result.DisplacementVectors))
    nodes = result.Mesh.FemMesh.Nodes  # compacted result mesh
    max_x = max(v.x for v in nodes.values())
    tol = 1e-6 * max(1.0, abs(max_x))
    edge_vals = [
        float(disp[nid].x)
        for nid, vec in sorted(nodes.items())
        if abs(vec.x - max_x) <= tol
    ]
    if not edge_vals:
        raise RuntimeError("no mesh nodes found on the free edge")
    return sum(edge_vals) / len(edge_vals)


class TestQuasiIsoFemCrossValidation(TestFreeCADFP):
    """Same QI stack, two exports, membrane load case (§7.6)."""

    save_fcstd = False

    def _build_and_solve(
        self, isotropic, name, mesh_max_size=None, mesh_template=None,
        solve=True, stack_model=None,
    ):
        """Build one variant; ``solve=False`` stops after meshing (export-only).

        ``stack_model`` (a StackModelType member name) sets the laminate's
        stack model before recompute; ``None`` leaves the Discrete default.

        ``mesh_template`` (an existing FemMeshObject) forces both variants
        onto the *same* mesh, so the cross-validation is not confounded by
        gmsh producing a slightly different mesh per build.
        """
        doc = FreeCAD.newDocument(name)

        from Composites.compositeexamples.examples._shell_example_common import (
            _add_shell_section_and_material,
            _prepare_feature_import_environment,
        )

        _prepare_feature_import_environment()
        from Composites.features.CompositeShell import CompositeShellFP
        from Composites.features.CompositeLaminate import CompositeLaminateFP
        from Composites.features.FibreCompositeLamina import (
            FibreCompositeLaminaFP,
        )
        from Composites.features.Rosette import RosetteFP
        from Composites.objects import SymmetryType, WeaveType

        support = doc.addObject("Part::Feature", f"{name}_Support")
        support.Shape = Part.makePlane(PLATE_LENGTH, PLATE_WIDTH)

        plies = []
        for idx, angle in enumerate(QI_ANGLES, start=1):
            ply = doc.addObject("App::FeaturePython", f"{name}_Ply{idx:02d}")
            FibreCompositeLaminaFP(ply)
            ply.FibreMaterial = CARBON
            ply.FibreVolumeFraction = 55
            ply.Thickness = FreeCAD.Units.Quantity("0.2 mm")
            ply.Angle = angle
            ply.WeaveType = WeaveType.UD.name
            plies.append(ply)
        laminate = doc.addObject("Part::FeaturePython", f"{name}_Laminate")
        CompositeLaminateFP(laminate, laminae=plies)
        laminate.ResinMaterial = RESIN
        laminate.FibreVolumeFraction = 55
        laminate.Symmetry = SymmetryType.Even.name
        laminate.IsotropicEquivalent = isotropic
        if stack_model is not None:
            laminate.StackModelType = stack_model
        doc.recompute()

        shell = doc.addObject("Part::FeaturePython", f"{name}_Shell")
        CompositeShellFP(shell, support, laminate=laminate, rosette=None)
        if not isotropic:
            # The draped export needs a fibre frame.
            rosette = doc.addObject("Part::FeaturePython", f"{name}_Rosette")
            RosetteFP(rosette, support=(support, ["Face1"]))
            rosette.Angle = 0.0
            shell.Rosette = rosette
            shell.DrapePitch = 5.0
        doc.recompute()

        self.assertNotIn("Invalid", laminate.State)
        self.assertNotIn("Invalid", shell.State)

        analysis, solver, mesh_obj = _create_fem_base(doc, name)
        if mesh_template is not None:
            # Reuse the partner variant's mesh verbatim.
            mesh_obj.FemMesh = mesh_template.FemMesh
        elif mesh_max_size is not None:
            # gmsh characteristic length: None keeps the (very coarse)
            # default, which is the historical §7.6 configuration.
            mesh_obj.CharacteristicLengthMax = mesh_max_size
        _add_shell_section_and_material(
            doc, analysis, support, name, shell_obj=shell
        )
        if mesh_template is None:
            _mesh_support(mesh_obj, support)
        min_edge, max_edge = _edge_names_by_x(support)
        _add_fixed_constraint(doc, analysis, support, min_edge, name)
        _add_edge_force(doc, analysis, support, max_edge, name)
        doc.recompute()

        if not solve:
            return {
                "doc": doc,
                "analysis": analysis,
                "solver": solver,
                "shell": shell,
                "laminate": laminate,
                "mesh_obj": mesh_obj,
                "displacement": None,
                "solver_input": None,
                "solver_inp": None,
                "mesh_node_count": mesh_obj.FemMesh.NodeCount,
            }

        solve_result, fem = _run_ccx(analysis, solver, mesh_obj)
        if not solve_result:
            raise RuntimeError(f"CalculiX solve failed for {name}")
        displacement = _avg_free_edge_displacement(analysis, mesh_obj, support)
        with open(fem.inp_file_name, encoding="utf-8", errors="ignore") as fh:
            solver_input = fh.read()
        return {
            "doc": doc,
            "analysis": analysis,
            "solver": solver,
            "shell": shell,
            "laminate": laminate,
            "mesh_obj": mesh_obj,
            "displacement": displacement,
            "solver_input": solver_input,
            "solver_inp": fem.inp_file_name,
            "mesh_node_count": mesh_obj.FemMesh.NodeCount,
        }

    def tearDown(self):
        for doc_name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(doc_name)

    def test_cross_validation_membrane(self):
        """QI presentation vs per-ply draped export, same stack.

        Compares the mean axial edge displacement (ux) of the two exports
        and asserts agreement within the 5% §7.6 tolerance.
        """
        qi = self._build_and_solve(isotropic=True, name="QIVariant")
        draped = self._build_and_solve(isotropic=False, name="DrapedVariant")

        # Both solves are the same model: identical meshes.
        self.assertEqual(
            qi["mesh_node_count"], draped["mesh_node_count"]
        )
        # The QI export is the plain isotropic path...
        self.assertNotIn("*ORIENTATION", qi["solver_input"])
        self.assertIn("TYPE=ISO", qi["solver_input"])
        # ...and the draped export is the conventional composite path.
        self.assertIn("*ORIENTATION", draped["solver_input"])
        self.assertIn("COMPOSITE,ORIENTATION=", draped["solver_input"])

        from FreeCAD import Console

        Console.PrintMessage(
            f"\n[QI cross-validation] QI presentation: "
            f"{qi['displacement']:.6e} mm; "
            f"per-ply draped export: "
            f"{draped['displacement']:.6e} mm\n"
        )
        relative = abs(
            qi["displacement"] - draped["displacement"]
        ) / draped["displacement"]
        Console.PrintMessage(
            f"[QI cross-validation] relative difference: {relative:.3e}\n"
        )

        # §7.6 membrane agreement: mean axial ux, 5% tolerance.
        self.assertGreater(qi["displacement"], 0.0)
        self.assertGreater(draped["displacement"], 0.0)
        self.assertLessEqual(
            relative,
            QI_CROSS_VALIDATION_TOLERANCE,
            f"QI vs draped membrane disagreement {relative:.2%} exceeds "
            f"{QI_CROSS_VALIDATION_TOLERANCE:.0%}",
        )


def run_qi_convergence(sizes=(None, 30.0, 15.0, 7.5, 4.0)):
    """Mesh-convergence sweep, QI presentation only (variant (a)).

    The draped variant is intentionally excluded (user directive
    2026-09-16).  Reports the average free-edge displacement per mesh
    density; a converging series validates the QI export end to end.
    """
    case = TestQuasiIsoFemCrossValidation("test_cross_validation_membrane")
    print(f"{'clmax':>8} {'nodes':>7} {'avg free-edge disp':>20}")
    results = []
    for size in sizes:
        name = f"QIConv{int(size) if size else 0}"
        r = case._build_and_solve(isotropic=True, name=name, mesh_max_size=size)
        print(f"{str(size):>8} {r['mesh_node_count']:>7} {r['displacement']:>20.8e}")
        results.append(r)
        FreeCAD.closeDocument(name)
    return results


if __name__ == "__main__":
    unittest.main()
