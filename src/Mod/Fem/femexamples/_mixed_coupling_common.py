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

STEEL = {
    "Name": "CalculiX-Steel",
    "YoungsModulus": "210000 MPa",
    "PoissonRatio": "0.30",
}

COINCIDENT_TOLERANCE = 1e-6
_ROUND_DIGITS = 6


def planar_face(points):
    """Return a planar Face through the given corner points, in order."""
    corners = [FreeCAD.Vector(*point) for point in points]
    wire = Part.makePolygon(corners + [corners[0]])
    return Part.Face(wire)


def face_normal(face):
    """Return the outward normal of a planar face, sampled away from its rim."""
    u0, u1, v0, v1 = face.ParameterRange
    return face.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))


def plane_offset(face):
    """Return the signed distance of a planar face's plane from the origin."""
    return face.CenterOfMass.dot(face_normal(face))


def find_face_reference(obj, normal, offset, tolerance=COINCIDENT_TOLERANCE):
    """Return ``(obj, "FaceN")`` for the face whose plane is ``normal`` at ``offset``."""
    wanted = FreeCAD.Vector(*normal).normalize()
    for index, face in enumerate(obj.Shape.Faces, start=1):
        if face_normal(face).dot(wanted) < 1.0 - tolerance:
            continue
        if abs(plane_offset(face) - offset) <= tolerance:
            return (obj, f"Face{index}")
    raise ValueError(f"no face of {obj.Name} lies on {normal} at {offset}")


def paired_faces_by_plane(solid_shape, shell_shape, tolerance):
    """Pairs the shell faces to the solid faces they lie on or over, by plane.

    A pair is a shell face and a solid face whose normals are parallel and whose
    planes are no further apart than ``tolerance``. This is the interface a face
    coupling is tied over, and it ignores the solid faces the shell does not
    reach.
    """
    pairs = []
    for solid_index, solid_face in enumerate(solid_shape.Faces, start=1):
        solid_normal = face_normal(solid_face)
        for shell_index, shell_face in enumerate(shell_shape.Faces, start=1):
            if face_normal(shell_face).dot(solid_normal) < 1.0 - COINCIDENT_TOLERANCE:
                continue
            gap = abs((shell_face.CenterOfMass - solid_face.CenterOfMass).dot(solid_normal))
            if gap <= tolerance:
                pairs.append((f"Face{shell_index}", f"Face{solid_index}"))
    return pairs


def extreme_face_reference(obj, axis, sign):
    """Return ``(obj, "FaceN")`` for the face furthest along ``axis`` in ``sign``."""
    best_index = None
    best_value = None
    for index, face in enumerate(obj.Shape.Faces, start=1):
        value = face.CenterOfMass[axis] * sign
        if best_value is None or value > best_value:
            best_index, best_value = index, value
    if best_index is None:
        raise ValueError(f"{obj.Name} has no faces")
    return (obj, f"Face{best_index}")


def find_edge_reference(obj, point_a, point_b):
    """Return ``(obj, "EdgeN")`` for the edge running between two points."""
    wanted = _endpoint_key(point_a, point_b)
    for index, edge in enumerate(obj.Shape.Edges, start=1):
        if _edge_endpoints(edge) == wanted:
            return (obj, f"Edge{index}")
    raise ValueError(f"no edge of {obj.Name} runs between {point_a} and {point_b}")


def _edge_endpoints(edge):
    vertices = edge.Vertexes
    if len(vertices) != 2:
        return None
    return _endpoint_key(vertices[0].Point, vertices[1].Point)


def _endpoint_key(point_a, point_b):
    return tuple(sorted((_rounded(point_a), _rounded(point_b))))


def _rounded(point):
    vector = point if isinstance(point, FreeCAD.Vector) else FreeCAD.Vector(*point)
    return (
        round(vector.x, _ROUND_DIGITS),
        round(vector.y, _ROUND_DIGITS),
        round(vector.z, _ROUND_DIGITS),
    )


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


def add_force(doc, analysis, reference, magnitude, direction=None):
    """Return a force on a reference, along the reference's normal or a direction."""
    force = ObjectsFem.makeConstraintForce(doc, "Force")
    force.References = [reference]
    force.Force = f"{magnitude:.1f} N"
    if direction is None:
        manager.set_direction_compat(force, reference)
        manager.set_reversed_compat(force, False)
    else:
        force.DirectionVector = FreeCAD.Vector(*direction)
    analysis.addObject(force)
    return force


def add_mesh(doc, analysis, shape):
    """Return the mesh object spanning the whole compound, with no mesher run."""
    femmesh_obj = analysis.addObject(ObjectsFem.makeMeshGmsh(doc, manager.get_meshname()))[0]
    femmesh_obj.Shape = shape
    femmesh_obj.SecondOrderLinear = False
    return femmesh_obj
