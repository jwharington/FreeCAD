# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2026                                                     *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# ***************************************************************************

import FreeCAD

import ObjectsFem

from . import manager
from .manager import get_meshname
from .manager import init_doc
from .meshes import generate_mesh


def get_information():
    return {
        "name": "Orthotropic shell with material LCS",
        "meshtype": "face",
        "meshelement": "Tria6",
        "constraints": ["fixed", "force"],
        "solvers": ["ccxtools"],
        "material": "orthotropic",
        "equations": ["mechanical"],
    }


def get_explanation(header=""):
    return (
        header
        + """

To run the example from Python console use:
from femexamples.material_orthotropic_shell_lcs import setup
setup()

This example exercises fem-orthotropic shell material paths:
- engineering-constants orthotropic material fields in Fem::MaterialCommon
- LocalCoordinateSystem wiring for orthotropic orientation
- shell thickness + shell mesh export path used by CalculiX writer

"""
    )


def setup(doc=None, solvertype="ccxtools"):

    if doc is None:
        doc = init_doc()

    manager.add_explanation_obj(doc, get_explanation(manager.get_header(get_information())))

    geom_obj = doc.addObject("Part::Plane", "OrthoShellFace")
    geom_obj.Width = 3000
    geom_obj.Length = 12000
    doc.recompute()

    if FreeCAD.GuiUp:
        geom_obj.ViewObject.Document.activeView().viewAxonometric()
        geom_obj.ViewObject.Document.activeView().fitAll()

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")

    if solvertype == "ccxtools":
        solver_obj = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiXCcxTools")
        solver_obj.WorkingDir = ""
        solver_obj.AnalysisType = "static"
        solver_obj.ModelSpace = "3D"
        solver_obj.SplitInputWriter = False
    else:
        FreeCAD.Console.PrintWarning(
            "Unknown or unsupported solver type: {}. Falling back to ccxtools.\n".format(
                solvertype
            )
        )
        solver_obj = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiXCcxTools")
        solver_obj.WorkingDir = ""
        solver_obj.AnalysisType = "static"
        solver_obj.ModelSpace = "3D"
        solver_obj.SplitInputWriter = False

    analysis.addObject(solver_obj)

    shell_obj = ObjectsFem.makeElementGeometry2D(doc, 8.0, "ShellThickness")
    shell_obj.References = [(geom_obj, "Face1")]
    analysis.addObject(shell_obj)

    # Use a simple geometric object as LCS anchor. GeoFeature-based objects provide
    # getGlobalPlacement(), which FEM uses for orthotropic orientation export.
    lcs_obj = doc.addObject("Part::Feature", "MaterialLCS")
    lcs_obj.Placement = FreeCAD.Placement(
        FreeCAD.Vector(0, 0, 0),
        FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 35),
    )

    material_obj = ObjectsFem.makeMaterialSolid(doc, "OrthotropicMaterial")
    mat = material_obj.Material
    mat["Name"] = "Orthotropic-CarbonLike"
    mat["YoungsModulusX"] = "135000 MPa"
    mat["YoungsModulusY"] = "9500 MPa"
    mat["YoungsModulusZ"] = "9500 MPa"
    mat["PoissonRatioXY"] = "0.28"
    mat["PoissonRatioXZ"] = "0.28"
    mat["PoissonRatioYZ"] = "0.45"
    mat["ShearModulusXY"] = "5200 MPa"
    mat["ShearModulusXZ"] = "5200 MPa"
    mat["ShearModulusYZ"] = "3300 MPa"
    material_obj.Material = mat
    material_obj.References = [(geom_obj, "Face1")]
    material_obj.LocalCoordinateSystem = lcs_obj
    analysis.addObject(material_obj)

    con_fixed = ObjectsFem.makeConstraintFixed(doc, "ConstraintFixed")
    con_fixed.References = [(geom_obj, "Edge1")]
    analysis.addObject(con_fixed)

    con_force = ObjectsFem.makeConstraintForce(doc, "ConstraintForce")
    con_force.References = [(geom_obj, "Edge3")]
    con_force.Force = "1200000 N"
    con_force.Direction = (geom_obj, ["Edge3"])
    con_force.Reversed = True
    analysis.addObject(con_force)

    from .meshes.mesh_canticcx_tria6 import create_nodes, create_elements

    fem_mesh = generate_mesh.mesh_from_existing(create_nodes, create_elements)
    femmesh_obj = analysis.addObject(ObjectsFem.makeMeshGmsh(doc, get_meshname()))[0]
    femmesh_obj.FemMesh = fem_mesh
    femmesh_obj.Shape = geom_obj
    femmesh_obj.SecondOrderLinear = False
    femmesh_obj.ElementDimension = "2D"

    doc.recompute()
    return doc
