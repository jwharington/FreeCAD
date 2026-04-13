# ***************************************************************************
# *   Copyright (c) 2026 John Wharington <jwharington@gmail.com>            *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

import os

import FreeCAD
import ObjectsFem

from . import manager
from .manager import get_meshname, init_doc


def get_information():
    return {
        "name": "Constraint Hydrostatic Pressure (Data File)",
        "meshtype": "face",
        "meshelement": "Tria6",
        "constraints": ["fixed", "hydrostaticpressure"],
        "solvers": ["ccxtools"],
        "material": "solid",
        "equations": ["mechanical"],
    }


def get_explanation(header=""):
    return header + """

To run the example from Python console use:
from femexamples.constraint_hydrostaticpressure_datafile import setup
setup()

This example configures the hydrostatic pressure constraint to read
pressure-distribution values from a CSV file.

"""


def setup(doc=None, solvertype="ccxtools"):

    if doc is None:
        doc = init_doc()

    manager.add_explanation_obj(
        doc,
        get_explanation(manager.get_header(get_information())),
    )

    geom_obj = doc.addObject("Part::Box", "Box")
    geom_obj.Height = geom_obj.Width = 2000
    geom_obj.Length = 8000
    doc.recompute()
    if FreeCAD.GuiUp:
        geom_obj.ViewObject.Document.activeView().viewAxonometric()
        geom_obj.ViewObject.Document.activeView().fitAll()

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")

    if solvertype == "ccxtools":
        solver_obj = ObjectsFem.makeSolverCalculiXCcxTools(
            doc,
            "CalculiXCcxTools",
        )
        solver_obj.WorkingDir = ""
    else:
        FreeCAD.Console.PrintWarning(
            "Unknown or unsupported solver type: {}. "
            "No solver object was created.\n".format(solvertype)
        )
    if solvertype == "ccxtools":
        solver_obj.SplitInputWriter = False
        solver_obj.AnalysisType = "static"
        solver_obj.GeometricalNonlinearity = False
        solver_obj.ThermoMechSteadyState = False
        solver_obj.MatrixSolverType = "default"
        solver_obj.IterationsControlParameterTimeUse = False
    analysis.addObject(solver_obj)

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

    con_fixed = ObjectsFem.makeConstraintFixed(doc, "ConstraintFixed")
    con_fixed.References = [(geom_obj, "Face1")]
    analysis.addObject(con_fixed)

    con_hydrostaticpressure = ObjectsFem.makeConstraintHydrostaticPressure(
        doc, "ConstraintHydrostaticPressure"
    )
    con_hydrostaticpressure.ModelType = "NearestNeighbour"
    con_hydrostaticpressure.BasePressureScale = "1 MPa"
    con_hydrostaticpressure.DataFile = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "constraint_hydrostaticpressure_datafile.csv",
    )
    con_hydrostaticpressure.References = [
        (geom_obj, "Face2"),
        (geom_obj, "Face3"),
        (geom_obj, "Face4"),
        (geom_obj, "Face5"),
        (geom_obj, "Face6"),
    ]
    analysis.addObject(con_hydrostaticpressure)

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
