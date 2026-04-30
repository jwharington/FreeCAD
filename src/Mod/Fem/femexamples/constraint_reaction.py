# ***************************************************************************
# *   Copyright (c) 2026 FreeCAD contributors                               *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# ***************************************************************************

import FreeCAD
import ObjectsFem

from . import manager
from .manager import get_meshname, init_doc


def get_information():
    return {
        "name": "Constraint Reaction",
        "meshtype": "face",
        "meshelement": "Tria6",
        "constraints": ["fixed", "reaction"],
        "solvers": ["ccxtools"],
        "material": "solid",
        "equations": ["mechanical"],
    }


def get_explanation(header=""):
    return header + """

To run the example from Python console use:
from femexamples.constraint_reaction import setup
setup()

This setup example shows how to define a reaction-based distributed
pressure constraint acting on the cylindrical face of a beam cutout.

"""


def setup(doc=None, solvertype="ccxtools"):

    # init FreeCAD document
    if doc is None:
        doc = init_doc()

    # explanation object
    manager.add_explanation_obj(
        doc,
        get_explanation(manager.get_header(get_information())),
    )

    # geometric object: beam with cylindrical cutout
    beam = doc.addObject("Part::Box", "Beam")
    beam.Height = beam.Width = 2000
    beam.Length = 8000

    cutout = doc.addObject("Part::Cylinder", "Cutout")
    cutout.Radius = 500
    cutout.Height = beam.Width
    cutout.Placement = FreeCAD.Placement(
        FreeCAD.Vector(4000, cutout.Height, 1000),
        FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 90),
    )

    geom_obj = doc.addObject("Part::Cut", "BeamWithCutout")
    geom_obj.Base = beam
    geom_obj.Tool = cutout

    doc.recompute()

    # Use geometric queries instead of hard-coded face indices to keep the
    # example robust against face renumbering after boolean operations.
    face_names = [f"Face{i}" for i, _ in enumerate(geom_obj.Shape.Faces, start=1)]
    fixed_face_name = min(
        enumerate(geom_obj.Shape.Faces, start=1),
        key=lambda item: item[1].CenterOfMass.x,
    )[0]
    fixed_face_name = f"Face{fixed_face_name}"

    cylindrical_faces = []
    for i, face in enumerate(geom_obj.Shape.Faces, start=1):
        surface = getattr(face, "Surface", None)
        if surface is not None and hasattr(surface, "Radius"):
            cylindrical_faces.append(f"Face{i}")

    if not cylindrical_faces:
        # Fallback: apply reaction to all non-fixed faces.
        cylindrical_faces = [name for name in face_names if name != fixed_face_name]

    if FreeCAD.GuiUp:
        beam.ViewObject.hide()
        cutout.ViewObject.hide()
        geom_obj.ViewObject.Document.activeView().viewAxonometric()
        geom_obj.ViewObject.Document.activeView().fitAll()

    # analysis
    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")

    # solver
    if solvertype == "ccxtools":
        solver_obj = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiXCcxTools")
        solver_obj.WorkingDir = ""
        solver_obj.SplitInputWriter = False
        solver_obj.AnalysisType = "static"
        solver_obj.GeometricalNonlinearity = False
        solver_obj.ThermoMechSteadyState = False
        solver_obj.MatrixSolverType = "default"
        solver_obj.IterationsControlParameterTimeUse = False
        analysis.addObject(solver_obj)
    else:
        FreeCAD.Console.PrintWarning(
            "Unknown or unsupported solver type: {}. "
            "No solver object was created.\n".format(solvertype)
        )

    # shell thickness + material for 2D face mesh setup
    thickness_obj = ObjectsFem.makeElementGeometry2D(
        doc,
        1.0,
        "ShellThickness",
    )
    analysis.addObject(thickness_obj)

    material_obj = ObjectsFem.makeMaterialSolid(doc, "FemMaterial")
    mat = material_obj.Material
    mat["Name"] = "Steel-Generic"
    mat["YoungsModulus"] = "200000 MPa"
    mat["PoissonRatio"] = "0.30"
    material_obj.Material = mat
    analysis.addObject(material_obj)

    # constraint fixed
    con_fixed = ObjectsFem.makeConstraintFixed(doc, "ConstraintFixed")
    con_fixed.References = [(geom_obj, fixed_face_name)]
    analysis.addObject(con_fixed)

    # reaction constraint
    con_reaction = ObjectsFem.makeConstraintReaction(doc, "ConstraintReaction")
    con_reaction.ModelType = "Cosine"
    con_reaction.Force = FreeCAD.Vector(0, 0, -2000)
    con_reaction.Torque = FreeCAD.Vector(10, 0, 0)
    con_reaction.Origin = FreeCAD.Placement(
        FreeCAD.Vector(4000, 1000, 1000),
        FreeCAD.Rotation(),
    )
    con_reaction.References = [(geom_obj, face_name) for face_name in cylindrical_faces]
    analysis.addObject(con_reaction)

    # mesh
    femmesh_obj = analysis.addObject(
        ObjectsFem.makeMeshGmsh(doc, get_meshname())
    )[0]
    femmesh_obj.Shape = geom_obj
    femmesh_obj.SecondOrderLinear = False
    femmesh_obj.ElementDimension = "2D"
    femmesh_obj.CharacteristicLengthMax = "250 mm"

    from femmesh.gmshtools import GmshTools

    gmsh_mesh = GmshTools(femmesh_obj)
    gmsh_mesh.create_mesh()

    doc.recompute()

    if FreeCAD.GuiUp:
        geom_obj.ViewObject.Document.activeView().viewAxonometric()
        geom_obj.ViewObject.Document.activeView().fitAll()

    return doc
