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
    assembly, slider_joint, motion_formula="40*time", time_end=0.3, time_step=0.1
):
    """Create and run an Assembly kinematic simulation.  Works headless and in GUI."""
    try:
        import UtilsAssembly

        sim_group = UtilsAssembly.getSimulationGroup(assembly)
        simulation = sim_group.newObject("App::FeaturePython", "Simulation")

        # Set proxy so doubleClicked works after document reload.
        # CommandCreateSimulation.Simulation adds GroupExtension + properties + Proxy;
        # it imports pivy so falls back to a minimal proxy when running headless.
        try:
            from CommandCreateSimulation import Simulation as _SimClass
            from CommandCreateSimulation import ViewProviderSimulation
            _SimClass(simulation)  # sets Proxy, adds extension and properties
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
                def dumps(self): return None
                def loads(self, state): return None
                def execute(self, feaPy): pass
                def onChanged(self, feaPy, prop): pass

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

        # Re-set desired values (CommandCreateSimulation.Simulation sets its own defaults)
        simulation.aTimeStart = 0.0
        simulation.bTimeEnd = time_end
        simulation.cTimeStepOutput = time_step
        simulation.fGlobalErrorTolerance = 1.0e-6
        simulation.jFramesPerSecond = 30
        simulation.Dynamic = False

        if slider_joint is not None:
            motion = assembly.newObject("App::FeaturePython", "Motion")
            try:
                from CommandCreateSimulation import Motion as _MotionClass
                from CommandCreateSimulation import ViewProviderMotion
                _MotionClass(motion, motionType="Linear")  # sets Proxy + creates properties
                if FreeCAD.GuiUp:
                    ViewProviderMotion(motion.ViewObject)
            except (ImportError, NameError):
                class _MinimalMotionProxy:
                    def dumps(self): return None
                    def loads(self, state): return None
                    def execute(self, feaPy): pass
                    def onChanged(self, feaPy, prop): pass
                motion.Proxy = _MinimalMotionProxy()
                for prop, ptype in [
                    ("Joint", "App::PropertyXLinkSub"),
                    ("Formula", "App::PropertyString"),
                    ("MotionType", "App::PropertyEnumeration"),
                ]:
                    if not hasattr(motion, prop):
                        motion.addProperty(ptype, prop, "Motion")
                motion.MotionType = ["Angular", "Linear"]
            motion.MotionType = "Linear"
            try:
                motion.Joint = (slider_joint, [])
            except Exception:
                motion.Joint = slider_joint
            motion.Formula = motion_formula
            motions = simulation.Group
            motions.append(motion)
            simulation.Group = motions
        else:
            FreeCAD.Console.PrintWarning(
                "No slider joint available for motion; running kinematic simulation without motion.\n"
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

This example demonstrates a forced (kinematic) Assembly simulation where a
prismatic (slider) joint drives a linkage connected to a pendulum body. The
pendulum LinkBody transfers assembly joint loads into FEM constraints and runs
full FEM analysis for stored load cases.

"""


def setup(doc=None, solvertype="ccxtools", exercise_loadcases=True):

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
    # Extend 25 mm upstream of the housing centerline.
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

    pendulum_shape = doc.addObject("Part::Cut", "PendulumShape")
    pendulum_shape.Label = "PendulumShape"
    pendulum_shape.Base = pendulum_base
    pendulum_shape.Tool = housing_cutter

    slider_shape = doc.addObject("Part::Box", "SliderShape")
    slider_shape.Label = "SliderShape"
    slider_shape.Length = 80
    slider_shape.Width = 50
    slider_shape.Height = 50

    rod_shape = doc.addObject("Part::Box", "RodShape")
    rod_shape.Label = "RodShape"
    rod_shape.Length = 220
    rod_shape.Width = 30
    rod_shape.Height = 30

    doc.recompute()
    reaction_face_name = _find_cylindrical_face_name(pendulum_shape, housing_shape.Radius)
    FreeCAD.Console.PrintMessage(f"[LinkBody] Reaction face selected: {reaction_face_name}\n")

    if FreeCAD.GuiUp:
        pendulum_shape.ViewObject.Visibility = False
        pendulum_base.ViewObject.Visibility = False
        housing_cutter.ViewObject.Visibility = False
        housing_shape.ViewObject.Visibility = False
        slider_shape.ViewObject.Visibility = False
        rod_shape.ViewObject.Visibility = False

    assembly = None
    pendulum_link = None
    slider_joint = None

    try:
        try:
            import AssemblyApp  # noqa: F401
        except Exception:
            pass

        assembly = doc.addObject("Assembly::AssemblyObject", "ForcedPendulumAssembly")
        assembly.Label = "ForcedPendulumAssembly"

        housing_link = assembly.newObject("App::Link", "Housing")
        housing_link.LinkedObject = housing_shape
        # Rotation(X,-90) aligns cylinder axis (local Z) with world +Y (pendulum rotation axis).
        housing_link.Placement = FreeCAD.Placement(
            FreeCAD.Vector(-25, 0, 0),
            FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90),
        )

        pendulum_link = assembly.newObject("App::Link", "Pendulum")
        pendulum_link.LinkedObject = pendulum_shape
        pendulum_link.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0, 0, 0),
            FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 20),
        )

        slider_link = assembly.newObject("App::Link", "Slider")
        slider_link.LinkedObject = slider_shape
        slider_link.Placement = FreeCAD.Placement(
            FreeCAD.Vector(330, 0, 0),
            FreeCAD.Rotation(),
        )

        rod_link = assembly.newObject("App::Link", "Rod")
        rod_link.LinkedObject = rod_shape
        rod_link.Placement = FreeCAD.Placement(
            FreeCAD.Vector(180, 10, 10),
            FreeCAD.Rotation(),
        )

        joint_group = assembly.newObject("Assembly::JointGroup", "Joints")

        try:
            from JointObject import GroundedJoint as _GroundedJoint
            from JointObject import Joint as _Joint

            ground_joint = joint_group.newObject("App::FeaturePython", "GroundedJoint")
            ground_joint.Label = "GroundedJoint"
            _GroundedJoint(ground_joint, housing_link)

            cyl_joint = joint_group.newObject("App::FeaturePython", "PendulumCylindrical")
            cyl_joint.Label = "PendulumCylindrical"
            _Joint(cyl_joint, 2)
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

            slider_joint = joint_group.newObject("App::FeaturePython", "DriverSlider")
            slider_joint.Label = "DriverSlider"
            _Joint(slider_joint, 3)
            slider_joint.Detach1 = True
            slider_joint.Detach2 = True
            slider_joint.Placement1 = FreeCAD.Placement(
                FreeCAD.Vector(350, 25, 25),
                FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 0),
            )
            slider_joint.Placement2 = FreeCAD.Placement(
                FreeCAD.Vector(350, 25, 25),
                FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 0),
            )

            rev_joint_1 = joint_group.newObject("App::FeaturePython", "RodToPendulum")
            rev_joint_1.Label = "RodToPendulum"
            _Joint(rev_joint_1, 1)
            rev_joint_1.Detach1 = True
            rev_joint_1.Detach2 = True
            rev_joint_1.Placement1 = FreeCAD.Placement(
                FreeCAD.Vector(460, 25, 25),
                FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 0),
            )
            rev_joint_1.Placement2 = FreeCAD.Placement(
                FreeCAD.Vector(460, 25, 25),
                FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 0),
            )

            rev_joint_2 = joint_group.newObject("App::FeaturePython", "RodToSlider")
            rev_joint_2.Label = "RodToSlider"
            _Joint(rev_joint_2, 1)
            rev_joint_2.Detach1 = True
            rev_joint_2.Detach2 = True
            rev_joint_2.Placement1 = FreeCAD.Placement(
                FreeCAD.Vector(350, 25, 25),
                FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 0),
            )
            rev_joint_2.Placement2 = FreeCAD.Placement(
                FreeCAD.Vector(350, 25, 25),
                FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 0),
            )
        except Exception:
            pass

    except Exception:
        assembly = None
        pendulum_link = None

    if assembly is not None and slider_joint is not None:
        cyl_joint.Proxy.setJointConnectors(
            cyl_joint,
            [
                [housing_link, ["Face1"]],
                [pendulum_link, [reaction_face_name]],
            ],
        )
        slider_joint.Proxy.setJointConnectors(
            slider_joint,
            [
                [housing_link, ["Face1"]],
                [slider_link, ["Face1"]],
            ],
        )
        rev_joint_1.Proxy.setJointConnectors(
            rev_joint_1,
            [
                [pendulum_link, ["Face1"]],
                [rod_link, ["Face1"]],
            ],
        )
        rev_joint_2.Proxy.setJointConnectors(
            rev_joint_2,
            [
                [slider_link, ["Face1"]],
                [rod_link, ["Face1"]],
            ],
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

    con_jig = ObjectsFem.makeConstraintJig321(doc, "ConstraintJig321")
    con_jig.References = [(pendulum_shape, "Face1")]
    con_jig.CenterOfMass = FreeCAD.Vector(250, 25, 25)
    con_jig.LinearAcceleration = FreeCAD.Vector(0, 0, -9810)
    con_jig.LinearVelocity = FreeCAD.Vector(0, 0, 0)
    con_jig.AngularVelocity = FreeCAD.Vector(0, 0, 0)
    analysis.addObject(con_jig)

    con_reaction = ObjectsFem.makeConstraintReaction(doc, "ConstraintReaction")
    con_reaction.References = [(pendulum_shape, reaction_face_name)]
    con_reaction.Force = FreeCAD.Vector(0, 0, 80)
    con_reaction.Torque = FreeCAD.Vector(0, 12000, 0)
    con_reaction.Origin = FreeCAD.Placement(
        FreeCAD.Vector(0, 25, 25),
        FreeCAD.Rotation(),
    )
    analysis.addObject(con_reaction)

    femmesh_obj = analysis.addObject(
        ObjectsFem.makeMeshGmsh(doc, get_meshname())
    )[0]
    femmesh_obj.Shape = pendulum_shape
    femmesh_obj.SecondOrderLinear = False
    femmesh_obj.ElementDimension = "3D"
    # Keep the default mesh coarse for stable/fast CI runs and to avoid Gmsh stalls.
    femmesh_obj.CharacteristicLengthMax = "100 mm"

    from femmesh.gmshtools import GmshTools

    gmsh_mesh = GmshTools(femmesh_obj)
    gmsh_mesh.create_mesh()

    if pendulum_link is not None:
        try:
            from FemLink import UtilsAnalysis as _UtilsAnalysis
            from FemLink.LinkBody import LinkBody

            linkbody_fp = doc.addObject("App::FeaturePython", "LinkBody_Pendulum")
            linkbody_fp.Label = "LinkBody_Pendulum"
            LinkBody(linkbody_fp, pendulum_link)
            if FreeCAD.GuiUp:
                from FemLink.ViewLinkBody import VPLinkBody

                VPLinkBody(linkbody_fp.ViewObject)
            if assembly is not None:
                assembly.addObject(linkbody_fp)

            if exercise_loadcases and assembly is not None:
                _, n_frames = create_and_run_simulation(assembly, slider_joint)
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
        except Exception as exc:
            FreeCAD.Console.PrintWarning(
                f"FemLink.LinkBody unavailable; LinkBody object not created: {exc}\n"
            )

    doc.recompute()

    if FreeCAD.GuiUp and assembly is not None:
        try:
            import FreeCADGui

            FreeCADGui.ActiveDocument.setEdit(assembly)
        except Exception:
            pass

    if FreeCAD.GuiUp:
        femmesh_obj.ViewObject.Visibility = True
        femmesh_obj.ViewObject.Document.activeView().viewAxonometric()
        femmesh_obj.ViewObject.Document.activeView().fitAll()

    return doc
