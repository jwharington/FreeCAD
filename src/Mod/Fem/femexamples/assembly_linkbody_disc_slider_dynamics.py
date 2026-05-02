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


def _find_cylindrical_face_name(shape_obj, target_radius=None):
    """Return the first cylindrical face name, optionally matching radius."""
    try:
        faces = shape_obj.Shape.Faces
    except Exception:
        return "Face1"

    for idx, face in enumerate(faces, start=1):
        surface = getattr(face, "Surface", None)
        if surface is None or not hasattr(surface, "Radius"):
            continue
        if target_radius is None:
            return f"Face{idx}"
        try:
            if abs(float(surface.Radius) - float(target_radius)) < 1.0e-6:
                return f"Face{idx}"
        except Exception:
            continue

    return "Face1"


def create_and_run_simulation(
    assembly,
    slider_joint=None,
    revolute_joint=None,
    slider_formula="",
    revolute_formula="30*time",
    time_end=0.3,
    time_step=0.1,
):
    """Create and run a dynamic assembly simulation with optional joint motions."""
    try:
        import UtilsAssembly

        sim_group = UtilsAssembly.getSimulationGroup(assembly)
        simulation = sim_group.newObject("App::FeaturePython", "Simulation")

        try:
            from CommandCreateSimulation import Simulation as _SimClass
            from CommandCreateSimulation import ViewProviderSimulation

            _SimClass(simulation)
            if FreeCAD.GuiUp:
                ViewProviderSimulation(simulation.ViewObject)
        except (ImportError, NameError):
            simulation.addExtension("App::GroupExtensionPython")

            class _MinimalSimProxy:
                def getAssembly(self, feaPy):
                    for obj in feaPy.InList:
                        if obj.isDerivedFrom("Assembly::AssemblyObject"):
                            return obj
                    return None

                def dumps(self):
                    return None

                def loads(self, state):
                    return None

                def execute(self, feaPy):
                    pass

                def onChanged(self, feaPy, prop):
                    pass

            simulation.Proxy = _MinimalSimProxy()
            for prop, ptype in [
                ("aTimeStart", "App::PropertyFloat"),
                ("bTimeEnd", "App::PropertyFloat"),
                ("cTimeStepOutput", "App::PropertyFloat"),
                ("fGlobalErrorTolerance", "App::PropertyFloat"),
                ("jFramesPerSecond", "App::PropertyInteger"),
                ("Dynamic", "App::PropertyBool"),
            ]:
                if not hasattr(simulation, prop):
                    simulation.addProperty(ptype, prop, "Simulation")

        simulation.aTimeStart = 0.0
        simulation.bTimeEnd = time_end
        simulation.cTimeStepOutput = time_step
        simulation.fGlobalErrorTolerance = 1.0e-6
        simulation.jFramesPerSecond = 30
        simulation.Dynamic = True

        def _attach_motion(joint_obj, motion_type, formula, motion_name):
            if joint_obj is None or not formula:
                return False

            motion = assembly.newObject("App::FeaturePython", motion_name)
            try:
                from CommandCreateSimulation import Motion as _MotionClass
                from CommandCreateSimulation import ViewProviderMotion

                _MotionClass(motion, motionType=motion_type)
                if FreeCAD.GuiUp:
                    ViewProviderMotion(motion.ViewObject)
            except (ImportError, NameError):
                class _MinimalMotionProxy:
                    def dumps(self):
                        return None

                    def loads(self, state):
                        return None

                    def execute(self, feaPy):
                        pass

                    def onChanged(self, feaPy, prop):
                        pass

                motion.Proxy = _MinimalMotionProxy()
                for prop, ptype in [
                    ("Joint", "App::PropertyXLinkSub"),
                    ("Formula", "App::PropertyString"),
                    ("MotionType", "App::PropertyEnumeration"),
                ]:
                    if not hasattr(motion, prop):
                        motion.addProperty(ptype, prop, "Motion")
                motion.MotionType = ["Angular", "Linear"]

            motion.MotionType = motion_type
            try:
                motion.Joint = (joint_obj, [])
            except Exception:
                motion.Joint = joint_obj
            motion.Formula = formula

            motions = simulation.Group
            motions.append(motion)
            simulation.Group = motions
            return True

        added_slider = _attach_motion(
            slider_joint,
            "Linear",
            slider_formula,
            "SliderMotion",
        )
        added_spin = _attach_motion(
            revolute_joint,
            "Angular",
            revolute_formula,
            "DiscSpinMotion",
        )

        if not (added_slider or added_spin):
            FreeCAD.Console.PrintWarning(
                "No motion formula configured; running dynamic simulation without explicit drives.\n"
            )

        assembly.generateSimulation(simulation)
        return simulation, assembly.numberOfFrames()
    except Exception as exc:
        FreeCAD.Console.PrintWarning(f"Dynamic simulation setup/run failed: {exc}\n")
        return None, 0


