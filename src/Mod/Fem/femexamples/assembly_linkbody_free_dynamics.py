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
from MotionObject import Motion as _MotionClass
from MotionObject import ViewProviderMotion
from SimulationObject import Simulation as _SimClass
from ViewProviderSimulation import ViewProviderSimulation

from . import manager
from .manager import get_meshname, init_doc

if FreeCAD.GuiUp:
	import FreeCADGui as FreeCADGuiMod
else:
	FreeCADGuiMod = None


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
	assembly, cyl_joint, motion_formula="", time_end=0.3, time_step=0.1
):
	"""Create and run an Assembly dynamic simulation.  Works headless and in GUI."""
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
		simulation.Dynamic = True

		if cyl_joint is not None and motion_formula:
			motion = assembly.newObject("App::FeaturePython", "Motion")
			_MotionClass(motion, motionType="Angular")  # sets Proxy + creates properties
			if FreeCAD.GuiUp:
				ViewProviderMotion(motion.ViewObject)
			motion.MotionType = "Angular"
			try:
				motion.Joint = (cyl_joint, [])
			except Exception:
				motion.Joint = cyl_joint
			motion.Formula = motion_formula
			motions = simulation.Group
			motions.append(motion)
			simulation.Group = motions
		elif cyl_joint is None:
			FreeCAD.Console.PrintWarning(
				"No cylindrical joint available for motion; "
				"running dynamic simulation without explicit motion.\n"
			)

		assembly.generateSimulation(simulation)
		return simulation, assembly.numberOfFrames()
	except Exception as exc:
		FreeCAD.Console.PrintWarning(f"Dynamic simulation setup/run failed: {exc}\n")
		return None, 0


# Keep old name as alias for backward compatibility
_create_and_run_dynamic_simulation = create_and_run_simulation


def get_information():
	return {
		"name": "Assembly LinkBody - Free Dynamics Pendulum",
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
from femexamples.assembly_linkbody_free_dynamics import setup
setup()

This example demonstrates the Assembly -> FEM LinkBody workflow for a free-
dynamics pendulum arm rotating on a revolute bearing.

Geometry
--------
	Housing  : Part::Cylinder, O25 mm bore, 50 mm wide  (fixed ground body)
	Pendulum : Part::Cut(Box - Cylinder), 525 x 50 x 50 mm steel arm

The two parts are connected by a Revolute joint (constrains five DOF,
leaves one rotation free) at the assembly origin. The LinkBody feature
links the pendulum's App::Link in the assembly to its dedicated FEM analysis.

Snapshot conditions (45 deg swing, w = 1 rad/s about +Y)
--------------------------------------------------------
  CM position (global) : (177, 25, -177) mm from bearing centre
  Angular velocity     : w = (0, 1, 0) rad/s
  CM acceleration      : a_cm = (-177, 0, -9633) mm/s^2
						 (centripetal toward pivot + gravity)

  Bearing reaction force  : F ~= (-2, 0, 99) N
  Bearing reaction torque : T ~= (0, 17000, 0) N*mm
  (bending moment due to weight arm at 45 deg)

The LinkBody load-case pipeline creates FEM constraints (including Jig321
and Reaction) from assembly kinematics/loads. This example intentionally does
not create those constraints manually to keep it aligned with the production
TaskAssemblyLinkBody workflow.

When `exercise_loadcases=True`, this example also exercises the LinkBody
load-case pipeline used by TaskAssemblyLinkBody:
	create+run dynamic assembly simulation -> collect/synthesize states
	-> full/reduced stored analysis
	(full FEM analysis, not dry-run)

"""


def setup(
	doc=None,
	solvertype="ccxtools",
	exercise_loadcases=True,
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

	doc.recompute()
	reaction_face_name = _find_cylindrical_face_name(pendulum_shape, housing_shape.Radius)
	FreeCAD.Console.PrintMessage(f"[LinkBody] Reaction face selected: {reaction_face_name}\n")

	if FreeCAD.GuiUp:
		pendulum_shape.ViewObject.Visibility = False
		housing_shape.ViewObject.Visibility = False
		pendulum_base.ViewObject.Visibility = False
		housing_cutter.ViewObject.Visibility = False

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
	# Rotation(X,-90) aligns cylinder axis (local Z) with world +Y (pendulum rotation axis).
	# Optional assembly_rot_x pre-rotates the entire mechanism about global X.
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
	# Placement1 in housing_link local (with Rotation(X,-90) on link):
	# world pos = (-25,0,0) + Rx(-90)*(0,0,25) = (-25,25,0) — same as before.
	cyl_joint.Placement1 = FreeCAD.Placement(
		FreeCAD.Vector(0, 0, 25),
		FreeCAD.Rotation(),
	)
	cyl_joint.Placement2 = FreeCAD.Placement(
		FreeCAD.Vector(0, 25, 25),
		FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90),
	)

	analysis = ObjectsFem.makeAnalysis(doc, "Analysis_PendulumShape")
	analysis.Label = "Analysis PendulumShape"

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

	material_obj = ObjectsFem.makeMaterialSolid(doc, "FemMaterial")
	mat = material_obj.Material
	mat["Name"] = "Steel-Generic"
	mat["YoungsModulus"] = "210000 MPa"
	mat["PoissonRatio"] = "0.30"
	mat["Density"] = "7900 kg/m^3"
	material_obj.Material = mat
	analysis.addObject(material_obj)

	# NOTE:
	# FEM constraints are generated by the LinkBody load-case pipeline.
	# Do not add explicit Jig321/Reaction constraints here; doing so diverges
	# from TaskAssemblyLinkBody behavior and can duplicate or conflict with
	# generated constraints.

	femmesh_obj = analysis.addObject(
		ObjectsFem.makeMeshGmsh(doc, get_meshname())
	)[0]
	femmesh_obj.Shape = pendulum_shape
	femmesh_obj.SecondOrderLinear = False
	femmesh_obj.ElementDimension = "3D"
	# Keep the default mesh coarse for stable/fast CI runs and to avoid Gmsh stalls.
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
		)
		FreeCAD.Console.PrintMessage(
			f"Assembly dynamic simulation frames: {n_frames}\n"
		)
		FreeCAD.Console.PrintMessage(
			"LinkBody load-case exercise: "
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
