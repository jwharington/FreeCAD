import math
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
    sampled state.

    Physical consistency requirement:
    when VirtualForces and Reaction loads are correctly balanced for a load case,
    the Jig321 reaction must be zero (up to numerical noise). Non-zero Jig
    reactions are therefore treated as a closure/sign/reference mismatch signal,
    not as an expected operating condition.

        Short-term mesh/discretisation correction note:
        CalculiX body-load integration uses mesh mass/inertia, while MbD states are
        resolved from exact body properties. To reduce this mismatch, a single
        correction factor may be exported to CalculiX through VirtualForces.
        Current simplification assumes:
            - no center-of-gravity shift between exact and mesh body representations
            - I_exact / I_mesh == m_exact / m_mesh
        Under this assumption, one scalar factor scales both translational and
        rotational inertial terms on the CalculiX writer side.
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

        obj.addProperty(
            "App::PropertyFloat",
            "InertialCorrectionFactor",
            "Simplified equilibrium calculation",
            "Single-factor mesh-vs-exact inertial correction passed to CalculiX",
            locked=True,
        ).InertialCorrectionFactor = 1.0

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

    def refreshViewData(self, fp):
        """Refresh line_info for VP rendering without modifying FEM constraints.

        Used by simulation frame playback when continuous FEM recompute is off.
        """
        if not hasattr(fp, "Body") or not fp.Body:
            return
        if not fp.Body.getLinkedObject():
            return
        if self._get_body_mass_tons(fp.Body) is None:
            return

        assembly = fp.getParentGroup()
        if assembly is None:
            return

        saved_state = getattr(self, "state", None)
        saved_force_total = getattr(self, "force_total", None)
        try:
            # SAVE mode with analysis=None computes force/torque/accel visual
            # vectors from live assembly kinematics without touching FEM objects.
            self.state = {}
            self.line_info = []
            self.force_total = Vector(0, 0, 0)
            body = fp.Body
            self.updateJoints(fp, None, assembly, body, mode=UpdateMode.SAVE)
            self.updateJig(fp, None, body, mode=UpdateMode.SAVE)
        finally:
            if saved_state is not None:
                self.state = saved_state
            elif hasattr(self, "state"):
                del self.state

            if saved_force_total is not None:
                self.force_total = saved_force_total
            elif hasattr(self, "force_total"):
                del self.force_total

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

    def _cleanup_duplicate_constraints(self, analysis, target_obj, keep_obj, constraint_type):
        constraints = find_common_group_objects(analysis, "Fem::ConstraintPython")
        for obj in constraints:
            if obj == keep_obj:
                continue
            proxy = getattr(obj, "Proxy", None)
            if not proxy or getattr(proxy, "Type", "") != constraint_type:
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

    def _sanitize_positive_factor(self, value):
        try:
            factor = float(value)
        except (TypeError, ValueError):
            return 1.0
        if not math.isfinite(factor) or factor <= 0.0:
            return 1.0
        return factor

    def _as_volume_mm3(self, value):
        if value is None:
            return None

        if hasattr(value, "getValueAs"):
            try:
                q = value.getValueAs("mm^3")
                if hasattr(q, "Value"):
                    value = q.Value
                else:
                    value = q
            except Exception:
                if hasattr(value, "Value"):
                    value = value.Value
        elif hasattr(value, "Value"):
            value = value.Value

        try:
            volume = float(value)
        except (TypeError, ValueError):
            return None

        if not math.isfinite(volume) or volume <= 0.0:
            return None
        return volume

    def _as_vector(self, value):
        if isinstance(value, Vector):
            return Vector(value.x, value.y, value.z)
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return Vector(float(value[0]), float(value[1]), float(value[2]))
        return None

    def _tetra_volume_mm3(self, a, b, c, d):
        return abs((b - a).dot((c - a).cross(d - a))) / 6.0

    def _compute_mesh_volume_mm3_from_elements(self, fem_mesh):
        volume_ids = getattr(fem_mesh, "Volumes", ()) or ()
        if not volume_ids:
            return None

        total = 0.0
        supported = 0
        for volume_id in volume_ids:
            try:
                node_ids = tuple(fem_mesh.getElementNodes(volume_id))
            except Exception:
                continue
            if len(node_ids) < 4:
                continue

            # FEM examples used in LinkBody tests are tetra meshes. For higher-order
            # tetrahedra, getElementNodes returns corner nodes first, so using first
            # four nodes preserves the linear element volume used by CalculiX loads.
            try:
                a = self._as_vector(fem_mesh.getNodeById(int(node_ids[0])))
                b = self._as_vector(fem_mesh.getNodeById(int(node_ids[1])))
                c = self._as_vector(fem_mesh.getNodeById(int(node_ids[2])))
                d = self._as_vector(fem_mesh.getNodeById(int(node_ids[3])))
            except Exception:
                continue

            if None in (a, b, c, d):
                continue

            total += self._tetra_volume_mm3(a, b, c, d)
            supported += 1

        if supported <= 0:
            return None

        return self._as_volume_mm3(total)

    def _get_body_volume_mm3(self, body_obj):
        shape = getattr(body_obj, "Shape", None)
        if shape is None:
            return None
        return self._as_volume_mm3(getattr(shape, "Volume", None))

    def _iter_analysis_mesh_objects(self, analysis):
        if analysis is None:
            return []

        mesh_objs = []
        seen = set()

        for type_id in ("Fem::FemMeshObject", "Fem::FemMeshObjectPython"):
            try:
                candidates = find_common_group_objects(analysis, type_id)
            except Exception:
                candidates = []
            for obj in candidates:
                if obj in seen:
                    continue
                mesh_objs.append(obj)
                seen.add(obj)

        for obj in getattr(analysis, "Group", []):
            if obj in seen:
                continue
            if hasattr(obj, "FemMesh"):
                mesh_objs.append(obj)
                seen.add(obj)

        return mesh_objs

    def _get_mesh_volume_mm3(self, analysis, body_obj):
        mesh_objs = self._iter_analysis_mesh_objects(analysis)
        if not mesh_objs:
            return None

        body_mesh_objs = [m for m in mesh_objs if getattr(m, "Shape", None) == body_obj]
        if not body_mesh_objs:
            body_mesh_objs = mesh_objs

        for mesh_obj in body_mesh_objs:
            fem_mesh = getattr(mesh_obj, "FemMesh", None)
            if fem_mesh is None:
                continue

            mesh_volume = self._as_volume_mm3(getattr(fem_mesh, "Volume", None))
            if mesh_volume is None and hasattr(fem_mesh, "getVolume"):
                try:
                    mesh_volume = self._as_volume_mm3(fem_mesh.getVolume())
                except Exception:
                    mesh_volume = None

            if mesh_volume is None:
                mesh_volume = self._compute_mesh_volume_mm3_from_elements(fem_mesh)

            if mesh_volume is not None:
                return mesh_volume

        return None

    def _compute_inertial_correction_factor(self, fp, analysis, body_obj):
        # One-scalar correction caveat: this assumes no CoG shift and uses
        # volume ratio as a proxy for both mass and inertia ratio.
        fallback_factor = self._sanitize_positive_factor(
            getattr(fp, "InertialCorrectionFactor", 1.0)
        )

        body_volume = self._get_body_volume_mm3(body_obj)
        mesh_volume = self._get_mesh_volume_mm3(analysis, body_obj)
        if body_volume is None or mesh_volume is None:
            return fallback_factor

        ratio = body_volume / mesh_volume
        return self._sanitize_positive_factor(ratio)

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

        def virtual_forces_matcher(obj):
            proxy = getattr(obj, "Proxy", None)
            if not proxy or getattr(proxy, "Type", "") != "Fem::ConstraintVirtualForces":
                return False
            return self._constraint_references_object(obj, body_obj)

        def apply_relative_velocity_fallback(linear_velocity, relative_velocity):
            if relative_velocity.Length > 0.0:
                return relative_velocity
            if linear_velocity.Length > 0.0:
                return linear_velocity
            return relative_velocity

        def ensure_constraints():
            def on_new(obj):
                obj.References = [body_obj]

            jig_obj = self.get_analysis_constraint(
                analysis,
                f"Jig_{body.Label}",
                ObjectsFem.makeConstraintJig321,
                on_new=on_new,
                matcher=jig_matcher,
            )
            if not self._constraint_references_object(jig_obj, body_obj):
                jig_obj.References = [body_obj]
            self._cleanup_duplicate_constraints(
                analysis,
                body_obj,
                jig_obj,
                "Fem::ConstraintJig321",
            )

            vf_obj = self.get_analysis_constraint(
                analysis,
                f"VirtualForces_{body.Label}",
                ObjectsFem.makeConstraintVirtualForces,
                on_new=on_new,
                matcher=virtual_forces_matcher,
            )
            if not self._constraint_references_object(vf_obj, body_obj):
                vf_obj.References = [body_obj]
            self._cleanup_duplicate_constraints(
                analysis,
                body_obj,
                vf_obj,
                "Fem::ConstraintVirtualForces",
            )

            correction_factor = self._compute_inertial_correction_factor(
                fp,
                analysis,
                body_obj,
            )
            try:
                fp.InertialCorrectionFactor = correction_factor
            except Exception:
                pass
            vf_obj.InertialCorrectionFactor = correction_factor
            return jig_obj, vf_obj

        if mode is UpdateMode.LOAD:
            jig_obj, vf_obj = ensure_constraints()
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
                    vf_obj.LinearAcceleration = self.state[(id, "LinearAcceleration")] / mass

                linear_velocity = self.state.get((id, "LinearVelocity"), Vector(0, 0, 0))
                angular_velocity = self.state.get((id, "AngularVelocity"), Vector(0, 0, 0))
                angular_acceleration = self.state.get((id, "AngularAcceleration"), Vector(0, 0, 0))
                relative_velocity = self.state.get((id, "RelativeVelocity"), linear_velocity)
                relative_velocity = apply_relative_velocity_fallback(
                    linear_velocity,
                    relative_velocity,
                )

                vf_obj.LinearVelocity = linear_velocity
                vf_obj.AngularVelocity = angular_velocity
                vf_obj.AngularAcceleration = angular_acceleration
                vf_obj.RelativeVelocity = relative_velocity

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
            angular_acceleration = Vector(0, 0, 0)
            relative_velocity = Vector(0, 0, 0)
        else:
            linear_acceleration = body.LinearAcceleration
            linear_velocity = body.LinearVelocity
            angular_velocity = body.AngularVelocity
            angular_acceleration = getattr(body, "AngularAcceleration", Vector(0, 0, 0))
            relative_velocity = getattr(body, "RelativeVelocity", linear_velocity)
            relative_velocity = apply_relative_velocity_fallback(
                linear_velocity,
                relative_velocity,
            )

        if mode is UpdateMode.EXECUTE or (mode is UpdateMode.SAVE and analysis is not None):
            jig_obj, vf_obj = ensure_constraints()
            vf_obj.CenterOfMass = center_of_mass
            vf_obj.LinearAcceleration = linear_acceleration
            vf_obj.LinearVelocity = linear_velocity
            vf_obj.AngularVelocity = angular_velocity
            vf_obj.AngularAcceleration = angular_acceleration
            vf_obj.RelativeVelocity = relative_velocity

        self.force_total -= linear_acceleration * mass

        if mode is UpdateMode.SAVE:
            id = body.Label
            self.state[(id, "LinearAcceleration")] = linear_acceleration * mass
            self.state[(id, "LinearVelocity")] = linear_velocity
            self.state[(id, "AngularVelocity")] = angular_velocity
            self.state[(id, "AngularAcceleration")] = angular_acceleration
            self.state[(id, "RelativeVelocity")] = relative_velocity

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
            if hasattr(body, "CenterOfMass") and hasattr(obj, "CenterOfMass"):
                obj.CenterOfMass = body.CenterOfMass

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
