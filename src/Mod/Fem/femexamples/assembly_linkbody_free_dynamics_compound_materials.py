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

import AssemblyApp  # noqa: F401
import FreeCAD
import ObjectsFem
import Part
import UtilsAssembly  # noqa: F401
from FemLink import UtilsAnalysis as _UtilsAnalysis
from FemLink.LinkBody import LinkBody
from FemLink.ViewLinkBody import VPLinkBody
from femmesh.gmshtools import GmshTools
from JointObject import (
    GroundedJoint as _GroundedJoint,
)
from JointObject import (
    Joint as _Joint,
)
from JointObject import (
    ViewProviderGroundedJoint as _VPGroundedJoint,
)
from JointObject import (
    ViewProviderJoint as _VPJoint,
)

from . import manager
from .assembly_linkbody_free_dynamics import (
    _find_cylindrical_face_name,
    create_and_run_simulation,
)
from .manager import get_meshname, init_doc

if FreeCAD.GuiUp:
    import FreeCADGui as FreeCADGuiMod
else:
    FreeCADGuiMod = None


def get_information():
    return {
        "name": "Assembly LinkBody - Free Dynamics Compound Pendulum",
        "meshtype": "solid",
        "meshelement": "Tet10",
        "constraints": ["quasi-static"],
        "solvers": ["ccxtools"],
        "material": "multimaterial",
        "equations": ["mechanical"],
    }


def get_explanation(header=""):
    return header + """

To run the example from Python console use:
from femexamples.assembly_linkbody_free_dynamics_compound_materials import setup
setup()

This example extends the free-dynamics LinkBody pendulum by building the
pendulum as a two-solid comp-solid with two distinct FEM materials:

    Solid1 (core arm) : steel
    Solid2 (tip block): aluminium

The assembly and LinkBody workflow is intentionally kept close to
assembly_linkbody_free_dynamics.py to provide a regression target for
mixed-material inertial export on one assembly body.

When `exercise_loadcases=True`, this example also exercises the same
LinkBody load-case pipeline used by TaskAssemblyLinkBody.
`loadcase_analysis_mode` selects full, reduced, or both analysis paths.

"""


