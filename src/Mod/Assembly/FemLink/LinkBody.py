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


def get_reference_subobject(reference):
    if not reference or len(reference) != 2:
        return None

    obj, subs = reference
    sel_obj = None
    sel_subs = []
    if not subs:
        return None
    for sub in subs:
        sel_obj = UtilsAssembly.getObject((obj, [sub]))
        if UtilsAssembly.isLink(sel_obj):
            link_obj = sel_obj
            sel_obj = link_obj.getLinkedObject()
            # Assembly references may come either as fully-qualified path-like
            # names (e.g. "Link.Face7") or plain sub-element names ("Face7").
            # Keep plain names unchanged; only strip a leading object segment
            # when one is explicitly present.
            if "." in sub:
                names = sub.split(".")
                if len(names) > 1:
                    sel_subs.append(".".join(names[1:]))
                else:
                    sel_subs.append(sub)
            else:
                sel_subs.append(sub)
        else:
            sel_subs.append(sub)
    return (sel_obj, list(set(sel_subs)))


def has_valid_reference_subobject(reference):
    if not reference or len(reference) != 2:
        return False
    obj, subs = reference
    if obj is None or not subs:
        return False
    return any(isinstance(s, str) and s.strip() for s in subs)


def clear_post_pipelines(analysis):
    post = find_common_group_objects(analysis, "Fem::FemPostPipeline")
    for p in post:
        analysis.Document.removeObject(p.Name)


def _material_matches_body(material_obj, body):
    references = getattr(material_obj, "References", [])
    if not references:
        return True

    for reference in references:
        if not reference:
            continue
        ref_obj = reference[0]
        if ref_obj == body:
            return True
    return False


def _get_mechanical_material(doc, body):
    for analysis in doc.findObjects(Type="Fem::FemAnalysis"):
        for obj in getattr(analysis, "Group", []):
            material = getattr(obj, "Material", None)
            if material is None:
                continue
            material_data = dict(material)
            if "YoungsModulus" not in material_data or "PoissonRatio" not in material_data:
                continue
            if _material_matches_body(obj, body):
                return material_data

    material_data = dict(body.ShapeMaterial)
    material_data.setdefault("Name", body.Label)
    material_data.setdefault("YoungsModulus", "210000 MPa")
    material_data.setdefault("PoissonRatio", "0.30")
    material_data.setdefault("Density", "7900 kg/m^3")
    return material_data


