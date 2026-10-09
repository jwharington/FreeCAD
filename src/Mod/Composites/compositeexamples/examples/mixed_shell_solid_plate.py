# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""A composite skin as shells over a solid spar, in one analysis.

This is the case the mixed shelf-and-solid work exists for: a laminated
``Composite::Shell`` skin, meshed as shells, bonded to a solid spar that is
meshed as volumes, solved together by CalculiX. Before this, FreeCAD's FEM
pipeline held one element dimension per analysis, so a shell thickness on a
mesh with volume elements was refused outright.

Two things make it work and both matter:

* the skin and the spar are meshed **apart** and merged node-disjoint. A shell
  that shares a solid's nodes is a hinge in CalculiX, and ``getFacesOnly``
  stops reporting it as a shell at all, both silently;
* the coupling is a ``*TIE`` over the interface, written by the ordinary tie
  writer once the reference resolves to the right dimension.

The skin is declared ``IsotropicEquivalent`` so the solver sees one isotropic
layer: that keeps the example off the drape backend, which is a separate
concern and needs no shell-and-solid coupling to be exercised. The load case is
a cantilever - root fixed, tip pulled down - which is the one the section 7
probe uses for its numerical check.
"""

import os

import FreeCAD
import Part

from femexamples.meshes.merged_mesh import mesh_parts_separately

from ...features.CompositeShell import CompositeShellFP
from ._shell_example_common import (
    _add_analysis_member,
    _add_shell_section_and_material,
    _create_fem_base,
    _run_ccx,
    _set_constraint_refs,
    ensure_document,
    make_qi_laminate,
)

SPAR_LENGTH = 100.0
SPAR_WIDTH = 20.0
SPAR_HEIGHT = 20.0
FORCE_N = 1000.0
STEEL = {"YoungsModulus": "210000 MPa", "PoissonRatio": "0.30"}

DOCUMENT_NAME = "Composites_Mixed_Shell_Solid_Plate"


def _ensure_document(doc):
    if doc is not None:
        return doc
    if DOCUMENT_NAME in FreeCAD.listDocuments():
        FreeCAD.closeDocument(DOCUMENT_NAME)
    return FreeCAD.newDocument(DOCUMENT_NAME)


def _make_spar(doc):
    spar = doc.addObject("Part::Box", "Spar")
    spar.Length = SPAR_LENGTH
    spar.Width = SPAR_WIDTH
    spar.Height = SPAR_HEIGHT
    return spar


def _make_skin_support(doc):
    support = doc.addObject("Part::Feature", "SkinSupport")
    support.Shape = Part.makePlane(SPAR_LENGTH, SPAR_WIDTH)
    support.Placement.Base = FreeCAD.Vector(0.0, 0.0, SPAR_HEIGHT)
    return support


def _make_skin(doc, support):
    laminate = make_qi_laminate(doc, "QILaminate")
    shell = doc.addObject("Part::FeaturePython", "SkinShell")
    CompositeShellFP(shell, support, laminate=laminate, rosette=None)
    doc.recompute()
    return shell, laminate


def _face_name(obj, *, axis, value):
    for index, face in enumerate(obj.Shape.Faces, start=1):
        centre = face.CenterOfMass
        if abs(getattr(centre, axis) - value) < 1e-6:
            return f"Face{index}"
    raise ValueError(f"{obj.Name} has no face on {axis}={value}")


def _edge_name(obj, *, x, z):
    for index, edge in enumerate(obj.Shape.Edges, start=1):
        centre = edge.CenterOfMass
        if abs(centre.x - x) < 1e-6 and abs(centre.z - z) < 1e-6:
            return f"Edge{index}"
    raise ValueError(f"{obj.Name} has no edge at x={x}, z={z}")


def _add_spar_material(doc, analysis, spar, tag):
    import ObjectsFem

    material = ObjectsFem.makeMaterialSolid(doc, f"{tag}_SparMaterial")
    data = material.Material
    data["Name"] = "SparSteel"
    data.update(STEEL)
    material.Material = data
    # An empty sub-element names the solid itself, so this material reaches
    # volumes only - the skin's faces belong to the other material.
    _set_constraint_refs(material, [(spar, "")])
    _add_analysis_member(analysis, material)
    return material


def _add_load_case(doc, analysis, spar, tag):
    import ObjectsFem

    fixed = ObjectsFem.makeConstraintFixed(doc, f"{tag}_Fixed")
    _set_constraint_refs(fixed, [(spar, _face_name(spar, axis="x", value=0.0))])
    _add_analysis_member(analysis, fixed)

    force = ObjectsFem.makeConstraintForce(doc, f"{tag}_Force")
    _set_constraint_refs(force, [(spar, _edge_name(spar, x=SPAR_LENGTH, z=0.0))])
    force.Force = f"{FORCE_N} N"
    force.DirectionVector = FreeCAD.Vector(0.0, 0.0, -1.0)
    _add_analysis_member(analysis, force)


def _add_tie(doc, analysis, spar, support, tag):
    import ObjectsFem

    tie = ObjectsFem.makeConstraintTie(doc, f"{tag}_Tie")
    _set_constraint_refs(
        tie, [(support, "Face1"), (spar, _face_name(spar, axis="z", value=SPAR_HEIGHT))]
    )
    tie.Tolerance = 1.0
    _add_analysis_member(analysis, tie)
    return tie


def _max_displacement(analysis):
    for obj in analysis.Group:
        if obj.isDerivedFrom("Fem::FemResultObject"):
            lengths = getattr(obj, "DisplacementLengths", None)
            if lengths:
                return max(float(value) for value in lengths)
    return None


def build(doc=None, run_solver=False):
    """Build the mixed skin-on-spar cantilever; ``run_solver=True`` solves it."""
    doc = _ensure_document(doc)
    tag = "MixedShellSolidPlate"

    spar = _make_spar(doc)
    support = _make_skin_support(doc)
    shell, laminate = _make_skin(doc, support)
    doc.recompute()

    result = {"doc": doc, "spar": spar, "support": support, "shell": shell, "laminate": laminate}
    if not run_solver:
        return result

    analysis, solver, mesh_obj = _create_fem_base(doc, tag)
    _add_shell_section_and_material(doc, analysis, support, tag, shell_obj=shell)
    _add_spar_material(doc, analysis, spar, tag)
    _add_load_case(doc, analysis, spar, tag)
    _add_tie(doc, analysis, spar, support, tag)

    # The mesher never sees the two together: a skin sharing the spar's nodes
    # would be a hinge, and would stop being detected as a shell.
    mesh_obj.FemMesh = mesh_parts_separately(doc, [spar, support])
    geometry = doc.addObject("Part::Compound", f"{tag}_Geometry")
    geometry.Links = [spar, support]
    mesh_obj.Shape = geometry
    doc.recompute()

    solve_result, fem = _run_ccx(analysis, solver, mesh_obj)
    if not solve_result:
        raise RuntimeError("CalculiX solve failed for the mixed skin-on-spar plate")

    with open(fem.inp_file_name, encoding="utf-8", errors="ignore") as fh:
        solver_input = fh.read()

    result.update(
        {
            "analysis": analysis,
            "solver": solver,
            "mesh": mesh_obj,
            "max_displacement": _max_displacement(analysis),
            "inp_file": os.path.abspath(fem.inp_file_name),
            "solver_input": solver_input,
        }
    )
    return result


def main():
    case = build(run_solver=True)
    print(f"mixed_shell_solid_plate: max_displacement={case['max_displacement']}")


if __name__ == "__main__":
    main()