def setup(
    doc=None,
    solvertype="ccxtools",
    exercise_loadcases=True,
    loadcase_analysis_mode="both",
    batch_mode=True,
    assembly_rotation_deg_x=0.0,
    assembly_shift_x=0.0,
    assembly_shift_y=0.0,
    assembly_shift_z=0.0,
):

    if doc is None:
        doc = init_doc()

    manager.add_explanation_obj(
        doc,
        get_explanation(manager.get_header(get_information())),
    )

    # Grounded bearing housing.
    housing_shape = doc.addObject("Part::Cylinder", "HousingShape")
    housing_shape.Label = "HousingShape"
    housing_shape.Radius = 12.5
    housing_shape.Height = 50

    # Pendulum core arm with bearing cutout.
    pendulum_core_base = doc.addObject("Part::Box", "PendulumCoreBase")
    pendulum_core_base.Label = "PendulumCoreBase"
    pendulum_core_base.Length = 300
    pendulum_core_base.Width = 50
    pendulum_core_base.Height = 50
    pendulum_core_base.Placement = FreeCAD.Placement(
        FreeCAD.Vector(-25, 0, 0),
        FreeCAD.Rotation(),
    )

    housing_cutter = doc.addObject("Part::Cylinder", "HousingCutter")
    housing_cutter.Label = "HousingCutter"
    housing_cutter.Radius = housing_shape.Radius
    housing_cutter.Height = 50
    housing_cutter.Placement = FreeCAD.Placement(
        FreeCAD.Vector(0, 0, 25),
        FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90),
    )

    pendulum_core_shape = doc.addObject("Part::Cut", "PendulumCoreShape")
    pendulum_core_shape.Label = "PendulumCoreShape"
    pendulum_core_shape.Base = pendulum_core_base
    pendulum_core_shape.Tool = housing_cutter

    # Tip block made as a separate solid for mixed-material assignment.
    pendulum_tip_shape = doc.addObject("Part::Box", "PendulumTipShape")
    pendulum_tip_shape.Label = "PendulumTipShape"
    pendulum_tip_shape.Length = 225
    pendulum_tip_shape.Width = 40
    pendulum_tip_shape.Height = 40
    pendulum_tip_shape.Placement = FreeCAD.Placement(
        FreeCAD.Vector(275, 5, 5),
        FreeCAD.Rotation(),
    )

    # Ensure generated parametric primitives have valid TopoShapes before
    # constructing the compound body used for material sub-shape references.
    doc.recompute()

    core_shape = pendulum_core_shape.Shape.copy()
    tip_shape = pendulum_tip_shape.Shape.copy()
    if core_shape.isNull() or tip_shape.isNull():
        raise RuntimeError(
            "Compound pendulum source shape is null after recompute. "
            "Cannot assign per-solid materials."
        )

    # Keep the pendulum as one assembly body while preserving two solid regions.
    # Use Part::Feature to avoid Part::Compound view-provider instability in GUI/MCP.
    pendulum_shape = doc.addObject("Part::Feature", "PendulumShape")
    pendulum_shape.Shape = Part.makeCompound([core_shape, tip_shape])

    doc.recompute()
    solid_count = len(getattr(pendulum_shape.Shape, "Solids", []))
    if solid_count < 2:
        raise RuntimeError(
            "Compound pendulum generated fewer than two solids; "
            "mixed-material Solid1/Solid2 references are invalid."
        )

    reaction_face_name = _find_cylindrical_face_name(pendulum_shape, housing_shape.Radius)
    FreeCAD.Console.PrintMessage(f"[LinkBody] Reaction face selected: {reaction_face_name}\n")

    if FreeCAD.GuiUp:
        pendulum_shape.ViewObject.Visibility = False
        housing_shape.ViewObject.Visibility = False
        pendulum_core_base.ViewObject.Visibility = False
        housing_cutter.ViewObject.Visibility = False
        pendulum_core_shape.ViewObject.Visibility = False
        pendulum_tip_shape.ViewObject.Visibility = False

    assembly_rot_x = FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), float(assembly_rotation_deg_x))
    assembly_shift = FreeCAD.Vector(
        float(assembly_shift_x),
        float(assembly_shift_y),
        float(assembly_shift_z),
    )

    assembly = doc.addObject("Assembly::AssemblyObject", "PendulumAssembly")
    assembly.Label = "PendulumAssembly"

    housing_link = assembly.newObject("App::Link", "Housing")
    housing_link.LinkedObject = housing_shape
    housing_link.Placement = FreeCAD.Placement(
        FreeCAD.Vector(-25, 0, 0) + assembly_shift,
        assembly_rot_x.multiply(FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90)),
    )
    if abs(float(assembly_rotation_deg_x)) > 1.0e-12:
        FreeCAD.Console.PrintMessage(
            f"[LinkBody] Assembly pre-rotation about X: {float(assembly_rotation_deg_x):.3f} deg\n"
        )
    if assembly_shift.Length > 1.0e-12:
        FreeCAD.Console.PrintMessage(
            "[LinkBody] Assembly shift (mm): "
            f"({assembly_shift.x:.3f},{assembly_shift.y:.3f},{assembly_shift.z:.3f})\n"
        )

    pendulum_link = assembly.newObject("App::Link", "Pendulum")
    pendulum_link.LinkedObject = pendulum_shape
    pendulum_link.Placement = FreeCAD.Placement(
        FreeCAD.Vector(0, 0, 0) + assembly_shift,
        assembly_rot_x.multiply(FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 45)),
    )

    joint_group = assembly.newObject("Assembly::JointGroup", "Joints")

    ground_joint = joint_group.newObject("App::FeaturePython", "GroundedJoint")
    ground_joint.Label = "GroundedJoint"
    _GroundedJoint(ground_joint, housing_link)
    if FreeCAD.GuiUp:
        _VPGroundedJoint(ground_joint.ViewObject)

    cyl_joint = joint_group.newObject("App::FeaturePython", "RevoluteJoint")
    cyl_joint.Label = "RevoluteJoint"
    _Joint(cyl_joint, 1)
    if FreeCAD.GuiUp:
        _VPJoint(cyl_joint.ViewObject)
    cyl_joint.Detach1 = True
    cyl_joint.Detach2 = True
    cyl_joint.Placement1 = FreeCAD.Placement(
        FreeCAD.Vector(0, 0, 25),
        FreeCAD.Rotation(),
    )
    cyl_joint.Placement2 = FreeCAD.Placement(
        FreeCAD.Vector(0, 25, 25),
        FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90),
    )

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis_PendulumShape")
    analysis.Label = "Analysis PendulumCompoundShape"

    cyl_joint.Proxy.setJointConnectors(
        cyl_joint,
        [
            [housing_link, ["Face1"]],
            [pendulum_link, [reaction_face_name]],
        ],
    )

    if solvertype == "ccxtools":
        solver_obj = ObjectsFem.makeSolverCalculiXCcxTools(
            doc,
            "CalculiXCcxTools",
        )
        solver_obj.SplitInputWriter = False
        solver_obj.AnalysisType = "static"
        solver_obj.GeometricalNonlinearity = False
        solver_obj.ThermoMechSteadyState = False
        solver_obj.MatrixSolverType = "default"
        solver_obj.IterationsControlParameterTimeUse = False
        solver_obj.WorkingDir = ""
        analysis.addObject(solver_obj)
    else:
        FreeCAD.Console.PrintWarning(
            "Unknown or unsupported solver type: {}. "
            "No solver object was created.\n".format(solvertype)
        )

    material_obj_core = ObjectsFem.makeMaterialSolid(doc, "FemMaterialCore")
    mat = material_obj_core.Material
    mat["Name"] = "Steel-Core"
    mat["YoungsModulus"] = "210000 MPa"
    mat["PoissonRatio"] = "0.30"
    mat["Density"] = "7900 kg/m^3"
    material_obj_core.Material = mat
    material_obj_core.References = [(pendulum_shape, "Solid1")]
    analysis.addObject(material_obj_core)

    material_obj_tip = ObjectsFem.makeMaterialSolid(doc, "FemMaterialTip")
    mat = material_obj_tip.Material
    mat["Name"] = "Aluminium-Tip"
    mat["YoungsModulus"] = "70000 MPa"
    mat["PoissonRatio"] = "0.33"
    mat["Density"] = "2700 kg/m^3"
    material_obj_tip.Material = mat
    material_obj_tip.References = [(pendulum_shape, "Solid2")]
    analysis.addObject(material_obj_tip)

    femmesh_obj = analysis.addObject(
        ObjectsFem.makeMeshGmsh(doc, get_meshname())
    )[0]
    femmesh_obj.Shape = pendulum_shape
    femmesh_obj.SecondOrderLinear = False
    femmesh_obj.ElementDimension = "3D"
    femmesh_obj.CharacteristicLengthMax = "100 mm"

    gmsh_mesh = GmshTools(femmesh_obj)
    gmsh_mesh.create_mesh()

    linkbody_fp = doc.addObject("App::FeaturePython", "LinkBody_Pendulum")
    linkbody_fp.Label = "LinkBody_Pendulum"
    LinkBody(linkbody_fp, pendulum_link)
    if FreeCAD.GuiUp:
        VPLinkBody(linkbody_fp.ViewObject)
    assembly.addObject(linkbody_fp)

    if exercise_loadcases:
        _, n_frames = create_and_run_simulation(
            assembly,
            cyl_joint,
            motion_formula="",
        )
        summary = _UtilsAnalysis.exercise_load_case_pipeline(
            assembly,
            linkbody_fp,
            dry_run=False,
            batch_mode=batch_mode,
            analysis_mode=loadcase_analysis_mode,
        )
        FreeCAD.Console.PrintMessage(
            f"Assembly dynamic simulation frames: {n_frames}\n"
        )
        FreeCAD.Console.PrintMessage(
            "LinkBody load-case exercise: "
            f"mode={loadcase_analysis_mode}, "
            f"states={summary['num_states']}, "
            f"full_hull={summary['full_hull_size']}, "
            f"reduced_hull={summary['reduced_hull_size']}\n"
        )
    else:
        FreeCAD.Console.PrintWarning(
            "exercise_loadcases=False: no LinkBody-generated Jig321/Reaction constraints "
            "were added to the FEM analysis.\n"
        )

    doc.recompute()

    if FreeCAD.GuiUp:
        try:
            FreeCADGuiMod.ActiveDocument.setEdit(assembly)
        except Exception:
            pass
        cyl_joint.Placement1 = FreeCAD.Placement(
            FreeCAD.Vector(0, 0, 25),
            FreeCAD.Rotation(),
        )
        cyl_joint.Placement2 = FreeCAD.Placement(
            FreeCAD.Vector(0, 25, 25),
            FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90),
        )

    if FreeCAD.GuiUp:
        femmesh_obj.ViewObject.Visibility = True
        femmesh_obj.ViewObject.Document.activeView().viewAxonometric()
        femmesh_obj.ViewObject.Document.activeView().fitAll()

    return doc