def get_information():
    return {
        "name": "Assembly LinkBody – Disc-on-Slider Dynamic Rig",
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
from femexamples.assembly_linkbody_disc_slider_dynamics import setup
setup()

This example builds a dynamic rig intended for LinkBody virtual-force tests:

- A grounded rail supports a slider box through a prismatic joint.
- A disc is mounted to the slider with a revolute joint.
- The disc revolute joint can be offset from the disc centroid.

The offset enables eccentric-rotation effects (centrifugal contribution), while
combined slider + disc motion enables Coriolis-related terms. This makes the
rig useful for targeted Jig321/CENTRIF/CORIO validation.

Useful test modes
-----------------
- Centrifugal-focused: slider motion off, disc spin on, nonzero joint offset.
- Coriolis-focused: slider motion on + disc spin on (adjust offset as needed).

As in other LinkBody examples, Jig321/Reaction constraints are generated by the
load-case pipeline (TaskAssemblyLinkBody-aligned behavior).

"""


def setup(
    doc=None,
    solvertype="ccxtools",
    exercise_loadcases=True,
    connect_joints=True,
    slider_motion_formula="",
    revolute_motion_formula="30*time",
    disc_joint_offset_x=20.0,
    disc_joint_offset_y=0.0,
    disc_joint_offset_z=0.0,
    time_end=0.3,
    time_step=0.1,
):
    """Create a disc-on-slider dynamic Assembly+FEM LinkBody example.

    Parameters
    ----------
    disc_joint_offset_* : float
        Offset (mm) of the revolute joint from the disc center, expressed in
        the disc link local coordinate system.
    slider_motion_formula : str
        Linear motion formula for the prismatic joint (empty => no slider drive).
    revolute_motion_formula : str
        Angular motion formula for the disc revolute joint (empty => no spin drive).
    """
    if doc is None:
        doc = init_doc()

    manager.add_explanation_obj(
        doc,
        get_explanation(manager.get_header(get_information())),
    )

    rail_shape = doc.addObject("Part::Box", "RailShape")
    rail_shape.Label = "RailShape"
    rail_shape.Length = 400.0
    rail_shape.Width = 120.0
    rail_shape.Height = 80.0

    slider_shape = doc.addObject("Part::Box", "SliderShape")
    slider_shape.Label = "SliderShape"
    slider_shape.Length = 100.0
    slider_shape.Width = 100.0
    slider_shape.Height = 100.0

    disc_shape = doc.addObject("Part::Cylinder", "DiscShape")
    disc_shape.Label = "DiscShape"
    disc_shape.Radius = 45.0
    disc_shape.Height = 20.0

    doc.recompute()

    disc_face_name = _find_cylindrical_face_name(disc_shape, disc_shape.Radius)
    FreeCAD.Console.PrintMessage(f"[DiscSliderRig] Disc cylindrical face selected: {disc_face_name}\n")

    if FreeCAD.GuiUp:
        rail_shape.ViewObject.Visibility = False
        slider_shape.ViewObject.Visibility = False
        disc_shape.ViewObject.Visibility = False

    assembly = None
    rail_link = None
    slider_link = None
    disc_link = None
    slider_joint = None
    revolute_joint = None

    try:
        try:
            import AssemblyApp  # noqa: F401
        except Exception:
            pass

        assembly = doc.addObject("Assembly::AssemblyObject", "DiscSliderAssembly")
        assembly.Label = "DiscSliderAssembly"

        rail_link = assembly.newObject("App::Link", "Rail")
        rail_link.LinkedObject = rail_shape
        rail_link.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0, 0, 0),
            FreeCAD.Rotation(),
        )

        rail_slider_marker_local = FreeCAD.Vector(
            0.5 * float(rail_shape.Length),
            0.5 * float(rail_shape.Width),
            float(rail_shape.Height),
        )

        slider_joint_marker_local = FreeCAD.Vector(
            0.5 * float(slider_shape.Length),
            0.5 * float(slider_shape.Width),
            0.0,
        )

        slider_initial_pos = rail_slider_marker_local - slider_joint_marker_local

        slider_link = assembly.newObject("App::Link", "SliderBox")
        slider_link.LinkedObject = slider_shape
        slider_link.Placement = FreeCAD.Placement(
            slider_initial_pos,
            FreeCAD.Rotation(),
        )

        slider_disc_marker_local = FreeCAD.Vector(
            float(slider_shape.Length),
            0.5 * float(slider_shape.Width),
            0.5 * float(slider_shape.Height),
        )

        disc_center_local = FreeCAD.Vector(0.0, 0.0, 0.5 * float(disc_shape.Height))
        disc_joint_marker_local = disc_center_local + FreeCAD.Vector(
            float(disc_joint_offset_x),
            float(disc_joint_offset_y),
            float(disc_joint_offset_z),
        )

        slider_world_pos = slider_link.Placement.Base + slider_disc_marker_local
        disc_initial_pos = slider_world_pos - disc_joint_marker_local

        disc_link = assembly.newObject("App::Link", "Disc")
        disc_link.LinkedObject = disc_shape
        disc_link.Placement = FreeCAD.Placement(
            disc_initial_pos,
            FreeCAD.Rotation(),
        )

        if connect_joints:
            joint_group = assembly.newObject("Assembly::JointGroup", "Joints")

            try:
                from JointObject import GroundedJoint as _GroundedJoint
                from JointObject import Joint as _Joint
                from JointObject import ViewProviderGroundedJoint as _VPGroundedJoint
                from JointObject import ViewProviderJoint as _VPJoint

                ground_joint = joint_group.newObject("App::FeaturePython", "GroundedRail")
                ground_joint.Label = "GroundedRail"
                _GroundedJoint(ground_joint, rail_link)
                if FreeCAD.GuiUp:
                    _VPGroundedJoint(ground_joint.ViewObject)

                slider_joint = joint_group.newObject("App::FeaturePython", "RailToSliderPrismatic")
                slider_joint.Label = "RailToSliderPrismatic"
                _Joint(slider_joint, 3)  # prismatic
                if FreeCAD.GuiUp:
                    _VPJoint(slider_joint.ViewObject)
                slider_joint.Detach1 = True
                slider_joint.Detach2 = True
                # Align joint local Z with world +X translation axis.
                axis_rot = FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), -90)
                slider_joint.Placement1 = FreeCAD.Placement(
                    rail_slider_marker_local,
                    axis_rot,
                )
                slider_joint.Placement2 = FreeCAD.Placement(
                    slider_joint_marker_local,
                    axis_rot,
                )

                revolute_joint = joint_group.newObject("App::FeaturePython", "SliderToDiscRevolute")
                revolute_joint.Label = "SliderToDiscRevolute"
                _Joint(revolute_joint, 1)  # revolute
                if FreeCAD.GuiUp:
                    _VPJoint(revolute_joint.ViewObject)
                revolute_joint.Detach1 = True
                revolute_joint.Detach2 = True
                revolute_joint.Placement1 = FreeCAD.Placement(
                    slider_disc_marker_local,
                    FreeCAD.Rotation(),
                )
                revolute_joint.Placement2 = FreeCAD.Placement(
                    disc_joint_marker_local,
                    FreeCAD.Rotation(),
                )
            except Exception:
                pass

    except Exception:
        assembly = None
        disc_link = None

    if assembly is not None and connect_joints and slider_joint is not None and revolute_joint is not None:
        slider_joint.Proxy.setJointConnectors(
            slider_joint,
            [
                [rail_link, ["Face6"]],
                [slider_link, ["Face5"]],
            ],
        )
        revolute_joint.Proxy.setJointConnectors(
            revolute_joint,
            [
                [slider_link, ["Face2"]],
                [disc_link, [disc_face_name]],
            ],
        )
    elif assembly is not None and not connect_joints:
        FreeCAD.Console.PrintWarning(
            "connect_joints=False: parts left unconnected for layout inspection.\n"
        )

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis_DiscShape")
    analysis.Label = "Analysis DiscShape"

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
    femmesh_obj.Shape = disc_shape
    femmesh_obj.SecondOrderLinear = False
    femmesh_obj.ElementDimension = "3D"
    femmesh_obj.CharacteristicLengthMax = "20 mm"

    from femmesh.gmshtools import GmshTools

    gmsh_mesh = GmshTools(femmesh_obj)
    gmsh_mesh.create_mesh()

    if disc_link is not None:
        try:
            from FemLink import UtilsAnalysis as _UtilsAnalysis
            from FemLink.LinkBody import LinkBody

            linkbody_fp = doc.addObject("App::FeaturePython", "LinkBody_Disc")
            linkbody_fp.Label = "LinkBody_Disc"
            LinkBody(linkbody_fp, disc_link)
            if FreeCAD.GuiUp:
                from FemLink.ViewLinkBody import VPLinkBody

                VPLinkBody(linkbody_fp.ViewObject)
            if assembly is not None:
                assembly.addObject(linkbody_fp)

            if exercise_loadcases and assembly is not None and connect_joints:
                _, n_frames = create_and_run_simulation(
                    assembly,
                    slider_joint=slider_joint,
                    revolute_joint=revolute_joint,
                    slider_formula=slider_motion_formula,
                    revolute_formula=revolute_motion_formula,
                    time_end=time_end,
                    time_step=time_step,
                )
                summary = _UtilsAnalysis.exercise_load_case_pipeline(
                    assembly,
                    linkbody_fp,
                    dry_run=False,
                )
                FreeCAD.Console.PrintMessage(
                    f"Disc-slider dynamic simulation frames: {n_frames}\n"
                )
                FreeCAD.Console.PrintMessage(
                    "LinkBody load-case exercise: "
                    f"states={summary['num_states']}, "
                    f"full_hull={summary['full_hull_size']}, "
                    f"reduced_hull={summary['reduced_hull_size']}\n"
                )
            elif not connect_joints:
                FreeCAD.Console.PrintWarning(
                    "connect_joints=False: skipping load-case simulation/pipeline.\n"
                )
            else:
                FreeCAD.Console.PrintWarning(
                    "exercise_loadcases=False: no LinkBody-generated Jig321/Reaction constraints "
                    "were added to the FEM analysis.\n"
                )
        except Exception as exc:
            FreeCAD.Console.PrintWarning(
                f"FemLink.LinkBody unavailable; LinkBody object not created: {exc}\n"
            )

    doc.recompute()

    if FreeCAD.GuiUp and assembly is not None and connect_joints:
        try:
            import FreeCADGui

            FreeCADGui.ActiveDocument.setEdit(assembly)
        except Exception:
            pass

    if FreeCAD.GuiUp:
        femmesh_obj.ViewObject.Visibility = True
        view = femmesh_obj.ViewObject.Document.activeView()
        view.viewAxonometric()
        view.fitAll()

    return doc
