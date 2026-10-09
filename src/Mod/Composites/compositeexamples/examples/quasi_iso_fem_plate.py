# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Quasi-isotropic FEM plate example (PRD quasi_isotropic_laminate.md §8.3).

A flat rectangular plate with a QI laminate ``[0/45/-45/90]s`` declared
``IsotropicEquivalent``, carried by a ``Composite::Shell`` with no
rosette, solved through FreeCAD FEM + CalculiX: the solver input shows a
plain ``*ELASTIC, TYPE=ISO`` material and a single-layer shell section —
no ``*ORIENTATION``, no per-element machinery.
"""

import os

import FreeCAD
import Part

from ...features.CompositeShell import CompositeShellFP
from ...objects import SymmetryType, WeaveType
from ._shell_example_common import (
    make_qi_laminate,
    _add_analysis_member,
    _add_fixed_constraint,
    _add_shell_section_and_material,
    _carbon_material,
    _create_fem_base,
    _mesh_support,
    _prepare_feature_import_environment,
    _resin_material,
    _run_ccx,
    _set_constraint_refs,
    ensure_document,
)

PLATE_LENGTH = 100.0
PLATE_WIDTH = 60.0
QI_ANGLES = (0.0, 45.0, -45.0, 90.0)
FORCE_N = 1000.0

DOCUMENT_NAME = "Composites_QuasiIso_FEM_Plate"


def _ensure_document(doc):
    if doc is not None:
        return doc
    if DOCUMENT_NAME in FreeCAD.listDocuments():
        FreeCAD.closeDocument(DOCUMENT_NAME)
    return FreeCAD.newDocument(DOCUMENT_NAME)


def _make_qi_laminate(doc, name="QILaminate"):
    return make_qi_laminate(doc, name, angles=QI_ANGLES)


def _make_plate(doc):
    support = doc.addObject("Part::Feature", "PlateSupport")
    support.Shape = Part.makePlane(PLATE_LENGTH, PLATE_WIDTH)
    return support


def _edge_names_by_x(support):
    """The plate's edges at min-x and max-x (the membrane load path)."""
    min_edge, max_edge, min_x, max_x = None, None, None, None
    for idx, edge in enumerate(support.Shape.Edges, start=1):
        x = sum(v.Point.x for v in edge.Vertexes) / len(edge.Vertexes)
        if min_x is None or x < min_x:
            min_x, min_edge = x, f"Edge{idx}"
        if max_x is None or x > max_x:
            max_x, max_edge = x, f"Edge{idx}"
    return min_edge, max_edge


def _add_edge_force(doc, analysis, support, edge_name, tag):
    """In-plane point force along +x on the given edge (membrane load)."""
    import ObjectsFem

    force_obj = ObjectsFem.makeConstraintForce(doc, f"{tag}_Force")
    _set_constraint_refs(force_obj, [(support, edge_name)])
    # PropertyForce stores an internal-unit quantity; a bare float is
    # interpreted as that internal unit, not Newtons (measured: 1000.0
    # wrote a 1 N *CLOAD).  Assign unit-explicit.
    force_obj.Force = f"{FORCE_N} N"
    # Direction must be a line/plane geo feature (FEM API); an App::Line
    # along +x drives the in-plane pull.
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


def _max_displacement(analysis):
    for obj in analysis.Group:
        if obj.isDerivedFrom("Fem::FemResultObject"):
            lengths = getattr(obj, "DisplacementLengths", None)
            if lengths:
                return max(float(v) for v in lengths)
    return None


def _solver_input_snippet(inp_file):
    """The material + section blocks proving the ISO single-layer path."""
    with open(inp_file, encoding="utf-8", errors="ignore") as fh:
        text = fh.read()
    lines = text.splitlines()
    snippet = []
    for idx, line in enumerate(lines):
        if line.startswith("*MATERIAL") or line.startswith("*ELASTIC"):
            snippet.extend(lines[idx : idx + 6])
            snippet.append("")
        if line.startswith("*SHELL SECTION") or line.startswith(
            "*SOLID SECTION"
        ):
            snippet.extend(lines[idx : idx + 3])
            snippet.append("")
    return "\n".join(snippet)


def build(doc=None, run_solver=False):
    """Build the QI FEM plate; ``run_solver=True`` solves via CalculiX."""
    doc = _ensure_document(doc)

    support = _make_plate(doc)
    laminate = _make_qi_laminate(doc)
    shell = doc.addObject("Part::FeaturePython", "QIShell")
    CompositeShellFP(shell, support, laminate=laminate, rosette=None)
    doc.recompute()

    result = {
        "doc": doc,
        "laminate": laminate,
        "shell": shell,
    }
    if not run_solver:
        return result

    analysis, solver, mesh_obj = _create_fem_base(doc, "QuasiIsoFemPlate")
    _add_shell_section_and_material(
        doc, analysis, support, "QuasiIsoFemPlate", shell_obj=shell
    )
    mesher = _mesh_support(mesh_obj, support)
    min_edge, max_edge = _edge_names_by_x(support)
    _add_fixed_constraint(doc, analysis, support, min_edge, "QuasiIsoFemPlate")
    _add_edge_force(doc, analysis, support, max_edge, "QuasiIsoFemPlate")
    doc.recompute()

    solve_result, fem = _run_ccx(analysis, solver, mesh_obj)
    if not solve_result:
        raise RuntimeError("CalculiX solve failed for the QI plate")
    with open(fem.inp_file_name, encoding="utf-8", errors="ignore") as fh:
        solver_input = fh.read()

    result.update(
        {
            "analysis": analysis,
            "solver": solver,
            "mesh": mesh_obj,
            "mesher": mesher,
            "max_displacement": _max_displacement(analysis),
            "inp_file": os.path.abspath(fem.inp_file_name),
            "solver_input_snippet": _solver_input_snippet(fem.inp_file_name),
            "solver_input": solver_input,
        }
    )
    return result


def main():
    case = build(run_solver=True)
    print(
        f"quasi_iso_fem_plate: max_displacement={case['max_displacement']}"
    )
    print(case["solver_input_snippet"])


if __name__ == "__main__":
    main()
