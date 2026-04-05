from enum import Enum, auto

import Fem
import FreeCAD
import ObjectsFem
import UtilsAssembly
from femresult.resulttools import purge_result_objects as purge
from femsolver.run import run_fem_solver
from femtools.femutils import get_pref_working_dir
from FreeCAD import Console, Vector

from .FPBase import FPBase
from .UtilsFemLink import find_common_group_objects, get_assembly_bodies

# create FEM analysis for each body?


class UpdateMode(Enum):
    SAVE = auto()
    EXECUTE = auto()
    LOAD = auto()


class LineType(Enum):
    FORCE = auto()
    TORQUE = auto()
    LINEAR_ACCELERATION = auto()


def analysis_label(body_label):
    return f"Analysis {body_label}"


def obj_save_load(obj, id, state, vars, mode, mass):
    for var in vars:
        if var == "LinearAcceleration":
            scale = mass
        else:
            scale = 1.0
        match mode:
            case UpdateMode.SAVE:
                state[(id, var)] = getattr(obj, var) * scale
            case UpdateMode.LOAD:
                setattr(obj, var, state[(id, var)] / scale)
            case _:
                pass


def get_reference_subobject(reference):
    obj, subs = reference
    sel_obj = None
    sel_subs = []
    if not subs:
        return None
    for sub in subs:
        sel_obj = UtilsAssembly.getObject((obj, [sub]))
        if UtilsAssembly.isLink(sel_obj):
            names = sub.split(".")
            sel_obj = sel_obj.getLinkedObject()
            names[0] = sel_obj.Name
            names.pop(0)
            sel_subs.append(".".join(names))
        else:
            sel_subs.append(sub)
    return (sel_obj, list(set(sel_subs)))


def clear_post_pipelines(analysis):
    post = find_common_group_objects(analysis, "Fem::FemPostPipeline")
    for p in post:
        analysis.Document.removeObject(p.Name)


