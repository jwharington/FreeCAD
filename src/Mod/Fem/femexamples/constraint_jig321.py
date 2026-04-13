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
        "name": "Constraint Jig 3-2-1",
        "meshtype": "solid",
        "meshelement": "Tet10",
        "constraints": ["jig321", "pressure"],
        "solvers": ["ccxtools"],
        "material": "solid",
        "equations": ["mechanical"],
    }


def get_explanation(header=""):
    return header + """

To run the example from Python console use:
from femexamples.constraint_jig321 import setup
setup()

This example uses a 3-2-1 jig as boundary condition and a pressure load.

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

    # geometric object
    geom_obj = doc.addObject("Part::Box", "Box")
    geom_obj.Length = 4000
    geom_obj.Width = 1000
    geom_obj.Height = 1000
    doc.recompute()
    if FreeCAD.GuiUp:
        geom_obj.ViewObject.Document.activeView().viewAxonometric()
        geom_obj.ViewObject.Document.activeView().fitAll()

    # analysis
    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")

    # solver
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

    # material
    material_obj = ObjectsFem.makeMaterialSolid(doc, "FemMaterial")
    mat = material_obj.Material
    mat["Name"] = "CalculiX-Steel"
    mat["YoungsModulus"] = "210000 MPa"
    mat["PoissonRatio"] = "0.30"
    mat["Density"] = "7900 kg/m^3"
    material_obj.Material = mat
    analysis.addObject(material_obj)

    # load
    con_pressure = ObjectsFem.makeConstraintPressure(doc, "ConstraintPressure")
    con_pressure.Pressure = "2 MPa"
    con_pressure.References = [(geom_obj, "Face2")]
    analysis.addObject(con_pressure)

    # 3-2-1 jig support
    con_jig321 = ObjectsFem.makeConstraintJig321(doc, "ConstraintJig321")
    con_jig321.References = [(geom_obj, "Face1")]
    con_jig321.CenterOfMass = FreeCAD.Vector(2000, 500, 500)
    con_jig321.LinearVelocity = FreeCAD.Vector(0, 0, 0)
    con_jig321.AngularVelocity = FreeCAD.Vector(0, 0, 0)
    con_jig321.LinearAcceleration = FreeCAD.Vector(0, 0, -9810)
    analysis.addObject(con_jig321)

    # mesh
    femmesh_obj = analysis.addObject(
        ObjectsFem.makeMeshGmsh(doc, get_meshname())
    )[0]
    femmesh_obj.Shape = geom_obj
    femmesh_obj.SecondOrderLinear = False
    femmesh_obj.ElementDimension = "3D"
    femmesh_obj.CharacteristicLengthMax = "250 mm"

    from femmesh import meshtools
    from femmesh.gmshtools import GmshTools

    gmsh_mesh = GmshTools(femmesh_obj)
    gmsh_mesh.create_mesh()

    # Precompute 3-2-1 support nodes for immediate marker visualization.
    if meshtools.is_solid_femmesh(femmesh_obj.FemMesh):
        support_nodes = set()
        ref_objects = {ref[0] for ref in con_jig321.References}
        for robj in ref_objects:
            for i, _ in enumerate(robj.Shape.Faces, start=1):
                face = meshtools.sub_shape_at_global_placement(
                    robj,
                    f"Face{i}",
                )
                support_nodes.update(
                    meshtools.get_nodes_by_face_with_fallback(
                        femmesh_obj.FemMesh,
                        face,
                    )
                )
        support_nodes = sorted(support_nodes)
    else:
        support_nodes = meshtools.get_femnodes_by_references(
            femmesh_obj.FemMesh,
            con_jig321.References,
        )
    con_jig321.Proxy.find_largest_triangle(
        con_jig321,
        femmesh_obj.FemMesh,
        support_nodes,
    )

    doc.recompute()

    if FreeCAD.GuiUp:
        geom_obj.ViewObject.Document.activeView().viewAxonometric()
        geom_obj.ViewObject.Document.activeView().fitAll()

    return doc
