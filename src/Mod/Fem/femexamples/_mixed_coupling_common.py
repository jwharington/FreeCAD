# ***************************************************************************
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *                                                                         *
# ***************************************************************************

"""Shared building blocks for the mixed shell + solid coupling examples.

The face family (a shell lying on or over a solid face) and the edge family
(a shell continuing a solid along an edge) differ only in their geometry.
Everything else they need is the same: the solver and material scaffold, the
shell-thickness object, the compound the mesh object is built from, and the
geometric sub-shape lookups that turn an intended interface into a FreeCAD
reference. Keeping those here leaves each example module describing nothing
but what makes its variants different.
"""

import FreeCAD
import Part

import ObjectsFem

from . import manager
from .meshes.merged_mesh import mesh_parts_separately

STEEL = {
    "Name": "CalculiX-Steel",
    "YoungsModulus": "210000 MPa",
    "PoissonRatio": "0.30",
}

def planar_face(points):
    """Return a planar Face through the given corner points, in order."""
    corners = [FreeCAD.Vector(*point) for point in points]
    wire = Part.makePolygon(corners + [corners[0]])
    return Part.Face(wire)


def make_compound(doc, name, objects):
    """Return a Part::Compound over the given objects, the shape the mesh uses."""
    compound = doc.addObject("Part::Compound", name)
    compound.Links = objects
    return compound


def add_shape(doc, name, shape):
    """Return a Part::Feature carrying a real Part shape."""
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = shape
    return obj


def add_analysis(doc, solvertype):
    """Return an analysis carrying the ccxtools solver and a steel material."""
    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")

    solver_obj = _make_solver(doc, solvertype)
    if solver_obj is not None:
        analysis.addObject(solver_obj)

    material_obj = ObjectsFem.makeMaterialSolid(doc, "MechanicalMaterial")
    material_obj.Material = STEEL
    analysis.addObject(material_obj)
    return analysis


def _make_solver(doc, solvertype):
    if solvertype != "ccxtools":
        FreeCAD.Console.PrintWarning(
            "Unknown or unsupported solver type: {}. "
            "No solver object was created.\n".format(solvertype)
        )
        return None

    solver_obj = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiXCcxTools")
    solver_obj.WorkingDir = ""
    solver_obj.SplitInputWriter = False
    solver_obj.AnalysisType = "static"
    solver_obj.GeometricalNonlinearity = False
    solver_obj.ThermoMechSteadyState = False
    solver_obj.MatrixSolverType = "default"
    solver_obj.IterationsControlParameterTimeUse = False
    return solver_obj


def add_shell_thickness(doc, analysis, thickness, offset=0.0):
    """Return the shell-thickness object carrying the shell's section offset."""
    thickness_obj = ObjectsFem.makeElementGeometry2D(doc, thickness, "ShellThickness")
    thickness_obj.Offset = offset
    analysis.addObject(thickness_obj)
    return thickness_obj


def add_tie(doc, analysis, name, slave_ref, master_ref, tolerance):
    """Return a Tie from a shell slave reference to a solid master reference."""
    tie = ObjectsFem.makeConstraintTie(doc, name)
    tie.References = [slave_ref, master_ref]
    tie.Tolerance = tolerance
    analysis.addObject(tie)
    return tie


def add_fixed(doc, analysis, reference):
    fixed = ObjectsFem.makeConstraintFixed(doc, "Fixed")
    fixed.References = [reference]
    analysis.addObject(fixed)
    return fixed


def add_force(doc, analysis, reference, magnitude, direction):
    """Return a force of ``magnitude`` on ``reference`` along ``direction``.

    The axis reaches the deck through ``Direction``, the element that gives the
    force its direction. ``DirectionVector`` cannot carry it: Fem treats that
    property as an output and recomputes it from the referenced face's normal
    whenever the constraint is recomputed, so a vector written there becomes the
    face normal rather than the load axis. Fem reads a datum element's local Z as
    the direction, so this supplies one ``App::Line`` rotated to point along
    ``direction``.
    """
    force = ObjectsFem.makeConstraintForce(doc, "Force")
    force.References = [reference]
    force.Force = f"{magnitude:.1f} N"
    direction_obj = doc.addObject("App::Line", "ForceDirection")
    direction_obj.Placement = FreeCAD.Placement(
        FreeCAD.Vector(0.0, 0.0, 0.0),
        FreeCAD.Rotation(FreeCAD.Vector(0.0, 0.0, 1.0), FreeCAD.Vector(*direction)),
    )
    force.Direction = (direction_obj, [])
    analysis.addObject(force)
    return force


def add_mesh(doc, analysis, shape):
    """Return the mesh object spanning the whole compound, with no mesher run."""
    femmesh_obj = analysis.addObject(ObjectsFem.makeMeshGmsh(doc, manager.get_meshname()))[0]
    femmesh_obj.Shape = shape
    femmesh_obj.SecondOrderLinear = False
    return femmesh_obj