class LinkBody(FPBase):

    def __init__(self, obj, body=None):

        obj.addProperty(
            "App::PropertyLink",
            "Body",
            "Assembly",
            "Link to the assembly body",
            locked=True,
        ).Body = body

        obj.addProperty(
            "App::PropertyBool",
            "SimpleEquilibrium",
            "Simplified equilibrium calculation",
            locked=True,
        ).SimpleEquilibrium = False

        if obj.Body:
            if obj.Body.getLinkedObject():
                obj.Label = f"LinkBody_{obj.Body.getLinkedObject().Label}"

        super().__init__(obj)

    def execute(self, fp):
        if not hasattr(fp, "Body"):
            return
        if not fp.Body:
            return
        if not fp.Body.getLinkedObject():
            return

        analysis = self.findAnalysis(fp)

        # self.updateFEMLinks(fp, mode=UpdateMode.EXECUTE)

    def createAnalysis(self, fp):
        Console.PrintMessage(f"Creating FEM analysis for body {fp.Body.Label}\n")
        doc = fp.Document
        doc.recompute()
        body = fp.Body.getLinkedObject()
        analysis = ObjectsFem.makeAnalysis(doc)
        analysis.Label = analysis_label(body.Label)

        solver_obj = ObjectsFem.makeSolverCalculiXCcxTools(doc)
        solver_obj.Label = f"Solver_{body.Label}"
        analysis.addObject(solver_obj)

        material_label = body.ShapeMaterial.Name
        material_obj = ObjectsFem.makeMaterialSolid(doc, material_label)
        material_obj.Material = body.ShapeMaterial
        material_obj.Label = f"Material_{body.Label}"
        analysis.addObject(material_obj)

        mesh_label = f"Mesh_{body.Label}"
        mesh = ObjectsFem.makeMeshGmsh(doc)
        femmesh_obj = analysis.addObject(mesh)[0]
        femmesh_obj.Shape = body
        femmesh_obj.ElementOrder = "2nd"
        femmesh_obj.Label = mesh_label
        # femmesh_obj.CharacteristicLengthMax = "1 mm"
        femmesh_obj.ViewObject.Visibility = False

        doc.recompute()

        # generate the mesh
        from femmesh import gmshtools

        gmsh_mesh = gmshtools.GmshTools(femmesh_obj, analysis)
        gmsh_mesh.create_mesh()

        # if fp.ViewObject:
        #     # deactivate edit mode for link body
        #     fp.ViewObject.Document.resetEdit()

        return analysis

    def purge(self, fp):
        if analysis := self.findAnalysis(fp):
            purge(analysis)
            clear_post_pipelines(analysis)
        self.result_map = {}

    def runAnalysis(self, fp, index):
        if not (analysis := self.findAnalysis(fp)):
            Console.PrintMessage("no analysis found\n")
            return

        solver = find_common_group_objects(analysis, "Fem::FemSolverObjectPython")[0]

        if hasattr(solver, "WorkingDirectory") and not solver.WorkingDirectory:
            solver.WorkingDirectory = get_pref_working_dir(solver)

        def get_results():
            result_series = find_common_group_objects(analysis, "Fem::FemResultObjectPython")
            return {r.Label: r for r in result_series}

        results_old = get_results()

        run_fem_solver(solver, solver.WorkingDirectory)

        if not hasattr(self, "result_map"):
            self.result_map = {}
        results = [v for k, v in get_results().items() if k not in results_old]
        for result in results:
            result.Mesh.Placement = self.mesh_placement
            self.result_map[index] = result
            # assumes one result per index

        clear_post_pipelines(analysis)

        # TODO rename or copy result object to index
        # Fem::FemMeshObjectPython within Fem::FemResultObjectPython
        # delete Fem::FemPostPipeline

    def findAnalysis(self, fp):
        label = analysis_label(fp.Body.getLinkedObject().Label)
        doc = fp.Document
        objs = doc.findObjects(Type="Fem::FemAnalysis", Label=label)
        if objs:
            return objs[0]
        else:
            return self.createAnalysis(fp)

    def onChanged(self, fp, prop):
        if FreeCAD.ActiveDocument.Restoring:
            return
        super().onChanged(fp, prop)
        match prop:
            case "Body":
                self.execute(fp)

    def get_analysis_obj(self, analysis, label, maker, typeid, on_new=None):

        def find_analysis_obj():
            objs = find_common_group_objects(analysis, typeid)
            for obj in objs:
                if obj.Label == label:
                    return obj
            return None

        obj = find_analysis_obj()
        if not obj:
            doc = FreeCAD.ActiveDocument
            obj = maker(doc)
            obj.Label = label
            if on_new:
                on_new(obj)
            analysis.addObject(obj)
        return obj

    def get_analysis_constraint(self, analysis, label, maker, on_new=None):
        return self.get_analysis_obj(analysis, label, maker, "Fem::ConstraintPython", on_new)

    def getMass(self, fp):
        return fp.Body.Mass / 1000.0

    def updateFEMLinks(self, fp, mode: UpdateMode):
        # upon changes to assembly items, update linked FEM items
        analysis = self.findAnalysis(fp)
        assembly = fp.getParentGroup()
        if mode is UpdateMode.SAVE:
            self.state = {}

        for body in get_assembly_bodies(assembly):
            key = (body.Label, "Placement")
            match mode:
                case UpdateMode.SAVE:
                    self.state[key] = self.getBodyPlacement(body)
                case _:
                    if not hasattr(self, "state"):
                        self.state = {}
                    placement = self.state.get(key, self.getBodyPlacement(body))
                    self.setBodyPlacement(body, placement)
                    if body == fp.Body:
                        self.mesh_placement = placement

        self.line_info = []

        self.force_total = Vector(0, 0, 0)
        body = fp.Body
        self.updateJoints(fp, analysis, assembly, body, mode=mode)
        self.updateJig(fp, analysis, body, mode=mode)
        # Console.PrintMessage(f"force_total {self.force_total}\n")

        if mode is UpdateMode.SAVE:
            self.capture()

    def updateJig(self, fp, analysis, body, mode: UpdateMode):

        def on_new(obj):
            obj.References = [body.getLinkedObject()]

        obj = self.get_analysis_constraint(
            analysis, f"Jig_{body.Label}", ObjectsFem.makeConstraintJig321, on_new=on_new
        )

        if hasattr(body, "CenterOfMass"):
            obj.CenterOfMass = body.CenterOfMass
            mass = body.Mass / 1000.0
            if fp.SimpleEquilibrium:
                obj.LinearAcceleration = self.force_total / mass
                obj.LinearVelocity = Vector(0, 0, 0)
                obj.AngularVelocity = Vector(0, 0, 0)
            else:
                obj.LinearAcceleration = body.LinearAcceleration
                obj.LinearVelocity = body.LinearVelocity
                obj.AngularVelocity = body.AngularVelocity

            self.force_total -= obj.LinearAcceleration * mass

            id = body.Label

            obj_save_load(
                obj,
                id,
                self.state,
                ["LinearAcceleration", "LinearVelocity", "AngularVelocity"],
                mode=mode,
                mass=mass,
            )

            self.line_info.append(
                (
                    obj.CenterOfMass,
                    obj.LinearAcceleration,
                    LineType.LINEAR_ACCELERATION,
                )
            )
            return True
        return False

    def updateJoint(self, fp, analysis, body, joint, side, mode: UpdateMode):
        # get force/torque/position from assembly joint
        # set force/torque/position for FEM reaction constraint

        def attr_side(label, default):
            return getattr(joint, label + str(side), default)

        def on_new(obj):
            obj.References = get_reference_subobject(attr_side("Reference", None))

        id = f"Reaction_{body.Label}_{joint.Label}"

        obj = self.get_analysis_constraint(
            analysis,
            id,
            ObjectsFem.makeConstraintReaction,
            on_new=on_new,
        )

        obj.Force = attr_side("Force", Vector(0, 0, 0))
        obj.Torque = attr_side("Torque", Vector(0, 0, 0))
        obj.Origin.Base = attr_side("Origin", Vector(0, 0, 0))

        obj_save_load(obj, id, self.state, ["Force", "Torque"], mode=mode, mass=body.Mass / 1000.0)

        self.force_total += obj.Force
        self.line_info.append((obj.Origin.Base, obj.Force, LineType.FORCE))
        self.line_info.append((obj.Origin.Base, obj.Torque, LineType.TORQUE))

    def updateJoints(self, fp, analysis, assembly, body, mode: UpdateMode):

        body_name = body.Name

        def joint_match(assembly, joint, side):
            reference = f"Reference{side}"
            if not hasattr(joint, reference):
                # Console.PrintMessage(f"grounded {joint.Label} ignored\n")
                return

            part = UtilsAssembly.getMovingPart(assembly, getattr(joint, reference))
            if part.Name == body_name:
                self.updateJoint(fp, analysis, body, joint, side, mode=mode)

        joint_groups = find_common_group_objects(assembly, "Assembly::JointGroup")
        force_groups = find_common_group_objects(assembly, "Assembly::ForceGroup")
        for group in joint_groups + force_groups:
            for joint in group.Group:
                assembly = self.getAssembly(joint)
                for i in [1, 2]:
                    joint_match(assembly, joint, i)

    def capture(self):
        if not hasattr(self, "all_states"):
            self.all_states = []
        self.all_states.append(self.state)
        self.state_keys = list(self.state.keys())

    def clear(self, fp):
        self.all_states = []

    def num_bodies(self, fp):
        return len(get_assembly_bodies(fp.getParentGroup()))

    def states_vector(self, fp):
        bodies = get_assembly_bodies(fp.getParentGroup())

        for state in self.all_states:
            vector = []
            for key, v in state.items():
                if isinstance(key, tuple) and (key[1] == "Placement"):
                    continue
                else:
                    vector.extend([v.x, v.y, v.z])

            for body in bodies:
                m = state[(body.Label, "Placement")].toMatrix()
                vector.extend(m.A)
                yield vector

    def state_set(self, fp, vector):
        bodies = get_assembly_bodies(fp.getParentGroup())
        self.state = {}
        j = 0
        for key in self.state_keys:
            if isinstance(key, tuple) and (key[1] == "Placement"):
                continue
            else:
                v = Vector(*[vector[i + j] for i in range(3)])
                self.state[key] = v
                j += 3

        for body in bodies:
            m = FreeCAD.Matrix(*vector[j : j + 16])
            self.state[(body.Label, "Placement")] = FreeCAD.Placement(m)
            j += 16
        # Console.PrintMessage(f"state {self.state}\n")

    def num_states(self):
        return len(getattr(self, "all_states", []))

    def getBodyPlacement(self, body):
        assy_placement = body.Placement
        placement = body.getLinkedObject().Placement
        return assy_placement.multiply(placement.inverse())

    def setBodyPlacement(self, body, body_placement):
        # b = a * p ^ -1 => a = b * p
        placement = body.getLinkedObject().Placement
        body.Placement = body_placement.multiply(placement)

    def scale(self, fp):
        if not hasattr(self, "all_states"):
            return
        if not (body := fp.Body.getLinkedObject()):
            return

        force_max = 0
        torque_max = 0
        linear_acceleration_max = 0

        physical_scale = body.Shape.BoundBox.DiagonalLength / 2.5

        for state in self.all_states:
            for k, v in state.items():
                if isinstance(k, tuple):
                    var = k[1]
                else:
                    var = k
                match var:
                    case "Force":
                        force_max = max(force_max, v.Length)
                    case "Torque":
                        torque_max = max(torque_max, v.Length)
                    case "LinearAcceleration":
                        linear_acceleration_max = max(linear_acceleration_max, v.Length)
                    case _:
                        pass

        Console.PrintMessage(
            f"max force {force_max}, max torque {torque_max}, max acceleration {linear_acceleration_max}\n"
        )
        fp.ViewObject.Proxy.scale(
            force_max=force_max,
            torque_max=torque_max,
            linear_acceleration_max=linear_acceleration_max,
            physical_scale=physical_scale,
        )
