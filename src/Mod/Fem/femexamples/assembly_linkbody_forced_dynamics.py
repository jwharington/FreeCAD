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

import AssemblyApp  # noqa: F401  # type: ignore[import-not-found]
import FreeCAD  # type: ignore[import-not-found]
import ObjectsFem
import UtilsAssembly  # noqa: F401  # type: ignore[import-not-found]
from FemLink import (
    UtilsAnalysis as _UtilsAnalysis,  # type: ignore[import-not-found]
)
from FemLink.LinkBody import LinkBody  # type: ignore[import-not-found]
from FemLink.ViewLinkBody import VPLinkBody  # type: ignore[import-not-found]
from femmesh.gmshtools import GmshTools
from JointObject import (  # type: ignore[import-not-found]
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
from MotionObject import Motion as _MotionClass
from MotionObject import ViewProviderMotion
from SimulationObject import Simulation as _SimClass
from ViewProviderSimulation import ViewProviderSimulation

from . import manager
from .manager import get_meshname, init_doc

if FreeCAD.GuiUp:
    import FreeCADGui as FreeCADGuiMod  # type: ignore[import-not-found]
else:
    FreeCADGuiMod = None


def _find_cylindrical_face_name(shape_obj, target_radius=None, prefer_max_x=False):
    """Return a cylindrical face name, optionally matching radius and max-x location."""
    try:
        faces = shape_obj.Shape.Faces
    except Exception:
        return "Face1"

    candidates = []
    for idx, face in enumerate(faces, start=1):
        surface = getattr(face, "Surface", None)
        if surface is None or not hasattr(surface, "Radius"):
            continue

        if target_radius is not None:
            try:
                if abs(float(surface.Radius) - float(target_radius)) >= 1.0e-6:
                    continue
            except Exception:
                continue

        if prefer_max_x:
            try:
                key_x = float(face.CenterOfMass.x)
            except Exception:
                key_x = float("-inf")
            candidates.append((key_x, idx))
        else:
            return f"Face{idx}"

    if candidates:
        _, best_idx = max(candidates, key=lambda item: item[0])
        return f"Face{best_idx}"

    return "Face1"


def create_and_run_simulation(
    assembly, driver_joint, motion_formula="40*time", time_end=0.3, time_step=0.1
):
    """Create and run an Assembly kinematic simulation.  Works headless and in GUI."""
    try:
        sim_group = UtilsAssembly.getSimulationGroup(assembly)
        simulation = sim_group.newObject("App::FeaturePython", "Simulation")

        _SimClass(simulation)  # sets Proxy, adds extension and properties
        if FreeCAD.GuiUp:
            ViewProviderSimulation(simulation.ViewObject)

        # Re-set desired values (CommandCreateSimulation.Simulation sets its own defaults)
        simulation.aTimeStart = 0.0
        simulation.bTimeEnd = time_end
        simulation.cTimeStepOutput = time_step
        simulation.fGlobalErrorTolerance = 1.0e-6
        simulation.jFramesPerSecond = 30
        simulation.Dynamic = False

        if driver_joint is not None:
            motion = assembly.newObject("App::FeaturePython", "Motion")
            _MotionClass(motion, motionType="Linear")  # sets Proxy + creates properties
            if FreeCAD.GuiUp:
                ViewProviderMotion(motion.ViewObject)
            motion.MotionType = "Linear"
            try:
                motion.Joint = (driver_joint, [])
            except Exception:
                motion.Joint = driver_joint
            motion.Formula = motion_formula
            motions = simulation.Group
            motions.append(motion)
            simulation.Group = motions
        else:
            FreeCAD.Console.PrintWarning(
                "No driver joint available for motion; running kinematic simulation without motion.\n"
            )

        assembly.generateSimulation(simulation)
        return simulation, assembly.numberOfFrames()
    except Exception as exc:
        FreeCAD.Console.PrintWarning(
            f"Kinematic simulation setup/run failed: {exc}\n"
        )
        return None, 0


# Keep old name as alias for backward compatibility
_create_and_run_kinematic_simulation = create_and_run_simulation


def get_information():
    return {
        "name": "Assembly LinkBody – Forced Dynamics (Prismatic Driven Linkage)",
        "meshtype": "solid",
        "meshelement": "Tet10",
        "constraints": ["quasi-static"],
        "solvers": ["ccxtools"],
        "material": "solid",
        "equations": ["mechanical"],
    }


def get_explanation(header=""):
    return header + """

To run the example from Python console use:
from femexamples.assembly_linkbody_forced_dynamics import setup
setup()
setup(connect_joints=False)  # pre-connection placement inspection view

This example demonstrates a forced (kinematic) Assembly simulation where a
prismatic actuator drives a slider/rod linkage between a grounded anchor and a
bearing surface at the pendulum free end. The pendulum also keeps the same
main cylindrical pivot arrangement as the free pendulum example.

The pendulum LinkBody transfers assembly joint loads into FEM constraints and
runs full FEM analysis for stored load cases.

IMPORTANT:
This example intentionally does not create explicit Jig321/Reaction FEM
constraints. Those are generated by the LinkBody load-case pipeline, matching
TaskAssemblyLinkBody production behavior.

"""


def setup(
    doc=None,
    solvertype="ccxtools",
    exercise_loadcases=True,
    connect_joints=True,
):
    if doc is None:
        doc = init_doc()

    manager.add_explanation_obj(
        doc,
        get_explanation(manager.get_header(get_information())),
    )

    housing_shape = doc.addObject("Part::Cylinder", "HousingShape")
    housing_shape.Label = "HousingShape"
    housing_shape.Radius = 12.5
    housing_shape.Height = 50

    pendulum_base = doc.addObject("Part::Box", "PendulumBase")
    pendulum_base.Label = "PendulumBase"
    pendulum_base.Length = 525
    pendulum_base.Width = 50
    pendulum_base.Height = 50
    pendulum_base.Placement = FreeCAD.Placement(
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

    actuator_pin_radius = 8.0
    free_end_x = 475.0
    free_end_y = 25.0
    free_end_z = 25.0

    free_end_cutter = doc.addObject("Part::Cylinder", "FreeEndCutter")
    free_end_cutter.Label = "FreeEndCutter"
    free_end_cutter.Radius = actuator_pin_radius
    free_end_cutter.Height = 50
    free_end_cutter.Placement = FreeCAD.Placement(
        FreeCAD.Vector(free_end_x, 0, free_end_z),
        FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90),
    )

    pendulum_cutters = doc.addObject("Part::MultiFuse", "PendulumCutters")
    pendulum_cutters.Label = "PendulumCutters"
    pendulum_cutters.Shapes = [housing_cutter, free_end_cutter]

    pendulum_shape = doc.addObject("Part::Cut", "PendulumShape")
    pendulum_shape.Label = "PendulumShape"
    pendulum_shape.Base = pendulum_base
    pendulum_shape.Tool = pendulum_cutters

    anchor_shape = doc.addObject("Part::Box", "AnchorShape")
    anchor_shape.Label = "AnchorShape"
    anchor_shape.Length = 60
    anchor_shape.Width = 70
    anchor_shape.Height = 70
    anchor_shape.Placement = FreeCAD.Placement(
        FreeCAD.Vector(0, 0, 0),
        FreeCAD.Rotation(),
    )

    slider_shape = doc.addObject("Part::Box", "SliderShape")
    slider_shape.Label = "SliderShape"
    slider_shape.Length = 80
    slider_shape.Width = 40
    slider_shape.Height = 40
    slider_shape.Placement = FreeCAD.Placement(
        FreeCAD.Vector(0, 0, 0),
        FreeCAD.Rotation(),
    )

    rod_shape = doc.addObject("Part::Box", "RodShape")
    rod_shape.Label = "RodShape"
    rod_shape.Length = 20
    rod_shape.Width = 20
    rod_shape.Height = 450
    rod_shape.Placement = FreeCAD.Placement(
        FreeCAD.Vector(0, 0, 0),
        FreeCAD.Rotation(),
    )

    doc.recompute()
    reaction_face_name = _find_cylindrical_face_name(pendulum_shape, housing_shape.Radius)
    free_end_face_name = _find_cylindrical_face_name(
        pendulum_shape,
        actuator_pin_radius,
        prefer_max_x=True,
    )
    FreeCAD.Console.PrintMessage(f"[LinkBody] Reaction face selected: {reaction_face_name}\n")
    FreeCAD.Console.PrintMessage(f"[LinkBody] Free-end bearing face selected: {free_end_face_name}\n")

    if FreeCAD.GuiUp:
        pendulum_shape.ViewObject.Visibility = False
        pendulum_base.ViewObject.Visibility = False
        housing_cutter.ViewObject.Visibility = False
        free_end_cutter.ViewObject.Visibility = False
        pendulum_cutters.ViewObject.Visibility = False
        housing_shape.ViewObject.Visibility = False
        anchor_shape.ViewObject.Visibility = False
        slider_shape.ViewObject.Visibility = False
        rod_shape.ViewObject.Visibility = False

    assembly = doc.addObject("Assembly::AssemblyObject", "ForcedPendulumAssembly")
    assembly.Label = "ForcedPendulumAssembly"

    housing_link = assembly.newObject("App::Link", "Housing")
    housing_link.LinkedObject = housing_shape
    housing_link.Placement = FreeCAD.Placement(
        FreeCAD.Vector(0, 0, 25),
        FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90),
    )

    pendulum_link = assembly.newObject("App::Link", "Pendulum")
    pendulum_link.LinkedObject = pendulum_shape
    pendulum_link.Placement = FreeCAD.Placement(
        FreeCAD.Vector(0, 0, 0),
        FreeCAD.Rotation(),
    )

    anchor_center_z = -500.0
    slider_center_z = -445.0
    rod_base_z = -425.0

    anchor_link = assembly.newObject("App::Link", "Anchor")
    anchor_link.LinkedObject = anchor_shape
    anchor_link.Placement = FreeCAD.Placement(
        FreeCAD.Vector(
            free_end_x - 0.5 * float(anchor_shape.Length),
            free_end_y - 0.5 * float(anchor_shape.Width),
            anchor_center_z - 0.5 * float(anchor_shape.Height),
        ),
        FreeCAD.Rotation(),
    )

    slider_link = assembly.newObject("App::Link", "ActuatorSlider")
    slider_link.LinkedObject = slider_shape
    slider_link.Placement = FreeCAD.Placement(
        FreeCAD.Vector(
            free_end_x - 0.5 * float(slider_shape.Length),
            free_end_y - 0.5 * float(slider_shape.Width),
            slider_center_z - 0.5 * float(slider_shape.Height),
        ),
        FreeCAD.Rotation(),
    )

    rod_link = assembly.newObject("App::Link", "ActuatorRod")
    rod_link.LinkedObject = rod_shape
    rod_link.Placement = FreeCAD.Placement(
        FreeCAD.Vector(
            free_end_x - 0.5 * float(rod_shape.Length),
            free_end_y - 0.5 * float(rod_shape.Width),
            rod_base_z,
        ),
        FreeCAD.Rotation(),
    )

    if connect_joints:
        joint_group = assembly.newObject("Assembly::JointGroup", "Joints")

        ground_joint = joint_group.newObject("App::FeaturePython", "GroundedJoint")
        ground_joint.Label = "GroundedJoint"
        _GroundedJoint(ground_joint, housing_link)
        if FreeCAD.GuiUp:
            _VPGroundedJoint(ground_joint.ViewObject)

        anchor_ground_joint = joint_group.newObject("App::FeaturePython", "AnchorGroundedJoint")
        anchor_ground_joint.Label = "AnchorGroundedJoint"
        _GroundedJoint(anchor_ground_joint, anchor_link)
        if FreeCAD.GuiUp:
            _VPGroundedJoint(anchor_ground_joint.ViewObject)

        cyl_joint = joint_group.newObject("App::FeaturePython", "PendulumRevolute")
        cyl_joint.Label = "PendulumRevolute"
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

        slider_joint = joint_group.newObject("App::FeaturePython", "AnchorToSliderRevolute")
        slider_joint.Label = "AnchorToSliderRevolute"
        _Joint(slider_joint, 1)
        if FreeCAD.GuiUp:
            _VPJoint(slider_joint.ViewObject)
        slider_joint.Detach1 = True
        slider_joint.Detach2 = True
        slider_joint.Placement1 = FreeCAD.Placement(
            FreeCAD.Vector(30, 35, 70),
            FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90),
        )
        slider_joint.Placement2 = FreeCAD.Placement(
            FreeCAD.Vector(40, 20, 0),
            FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90),
        )

        slider_rod_joint = joint_group.newObject("App::FeaturePython", "SliderToRodPrismatic")
        slider_rod_joint.Label = "SliderToRodPrismatic"
        _Joint(slider_rod_joint, 3)
        if FreeCAD.GuiUp:
            _VPJoint(slider_rod_joint.ViewObject)
        slider_rod_joint.Detach1 = True
        slider_rod_joint.Detach2 = True
        slider_rod_joint.Placement1 = FreeCAD.Placement(
            FreeCAD.Vector(40, 20, 40),
            FreeCAD.Rotation(),
        )
        slider_rod_joint.Placement2 = FreeCAD.Placement(
            FreeCAD.Vector(10, 10, 0),
            FreeCAD.Rotation(),
        )

        rod_pendulum_joint = joint_group.newObject("App::FeaturePython", "RodToPendulumSpherical")
        rod_pendulum_joint.Label = "RodToPendulumSpherical"
        _Joint(rod_pendulum_joint, 4)
        if FreeCAD.GuiUp:
            _VPJoint(rod_pendulum_joint.ViewObject)
        rod_pendulum_joint.Detach1 = True
        rod_pendulum_joint.Detach2 = True
        rod_pendulum_joint.Placement1 = FreeCAD.Placement(
            FreeCAD.Vector(10, 10, 450),
            FreeCAD.Rotation(),
        )
        rod_pendulum_joint.Placement2 = FreeCAD.Placement(
            FreeCAD.Vector(free_end_x, free_end_y, free_end_z),
            FreeCAD.Rotation(),
        )

        cyl_joint.Proxy.setJointConnectors(
            cyl_joint,
            [[housing_link, ["Face1"]], [pendulum_link, [reaction_face_name]]],
        )
        slider_joint.Proxy.setJointConnectors(
            slider_joint,
            [[anchor_link, ["Face6"]], [slider_link, ["Face5"]]],
        )
        slider_rod_joint.Proxy.setJointConnectors(
            slider_rod_joint,
            [[slider_link, ["Face6"]], [rod_link, ["Face5"]]],
        )
        rod_pendulum_joint.Proxy.setJointConnectors(
            rod_pendulum_joint,
            [[rod_link, ["Face6"]], [pendulum_link, [free_end_face_name]]],
        )
    else:
        slider_rod_joint = None
        FreeCAD.Console.PrintMessage(
            "[Layout] connect_joints=False: leaving parts unconnected in assembly for placement inspection.\n"
        )

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis_PendulumShape")
    analysis.Label = "Analysis PendulumShape"

    if solvertype == "ccxtools":
        solver_obj = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiXCcxTools")
        solver_obj.SplitInputWriter = False
        solver_obj.AnalysisType = "static"
        solver_obj.GeometricalNonlinearity = False
        solver_obj.ThermoMechSteadyState = False
        solver_obj.MatrixSolverType = "default"
        solver_obj.IterationsControlParameterTimeUse = False
        solver_obj.WorkingDir = ""
        analysis.addObject(solver_obj)

    material_obj = ObjectsFem.makeMaterialSolid(doc, "FemMaterial")
    mat = material_obj.Material
    mat["Name"] = "Steel-Generic"
    mat["YoungsModulus"] = "210000 MPa"
    mat["PoissonRatio"] = "0.30"
    mat["Density"] = "7900 kg/m^3"
    material_obj.Material = mat
    analysis.addObject(material_obj)

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

    if exercise_loadcases and connect_joints:
        _, n_frames = create_and_run_simulation(assembly, slider_rod_joint)
        summary = _UtilsAnalysis.exercise_load_case_pipeline(
            assembly,
            linkbody_fp,
            dry_run=False,
        )
        FreeCAD.Console.PrintMessage(
            f"Assembly kinematic simulation frames: {n_frames}\n"
        )
        FreeCAD.Console.PrintMessage(
            "LinkBody load-case exercise: "
            f"states={summary['num_states']}, "
            f"full_hull={summary['full_hull_size']}, "
            f"reduced_hull={summary['reduced_hull_size']}\n"
        )
    elif not connect_joints:
        FreeCAD.Console.PrintWarning(
            "connect_joints=False: skipping load-case simulation/pipeline; "
            "assembly remains in pre-connection layout mode.\n"
        )
    else:
        FreeCAD.Console.PrintWarning(
            "exercise_loadcases=False: no LinkBody-generated Jig321/Reaction constraints "
            "were added to the FEM analysis.\n"
        )

    doc.recompute()

    if FreeCAD.GuiUp and connect_joints:
        try:
            assert FreeCADGuiMod is not None
            if FreeCADGuiMod.ActiveDocument is not None:
                FreeCADGuiMod.ActiveDocument.setEdit(assembly)
        except Exception:
            pass

    if FreeCAD.GuiUp:
        femmesh_obj.ViewObject.Visibility = True
        view = femmesh_obj.ViewObject.Document.activeView()
        view.viewFront()
        view.fitAll()

    return doc