class LinkBody(FPBase):
    """Link assembly constraints and motion to FEM inputs for static FEA.

    This object transfers dynamic and kinematic constraint information from an
    assembly body into a per-part FEM analysis setup. Joint reaction forces and
    moments are applied at selected reaction surfaces, while
    motion-related effects are represented in the CalculiX solve through
    equivalent load terms.

    The workflow is treated as quasi-steady, following D'Alembert's principle:
    inertia effects are converted into statically equivalent actions for each
    sampled state. Small residual forces and moments can remain because of
    rounding and other numerical approximations. A 3-2-1 jig constraint is
    therefore added to support the model, and its influence should normally be
    negligible in the resulting stress field.
    """

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
        if self._get_body_mass_tons(fp.Body) is None:
            return

        self.updateFEMLinks(fp, mode=UpdateMode.EXECUTE)

        # line_info lives on the Python proxy, so force a ViewProvider refresh
        # after execute to keep symbols in sync during frame-by-frame playback.
        if FreeCAD.GuiUp and hasattr(fp, "ViewObject") and fp.ViewObject:
            vp_proxy = getattr(fp.ViewObject, "Proxy", None)
            if vp_proxy and hasattr(vp_proxy, "updateData"):
                try:
                    vp_proxy.updateData(fp, "line_info")
                except Exception:
                    pass

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

        material_data = _get_mechanical_material(doc, body)
        material_label = material_data.get("Name", body.Label)
        material_obj = ObjectsFem.makeMaterialSolid(doc, material_label)
        material_obj.Material = material_data
        material_obj.Label = f"Material_{body.Label}"
        material_obj.References = [(body, "Solid1")]
        analysis.addObject(material_obj)

        mesh_label = f"Mesh_{body.Label}"
        mesh = ObjectsFem.makeMeshGmsh(doc)
        femmesh_obj = analysis.addObject(mesh)[0]
        femmesh_obj.Shape = body
        femmesh_obj.ElementOrder = "2nd"
        femmesh_obj.Label = mesh_label
        # femmesh_obj.CharacteristicLengthMax = "1 mm"
        if femmesh_obj.ViewObject is not None:
            femmesh_obj.ViewObject.Visibility = False

        doc.recompute()

        # generate the mesh
        from femmesh import gmshtools

        gmsh_mesh = gmshtools.GmshTools(femmesh_obj)
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

        # Remove any stale DAT file objects from previous runs so that
        # load_results_ccxdat (called inside run_fem_solver) always creates
        # a fresh object with the canonical name "ccx_dat_file".
        stale_dat = [
            o
            for o in analysis.Group
            if o.TypeId == "App::TextDocument" and o.Name.startswith("ccx_dat_file")
        ]
        for o in stale_dat:
            analysis.Document.removeObject(o.Name)

        def get_results():
            result_series = find_common_group_objects(analysis, "Fem::FemResultObjectPython")
            return {r.Label: r for r in result_series}

        results_old = get_results()

        # Prevent Assembly recompute from re-solving and overwriting simulation
        # frame history while a per-frame FEM solve is running.
        assembly_prefs = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Assembly")
        solve_on_recompute = assembly_prefs.GetBool("SolveOnRecompute", True)
        try:
            if solve_on_recompute:
                assembly_prefs.SetBool("SolveOnRecompute", False)
            run_fem_solver(solver, solver.WorkingDirectory)
        finally:
            if solve_on_recompute:
                assembly_prefs.SetBool("SolveOnRecompute", True)

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
        objs = getattr(doc, "Objects", None)
        if objs is None and hasattr(doc, "findObjects"):
            try:
                objs = doc.findObjects(Type="Fem::FemAnalysis")
            except TypeError:
                objs = doc.findObjects()
        if objs is None:
            objs = []
        for obj in objs:
            type_id = getattr(obj, "TypeId", None)
            if type_id is not None and type_id != "Fem::FemAnalysis":
                continue
            obj_label = getattr(obj, "Label", None)
            # Objects returned by findObjects(Type=...) may not expose Label in tests.
            if obj_label is None or obj_label == label:
                return obj
        return self.createAnalysis(fp)

    def onChanged(self, fp, prop):
        if FreeCAD.ActiveDocument.Restoring:
            return
        super().onChanged(fp, prop)
        match prop:
            case "Body":
                self.execute(fp)

    def get_analysis_obj(self, analysis, label, maker, typeid, on_new=None, matcher=None):

        def find_analysis_obj():
            objs = find_common_group_objects(analysis, typeid)
            if matcher is not None:
                for obj in objs:
                    if matcher(obj):
                        return obj
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

    def get_analysis_constraint(self, analysis, label, maker, on_new=None, matcher=None):
        return self.get_analysis_obj(
            analysis,
            label,
            maker,
            "Fem::ConstraintPython",
            on_new,
            matcher=matcher,
        )

    def _constraint_references_object(self, constraint_obj, target_obj):
        refs = getattr(constraint_obj, "References", [])
        for ref in refs:
            if not ref:
                continue
            ref_obj = ref[0] if isinstance(ref, tuple) else ref
            if ref_obj == target_obj:
                return True
        return False

    def _cleanup_duplicate_jigs(self, analysis, target_obj, keep_obj):
        constraints = find_common_group_objects(analysis, "Fem::ConstraintPython")
        for obj in constraints:
            if obj == keep_obj:
                continue
            proxy = getattr(obj, "Proxy", None)
            if not proxy or getattr(proxy, "Type", "") != "Fem::ConstraintJig321":
                continue
            if not self._constraint_references_object(obj, target_obj):
                continue
            analysis.Document.removeObject(obj.Name)

    def getMass(self, fp):
        mass = self._get_body_mass_tons(fp.Body)
        return mass if mass is not None else 0.0

    def _get_body_mass_tons(self, body):
        if body is None:
            return None

        mass = getattr(body, "Mass", None)
        if mass is None and hasattr(body, "getLinkedObject"):
            linked = body.getLinkedObject()
            if linked is not None:
                mass = getattr(linked, "Mass", None)

        if mass is None:
            return None

        try:
            mass = float(mass)
        except (TypeError, ValueError):
            return None

        if mass <= 0.0:
            return None

        return mass / 1000.0

    def updateFEMLinks(self, fp, mode: UpdateMode):
        # upon changes to assembly items, update linked FEM items
        analysis = None
        if mode is not UpdateMode.SAVE:
            analysis = self.findAnalysis(fp)
        assembly = fp.getParentGroup()
        if mode is UpdateMode.SAVE:
            self.state = {}

        for body in get_assembly_bodies(assembly):
            key = (body.Label, "Placement")
            if mode is UpdateMode.SAVE:
                placement = self.getBodyPlacement(body)
                self.state[key] = placement
            elif mode is UpdateMode.LOAD:
                if not hasattr(self, "state"):
                    self.state = {}
                placement = self.state.get(key, self.getBodyPlacement(body))
                self.setBodyPlacement(body, placement)
            else:  # EXECUTE: use current live position, no state manipulation
                placement = self.getBodyPlacement(body)
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
        body_obj = body.getLinkedObject()

        def jig_matcher(obj):
            proxy = getattr(obj, "Proxy", None)
            if not proxy or getattr(proxy, "Type", "") != "Fem::ConstraintJig321":
                return False
            return self._constraint_references_object(obj, body_obj)

        if mode is UpdateMode.LOAD:

            def on_new(obj):
                obj.References = [body_obj]

            obj = self.get_analysis_constraint(
                analysis,
                f"Jig_{body.Label}",
                ObjectsFem.makeConstraintJig321,
                on_new=on_new,
                matcher=jig_matcher,
            )
            if not self._constraint_references_object(obj, body_obj):
                obj.References = [body_obj]
            self._cleanup_duplicate_jigs(analysis, body_obj, obj)
            # Restore constraint values from saved state; skip live body read.
            id = body.Label
            mass = self._get_body_mass_tons(body)
            if (id, "LinearAcceleration") in self.state:
                if mass is None:
                    Console.PrintWarning(
                        f"LinkBody: Mass unavailable for {body.Label}; "
                        "skipping linear acceleration restoration.\n"
                    )
                else:
                    obj.LinearAcceleration = self.state[(id, "LinearAcceleration")] / mass
                obj.LinearVelocity = self.state[(id, "LinearVelocity")]
                obj.AngularVelocity = self.state[(id, "AngularVelocity")]
            return True

        # SAVE or EXECUTE: read live body kinematics.
        if not hasattr(body, "CenterOfMass"):
            return False

        center_of_mass = body.CenterOfMass
        mass = self._get_body_mass_tons(body)
        if mass is None:
            Console.PrintWarning(
                f"LinkBody: Mass unavailable for {body.Label}; skipping jig update.\n"
            )
            return False
        if fp.SimpleEquilibrium:
            linear_acceleration = self.force_total / mass
            linear_velocity = Vector(0, 0, 0)
            angular_velocity = Vector(0, 0, 0)
        else:
            linear_acceleration = body.LinearAcceleration
            linear_velocity = body.LinearVelocity
            angular_velocity = body.AngularVelocity

        if mode is UpdateMode.EXECUTE or (mode is UpdateMode.SAVE and analysis is not None):

            def on_new(obj):
                obj.References = [body_obj]

            obj = self.get_analysis_constraint(
                analysis,
                f"Jig_{body.Label}",
                ObjectsFem.makeConstraintJig321,
                on_new=on_new,
                matcher=jig_matcher,
            )
            if not self._constraint_references_object(obj, body_obj):
                obj.References = [body_obj]
            self._cleanup_duplicate_jigs(analysis, body_obj, obj)
            obj.CenterOfMass = center_of_mass
            obj.LinearAcceleration = linear_acceleration
            obj.LinearVelocity = linear_velocity
            obj.AngularVelocity = angular_velocity

        self.force_total -= linear_acceleration * mass

        if mode is UpdateMode.SAVE:
            id = body.Label
            self.state[(id, "LinearAcceleration")] = linear_acceleration * mass
            self.state[(id, "LinearVelocity")] = linear_velocity
            self.state[(id, "AngularVelocity")] = angular_velocity

        self.line_info.append((center_of_mass, linear_acceleration, LineType.LINEAR_ACCELERATION))
        return True

    def updateJoint(self, fp, analysis, body, joint, side, mode: UpdateMode):
        # get force/torque/position from assembly joint
        # set force/torque/position for FEM reaction constraint

        def attr_side(label, default):
            return getattr(joint, label + str(side), default)

        def on_new(obj):
            reference = get_reference_subobject(attr_side("Reference", None))
            if has_valid_reference_subobject(reference):
                obj.References = reference

        id = f"Reaction_{body.Label}_{joint.Label}"

        if mode is UpdateMode.LOAD:
            obj = self.get_analysis_constraint(
                analysis,
                id,
                ObjectsFem.makeConstraintReaction,
                on_new=on_new,
            )
            # Restore constraint values from saved state; skip live joint read.
            if (id, "Force") in self.state:
                obj.Force = self.state[(id, "Force")]
                obj.Torque = self.state[(id, "Torque")]

            reference = get_reference_subobject(attr_side("Reference", None))
            if has_valid_reference_subobject(reference):
                obj.References = reference
            return

        # SAVE or EXECUTE: read live joint reactions.
        force = attr_side("Force", Vector(0, 0, 0))
        torque = attr_side("Torque", Vector(0, 0, 0))
        origin = attr_side("Origin", Vector(0, 0, 0))

        if mode is UpdateMode.EXECUTE or (mode is UpdateMode.SAVE and analysis is not None):
            obj = self.get_analysis_constraint(
                analysis,
                id,
                ObjectsFem.makeConstraintReaction,
                on_new=on_new,
            )
            obj.Force = force
            obj.Torque = torque
            obj.Origin.Base = origin

            reference = get_reference_subobject(attr_side("Reference", None))
            if has_valid_reference_subobject(reference):
                obj.References = reference

        if mode is UpdateMode.SAVE:
            self.state[(id, "Force")] = force
            self.state[(id, "Torque")] = torque

        self.force_total += force
        self.line_info.append((origin, force, LineType.FORCE))
        self.line_info.append((origin, torque, LineType.TORQUE))

    def updateJoints(self, fp, analysis, assembly, body, mode: UpdateMode):

        body_name = body.Name
        linked_body = body.getLinkedObject() if hasattr(body, "getLinkedObject") else None
        linked_body_name = linked_body.Name if linked_body is not None else None

        def is_target_body(part):
            if part is None:
                return False
            if getattr(part, "Name", None) in (body_name, linked_body_name):
                return True
            if hasattr(part, "getLinkedObject"):
                linked = part.getLinkedObject()
                if linked is not None and getattr(linked, "Name", None) in (
                    body_name,
                    linked_body_name,
                ):
                    return True
            return False

        def get_reference_object(joint_ref):
            try:
                return UtilsAssembly.getObject(joint_ref)
            except Exception:
                if isinstance(joint_ref, (list, tuple)) and joint_ref:
                    return joint_ref[0]
                return None

        def joint_match(assembly, joint, side):
            reference = f"Reference{side}"
            if not hasattr(joint, reference):
                # Console.PrintMessage(f"grounded {joint.Label} ignored\n")
                return

            joint_ref = getattr(joint, reference)
            part = None
            if mode is UpdateMode.SAVE:
                # Avoid getMovingPart() during SAVE since it can trigger model
                # updates while we are sampling already-solved frame history.
                ref_obj = get_reference_object(joint_ref)
                if is_target_body(ref_obj):
                    part = ref_obj
            else:
                try:
                    part = UtilsAssembly.getMovingPart(assembly, joint_ref)
                except TypeError:
                    # Newer UtilsAssembly signature takes only the reference tuple.
                    part = UtilsAssembly.getMovingPart(joint_ref)

            if is_target_body(part):
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
