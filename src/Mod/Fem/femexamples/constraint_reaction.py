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
        "solvers": [],
        "material": "solid",
        "equations": ["mechanical"],
    }


def get_explanation(header=""):
    return header + """

To run the example from Python console use:
from femexamples.constraint_reaction import setup
setup()

This setup example shows how to define a reaction-based distributed
pressure constraint on selected faces.

"""


def setup(doc=None, solvertype=None):
    del solvertype

    # init FreeCAD document
    if doc is None:
        doc = init_doc()

    # explanation object
    manager.add_explanation_obj(
        doc,
        get_explanation(manager.get_header(get_information())),
    )

    # geometric object
    geom_obj = doc.addObject("Part::Box", "Box")
    geom_obj.Height = geom_obj.Width = 2000
    geom_obj.Length = 8000
    doc.recompute()
    if FreeCAD.GuiUp:
        geom_obj.ViewObject.Document.activeView().viewAxonometric()
        geom_obj.ViewObject.Document.activeView().fitAll()

    # analysis
    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")

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
    con_fixed.References = [(geom_obj, "Face1")]
    analysis.addObject(con_fixed)

    # reaction constraint
    con_reaction = ObjectsFem.makeConstraintReaction(doc, "ConstraintReaction")
    con_reaction.ModelType = "Cosine"
    con_reaction.Force = FreeCAD.Vector(0, 0, -2000000)
    con_reaction.Torque = FreeCAD.Vector(0, 500000000, 0)
    con_reaction.Origin = FreeCAD.Placement(
        FreeCAD.Vector(0, 1000, 1000),
        FreeCAD.Rotation(),
    )
    con_reaction.References = [
        (geom_obj, "Face2"),
        (geom_obj, "Face3"),
        (geom_obj, "Face4"),
        (geom_obj, "Face5"),
        (geom_obj, "Face6"),
    ]
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
    return doc
