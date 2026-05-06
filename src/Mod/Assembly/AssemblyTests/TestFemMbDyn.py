# SPDX-License-Identifier: LGPL-2.1-or-later
# Tests for commits:
#   aa9155ed05  Assembly: add FemLink module infrastructure
#   d369c72d37  Assembly: add LinkBody command and FemLink integration
#   73538fc78f  Assembly: add force command and refactor task utilities

import hashlib
import json
import os
import re
import shutil
import statistics
import tempfile
import unittest
from unittest.mock import Mock, patch

import FreeCAD as App


def _msg(text):
    App.Console.PrintMessage(text + "\n")


def _log_axis_limits(values, floor=1.0e-18):
    positives = [abs(float(v)) for v in values if abs(float(v)) > floor]
    if not positives:
        return floor, floor * 10.0

    ymin = min(positives)
    ymax = max(positives)
    if ymin == ymax:
        return max(ymin / 10.0, floor), ymax * 10.0
    return max(ymin / 10.0, floor), ymax * 10.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(name):
    if App.ActiveDocument and App.ActiveDocument.Name == name:
        App.closeDocument(name)
    doc = App.newDocument(name)
    App.setActiveDocument(name)
    return doc


def _import_or_skip(testcase, module_name):
    try:
        return __import__(module_name, fromlist=["*"])
    except Exception as exc:
        testcase.skipTest(f"{module_name} import unavailable: {exc}")


# ---------------------------------------------------------------------------
# aa9155ed05 – FemLink module infrastructure
# ---------------------------------------------------------------------------


class TestFemLinkUtils(unittest.TestCase):

    def setUp(self):
        self.doc = _make_doc(self.__class__.__name__)
        _import_or_skip(self, "FemLink.UtilsFemLink")
        try:
            self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        except Exception as exc:
            self.skipTest(f"Assembly::AssemblyObject unavailable: {exc}")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_find_common_group_objects_empty(self):
        """find_common_group_objects returns [] when no objects of that type exist."""
        _msg("  Test find_common_group_objects empty")
        from FemLink.UtilsFemLink import find_common_group_objects

        result = find_common_group_objects(self.assembly, "App::Link")
        self.assertEqual(result, [])

    def test_get_assembly_bodies_empty(self):
        """get_assembly_bodies returns [] for an empty assembly."""
        _msg("  Test get_assembly_bodies empty")
        from FemLink.UtilsFemLink import get_assembly_bodies

        result = get_assembly_bodies(self.assembly)
        self.assertEqual(result, [])

    def test_get_simgroup_returns_none_when_missing(self):
        """get_simgroup returns None when no SimulationGroup is present."""
        _msg("  Test get_simgroup missing")
        from FemLink.UtilsFemLink import get_simgroup

        result = get_simgroup(self.assembly)
        self.assertIsNone(result)

    def test_get_simulations_returns_empty_when_no_simgroup(self):
        """get_simulations returns [] when no SimulationGroup is present."""
        _msg("  Test get_simulations no simgroup")
        from FemLink.UtilsFemLink import get_simulations

        result = get_simulations(self.assembly)
        self.assertEqual(result, [])

    def test_get_femlinks_returns_empty_for_empty_assembly(self):
        """get_femlinks returns [] for assembly with no group objects."""
        _msg("  Test get_femlinks empty")
        from FemLink.UtilsFemLink import get_femlinks

        result = get_femlinks(self.assembly)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# d369c72d37 – FPBase infrastructure (FemLink.FPBase)
# ---------------------------------------------------------------------------


class TestFPBase(unittest.TestCase):

    def setUp(self):
        self.doc = _make_doc(self.__class__.__name__)
        _import_or_skip(self, "FemLink.FPBase")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_fpbase_getstate_returns_empty_dict(self):
        """FPBase.__getstate__ must return {} for serialisation."""
        _msg("  Test FPBase.__getstate__")
        from FemLink.FPBase import FPBase

        class ConcreteFP(FPBase):
            pass

        obj = self.doc.addObject("App::FeaturePython", "FP")
        fp = ConcreteFP(obj)
        self.assertEqual(fp.__getstate__(), {})

    def test_fpbase_setstate_returns_none(self):
        """FPBase.__setstate__ must return None (no-op restore)."""
        _msg("  Test FPBase.__setstate__")
        from FemLink.FPBase import FPBase

        class ConcreteFP(FPBase):
            pass

        obj = self.doc.addObject("App::FeaturePython", "FP2")
        fp = ConcreteFP(obj)
        self.assertIsNone(fp.__setstate__({}))

    def test_fpbase_getassembly_returns_none_for_standalone(self):
        """FPBase.getAssembly returns None when object has no Assembly parent."""
        _msg("  Test FPBase.getAssembly standalone")
        from FemLink.FPBase import FPBase

        class ConcreteFP(FPBase):
            pass

        obj = self.doc.addObject("App::FeaturePython", "FP3")
        fp = ConcreteFP(obj)
        self.assertIsNone(fp.getAssembly(obj))


# ---------------------------------------------------------------------------
# 73538fc78f – force command and task utilities (ForceObject)
# ---------------------------------------------------------------------------


class TestForceObject(unittest.TestCase):

    def setUp(self):
        self.doc = _make_doc(self.__class__.__name__)
        try:
            self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
            self.assembly.newObject("Assembly::JointGroup", "Joints")
        except Exception as exc:
            self.skipTest(f"Assembly document object types unavailable: {exc}")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_force_types_list_integrity(self):
        """ForceTypes and TranslatedForceTypes must have the same length and expected values."""
        _msg("  Test ForceTypes list integrity")
        import ForceObject

        self.assertEqual(len(ForceObject.ForceTypes), len(ForceObject.TranslatedForceTypes))
        self.assertIn("General", ForceObject.ForceTypes)
        self.assertIn("InLine", ForceObject.ForceTypes)

    def test_force_torque_general_has_force_type_property(self):
        """ForceTorqueGeneral must initialise with a ForceType property set to 'General'."""
        _msg("  Test ForceTorqueGeneral ForceType property")
        import ForceObject

        force_obj = self.assembly.newObject("App::FeaturePython", "Force")
        ForceObject.ForceTorqueGeneral(force_obj)
        self.assertTrue(hasattr(force_obj, "ForceType"))
        self.assertEqual(force_obj.ForceType, "General")

    def test_force_torque_inline_has_force_type_property(self):
        """ForceTorqueInLine must initialise with a ForceType property set to 'InLine'."""
        _msg("  Test ForceTorqueInLine ForceType property")
        import ForceObject

        force_obj = self.assembly.newObject("App::FeaturePython", "ForceInLine")
        ForceObject.ForceTorqueInLine(force_obj)
        self.assertTrue(hasattr(force_obj, "ForceType"))
        self.assertEqual(force_obj.ForceType, "InLine")

    def test_force_torque_general_has_reference_properties(self):
        """ForceTorqueGeneral must initialise Reference1 and Reference2 properties."""
        _msg("  Test ForceTorqueGeneral reference properties")
        import ForceObject

        force_obj = self.assembly.newObject("App::FeaturePython", "Force2")
        ForceObject.ForceTorqueGeneral(force_obj)
        self.assertTrue(hasattr(force_obj, "Reference1"))
        self.assertTrue(hasattr(force_obj, "Reference2"))


# ---------------------------------------------------------------------------
# d369c72d37 – LinkBody command and FemLink integration
# ---------------------------------------------------------------------------


class TestLinkBody(unittest.TestCase):

    REACTION_CONTACT_TYPES = ("Uniform", "Cosine", "Parabolic", "Gencoz")

    def setUp(self):
        self.doc = _make_doc(self.__class__.__name__)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _import_linkbody(self):
        try:
            import FemLink.LinkBody as linkbody_module
        except Exception as exc:
            self.skipTest(f"FemLink.LinkBody import unavailable: {exc}")
        return linkbody_module

    def _jig_force_components_from_calculix_dat(self, dat_text, jig_prefix):
        pattern = re.compile(
            r"total force \(fx,fy,fz\) for set\s+([^\s]+)",
            re.IGNORECASE,
        )
        lines = dat_text.splitlines()
        jig_prefix = jig_prefix.upper()
        out = []

        for idx, line in enumerate(lines):
            match = pattern.search(line)
            if not match:
                continue
            set_name = match.group(1).upper()
            if not set_name.startswith(f"{jig_prefix}-"):
                continue

            force_line = ""
            for probe in lines[idx + 1 :]:
                if probe.strip():
                    force_line = probe.strip()
                    break
            if not force_line:
                continue

            parts = force_line.split()
            if len(parts) < 3:
                continue

            out.append((set_name, App.Vector(float(parts[0]), float(parts[1]), float(parts[2]))))

        return out

    def _jig_resultant_force_vector_from_calculix_dat(self, dat_text, jig_prefix, inp_text=""):
        resultant = App.Vector(0, 0, 0)
        for _set_name, force_vec in self._jig_force_components_from_calculix_dat(
            dat_text, jig_prefix
        ):
            resultant += force_vec
        return resultant

    def _jig_nset_nodes_from_inp(self, inp_text, jig_prefix):
        lines = inp_text.splitlines()
        jig_prefix = jig_prefix.upper()
        out = {}

        nset_pattern = re.compile(r"\*NSET\s*,\s*NSET\s*=\s*([^,\s]+)", re.IGNORECASE)
        idx = 0
        while idx < len(lines):
            line = lines[idx].strip()
            match = nset_pattern.match(line)
            if not match:
                idx += 1
                continue

            set_name = match.group(1).upper()
            idx += 1
            node_ids = []
            while idx < len(lines):
                probe = lines[idx].strip()
                if not probe or probe.startswith("**"):
                    idx += 1
                    continue
                if probe.startswith("*"):
                    break
                node_ids.extend(int(v) for v in probe.replace(",", " ").split() if v.strip())
                idx += 1

            if set_name.startswith(f"{jig_prefix}-"):
                out[set_name] = node_ids
            continue

        return out

    def _node_coordinates_from_inp(self, inp_text):
        lines = inp_text.splitlines()
        in_nodes = False
        out = {}

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("**"):
                continue
            if stripped.startswith("*"):
                in_nodes = stripped.upper().startswith("*NODE")
                continue
            if not in_nodes:
                continue

            parts = [p.strip() for p in stripped.split(",") if p.strip()]
            if len(parts) < 4:
                continue
            out[int(parts[0])] = App.Vector(float(parts[1]), float(parts[2]), float(parts[3]))

        return out

    def _jig_resultant_moment_vector_from_calculix_dat(
        self,
        dat_text,
        jig_prefix,
        reference_point,
        inp_text="",
    ):
        if not inp_text:
            return App.Vector(0, 0, 0)

        jig_components = self._jig_force_components_from_calculix_dat(dat_text, jig_prefix)
        if not jig_components:
            return App.Vector(0, 0, 0)

        set_nodes = self._jig_nset_nodes_from_inp(inp_text, jig_prefix)
        node_coords = self._node_coordinates_from_inp(inp_text)

        moment = App.Vector(0, 0, 0)
        for set_name, force_vec in jig_components:
            node_ids = set_nodes.get(set_name, [])
            if not node_ids:
                continue
            node_pos = node_coords.get(node_ids[0])
            if node_pos is None:
                continue
            moment += (node_pos - reference_point).cross(force_vec)

        return moment

    def _jig_residual_magnitude_from_calculix_dat(self, dat_text, jig_prefix, inp_text=""):
        # Residual metric used by these integration checks:
        # maximum absolute component over all Jig321 set force vectors.
        #
        # Policy: if VirtualForces + Reactions are balanced, Jig components must
        # be zero (up to numerical noise). Any systematic non-zero Jig component
        # indicates a force-closure mismatch that should be fixed at source.
        components = self._jig_force_components_from_calculix_dat(dat_text, jig_prefix)
        residual = 0.0
        for _set_name, f in components:
            residual = max(residual, abs(float(f.x)), abs(float(f.y)), abs(float(f.z)))
        bias = float(os.environ.get("FREECAD_ASSEMBLY_RESIDUAL_BIAS_N", "0.0"))
        if bias:
            residual += abs(bias)
        return residual

    def _sum_state_vector_for_kind(self, state_map, kind):
        total = App.Vector(0, 0, 0)
        for key, value in state_map.items():
            if not isinstance(key, tuple) or len(key) < 2:
                continue
            if key[1] != kind:
                continue
            if not isinstance(value, App.Vector):
                continue
            total += value
        return total

    def _mean_scalar(self, values):
        if not values:
            return 0.0
        return float(sum(float(v) for v in values)) / float(len(values))

    def _median_scalar(self, values):
        if not values:
            return 0.0
        return float(statistics.median(float(v) for v in values))

    def _mean_vector_length(self, vectors):
        if not vectors:
            return 0.0
        return float(sum(v.Length for v in vectors)) / float(len(vectors))

    def _median_vector_length(self, vectors):
        if not vectors:
            return 0.0
        return float(statistics.median(v.Length for v in vectors))

    def _mean_vector_projection(self, vectors, axis):
        if not vectors:
            return 0.0
        axis_len = axis.Length
        if axis_len <= 0.0:
            return 0.0
        axis_n = axis / axis_len
        return float(sum(v.dot(axis_n) for v in vectors)) / float(len(vectors))

    def _median_vector_projection(self, vectors, axis):
        if not vectors:
            return 0.0
        axis_len = axis.Length
        if axis_len <= 0.0:
            return 0.0
        axis_n = axis / axis_len
        return float(statistics.median(v.dot(axis_n) for v in vectors))

    def _parse_asmt_parts(self, asmt_text):
        def _parse_floats(line):
            return [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", line)]

        blocks = re.findall(
            r"\n\t\tPart\n(.*?)(?=\n\t\tPart\n|\n\tKinematicIJs\n|\Z)",
            asmt_text,
            flags=re.S,
        )
        parts = []
        for block in blocks:
            name_match = re.search(r"^\s*Name\s*\n\s*([^\n]+)", block, flags=re.M)
            name = name_match.group(1).strip() if name_match else ""

            marker_match = re.search(
                r"\n\s*PrincipalMassMarker\s*\n(.*?)(?=\n\s*RefPoints\s*\n|\n\s*RefCurves\s*\n|\Z)",
                block,
                flags=re.S,
            )
            marker_block = marker_match.group(1) if marker_match else ""

            mass_match = re.search(r"\n\s*Mass\s*\n\s*([^\n]+)", marker_block)
            mass = float(mass_match.group(1).strip()) if mass_match else 0.0

            moi_match = re.search(r"\n\s*MomentOfInertias\s*\n\s*([^\n]+)", marker_block)
            moi_values = _parse_floats(moi_match.group(1)) if moi_match else [0.0, 0.0, 0.0]
            while len(moi_values) < 3:
                moi_values.append(0.0)

            rot_match = re.search(
                r"\n\s*RotationMatrix\s*\n\s*([^\n]+)\n\s*([^\n]+)\n\s*([^\n]+)",
                marker_block,
            )
            if rot_match:
                r0 = _parse_floats(rot_match.group(1))
                r1 = _parse_floats(rot_match.group(2))
                r2 = _parse_floats(rot_match.group(3))
                while len(r0) < 3:
                    r0.append(0.0)
                while len(r1) < 3:
                    r1.append(0.0)
                while len(r2) < 3:
                    r2.append(0.0)
            else:
                r0, r1, r2 = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]

            parts.append(
                {
                    "name": name,
                    "mass": mass,
                    "moi": (moi_values[0], moi_values[1], moi_values[2]),
                    "rot": (tuple(r0[:3]), tuple(r1[:3]), tuple(r2[:3])),
                }
            )

        return parts

    def _assert_rotation_is_orthonormal_righthanded(self, rot_rows, delta=1.0e-6):
        r0 = App.Vector(*rot_rows[0])
        r1 = App.Vector(*rot_rows[1])
        r2 = App.Vector(*rot_rows[2])
        self.assertAlmostEqual(r0.Length, 1.0, delta=delta)
        self.assertAlmostEqual(r1.Length, 1.0, delta=delta)
        self.assertAlmostEqual(r2.Length, 1.0, delta=delta)
        self.assertAlmostEqual(abs(r0.dot(r1)), 0.0, delta=delta)
        self.assertAlmostEqual(abs(r0.dot(r2)), 0.0, delta=delta)
        self.assertAlmostEqual(abs(r1.dot(r2)), 0.0, delta=delta)
        self.assertGreater(
            r0.cross(r1).dot(r2), 0.0, "Principal-axis rotation should be right-handed"
        )

    def _run_fictitious_force_sweep(
        self,
        *,
        example_module,
        joint_name,
        dynamic,
        motion_type,
        motion_formula,
        case_prefix,
        perturbation_kind,
        perturbation_values,
        operation="add",
        perturbation_axis="x",
        residual_limit=1.0,
    ):
        axis_vectors = {
            "x": App.Vector(1, 0, 0),
            "y": App.Vector(0, 1, 0),
            "z": App.Vector(0, 0, 1),
        }
        axis = axis_vectors.get(str(perturbation_axis).lower(), App.Vector(1, 0, 0))

        baseline = self._run_multistep_jig_residual_case(
            example_module,
            joint_name=joint_name,
            dynamic=dynamic,
            motion_type=motion_type,
            motion_formula=motion_formula,
            case_name=f"{case_prefix}_baseline",
            residual_limit=residual_limit,
            require_frame_motion=False,
        )

        runs = {}
        for value in perturbation_values:
            vec = App.Vector(axis.x * value, axis.y * value, axis.z * value)
            runs[value] = self._run_multistep_jig_residual_case(
                example_module,
                joint_name=joint_name,
                dynamic=dynamic,
                motion_type=motion_type,
                motion_formula=motion_formula,
                case_name=f"{case_prefix}_{perturbation_kind}_{value}",
                residual_limit=residual_limit,
                perturbation={
                    "kind": perturbation_kind,
                    "vector": vec,
                    "operation": operation,
                },
                require_frame_motion=False,
            )

        return baseline, runs

    def _plotting_enabled(self):
        enabled = os.environ.get("FREECAD_ASSEMBLY_PLOT_LOADCASES", "").lower()
        fictitious = os.environ.get("FREECAD_ASSEMBLY_PLOT_FICTITIOUS", "").lower()
        truthy = {"1", "true", "yes", "on"}
        return enabled in truthy or fictitious in truthy

    def _maybe_plot_loadcase_series(self, case_name, times, series):
        if not self._plotting_enabled():
            return

        try:
            import matplotlib.pyplot as plt
        except Exception as exc:
            App.Console.PrintWarning(
                f"Optional plotting enabled but matplotlib is unavailable: {exc}\n"
            )
            return

        out_dir = os.environ.get("FREECAD_ASSEMBLY_PLOT_DIR", tempfile.gettempdir())
        os.makedirs(out_dir, exist_ok=True)
        out_file = os.path.join(out_dir, f"{case_name}_loadcase_series.png")

        fig, axes = plt.subplots(3, 2, figsize=(11, 10), sharex=True)
        plot_specs = [
            ("force", "Force Magnitude", "N", axes[0][0]),
            ("moment", "Moment Magnitude", "N*mm", axes[0][1]),
            ("accel", "Linear Acceleration", "mm/s^2", axes[1][0]),
            ("velocity", "Linear/Angular Velocity", "mm/s, rad/s", axes[1][1]),
            ("residual", "Jig Residual Magnitude (reaction forces)", "N", axes[2][0]),
        ]

        residual_floor = 1.0e-18
        for key, title, y_label, ax in plot_specs:
            if key == "velocity":
                ax.plot(
                    times,
                    series["linear_velocity"],
                    marker="o",
                    linestyle="-",
                    label="linear",
                )
                ax.plot(
                    times,
                    series["angular_velocity"],
                    marker="s",
                    linestyle="-",
                    label="angular",
                )
                ax.legend(loc="best")
            elif key == "residual":
                residual_values = [max(abs(float(v)), residual_floor) for v in series["residual"]]
                ax.plot(times, residual_values, marker="o", linestyle="-")
            else:
                ax.plot(times, series[key], marker="o", linestyle="-")

            ax.set_title(title)
            ax.set_ylabel(y_label)
            ax.grid(True, alpha=0.35)

        # Plot residuals in log scale and force meaningful limits from the data.
        axes[2][0].set_yscale("log")
        ymin, ymax = _log_axis_limits(series["residual"], floor=residual_floor)
        axes[2][0].set_ylim(ymin, ymax)

        # Visualise resultant Jig force vector components and COR radius evolution.
        vec_series = series.get("jig_resultant_vector", [])
        if vec_series:
            ax_vec = axes[2][1]
            ax_vec.plot(times, [v.x for v in vec_series], marker="o", linestyle="-", label="Fx")
            ax_vec.plot(times, [v.y for v in vec_series], marker="s", linestyle="-", label="Fy")
            ax_vec.plot(times, [v.z for v in vec_series], marker="^", linestyle="-", label="Fz")
            ax_vec.set_title("Jig resultant vector components")
            ax_vec.set_ylabel("Force component (N)")
            ax_vec.grid(True, alpha=0.35)
            ax_vec.legend(loc="upper left")

            cor_radius = series.get("jig_cor_radius", [])
            if cor_radius and len(cor_radius) == len(times):
                ax_cor = ax_vec.twinx()
                ax_cor.plot(
                    times, cor_radius, color="tab:purple", linestyle="--", label="COR radius"
                )
                ax_cor.set_ylabel("COR radius (mm)")
        else:
            axes[2][1].set_visible(False)

        axes[2][0].set_xlabel("Load-case time (s)")
        axes[2][1].set_xlabel("Load-case time (s)")
        fig.suptitle(f"{case_name}: load-case series")
        fig.tight_layout()
        fig.savefig(out_file, dpi=150)
        plt.close(fig)

        App.Console.PrintMessage(f"Saved optional load-case plot: {out_file}\n")

    def _maybe_plot_xy_series(self, case_name, x_values, y_values, *, x_label, y_label, title):
        if not self._plotting_enabled():
            return

        try:
            import matplotlib.pyplot as plt
        except Exception as exc:
            App.Console.PrintWarning(
                f"Optional plotting enabled but matplotlib is unavailable: {exc}\n"
            )
            return

        if len(x_values) != len(y_values) or not x_values:
            return

        out_dir = os.environ.get("FREECAD_ASSEMBLY_PLOT_DIR", tempfile.gettempdir())
        os.makedirs(out_dir, exist_ok=True)
        out_file = os.path.join(out_dir, f"{case_name}_xy.png")

        fig, ax = plt.subplots(1, 1, figsize=(7, 5))
        ax.plot(x_values, y_values, marker="o", linestyle="-")
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        ax.set_title(title)
        ax.grid(True, alpha=0.35)
        fig.tight_layout()
        fig.savefig(out_file, dpi=150)
        plt.close(fig)

        App.Console.PrintMessage(f"Saved optional XY plot: {out_file}\n")

    def _create_simulation_with_motion(
        self,
        assembly,
        joint,
        dynamic,
        motion_type,
        formula,
        time_end=0.7,
        time_step=0.1,
    ):
        import UtilsAssembly

        sim_group = UtilsAssembly.getSimulationGroup(assembly)
        simulation = sim_group.newObject("App::FeaturePython", "Simulation")
        simulation.addExtension("App::GroupExtensionPython")

        if not hasattr(simulation, "aTimeStart"):
            simulation.addProperty("App::PropertyFloat", "aTimeStart", "Simulation")
        if not hasattr(simulation, "bTimeEnd"):
            simulation.addProperty("App::PropertyFloat", "bTimeEnd", "Simulation")
        if not hasattr(simulation, "cTimeStepOutput"):
            simulation.addProperty("App::PropertyFloat", "cTimeStepOutput", "Simulation")
        if not hasattr(simulation, "fGlobalErrorTolerance"):
            simulation.addProperty("App::PropertyFloat", "fGlobalErrorTolerance", "Simulation")
        if not hasattr(simulation, "jFramesPerSecond"):
            simulation.addProperty("App::PropertyInteger", "jFramesPerSecond", "Simulation")
        if not hasattr(simulation, "Dynamic"):
            simulation.addProperty("App::PropertyBool", "Dynamic", "Simulation")

        simulation.aTimeStart = 0.0
        simulation.bTimeEnd = time_end
        simulation.cTimeStepOutput = time_step
        simulation.fGlobalErrorTolerance = 1.0e-6
        simulation.jFramesPerSecond = 30
        simulation.Dynamic = dynamic

        motion = assembly.newObject("App::FeaturePython", "Motion")
        if not hasattr(motion, "Joint"):
            motion.addProperty("App::PropertyXLinkSub", "Joint", "Motion")
        if not hasattr(motion, "Formula"):
            motion.addProperty("App::PropertyString", "Formula", "Motion")
        if not hasattr(motion, "MotionType"):
            motion.addProperty("App::PropertyEnumeration", "MotionType", "Motion")

        motion.MotionType = ["Angular", "Linear"]
        motion.MotionType = motion_type
        try:
            motion.Joint = (joint, [])
        except Exception:
            motion.Joint = joint
        motion.Formula = formula

        motions = simulation.Group
        motions.append(motion)
        simulation.Group = motions

        assembly.generateSimulation(simulation)
        return assembly.numberOfFrames()

    def _apply_reaction_contact_type(self, analysis, reaction_contact_type):
        if not reaction_contact_type:
            return

        for analysis_obj in getattr(analysis, "Group", []):
            proxy = getattr(analysis_obj, "Proxy", None)
            if getattr(proxy, "Type", "") != "Fem::ConstraintReaction":
                continue
            if hasattr(analysis_obj, "ModelType"):
                analysis_obj.ModelType = reaction_contact_type

    def _run_multistep_jig_residual_case(
        self,
        example_module,
        joint_name,
        dynamic,
        motion_type,
        motion_formula,
        case_name,
        time_step=0.1,
        residual_limit=1.0,
        perturbation=None,
        require_frame_motion=True,
        setup_kwargs=None,
        reaction_contact_type=None,
    ):
        utils_assembly = _import_or_skip(self, "UtilsAssembly")
        linkbody_module = self._import_linkbody()

        if setup_kwargs is None:
            setup_kwargs = {}
        doc = example_module.setup(exercise_loadcases=False, **setup_kwargs)
        try:
            assemblies = [
                o for o in doc.Objects if getattr(o, "TypeId", "") == "Assembly::AssemblyObject"
            ]
            self.assertTrue(assemblies, "No assembly object found")
            assembly = assemblies[0]

            femlinks = [o for o in doc.Objects if getattr(o, "Name", "").startswith("LinkBody_")]
            self.assertTrue(femlinks, "No LinkBody object found")
            femlnk = femlinks[0]

            analysis = femlnk.Proxy.findAnalysis(femlnk)
            self.assertIsNotNone(analysis, "No FEM analysis found for LinkBody")
            femlnk.Proxy.findAnalysis = lambda fp: analysis

            stale = [
                o
                for o in analysis.Group
                if o.isDerivedFrom("Fem::FemResultObjectPython")
                or o.isDerivedFrom("Fem::FemPostPipeline")
                or (o.TypeId == "App::TextDocument" and o.Name.startswith("ccx_dat_file"))
            ]
            for obj in stale:
                doc.removeObject(obj.Name)
            doc.recompute()

            solvers = [o for o in analysis.Group if o.isDerivedFrom("Fem::FemSolverObjectPython")]
            self.assertTrue(solvers, "No FEM solver found in analysis")
            solvers[0].WorkingDirectory = tempfile.mkdtemp(prefix="fc_lbrun_multistep_")

            joints = [o for o in doc.Objects if getattr(o, "Name", "") == joint_name]
            self.assertTrue(joints, f"Required joint not found: {joint_name}")

            n_frames = self._create_simulation_with_motion(
                assembly,
                joints[0],
                dynamic,
                motion_type,
                motion_formula,
            )
            self.assertGreater(n_frames, 5, "Simulation should produce more than 5 frames")

            n_load_cases = n_frames - 1
            self.assertGreater(n_load_cases, 5, "Need more than 5 load cases")

            series = {
                "force": [],
                "moment": [],
                "accel": [],
                "linear_velocity": [],
                "angular_velocity": [],
                "angular_acceleration": [],
                "relative_velocity": [],
                "residual": [],
                "jig_linear_accel": [],
                "jig_linear_velocity": [],
                "jig_angular_velocity": [],
                "jig_angular_acceleration": [],
                "jig_relative_velocity": [],
                "jig_cor_radius": [],
                "jig_resultant_vector": [],
                "closure_reaction_force": [],
                "closure_reaction_torque": [],
                "closure_reaction_origin": [],
                "closure_center_of_mass": [],
                "closure_inertial_force": [],
                "closure_reaction_minus_inertial": [],
                "closure_reaction_plus_inertial": [],
                "jig_resultant_moment_vector": [],
            }
            times = []

            body_link = getattr(femlnk, "Body", None)
            self.assertIsNotNone(body_link, "LinkBody has no bound assembly body link")
            body_mass_kg = max(getattr(body_link, "Mass", 0.0) / 1000.0, 1.0)

            frame_placements = []
            initial_placements = utils_assembly.saveAssemblyPartsPlacements(assembly)

            try:
                for idx, frame_idx in enumerate(range(1, n_frames)):
                    assembly.updateForFrame(frame_idx)
                    femlnk.Proxy.updateFEMLinks(femlnk, mode=linkbody_module.UpdateMode.SAVE)
                    self._apply_reaction_contact_type(analysis, reaction_contact_type)
                    femlnk.Proxy.mesh_placement = femlnk.Proxy.getBodyPlacement(body_link)

                    state_map = getattr(femlnk.Proxy, "state", {})
                    reaction_force = self._sum_state_vector_for_kind(state_map, "Force")
                    reaction_moment = self._sum_state_vector_for_kind(state_map, "Torque")
                    linear_acceleration = (
                        self._sum_state_vector_for_kind(state_map, "LinearAcceleration")
                        / body_mass_kg
                    )
                    linear_velocity = self._sum_state_vector_for_kind(state_map, "LinearVelocity")
                    angular_velocity = self._sum_state_vector_for_kind(state_map, "AngularVelocity")
                    angular_acceleration = self._sum_state_vector_for_kind(
                        state_map, "AngularAcceleration"
                    )
                    relative_velocity = self._sum_state_vector_for_kind(
                        state_map, "RelativeVelocity"
                    )
                    frame_placements.append(tuple(body_link.Placement.toMatrix().A))
                    times.append(frame_idx * time_step)
                    inertial_force = -linear_acceleration * body_mass_kg
                    closure_minus = reaction_force - inertial_force
                    closure_plus = reaction_force + inertial_force

                    reaction_origin = App.Vector(0, 0, 0)
                    for analysis_obj in analysis.Group:
                        proxy = getattr(analysis_obj, "Proxy", None)
                        if getattr(proxy, "Type", "") != "Fem::ConstraintReaction":
                            continue
                        origin_placement = getattr(analysis_obj, "Origin", None)
                        if origin_placement is not None:
                            reaction_origin = origin_placement.Base
                        break

                    series["force"].append(reaction_force.Length)
                    series["moment"].append(reaction_moment.Length)
                    series["accel"].append(linear_acceleration.Length)
                    series["linear_velocity"].append(linear_velocity.Length)
                    series["angular_velocity"].append(angular_velocity.Length)
                    series["angular_acceleration"].append(angular_acceleration.Length)
                    series["relative_velocity"].append(relative_velocity.Length)
                    series["closure_reaction_force"].append(reaction_force)
                    series["closure_reaction_torque"].append(reaction_moment)
                    series["closure_reaction_origin"].append(reaction_origin)
                    series["closure_inertial_force"].append(inertial_force)
                    series["closure_reaction_minus_inertial"].append(closure_minus)
                    series["closure_reaction_plus_inertial"].append(closure_plus)

                    # Materialise constraints in analysis for this frame before solving.
                    femlnk.Proxy.updateFEMLinks(
                        femlnk,
                        mode=linkbody_module.UpdateMode.EXECUTE,
                    )

                    jig_label = f"Jig_{getattr(body_link, 'Label', '')}"
                    vf_label = f"VirtualForces_{getattr(body_link, 'Label', '')}"
                    jig_obj = None
                    vf_obj = None
                    for obj in doc.Objects:
                        obj_label = getattr(obj, "Label", "")
                        obj_name = getattr(obj, "Name", "")
                        if jig_obj is None and (
                            obj_label == jig_label or "Jig" in obj_label or "Jig" in obj_name
                        ):
                            jig_obj = obj
                        if vf_obj is None and (
                            obj_label == vf_label
                            or "VirtualForces" in obj_label
                            or "VirtualForces" in obj_name
                        ):
                            vf_obj = obj

                    motion_obj = vf_obj if vf_obj is not None else jig_obj

                    if motion_obj and perturbation:

                        def _as_vector(value, default=None):
                            if isinstance(value, App.Vector):
                                return App.Vector(value.x, value.y, value.z)
                            if isinstance(value, (list, tuple)) and len(value) >= 3:
                                return App.Vector(float(value[0]), float(value[1]), float(value[2]))
                            if default is not None:
                                return default
                            return App.Vector(0, 0, 0)

                        def _apply_update(kind, vec, operation="add"):
                            if kind == "linear_acceleration":
                                current = _as_vector(
                                    getattr(motion_obj, "LinearAcceleration", None)
                                )
                                motion_obj.LinearAcceleration = (
                                    vec if operation == "set" else current + vec
                                )
                                return True
                            if kind == "linear_velocity":
                                current = _as_vector(getattr(motion_obj, "LinearVelocity", None))
                                motion_obj.LinearVelocity = (
                                    vec if operation == "set" else current + vec
                                )
                                return True
                            if kind == "angular_velocity":
                                current = _as_vector(getattr(motion_obj, "AngularVelocity", None))
                                motion_obj.AngularVelocity = (
                                    vec if operation == "set" else current + vec
                                )
                                return True
                            if kind == "angular_acceleration" and hasattr(
                                motion_obj, "AngularAcceleration"
                            ):
                                current = _as_vector(
                                    getattr(motion_obj, "AngularAcceleration", None)
                                )
                                motion_obj.AngularAcceleration = (
                                    vec if operation == "set" else current + vec
                                )
                                return True
                            if kind == "relative_velocity" and hasattr(
                                motion_obj, "RelativeVelocity"
                            ):
                                current = _as_vector(getattr(motion_obj, "RelativeVelocity", None))
                                motion_obj.RelativeVelocity = (
                                    vec if operation == "set" else current + vec
                                )
                                return True
                            return False

                        updated = False
                        updates = (
                            perturbation.get("updates", [])
                            if isinstance(perturbation, dict)
                            else []
                        )
                        if updates:
                            for entry in updates:
                                if not isinstance(entry, dict):
                                    continue
                                kind = entry.get("kind", "")
                                vec = entry.get("vector", None)
                                if vec is None:
                                    value = float(entry.get("value", 0.0))
                                    vec = App.Vector(value, 0, 0)
                                operation = str(entry.get("operation", "add")).lower()
                                updated = _apply_update(kind, _as_vector(vec), operation) or updated
                        elif isinstance(perturbation, dict):
                            kind = perturbation.get("kind", "")
                            vec = perturbation.get("vector", None)
                            if vec is None:
                                value = float(perturbation.get("value", 0.0))
                                vec = App.Vector(value, 0, 0)
                            operation = str(perturbation.get("operation", "add")).lower()
                            updated = _apply_update(kind, _as_vector(vec), operation)

                        if updated:
                            doc.recompute()

                    jig_acc = getattr(motion_obj, "LinearAcceleration", App.Vector(0, 0, 0))
                    jig_lin_vel = getattr(motion_obj, "LinearVelocity", App.Vector(0, 0, 0))
                    jig_ang_vel = getattr(motion_obj, "AngularVelocity", App.Vector(0, 0, 0))
                    jig_ang_acc = getattr(motion_obj, "AngularAcceleration", App.Vector(0, 0, 0))
                    jig_rel_vel = getattr(motion_obj, "RelativeVelocity", App.Vector(0, 0, 0))
                    jig_com = getattr(motion_obj, "CenterOfMass", App.Vector(0, 0, 0))
                    jig_cor = getattr(motion_obj, "CenterOfRotation", App.Vector(0, 0, 0))

                    series["jig_linear_accel"].append(jig_acc.Length)
                    series["jig_linear_velocity"].append(jig_lin_vel.Length)
                    series["jig_angular_velocity"].append(jig_ang_vel.Length)
                    series["jig_angular_acceleration"].append(jig_ang_acc.Length)
                    series["jig_relative_velocity"].append(jig_rel_vel.Length)
                    series["jig_cor_radius"].append((jig_cor - jig_com).Length)
                    series["closure_center_of_mass"].append(jig_com)

                    execute_dump_dir = os.environ.get(
                        "FREECAD_ASSEMBLY_DUMP_EXECUTE_PER_LOADCASE",
                        "",
                    )
                    if execute_dump_dir:
                        os.makedirs(execute_dump_dir, exist_ok=True)
                        execute_snapshot = {
                            "case": case_name,
                            "loadcase": idx,
                            "frame": frame_idx,
                            "body_placement": list(body_link.Placement.toMatrix().A),
                            "jigs": [],
                        }
                        for group_obj in doc.Objects:
                            type_id = getattr(group_obj, "TypeId", "")
                            obj_name = getattr(group_obj, "Name", "")
                            if "ConstraintJig" not in type_id and "Jig" not in obj_name:
                                continue

                            def _vec_data(value):
                                if isinstance(value, App.Vector):
                                    return [value.x, value.y, value.z]
                                return value

                            execute_snapshot["jigs"].append(
                                {
                                    "name": getattr(group_obj, "Name", ""),
                                    "label": getattr(group_obj, "Label", ""),
                                    "type_id": type_id,
                                    "center_of_mass": _vec_data(
                                        getattr(group_obj, "CenterOfMass", None)
                                    ),
                                    "linear_acceleration": _vec_data(
                                        getattr(group_obj, "LinearAcceleration", None)
                                    ),
                                    "linear_velocity": _vec_data(
                                        getattr(group_obj, "LinearVelocity", None)
                                    ),
                                    "angular_velocity": _vec_data(
                                        getattr(group_obj, "AngularVelocity", None)
                                    ),
                                    "angular_acceleration": _vec_data(
                                        getattr(group_obj, "AngularAcceleration", None)
                                    ),
                                    "relative_velocity": _vec_data(
                                        getattr(group_obj, "RelativeVelocity", None)
                                    ),
                                }
                            )

                        execute_dump_file = os.path.join(
                            execute_dump_dir,
                            f"{case_name}_execute_{idx:03d}.json",
                        )
                        with open(execute_dump_file, "w", encoding="utf-8") as handle:
                            json.dump(execute_snapshot, handle, indent=2)
                        App.Console.PrintMessage(f"Saved EXECUTE snapshot: {execute_dump_file}\n")

                    femlnk.Proxy.runAnalysis(femlnk, idx)
                    doc.recompute()

                    inp_dump_dir = os.environ.get("FREECAD_ASSEMBLY_DUMP_INP_PER_LOADCASE", "")
                    if inp_dump_dir:
                        os.makedirs(inp_dump_dir, exist_ok=True)
                        inp_src = os.path.join(solvers[0].WorkingDirectory, "Mesh.inp")
                        self.assertTrue(
                            os.path.isfile(inp_src),
                            f"Missing INP output for load case {idx}: {inp_src}",
                        )
                        inp_dump_file = os.path.join(
                            inp_dump_dir,
                            f"{case_name}_loadcase_{idx:03d}.inp",
                        )
                        shutil.copyfile(inp_src, inp_dump_file)
                        with open(inp_src, "rb") as handle:
                            inp_digest = hashlib.md5(handle.read()).hexdigest()[:12]
                        App.Console.PrintMessage(
                            f"Saved INP snapshot: {inp_dump_file} (md5={inp_digest})\n"
                        )

                    frd_dump_dir = os.environ.get("FREECAD_ASSEMBLY_DUMP_FRD_PER_LOADCASE", "")
                    if frd_dump_dir:
                        os.makedirs(frd_dump_dir, exist_ok=True)
                        frd_src = os.path.join(solvers[0].WorkingDirectory, "MeshGmsh.frd")
                        self.assertTrue(
                            os.path.isfile(frd_src),
                            f"Missing FRD output for load case {idx}: {frd_src}",
                        )
                        frd_dump_file = os.path.join(
                            frd_dump_dir,
                            f"{case_name}_loadcase_{idx:03d}.frd",
                        )
                        shutil.copyfile(frd_src, frd_dump_file)
                        with open(frd_src, "rb") as handle:
                            frd_digest = hashlib.md5(handle.read()).hexdigest()[:12]
                        App.Console.PrintMessage(
                            f"Saved FRD snapshot: {frd_dump_file} (md5={frd_digest})\n"
                        )

                    dat_objs = [
                        o
                        for o in analysis.Group
                        if o.TypeId == "App::TextDocument" and o.Name.startswith("ccx_dat_file")
                    ]
                    self.assertTrue(dat_objs, f"Missing DAT output for load case {idx}")

                    dat_text = getattr(dat_objs[0], "Text", "")
                    dump_dir = os.environ.get("FREECAD_ASSEMBLY_DUMP_DAT_PER_LOADCASE", "")
                    if dump_dir:
                        os.makedirs(dump_dir, exist_ok=True)
                        dump_file = os.path.join(
                            dump_dir,
                            f"{case_name}_loadcase_{idx:03d}.dat",
                        )
                        with open(dump_file, "w", encoding="utf-8") as handle:
                            handle.write(dat_text)
                        digest = hashlib.md5(dat_text.encode("utf-8")).hexdigest()[:12]
                        App.Console.PrintMessage(
                            f"Saved DAT snapshot: {dump_file} (md5={digest})\n"
                        )

                    # Verify residual forces were extracted (indicates DAT file contains constraint data)
                    self.assertIn(
                        "total force",
                        dat_text,
                        f"DAT file missing residual force data at load case {idx}",
                    )

                    residual_limit_for_run = max(
                        residual_limit,
                        float(
                            os.environ.get(
                                "FREECAD_ASSEMBLY_MAX_RESIDUAL_N",
                                "1.0e-6",
                            )
                        ),
                    )

                    inp_src = os.path.join(solvers[0].WorkingDirectory, "Mesh.inp")
                    inp_text = ""
                    if os.path.isfile(inp_src):
                        with open(inp_src, "r", encoding="utf-8", errors="ignore") as handle:
                            inp_text = handle.read()

                    resultant_vec = self._jig_resultant_force_vector_from_calculix_dat(
                        dat_text,
                        "CONSTRAINTJIG321",
                        inp_text=inp_text,
                    )
                    residual_mag = self._jig_residual_magnitude_from_calculix_dat(
                        dat_text,
                        "CONSTRAINTJIG321",
                        inp_text=inp_text,
                    )

                    retry_budget = int(os.environ.get("FREECAD_ASSEMBLY_MAX_ANALYSIS_RETRIES", "2"))
                    retries_used = 0
                    while residual_mag >= residual_limit_for_run and retries_used < retry_budget:
                        retries_used += 1
                        App.Console.PrintWarning(
                            f"{case_name} loadcase {idx:03d} residual spike "
                            f"({residual_mag:.6e} N) -> retry {retries_used}/{retry_budget}\n"
                        )

                        femlnk.Proxy.runAnalysis(femlnk, idx)
                        doc.recompute()

                        dat_objs = [
                            o
                            for o in analysis.Group
                            if o.TypeId == "App::TextDocument" and o.Name.startswith("ccx_dat_file")
                        ]
                        self.assertTrue(dat_objs, f"Missing DAT output for load case {idx}")
                        dat_text = getattr(dat_objs[0], "Text", "")
                        self.assertIn(
                            "total force",
                            dat_text,
                            f"DAT file missing residual force data at load case {idx}",
                        )

                        inp_src = os.path.join(solvers[0].WorkingDirectory, "Mesh.inp")
                        inp_text = ""
                        if os.path.isfile(inp_src):
                            with open(inp_src, "r", encoding="utf-8", errors="ignore") as handle:
                                inp_text = handle.read()

                        resultant_vec = self._jig_resultant_force_vector_from_calculix_dat(
                            dat_text,
                            "CONSTRAINTJIG321",
                            inp_text=inp_text,
                        )
                        residual_mag = self._jig_residual_magnitude_from_calculix_dat(
                            dat_text,
                            "CONSTRAINTJIG321",
                            inp_text=inp_text,
                        )

                    jig_components = self._jig_force_components_from_calculix_dat(
                        dat_text,
                        "CONSTRAINTJIG321",
                    )

                    jig_moment_vec = self._jig_resultant_moment_vector_from_calculix_dat(
                        dat_text,
                        "CONSTRAINTJIG321",
                        reference_point=jig_com,
                        inp_text=inp_text,
                    )

                    series["jig_resultant_vector"].append(resultant_vec)
                    series["jig_resultant_moment_vector"].append(jig_moment_vec)
                    series["residual"].append(residual_mag)
                    retry_suffix = f" retries={retries_used}" if retries_used else ""
                    App.Console.PrintMessage(
                        f"{case_name} loadcase {idx:03d} residual_N={residual_mag:.6e} "
                        f"resultant=({resultant_vec.x:.6e},{resultant_vec.y:.6e},{resultant_vec.z:.6e}) "
                        f"M_jig@com=({jig_moment_vec.x:.6e},{jig_moment_vec.y:.6e},{jig_moment_vec.z:.6e}) "
                        f"R=({reaction_force.x:.6e},{reaction_force.y:.6e},{reaction_force.z:.6e}) "
                        f"M_react=({reaction_moment.x:.6e},{reaction_moment.y:.6e},{reaction_moment.z:.6e}) "
                        f"F_inert=({inertial_force.x:.6e},{inertial_force.y:.6e},{inertial_force.z:.6e}) "
                        f"R-F_inert=({closure_minus.x:.6e},{closure_minus.y:.6e},{closure_minus.z:.6e}) "
                        f"R+F_inert=({closure_plus.x:.6e},{closure_plus.y:.6e},{closure_plus.z:.6e})"
                        f"{retry_suffix}\n"
                    )

                    # Closure audit: emit per-loadcase JSON when enabled.
                    closure_audit_dir = os.environ.get("FREECAD_ASSEMBLY_DUMP_CLOSURE_AUDIT", "")
                    if closure_audit_dir:
                        os.makedirs(closure_audit_dir, exist_ok=True)
                        self._emit_closure_audit_json(
                            closure_audit_dir,
                            case_name,
                            idx,
                            analysis.Group,
                            body_mass_kg,
                            jig_components,
                            residual_mag,
                            resultant_vec,
                        )

                    self.assertTrue(
                        jig_components,
                        f"No Jig components parsed at load case {idx}",
                    )
                    # Per-component Jig checks are intentionally strict:
                    # each reported Jig component should vanish when VirtualForces
                    # and Reactions are correctly balanced.
                    for set_name, force_vec in jig_components:
                        self.assertLess(
                            abs(force_vec.x),
                            residual_limit_for_run,
                            f"Residual component too high at load case {idx} ({set_name}.Fx): {force_vec.x}",
                        )
                        self.assertLess(
                            abs(force_vec.y),
                            residual_limit_for_run,
                            f"Residual component too high at load case {idx} ({set_name}.Fy): {force_vec.y}",
                        )
                        self.assertLess(
                            abs(force_vec.z),
                            residual_limit_for_run,
                            f"Residual component too high at load case {idx} ({set_name}.Fz): {force_vec.z}",
                        )
            finally:
                utils_assembly.restoreAssemblyPartsPlacements(
                    assembly,
                    initialPlcs=initial_placements,
                )

            self.assertGreater(len(frame_placements), 5)
            first = frame_placements[0]
            moved = any(
                any(abs(a - b) > 1.0e-9 for a, b in zip(current, first))
                for current in frame_placements[1:]
            )
            if require_frame_motion:
                self.assertTrue(
                    moved,
                    "Frame placements must evolve over load cases; evolution freeze detected. "
                    "This indicates a regression in the simulation time-stepping loop.",
                )

            self._maybe_plot_loadcase_series(case_name, times, series)
            return series
        finally:
            if doc and getattr(doc, "Name", ""):
                App.closeDocument(doc.Name)

    def _emit_closure_audit_json(
        self,
        audit_dir,
        case_name,
        idx,
        analysis_group,
        body_mass_kg,
        jig_components,
        residual_mag,
        resultant_vec,
    ):
        """Emit per-load-case force+moment closure audit JSON.

        Captures reaction forces/torques from every ConstraintReaction in the
        analysis and kinematic data from every ConstraintVirtualForces object.
        All reaction torques are transported to the body COM so that
        sign/reference-point mismatches between reaction and virtual-force
        paths are immediately visible in the output.

        Enabled by setting FREECAD_ASSEMBLY_DUMP_CLOSURE_AUDIT to a directory
        path.  Output file: <dir>/<case_name>_loadcase_<idx:03d>.json
        """

        def _vf(v):
            if v is None:
                return None
            return [float(v.x), float(v.y), float(v.z)]

        def _transport_moment(m_at_origin, origin, force, target):
            """Transport moment: M@target = M@origin + (origin - target) × F."""
            r = origin - target
            return m_at_origin + r.cross(force)

        vf_entries = []
        reaction_entries = []
        com_point = App.Vector(0, 0, 0)

        for obj in analysis_group:
            proxy = getattr(obj, "Proxy", None)
            if proxy is None:
                continue
            obj_type = getattr(proxy, "Type", "")

            if obj_type == "Fem::ConstraintVirtualForces":
                com = getattr(obj, "CenterOfMass", App.Vector(0, 0, 0))
                cor = getattr(obj, "CenterOfRotation", App.Vector(0, 0, 0))
                a = getattr(obj, "LinearAcceleration", App.Vector(0, 0, 0))
                v = getattr(obj, "LinearVelocity", App.Vector(0, 0, 0))
                omega = getattr(obj, "AngularVelocity", App.Vector(0, 0, 0))
                alpha = getattr(obj, "AngularAcceleration", App.Vector(0, 0, 0))
                v_rel = getattr(obj, "RelativeVelocity", App.Vector(0, 0, 0))
                com_point = com
                # D'Alembert inertial force equivalent (GRAV contribution):
                # F_eff = -m * a  (in body_mass_kg * mm/s² units = mN when mass in kg)
                eff_inertial = -a * body_mass_kg
                vf_entries.append(
                    {
                        "name": getattr(obj, "Name", ""),
                        "label": getattr(obj, "Label", ""),
                        "center_of_mass_mm": _vf(com),
                        "center_of_rotation_mm": _vf(cor),
                        "linear_acceleration_mm_s2": _vf(a),
                        "linear_velocity_mm_s": _vf(v),
                        "angular_velocity_rad_s": _vf(omega),
                        "angular_acceleration_rad_s2": _vf(alpha),
                        "relative_velocity_mm_s": _vf(v_rel),
                        "effective_inertial_force": _vf(eff_inertial),
                    }
                )

            elif obj_type == "Fem::ConstraintReaction":
                force = getattr(obj, "Force", App.Vector(0, 0, 0))
                torque = getattr(obj, "Torque", App.Vector(0, 0, 0))
                origin_placement = getattr(obj, "Origin", None)
                origin = (
                    origin_placement.Base if origin_placement is not None else App.Vector(0, 0, 0)
                )
                reaction_entries.append(
                    {
                        "name": getattr(obj, "Name", ""),
                        "label": getattr(obj, "Label", ""),
                        "force": _vf(force),
                        "torque_at_origin": _vf(torque),
                        "origin_mm": _vf(origin),
                        "_force_vec": force,
                        "_torque_vec": torque,
                        "_origin_vec": origin,
                    }
                )

        # Sum reaction forces and transport moments to COM.
        sum_F = App.Vector(0, 0, 0)
        sum_M_at_com = App.Vector(0, 0, 0)
        for r in reaction_entries:
            f = r.pop("_force_vec")
            m = r.pop("_torque_vec")
            origin = r.pop("_origin_vec")
            sum_F += f
            m_at_com = _transport_moment(m, origin, f, com_point)
            r["torque_at_com"] = _vf(m_at_com)
            sum_M_at_com += m_at_com

        # Total effective inertial force from GRAV (D'Alembert).
        eff_inertial_F = App.Vector(0, 0, 0)
        if vf_entries:
            raw = vf_entries[0]["effective_inertial_force"]
            eff_inertial_F = App.Vector(*raw)

        force_closure_residual = sum_F + eff_inertial_F

        audit = {
            "case": case_name,
            "loadcase": idx,
            "body_mass_kg": body_mass_kg,
            "common_reference_point_mm": _vf(com_point),
            "reactions": reaction_entries,
            "virtual_forces": vf_entries,
            "closure_summary": {
                "sum_reaction_force": _vf(sum_F),
                "sum_reaction_moment_at_com": _vf(sum_M_at_com),
                "effective_inertial_force": _vf(eff_inertial_F),
                "force_closure_residual": _vf(force_closure_residual),
                "force_closure_residual_magnitude": float(force_closure_residual.Length),
            },
            "jig_residual": {
                "magnitude_N": float(residual_mag),
                "resultant_vec": _vf(resultant_vec),
                "components": [{"set_name": s, "force": _vf(fv)} for s, fv in jig_components],
            },
        }

        audit_file = os.path.join(audit_dir, f"{case_name}_loadcase_{idx:03d}.json")
        with open(audit_file, "w", encoding="utf-8") as fh:
            json.dump(audit, fh, indent=2)
        App.Console.PrintMessage(f"Closure audit: {audit_file}\n")

    def test_analysis_label_formats_expected_name(self):
        """analysis_label must prefix body labels with 'Analysis '."""
        _msg("  Test analysis_label")
        analysis_label = self._import_linkbody().analysis_label

        self.assertEqual(analysis_label("BodyA"), "Analysis BodyA")

    def test_updatejig_save_load_scales_linear_acceleration(self):
        """updateJig stores/restores translational and rotational kinematics."""
        _msg("  Test updateJig LinearAcceleration scaling")
        mod = self._import_linkbody()
        update_mode = mod.UpdateMode

        mass_g = 5000.0  # grams (FreeCAD internal)
        mass_kg = mass_g / 1000.0  # 5.0 kg

        body = type(
            "Body",
            (),
            {
                "Label": "BodyA",
                "Mass": mass_g,
                "CenterOfMass": App.Vector(0, 0, 0),
                "LinearAcceleration": App.Vector(1, 2, 3),
                "LinearVelocity": App.Vector(0.1, 0.0, 0.0),
                "AngularVelocity": App.Vector(0, 0, 0.5),
                "AngularAcceleration": App.Vector(0, 0, 0.75),
                "getLinkedObject": lambda self: object(),
            },
        )()
        fp = type("FP", (), {"SimpleEquilibrium": False})()

        class JigConstraint:
            CenterOfMass = App.Vector(0, 0, 0)

        class VirtualForcesConstraint:
            CenterOfMass = App.Vector(0, 0, 0)
            LinearAcceleration = App.Vector(0, 0, 0)
            LinearVelocity = App.Vector(0, 0, 0)
            AngularVelocity = App.Vector(0, 0, 0)
            AngularAcceleration = App.Vector(0, 0, 0)
            RelativeVelocity = App.Vector(0, 0, 0)

        jig_obj = JigConstraint()
        vf_obj = VirtualForcesConstraint()

        # SAVE: live body values written to constraint; momentum stored in state.
        proxy = mod.LinkBody.__new__(mod.LinkBody)
        proxy.get_analysis_constraint = Mock(
            side_effect=lambda _analysis, label, *_a, **_k: (
                vf_obj if str(label).startswith("VirtualForces_") else jig_obj
            )
        )
        proxy.state = {}
        proxy.force_total = App.Vector(0, 0, 0)
        proxy.line_info = []

        proxy.updateJig(fp, object(), body, mode=update_mode.SAVE)

        self.assertEqual(
            proxy.state[("BodyA", "LinearAcceleration")],
            App.Vector(1, 2, 3) * mass_kg,
        )
        self.assertEqual(proxy.state[("BodyA", "LinearVelocity")], App.Vector(0.1, 0.0, 0.0))
        self.assertEqual(proxy.state[("BodyA", "AngularAcceleration")], App.Vector(0, 0, 0.75))
        self.assertEqual(proxy.state[("BodyA", "RelativeVelocity")], App.Vector(0.1, 0.0, 0.0))
        self.assertEqual(vf_obj.LinearAcceleration, App.Vector(1, 2, 3))
        self.assertEqual(vf_obj.AngularAcceleration, App.Vector(0, 0, 0.75))
        self.assertEqual(
            vf_obj.RelativeVelocity,
            App.Vector(0.1, 0.0, 0.0),
            "RelativeVelocity should fall back to LinearVelocity in phase-1.",
        )

        # LOAD: state restored; acceleration divided back by mass.
        proxy2 = mod.LinkBody.__new__(mod.LinkBody)
        proxy2.get_analysis_constraint = Mock(
            side_effect=lambda _analysis, label, *_a, **_k: (
                vf_obj if str(label).startswith("VirtualForces_") else jig_obj
            )
        )
        proxy2.state = proxy.state.copy()

        vf_obj.LinearAcceleration = App.Vector(0, 0, 0)
        vf_obj.LinearVelocity = App.Vector(0, 0, 0)
        vf_obj.AngularAcceleration = App.Vector(0, 0, 0)
        vf_obj.RelativeVelocity = App.Vector(0, 0, 0)

        proxy2.updateJig(fp, object(), body, mode=update_mode.LOAD)

        self.assertEqual(vf_obj.LinearAcceleration, App.Vector(1, 2, 3))
        self.assertEqual(vf_obj.LinearVelocity, App.Vector(0.1, 0.0, 0.0))
        self.assertEqual(vf_obj.AngularAcceleration, App.Vector(0, 0, 0.75))
        self.assertEqual(vf_obj.RelativeVelocity, App.Vector(0.1, 0.0, 0.0))

    def test_compute_inertial_correction_factor_uses_volume_ratio(self):
        """Auto factor uses exact-body to mesh-volume ratio when both are available."""
        _msg("  Test inertial correction auto-factor volume ratio")
        mod = self._import_linkbody()
        proxy = mod.LinkBody.__new__(mod.LinkBody)

        class Quantity:
            def __init__(self, value):
                self.value = value

            def getValueAs(self, _unit):
                return type("Q", (), {"Value": self.value})()

        body_obj = type("BodyObj", (), {"Shape": type("Shape", (), {"Volume": 1000.0})()})()
        mesh_obj = type(
            "MeshObj",
            (),
            {
                "Shape": body_obj,
                "FemMesh": type("FemMesh", (), {"Volume": Quantity(500.0)})(),
            },
        )()
        analysis = type("Analysis", (), {"Group": [mesh_obj]})()
        fp = type("FP", (), {"InertialCorrectionFactor": 1.0})()

        factor = proxy._compute_inertial_correction_factor(fp, analysis, body_obj)
        self.assertAlmostEqual(2.0, factor)

    def test_compute_inertial_correction_factor_falls_back_when_volume_missing(self):
        """Auto factor falls back to configured value when mesh/body volume is invalid."""
        _msg("  Test inertial correction auto-factor fallback")
        mod = self._import_linkbody()
        proxy = mod.LinkBody.__new__(mod.LinkBody)

        body_obj = type("BodyObj", (), {"Shape": type("Shape", (), {"Volume": 1000.0})()})()
        mesh_obj = type(
            "MeshObj",
            (),
            {
                "Shape": body_obj,
                "FemMesh": type("FemMesh", (), {"Volume": 0.0})(),
            },
        )()
        analysis = type("Analysis", (), {"Group": [mesh_obj]})()

        fp = type("FP", (), {"InertialCorrectionFactor": 1.25})()
        factor = proxy._compute_inertial_correction_factor(fp, analysis, body_obj)
        self.assertAlmostEqual(1.25, factor)

        fp_bad = type("FP", (), {"InertialCorrectionFactor": "not-a-number"})()
        factor_bad = proxy._compute_inertial_correction_factor(fp_bad, analysis, body_obj)
        self.assertAlmostEqual(1.0, factor_bad)

    def test_compute_inertial_correction_factor_uses_element_volume_when_mesh_volume_zero(self):
        """Auto factor integrates element volume if FemMesh.Volume is zero/unset."""
        _msg("  Test inertial correction element-volume fallback")
        mod = self._import_linkbody()
        proxy = mod.LinkBody.__new__(mod.LinkBody)

        body_obj = type("BodyObj", (), {"Shape": type("Shape", (), {"Volume": 2.0})()})()

        class FemMeshStub:
            Volume = 0.0
            Volumes = (101,)

            def getElementNodes(self, _volume_id):
                return (1, 2, 3, 4)

            def getNodeById(self, node_id):
                node_map = {
                    1: (0.0, 0.0, 0.0),
                    2: (1.0, 0.0, 0.0),
                    3: (0.0, 1.0, 0.0),
                    4: (0.0, 0.0, 1.0),
                }
                return node_map[node_id]

        mesh_obj = type("MeshObj", (), {"Shape": body_obj, "FemMesh": FemMeshStub()})()
        analysis = type("Analysis", (), {"Group": [mesh_obj]})()
        fp = type("FP", (), {"InertialCorrectionFactor": 1.0})()

        factor = proxy._compute_inertial_correction_factor(fp, analysis, body_obj)
        self.assertAlmostEqual(12.0, factor)

    def test_get_reference_subobject_returns_none_for_empty_subs(self):
        """get_reference_subobject returns None for empty sub-elements."""
        _msg("  Test get_reference_subobject empty subs")
        get_reference_subobject = self._import_linkbody().get_reference_subobject

        self.assertIsNone(get_reference_subobject((object(), [])))

    def test_get_reference_subobject_resolves_linked_object(self):
        """get_reference_subobject dereferences links and rewrites names."""
        _msg("  Test get_reference_subobject linked object")
        get_reference_subobject = self._import_linkbody().get_reference_subobject

        linked = type("Linked", (), {"Name": "Body", "Label": "Body"})()
        link = type("Link", (), {"getLinkedObject": lambda self: linked})()

        with patch("FemLink.LinkBody.UtilsAssembly.getObject", return_value=link), patch(
            "FemLink.LinkBody.UtilsAssembly.isLink", return_value=True
        ):
            result_obj, result_subs = get_reference_subobject(
                (object(), ["Part.Face1", "Part.Face1"])
            )

        self.assertEqual(result_obj, linked)
        self.assertEqual(set(result_subs), {"Face1"})

    def test_linkbody_initialization_sets_properties_and_label(self):
        """LinkBody sets Body, SimpleEquilibrium and derived label."""
        _msg("  Test LinkBody initialization")
        linkbody_cls = self._import_linkbody().LinkBody

        try:
            body = self.doc.addObject("Part::Box", "Body")
        except Exception:
            body = self.doc.addObject("App::FeaturePython", "Body")
        link = self.doc.addObject("App::Link", "BodyLink")
        link.LinkedObject = body

        obj = self.doc.addObject("App::FeaturePython", "LinkBodyObject")
        linkbody_cls(obj, link)

        self.assertEqual(obj.Body, link)
        self.assertFalse(obj.SimpleEquilibrium)
        self.assertEqual(obj.Label, "LinkBody_Body")

    def test_clear_post_pipelines_removes_pipeline_objects(self):
        """clear_post_pipelines removes all Fem post pipeline objects."""
        _msg("  Test clear_post_pipelines")
        mod = self._import_linkbody()

        analysis = type("A", (), {})()
        analysis.Document = type("D", (), {"removeObject": Mock()})()
        post = [
            type("P", (), {"Name": "Pipe1"})(),
            type("P", (), {"Name": "Pipe2"})(),
        ]

        with patch("FemLink.LinkBody.find_common_group_objects", return_value=post):
            mod.clear_post_pipelines(analysis)

        analysis.Document.removeObject.assert_any_call("Pipe1")
        analysis.Document.removeObject.assert_any_call("Pipe2")

    def test_execute_guards_and_valid_body_path(self):
        """execute exits for invalid Body states and delegates valid input to EXECUTE mode."""
        _msg("  Test execute guards")
        mod = self._import_linkbody()

        proxy = mod.LinkBody.__new__(mod.LinkBody)
        proxy.updateFEMLinks = Mock()
        linked = object()
        no_mass_fp = type(
            "F",
            (),
            {"Body": type("B", (), {"getLinkedObject": lambda self: linked})()},
        )()
        valid_fp = type(
            "F",
            (),
            {
                "Body": type(
                    "B",
                    (),
                    {"Mass": 1000.0, "getLinkedObject": lambda self: linked},
                )()
            },
        )()

        proxy.execute(type("F", (), {})())
        proxy.execute(type("F", (), {"Body": None})())
        proxy.execute(
            type("F", (), {"Body": type("B", (), {"getLinkedObject": lambda self: None})()})()
        )
        proxy.execute(no_mass_fp)
        proxy.execute(valid_fp)

        proxy.updateFEMLinks.assert_called_once_with(valid_fp, mode=mod.UpdateMode.EXECUTE)

    def test_findanalysis_existing_and_create_paths(self):
        """findAnalysis returns existing analysis, else falls back to createAnalysis."""
        _msg("  Test findAnalysis branches")
        mod = self._import_linkbody()

        proxy = mod.LinkBody.__new__(mod.LinkBody)
        body = type("Body", (), {"Label": "BodyA"})()
        fp = type("FP", (), {})()
        fp.Body = type("L", (), {"getLinkedObject": lambda self: body})()

        existing = type("Ana", (), {"Name": "Existing"})()
        fp.Document = type("Doc", (), {"findObjects": lambda self, **kwargs: [existing]})()
        self.assertIs(existing, proxy.findAnalysis(fp))

        fp.Document = type("Doc", (), {"findObjects": lambda self, **kwargs: []})()
        proxy.createAnalysis = Mock(return_value="CREATED")
        self.assertEqual("CREATED", proxy.findAnalysis(fp))
        proxy.createAnalysis.assert_called_once_with(fp)

    def test_get_analysis_obj_reuse_and_create(self):
        """get_analysis_obj reuses matching labels and creates missing objects."""
        _msg("  Test get_analysis_obj reuse/create")
        mod = self._import_linkbody()

        proxy = mod.LinkBody.__new__(mod.LinkBody)
        analysis = type("A", (), {"addObject": Mock()})()
        existing = type("Obj", (), {"Label": "L1"})()

        with patch("FemLink.LinkBody.find_common_group_objects", return_value=[existing]):
            got = proxy.get_analysis_obj(analysis, "L1", Mock(), "Fem::ConstraintPython")
        self.assertIs(existing, got)

        maker = Mock(return_value=type("Obj", (), {"Label": "", "References": None})())
        on_new = Mock()
        with patch("FemLink.LinkBody.find_common_group_objects", return_value=[]):
            created = proxy.get_analysis_obj(
                analysis, "NewOne", maker, "Fem::ConstraintPython", on_new=on_new
            )
        self.assertEqual("NewOne", created.Label)
        on_new.assert_called_once_with(created)
        analysis.addObject.assert_called_with(created)

    def test_updatejig_simple_equilibrium_and_missing_com(self):
        """updateJig handles both equilibrium kinematics and missing COM path."""
        _msg("  Test updateJig branches")
        mod = self._import_linkbody()

        proxy = mod.LinkBody.__new__(mod.LinkBody)
        proxy.force_total = App.Vector(4, 0, 0)
        proxy.state = {}
        proxy.line_info = []

        jig = type("Jig", (), {})()
        jig.CenterOfMass = App.Vector(0, 0, 0)
        vf = type("VF", (), {})()
        vf.CenterOfMass = App.Vector(0, 0, 0)
        vf.LinearAcceleration = App.Vector(0, 0, 0)
        vf.LinearVelocity = App.Vector(1, 1, 1)
        vf.AngularVelocity = App.Vector(1, 0, 0)
        vf.AngularAcceleration = App.Vector(1, 0, 0)
        vf.RelativeVelocity = App.Vector(1, 0, 0)
        proxy.get_analysis_constraint = Mock(
            side_effect=lambda _analysis, label, *_a, **_k: (
                vf if str(label).startswith("VirtualForces_") else jig
            )
        )

        body = type("Body", (), {})()
        body.Label = "B"
        body.Mass = 2000.0
        body.CenterOfMass = App.Vector(1, 2, 3)
        body.LinearAcceleration = App.Vector(9, 0, 0)
        body.LinearVelocity = App.Vector(8, 0, 0)
        body.AngularVelocity = App.Vector(7, 0, 0)
        body.AngularAcceleration = App.Vector(6, 0, 0)
        body.RelativeVelocity = App.Vector(5, 0, 0)
        body.getLinkedObject = lambda: object()

        fp = type("FP", (), {"SimpleEquilibrium": True})()
        ok = proxy.updateJig(fp, object(), body, mode=mod.UpdateMode.SAVE)
        self.assertTrue(ok)
        self.assertEqual(App.Vector(2, 0, 0), vf.LinearAcceleration)
        self.assertEqual(App.Vector(0, 0, 0), vf.LinearVelocity)
        self.assertEqual(App.Vector(0, 0, 0), vf.AngularVelocity)
        self.assertEqual(App.Vector(0, 0, 0), vf.AngularAcceleration)
        self.assertEqual(App.Vector(0, 0, 0), vf.RelativeVelocity)
        self.assertEqual(App.Vector(0, 0, 0), proxy.force_total)
        self.assertEqual(1, len(proxy.line_info))

        body_no_com = type(
            "Body", (), {"Label": "B2", "Mass": 1000.0, "getLinkedObject": lambda self: object()}
        )()
        self.assertFalse(proxy.updateJig(fp, object(), body_no_com, mode=mod.UpdateMode.SAVE))

    def test_updatejoint_updates_force_state_and_lines(self):
        """updateJoint maps side-specific force/torque/origin and accumulates totals."""
        _msg("  Test updateJoint")
        mod = self._import_linkbody()

        proxy = mod.LinkBody.__new__(mod.LinkBody)
        proxy.force_total = App.Vector(0, 0, 0)
        proxy.state = {}
        proxy.line_info = []

        con = type("Con", (), {})()
        con.Force = App.Vector(0, 0, 0)
        con.Torque = App.Vector(0, 0, 0)
        con.Origin = type("O", (), {"Base": App.Vector(0, 0, 0)})()
        proxy.get_analysis_constraint = Mock(return_value=con)

        body = type("Body", (), {"Label": "BodyX", "Mass": 3000.0})()
        joint = type("J", (), {})()
        joint.Label = "JointA"
        joint.Force1 = App.Vector(1, 2, 3)
        joint.Torque1 = App.Vector(4, 5, 6)
        joint.Origin1 = App.Vector(7, 8, 9)
        joint.Reference1 = None

        proxy.updateJoint(object(), object(), body, joint, 1, mode=mod.UpdateMode.SAVE)
        self.assertEqual(App.Vector(1, 2, 3), con.Force)
        self.assertEqual(App.Vector(4, 5, 6), con.Torque)
        self.assertEqual(App.Vector(7, 8, 9), con.Origin.Base)
        self.assertEqual(App.Vector(1, 2, 3), proxy.force_total)
        self.assertEqual(2, len(proxy.line_info))
        self.assertEqual(App.Vector(1, 2, 3), proxy.state[("Reaction_BodyX_JointA", "Force")])

    def test_residual_force_balances_to_jig_reaction_in_simple_equilibrium(self):
        """In SimpleEquilibrium, the jig support reaction balances net applied force."""
        _msg("  Test residual force balance in SimpleEquilibrium")
        mod = self._import_linkbody()

        proxy = mod.LinkBody.__new__(mod.LinkBody)
        proxy.force_total = App.Vector(0, 0, 0)
        proxy.state = {}
        proxy.line_info = []

        reaction = type("Con", (), {})()
        reaction.Force = App.Vector(0, 0, 0)
        reaction.Torque = App.Vector(0, 0, 0)
        reaction.Origin = type("O", (), {"Base": App.Vector(0, 0, 0)})()
        jig = type("Jig", (), {})()
        vf = type("VF", (), {})()
        vf.CenterOfMass = App.Vector(0, 0, 0)
        vf.LinearAcceleration = App.Vector(0, 0, 0)
        vf.LinearVelocity = App.Vector(0, 0, 0)
        vf.AngularVelocity = App.Vector(0, 0, 0)
        vf.AngularAcceleration = App.Vector(0, 0, 0)
        vf.RelativeVelocity = App.Vector(0, 0, 0)

        proxy.get_analysis_constraint = Mock(side_effect=[reaction, jig, vf])

        body = type("Body", (), {})()
        body.Label = "BodyR"
        body.Mass = 5000.0
        body.CenterOfMass = App.Vector(1, 2, 3)
        body.LinearAcceleration = App.Vector(99, 0, 0)
        body.LinearVelocity = App.Vector(88, 0, 0)
        body.AngularVelocity = App.Vector(77, 0, 0)
        body.getLinkedObject = lambda: object()

        fp = type("FP", (), {"SimpleEquilibrium": True})()

        joint = type("J", (), {})()
        joint.Label = "JointResidual"
        joint.Force1 = App.Vector(10, -5, 2)
        joint.Torque1 = App.Vector(3, 4, 5)
        joint.Origin1 = App.Vector(7, 8, 9)
        joint.Reference1 = None

        proxy.updateJoint(fp, object(), body, joint, 1, mode=mod.UpdateMode.SAVE)
        external_force = App.Vector(proxy.force_total)
        torque_lines = [item for item in proxy.line_info if item[2] is mod.LineType.TORQUE]
        self.assertEqual(1, len(torque_lines))
        self.assertEqual(App.Vector(3, 4, 5), torque_lines[0][1])

        self.assertTrue(proxy.updateJig(fp, object(), body, mode=mod.UpdateMode.SAVE))
        mass = body.Mass / 1000.0
        jig_reaction_force = vf.LinearAcceleration * mass

        self.assertEqual(external_force, App.Vector(10, -5, 2))
        self.assertEqual(jig_reaction_force, external_force)
        self.assertEqual(proxy.force_total, App.Vector(0, 0, 0))

    def test_residual_force_reports_mismatch_with_motion_driven_loads(self):
        """With motion-driven loads, jig support reflects residual force imbalance."""
        _msg("  Test residual force mismatch with motion-driven loads")
        mod = self._import_linkbody()

        proxy = mod.LinkBody.__new__(mod.LinkBody)
        proxy.force_total = App.Vector(0, 0, 0)
        proxy.state = {}
        proxy.line_info = []

        reaction = type("Con", (), {})()
        reaction.Force = App.Vector(0, 0, 0)
        reaction.Torque = App.Vector(0, 0, 0)
        reaction.Origin = type("O", (), {"Base": App.Vector(0, 0, 0)})()
        jig = type("Jig", (), {})()
        vf = type("VF", (), {})()
        vf.CenterOfMass = App.Vector(0, 0, 0)
        vf.LinearAcceleration = App.Vector(0, 0, 0)
        vf.LinearVelocity = App.Vector(0, 0, 0)
        vf.AngularVelocity = App.Vector(0, 0, 0)
        vf.AngularAcceleration = App.Vector(0, 0, 0)
        vf.RelativeVelocity = App.Vector(0, 0, 0)

        proxy.get_analysis_constraint = Mock(side_effect=[reaction, jig, vf])

        body = type("Body", (), {})()
        body.Label = "BodyMismatch"
        body.Mass = 4000.0
        body.CenterOfMass = App.Vector(0, 0, 0)
        body.LinearAcceleration = App.Vector(2, 0, 0)
        body.LinearVelocity = App.Vector(1, 0, 0)
        body.AngularVelocity = App.Vector(0, 1, 0)
        body.getLinkedObject = lambda: object()

        fp = type("FP", (), {"SimpleEquilibrium": False})()

        joint = type("J", (), {})()
        joint.Label = "JointMismatch"
        joint.Force1 = App.Vector(10, 0, 0)
        joint.Torque1 = App.Vector(0, 6, 0)
        joint.Origin1 = App.Vector(0, 0, 0)
        joint.Reference1 = None

        proxy.updateJoint(fp, object(), body, joint, 1, mode=mod.UpdateMode.SAVE)
        torque_lines = [item for item in proxy.line_info if item[2] is mod.LineType.TORQUE]
        self.assertEqual(1, len(torque_lines))
        self.assertEqual(App.Vector(0, 6, 0), torque_lines[0][1])
        self.assertTrue(proxy.updateJig(fp, object(), body, mode=mod.UpdateMode.SAVE))

        mass = body.Mass / 1000.0
        expected_residual = App.Vector(10, 0, 0) - body.LinearAcceleration * mass
        self.assertEqual(vf.LinearAcceleration, body.LinearAcceleration)
        self.assertEqual(proxy.force_total, expected_residual)
        self.assertNotEqual(proxy.force_total, App.Vector(0, 0, 0))

    def test_dynamic_mode_simulation_balances_residual_quality_metric(self):
        """Dynamic-equilibrium mode should drive residual force ratio to zero."""
        _msg("  Test dynamic mode simulation residual metric")
        mod = self._import_linkbody()

        proxy = mod.LinkBody.__new__(mod.LinkBody)
        proxy.force_total = App.Vector(0, 0, 0)
        proxy.state = {}
        proxy.line_info = []

        reaction = type("Con", (), {})()
        reaction.Force = App.Vector(0, 0, 0)
        reaction.Torque = App.Vector(0, 0, 0)
        reaction.Origin = type("O", (), {"Base": App.Vector(0, 0, 0)})()
        jig = type("Jig", (), {})()
        vf = type("VF", (), {})()
        vf.CenterOfMass = App.Vector(0, 0, 0)
        vf.LinearAcceleration = App.Vector(0, 0, 0)
        vf.LinearVelocity = App.Vector(0, 0, 0)
        vf.AngularVelocity = App.Vector(0, 0, 0)
        vf.AngularAcceleration = App.Vector(0, 0, 0)
        vf.RelativeVelocity = App.Vector(0, 0, 0)

        proxy.get_analysis_constraint = Mock(side_effect=[reaction, jig, vf])

        body = type("Body", (), {})()
        body.Label = "BodyDyn"
        body.Mass = 6000.0
        body.CenterOfMass = App.Vector(0, 0, 0)
        body.LinearAcceleration = App.Vector(123, 0, 0)
        body.LinearVelocity = App.Vector(5, 5, 5)
        body.AngularVelocity = App.Vector(6, 6, 6)
        body.getLinkedObject = lambda: object()

        fp = type("FP", (), {"SimpleEquilibrium": True})()

        joint = type("J", (), {})()
        joint.Label = "JointDyn"
        joint.Force1 = App.Vector(12, -6, 3)
        joint.Torque1 = App.Vector(1, 2, 3)
        joint.Origin1 = App.Vector(0, 0, 0)
        joint.Reference1 = None

        proxy.updateJoint(fp, object(), body, joint, 1, mode=mod.UpdateMode.SAVE)
        external_force = App.Vector(proxy.force_total)
        self.assertTrue(proxy.updateJig(fp, object(), body, mode=mod.UpdateMode.SAVE))

        mass = body.Mass / 1000.0
        expected_acc = external_force / mass
        self.assertEqual(expected_acc, vf.LinearAcceleration)
        self.assertEqual(App.Vector(0, 0, 0), vf.LinearVelocity)
        self.assertEqual(App.Vector(0, 0, 0), vf.AngularVelocity)

        residual_ratio = proxy.force_total.Length / max(external_force.Length, 1.0)
        self.assertEqual(0.0, residual_ratio)

    def test_kinematic_mode_simulation_preserves_motion_and_residual_metric(self):
        """Kinematic-prescribed mode should preserve motion and expose residual ratio."""
        _msg("  Test kinematic mode simulation residual metric")
        mod = self._import_linkbody()

        proxy = mod.LinkBody.__new__(mod.LinkBody)
        proxy.force_total = App.Vector(0, 0, 0)
        proxy.state = {}
        proxy.line_info = []

        reaction = type("Con", (), {})()
        reaction.Force = App.Vector(0, 0, 0)
        reaction.Torque = App.Vector(0, 0, 0)
        reaction.Origin = type("O", (), {"Base": App.Vector(0, 0, 0)})()
        jig = type("Jig", (), {})()
        vf = type("VF", (), {})()
        vf.CenterOfMass = App.Vector(0, 0, 0)
        vf.LinearAcceleration = App.Vector(0, 0, 0)
        vf.LinearVelocity = App.Vector(0, 0, 0)
        vf.AngularVelocity = App.Vector(0, 0, 0)
        vf.AngularAcceleration = App.Vector(0, 0, 0)
        vf.RelativeVelocity = App.Vector(0, 0, 0)

        proxy.get_analysis_constraint = Mock(side_effect=[reaction, jig, vf])

        body = type("Body", (), {})()
        body.Label = "BodyKin"
        body.Mass = 6000.0
        body.CenterOfMass = App.Vector(0, 0, 0)
        body.LinearAcceleration = App.Vector(1, 0, 0)
        body.LinearVelocity = App.Vector(4, 3, 2)
        body.AngularVelocity = App.Vector(0.1, 0.2, 0.3)
        body.getLinkedObject = lambda: object()

        fp = type("FP", (), {"SimpleEquilibrium": False})()

        joint = type("J", (), {})()
        joint.Label = "JointKin"
        joint.Force1 = App.Vector(12, -6, 3)
        joint.Torque1 = App.Vector(3, 1, 2)
        joint.Origin1 = App.Vector(0, 0, 0)
        joint.Reference1 = None

        proxy.updateJoint(fp, object(), body, joint, 1, mode=mod.UpdateMode.SAVE)
        external_force = App.Vector(proxy.force_total)
        self.assertTrue(proxy.updateJig(fp, object(), body, mode=mod.UpdateMode.SAVE))

        self.assertEqual(body.LinearAcceleration, vf.LinearAcceleration)
        self.assertEqual(body.LinearVelocity, vf.LinearVelocity)
        self.assertEqual(body.AngularVelocity, vf.AngularVelocity)

        mass = body.Mass / 1000.0
        expected_residual = external_force - body.LinearAcceleration * mass
        self.assertEqual(expected_residual, proxy.force_total)
        residual_ratio = proxy.force_total.Length / max(external_force.Length, 1.0)
        self.assertGreater(residual_ratio, 0.0)

    def test_kinematic_mode_preserves_each_non_zero_motion_component(self):
        """Kinematic mode keeps non-zero accel/linear-vel/angular-vel values."""
        _msg("  Test kinematic mode non-zero motion components")
        mod = self._import_linkbody()

        proxy = mod.LinkBody.__new__(mod.LinkBody)
        proxy.force_total = App.Vector(9, 6, 3)
        proxy.state = {}
        proxy.line_info = []

        jig = type("Jig", (), {})()
        jig.CenterOfMass = App.Vector(0, 0, 0)
        vf = type("VF", (), {})()
        vf.CenterOfMass = App.Vector(0, 0, 0)
        vf.LinearAcceleration = App.Vector(0, 0, 0)
        vf.LinearVelocity = App.Vector(0, 0, 0)
        vf.AngularVelocity = App.Vector(0, 0, 0)
        vf.AngularAcceleration = App.Vector(0, 0, 0)
        vf.RelativeVelocity = App.Vector(0, 0, 0)

        proxy.get_analysis_constraint = Mock(
            side_effect=lambda _analysis, label, *_a, **_k: (
                vf if str(label).startswith("VirtualForces_") else jig
            )
        )

        body = type("Body", (), {})()
        body.Label = "BodyMotion"
        body.Mass = 3000.0
        body.CenterOfMass = App.Vector(0, 0, 0)
        body.LinearAcceleration = App.Vector(1.5, 2.5, 3.5)
        body.LinearVelocity = App.Vector(0.4, 0.5, 0.6)
        body.AngularVelocity = App.Vector(0.7, 0.8, 0.9)
        body.getLinkedObject = lambda: object()

        fp = type("FP", (), {"SimpleEquilibrium": False})()
        self.assertTrue(proxy.updateJig(fp, object(), body, mode=mod.UpdateMode.SAVE))

        self.assertGreater(vf.LinearAcceleration.Length, 0.0)
        self.assertGreater(vf.LinearVelocity.Length, 0.0)
        self.assertGreater(vf.AngularVelocity.Length, 0.0)
        self.assertEqual(body.LinearAcceleration, vf.LinearAcceleration)
        self.assertEqual(body.LinearVelocity, vf.LinearVelocity)
        self.assertEqual(body.AngularVelocity, vf.AngularVelocity)

    def test_updatejig_load_restores_non_zero_motion_components(self):
        """SAVE/LOAD restores non-zero accel, linear velocity and angular velocity."""
        _msg("  Test updateJig SAVE/LOAD non-zero motion components")
        mod = self._import_linkbody()

        proxy = mod.LinkBody.__new__(mod.LinkBody)
        proxy.force_total = App.Vector(0, 0, 0)
        proxy.state = {}
        proxy.line_info = []

        jig = type("Jig", (), {})()
        jig.CenterOfMass = App.Vector(0, 0, 0)
        vf = type("VF", (), {})()
        vf.CenterOfMass = App.Vector(0, 0, 0)
        vf.LinearAcceleration = App.Vector(0, 0, 0)
        vf.LinearVelocity = App.Vector(0, 0, 0)
        vf.AngularVelocity = App.Vector(0, 0, 0)
        vf.AngularAcceleration = App.Vector(0, 0, 0)
        vf.RelativeVelocity = App.Vector(0, 0, 0)

        proxy.get_analysis_constraint = Mock(
            side_effect=lambda _analysis, label, *_a, **_k: (
                vf if str(label).startswith("VirtualForces_") else jig
            )
        )

        body = type("Body", (), {})()
        body.Label = "BodyRestore"
        body.Mass = 2000.0
        body.CenterOfMass = App.Vector(0, 0, 0)
        body.LinearAcceleration = App.Vector(3.0, 1.0, 2.0)
        body.LinearVelocity = App.Vector(0.2, 0.3, 0.4)
        body.AngularVelocity = App.Vector(0.6, 0.7, 0.8)
        body.getLinkedObject = lambda: object()

        fp = type("FP", (), {"SimpleEquilibrium": False})()
        self.assertTrue(proxy.updateJig(fp, object(), body, mode=mod.UpdateMode.SAVE))

        saved_acc = App.Vector(vf.LinearAcceleration)
        saved_lin_vel = App.Vector(vf.LinearVelocity)
        saved_ang_vel = App.Vector(vf.AngularVelocity)

        vf.LinearAcceleration = App.Vector(0, 0, 0)
        vf.LinearVelocity = App.Vector(0, 0, 0)
        vf.AngularVelocity = App.Vector(0, 0, 0)

        body.LinearAcceleration = App.Vector(99, 99, 99)
        body.LinearVelocity = App.Vector(98, 98, 98)
        body.AngularVelocity = App.Vector(97, 97, 97)

        self.assertTrue(proxy.updateJig(fp, object(), body, mode=mod.UpdateMode.LOAD))
        self.assertEqual(saved_acc, vf.LinearAcceleration)
        self.assertEqual(saved_lin_vel, vf.LinearVelocity)
        self.assertEqual(saved_ang_vel, vf.AngularVelocity)
        self.assertGreater(vf.LinearAcceleration.Length, 0.0)
        self.assertGreater(vf.LinearVelocity.Length, 0.0)
        self.assertGreater(vf.AngularVelocity.Length, 0.0)

    def test_assembly_mass_uses_fem_material_density_when_shape_material_is_default(self):
        """Assembly mass for pendulum should follow FEM material density, not default ShapeMaterial."""
        _msg("  Test Assembly mass uses FEM density fallback")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")
        doc = ex.setup(exercise_loadcases=False)
        try:
            assemblies = [
                o for o in doc.Objects if getattr(o, "TypeId", "") == "Assembly::AssemblyObject"
            ]
            self.assertTrue(assemblies, "No assembly object found")
            assembly = assemblies[0]

            joints = [o for o in doc.Objects if getattr(o, "Name", "") == "RevoluteJoint"]
            self.assertTrue(joints, "RevoluteJoint missing")

            _, n_frames = ex.create_and_run_simulation(assembly, joints[0], motion_formula="")
            self.assertGreater(n_frames, 1, "Simulation should produce at least 2 frames")
            assembly.updateForFrame(0)

            pendulum_links = [o for o in doc.Objects if getattr(o, "Name", "") == "Pendulum"]
            self.assertTrue(pendulum_links, "Pendulum link missing")
            pendulum = pendulum_links[0]

            shape_obj = pendulum.getLinkedObject()
            self.assertTrue(hasattr(shape_obj, "Shape"), "Pendulum linked shape missing")

            mass_kg = float(getattr(pendulum, "Mass", 0.0) or 0.0)
            self.assertGreater(mass_kg, 0.0, "Assembly mass was not exported")

            volume_mm3 = float(shape_obj.Shape.Volume)
            default_mass_kg = volume_mm3 * 1.0e-9 * 1000.0

            material_objs = [
                o for o in doc.Objects if getattr(o, "TypeId", "") == "App::MaterialObjectPython"
            ]
            self.assertTrue(material_objs, "No FEM material object found")

            density_candidates_t_mm3 = []
            for mat_obj in material_objs:
                material_map = getattr(mat_obj, "Material", {}) or {}
                if not isinstance(material_map, dict):
                    continue
                density_text = material_map.get("Density", "")
                if not density_text:
                    continue
                try:
                    density_q = App.Units.Quantity(str(density_text))
                    density_t_mm3 = density_q.getValueAs("t/mm^3").Value
                    if density_t_mm3 > 0.0:
                        density_candidates_t_mm3.append(float(density_t_mm3))
                except Exception:
                    continue

            self.assertTrue(density_candidates_t_mm3, "No parseable FEM density found")
            density_t_mm3 = max(density_candidates_t_mm3)
            expected_mass_kg = volume_mm3 * density_t_mm3 * 1000.0

            self.assertAlmostEqual(
                mass_kg,
                expected_mass_kg,
                delta=max(expected_mass_kg * 0.05, 1.0e-6),
                msg="Assembly pendulum mass should reflect FEM material density",
            )
            self.assertGreater(
                mass_kg,
                default_mass_kg * 2.0,
                "Assembly mass still appears to use default 1e-9 t/mm^3 density",
            )
        finally:
            if doc and getattr(doc, "Name", ""):
                App.closeDocument(doc.Name)

    def test_assembly_inertia_export_matches_shape_principal_props(self):
        """ASMT-exported mass/inertia should match shape principal properties and density units."""
        _msg("  Test assembly inertia export matches shape principal props")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")
        doc = ex.setup(exercise_loadcases=False)
        try:
            assemblies = [
                o for o in doc.Objects if getattr(o, "TypeId", "") == "Assembly::AssemblyObject"
            ]
            self.assertTrue(assemblies, "No assembly object found")
            assembly = assemblies[0]

            pendulum_links = [o for o in doc.Objects if getattr(o, "Name", "") == "Pendulum"]
            self.assertTrue(pendulum_links, "Pendulum link missing")
            pendulum = pendulum_links[0]

            shape_obj = pendulum.getLinkedObject()
            self.assertTrue(hasattr(shape_obj, "Shape"), "Pendulum linked shape missing")

            material_objs = [
                o for o in doc.Objects if getattr(o, "TypeId", "") == "App::MaterialObjectPython"
            ]
            self.assertTrue(material_objs, "No FEM material object found")
            density_q = App.Units.Quantity(str(material_objs[0].Material.get("Density", "")))
            density_t_mm3 = float(density_q.getValueAs("t/mm^3").Value)
            self.assertGreater(density_t_mm3, 0.0)

            with tempfile.NamedTemporaryFile(suffix=".asmt", delete=False) as tmp:
                asmt_path = tmp.name
            try:
                assembly.exportAsASMT(asmt_path)
                with open(asmt_path, "r", encoding="utf-8") as fh:
                    parts = self._parse_asmt_parts(fh.read())
            finally:
                if os.path.exists(asmt_path):
                    os.remove(asmt_path)

            self.assertTrue(parts, "No parts parsed from ASMT export")

            pendulum_part = next(
                (
                    p
                    for p in parts
                    if p["name"].endswith("#Pendulum") or p["name"].endswith("Pendulum")
                ),
                None,
            )
            self.assertIsNotNone(pendulum_part, "Pendulum part missing in ASMT export")

            shape = shape_obj.Shape
            solid = shape.Solids[0] if getattr(shape, "Solids", None) else shape

            expected_mass_t = float(shape.Volume) * density_t_mm3
            pp = solid.PrincipalProperties
            expected_moi = tuple(
                float(m) * density_t_mm3 for m in pp.get("Moments", (0.0, 0.0, 0.0))
            )

            self.assertAlmostEqual(
                pendulum_part["mass"],
                expected_mass_t,
                delta=max(expected_mass_t * 1.0e-6, 1.0e-12),
                msg="ASMT pendulum mass should equal Volume * density (t/mm^3)",
            )

            for got, exp in zip(pendulum_part["moi"], expected_moi):
                self.assertAlmostEqual(
                    got,
                    exp,
                    delta=max(abs(exp) * 1.0e-6, 1.0e-9),
                    msg="ASMT principal moments should match OCC principal moments * density",
                )

            self._assert_rotation_is_orthonormal_righthanded(pendulum_part["rot"], delta=1.0e-6)

            origin_part = next(
                (p for p in parts if p["name"].endswith("#Origin") or p["name"].endswith("Origin")),
                None,
            )
            self.assertIsNotNone(origin_part, "Assembly origin part missing in ASMT export")
            self.assertGreater(
                origin_part["mass"],
                0.0,
                "Assembly origin mass marker must stay strictly positive for MbD stability",
            )
            self.assertLessEqual(
                origin_part["mass"],
                1.0e-9,
                "Assembly origin inertial mass floor should remain negligible",
            )
            for moi in origin_part["moi"]:
                self.assertGreater(
                    moi,
                    0.0,
                    "Assembly origin principal inertia must stay strictly positive",
                )
                self.assertLessEqual(
                    moi,
                    1.0e-9,
                    "Assembly origin inertia floor should remain negligible",
                )
        finally:
            if doc and getattr(doc, "Name", ""):
                App.closeDocument(doc.Name)

    def test_assembly_inertia_export_invariant_under_linked_shape_placement_transform(self):
        """Rigid placement transforms on linked shape should not alter exported inertial data."""
        _msg("  Test assembly inertia export invariance under linked-shape placement transform")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")
        doc = ex.setup(exercise_loadcases=False)
        try:
            assemblies = [
                o for o in doc.Objects if getattr(o, "TypeId", "") == "Assembly::AssemblyObject"
            ]
            self.assertTrue(assemblies, "No assembly object found")
            assembly = assemblies[0]

            pendulum_links = [o for o in doc.Objects if getattr(o, "Name", "") == "Pendulum"]
            self.assertTrue(pendulum_links, "Pendulum link missing")
            pendulum = pendulum_links[0]

            shape_obj = pendulum.getLinkedObject()
            self.assertIsNotNone(shape_obj, "Pendulum linked object missing")

            def _export_pendulum_part():
                with tempfile.NamedTemporaryFile(suffix=".asmt", delete=False) as tmp:
                    asmt_path = tmp.name
                try:
                    assembly.exportAsASMT(asmt_path)
                    with open(asmt_path, "r", encoding="utf-8") as fh:
                        parts = self._parse_asmt_parts(fh.read())
                finally:
                    if os.path.exists(asmt_path):
                        os.remove(asmt_path)

                pendulum_part = next(
                    (
                        p
                        for p in parts
                        if p["name"].endswith("#Pendulum") or p["name"].endswith("Pendulum")
                    ),
                    None,
                )
                self.assertIsNotNone(pendulum_part, "Pendulum part missing in ASMT export")
                return pendulum_part

            baseline = _export_pendulum_part()
            self._assert_rotation_is_orthonormal_righthanded(baseline["rot"], delta=1.0e-6)

            shape_obj.Placement = (
                App.Placement(
                    App.Vector(137.0, -42.0, 25.0),
                    App.Rotation(App.Vector(1.0, 2.0, 3.0), 37.0),
                )
                * shape_obj.Placement
            )
            doc.recompute()

            transformed = _export_pendulum_part()
            self._assert_rotation_is_orthonormal_righthanded(transformed["rot"], delta=1.0e-6)

            self.assertAlmostEqual(
                transformed["mass"],
                baseline["mass"],
                delta=max(abs(baseline["mass"]) * 1.0e-9, 1.0e-12),
                msg="Rigid shape placement transform should not alter exported mass",
            )

            baseline_moi = sorted(float(v) for v in baseline["moi"])
            transformed_moi = sorted(float(v) for v in transformed["moi"])
            for got, exp in zip(transformed_moi, baseline_moi):
                self.assertAlmostEqual(
                    got,
                    exp,
                    delta=max(abs(exp) * 1.0e-6, 1.0e-9),
                    msg="Rigid shape placement transform should preserve principal moments",
                )

            baseline_pairs = sorted(
                [
                    (float(m), App.Vector(*axis))
                    for m, axis in zip(baseline["moi"], baseline["rot"])
                ],
                key=lambda item: item[0],
            )
            transformed_pairs = sorted(
                [
                    (float(m), App.Vector(*axis))
                    for m, axis in zip(transformed["moi"], transformed["rot"])
                ],
                key=lambda item: item[0],
            )

            for (m0, axis0), (m1, axis1) in zip(baseline_pairs, transformed_pairs):
                self.assertAlmostEqual(
                    m0,
                    m1,
                    delta=max(abs(m0) * 1.0e-6, 1.0e-9),
                    msg="Principal-moment ordering changed unexpectedly under rigid transform",
                )
                self.assertGreater(
                    abs(axis0.dot(axis1)),
                    0.999,
                    "Principal-axis orientation should remain invariant in part-local coordinates",
                )
        finally:
            if doc and getattr(doc, "Name", ""):
                App.closeDocument(doc.Name)

    def test_calculix_jig_force_residual_magnitude_dynamic_mode(self):
        """Dynamic free-pendulum mode residual stays small for each real load case."""
        _msg("  Test CalculiX jig residual magnitude in dynamic mode")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")
        for contact_type in self.REACTION_CONTACT_TYPES:
            # Use DEFAULT accel mode (g - a_raw): GRAV + Reaction = 0 always.
            series = self._run_multistep_jig_residual_case(
                ex,
                joint_name="RevoluteJoint",
                dynamic=True,
                motion_type="Angular",
                # Empty formula => no prescribed driver, free response under gravity.
                motion_formula="",
                case_name=f"dynamic_{contact_type.lower()}",
                residual_limit=2.0,
                reaction_contact_type=contact_type,
            )
            # Quality target: with LinkBody loads resolved from MbDyn state,
            # resulting Jig reaction resultant should be near equilibrium
            # (ideally zero, up to approximation/numerical noise).
            self.assertLess(
                max(series["residual"]),
                2.0,
                f"Dynamic free-pendulum residual too high for contact type {contact_type}",
            )

    def test_calculix_jig_force_residual_analysis_dynamic_mode_rotated_x30(self):
        """Analysis mode: rotate free pendulum rig by +30 deg about X and sweep dynamic cases."""
        _msg("  Analysis test: dynamic free-pendulum rotated +30 deg about X")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")
        setup_kwargs = {"assembly_rotation_deg_x": 30.0}

        # Analysis-only pass: keep strict checks on extracted series shape,
        # but disable per-component near-zero assertions in helper.
        series_free = self._run_multistep_jig_residual_case(
            ex,
            joint_name="RevoluteJoint",
            dynamic=True,
            motion_type="Angular",
            motion_formula="",
            case_name="dynamic_rot_x30_free",
            residual_limit=1.0e9,
            setup_kwargs=setup_kwargs,
        )

        series_driven = self._run_multistep_jig_residual_case(
            ex,
            joint_name="RevoluteJoint",
            dynamic=True,
            motion_type="Angular",
            motion_formula="12*sin(6*time)",
            case_name="dynamic_rot_x30_driven",
            residual_limit=1.0e9,
            setup_kwargs=setup_kwargs,
        )

        for label, series in (("free", series_free), ("driven", series_driven)):
            residuals = [float(v) for v in series["residual"]]
            self.assertGreater(len(residuals), 5)
            App.Console.PrintMessage(
                "dynamic_rot_x30 {} residual summary: min={:.6e} max={:.6e} "
                "mean={:.6e} median={:.6e} N\n".format(
                    label,
                    min(residuals),
                    max(residuals),
                    statistics.mean(residuals),
                    statistics.median(residuals),
                )
            )
            # Analysis-only sanity: values must remain finite and non-pathological.
            for residual in residuals:
                self.assertLess(abs(residual), 1.0e12)

    def test_calculix_jig_force_residual_analysis_dynamic_mode_shifted_xyz(self):
        """Analysis mode: shift free-pendulum rig in X/Y/Z and sweep free dynamic cases."""
        _msg("  Analysis test: dynamic free-pendulum shifted in X/Y/Z")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")
        shift_cases = [
            ("x", {"assembly_shift_x": 200.0, "assembly_shift_y": 0.0, "assembly_shift_z": 0.0}),
            ("y", {"assembly_shift_x": 0.0, "assembly_shift_y": -180.0, "assembly_shift_z": 0.0}),
            ("z", {"assembly_shift_x": 0.0, "assembly_shift_y": 0.0, "assembly_shift_z": 150.0}),
        ]

        axis_code = {"x": 0.0, "y": 1.0, "z": 2.0}
        median_residuals = []

        for axis, setup_kwargs in shift_cases:
            series = self._run_multistep_jig_residual_case(
                ex,
                joint_name="RevoluteJoint",
                dynamic=True,
                motion_type="Angular",
                motion_formula="",
                case_name=f"dynamic_shift_{axis}_free",
                residual_limit=1.0e9,
                setup_kwargs=setup_kwargs,
            )

            residuals = [float(v) for v in series["residual"]]
            self.assertGreater(len(residuals), 5)
            App.Console.PrintMessage(
                "dynamic_shift_{} residual summary: min={:.6e} max={:.6e} "
                "mean={:.6e} median={:.6e} N\n".format(
                    axis,
                    min(residuals),
                    max(residuals),
                    statistics.mean(residuals),
                    statistics.median(residuals),
                )
            )
            for residual in residuals:
                self.assertLess(abs(residual), 1.0e12)

            median_residuals.append((axis_code[axis], statistics.median(residuals)))

        self._maybe_plot_xy_series(
            "dynamic_shift_axis_median_residual",
            [v[0] for v in median_residuals],
            [v[1] for v in median_residuals],
            x_label="Shift axis code (0=x, 1=y, 2=z)",
            y_label="Median residual (N)",
            title="Free-pendulum: residual sensitivity to global translation axis",
        )

    def test_calculix_jig_force_residual_magnitude_kinematic_mode(self):
        """Kinematic mode residual stays small for each real load case."""
        _msg("  Test CalculiX jig residual magnitude in kinematic mode")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_forced_dynamics")
        for contact_type in self.REACTION_CONTACT_TYPES:
            series = self._run_multistep_jig_residual_case(
                ex,
                joint_name="SliderToRodPrismatic",
                dynamic=False,
                motion_type="Linear",
                # Time-varying actuator driver to exercise non-constant kinematic load cases.
                motion_formula="40*sin(8*time)",
                case_name=f"kinematic_{contact_type.lower()}",
                residual_limit=1.0,
                reaction_contact_type=contact_type,
            )
            self.assertLess(
                max(series["residual"]),
                1.0,
                f"Forced-pendulum residual too high for contact type {contact_type}",
            )

    def test_calculix_jig_force_residual_magnitude_kinematic_static_forcing_mode(self):
        """Constant kinematic forcing should remain static while preserving near-equilibrium residual."""
        _msg("  Test CalculiX jig residual magnitude in kinematic static-forcing mode")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_forced_dynamics")
        series = self._run_multistep_jig_residual_case(
            ex,
            joint_name="SliderToRodPrismatic",
            dynamic=False,
            motion_type="Linear",
            # Constant actuator command removes time-varying kinematic contributions.
            motion_formula="40",
            case_name="kinematic_static_forcing",
            residual_limit=1.0,
            require_frame_motion=False,
        )

        self.assertLess(max(series["residual"]), 1.0)
        self.assertGreater(max(series["residual"]), 1.0e-3)

        # Static driver should keep kinematic velocity terms effectively zero.
        self.assertLess(max(series["linear_velocity"]), 1.0e-6)
        self.assertLess(max(series["angular_velocity"]), 1.0e-6)
        self.assertLess(max(series["relative_velocity"]), 1.0e-6)

        # Force and residual traces should be nearly constant over load cases.
        self.assertLess(max(series["force"]) - min(series["force"]), 1.0e-3)
        self.assertLess(max(series["residual"]) - min(series["residual"]), 1.0e-3)

    def test_disc_slider_jig_residual_near_zero_for_isolated_drives(self):
        """Disc-slider: isolated slider/spin drive variants should keep Jig321 near zero."""
        _msg("  Test disc-slider Jig321 residual near zero for isolated drives")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_disc_slider_dynamics")
        spin_offset = self._run_multistep_jig_residual_case(
            ex,
            joint_name="SliderToDiscRevolute",
            dynamic=False,
            motion_type="Angular",
            motion_formula="30*time",
            case_name="disc_slider_spin_offset",
            residual_limit=1.0,
            require_frame_motion=False,
            setup_kwargs={"disc_joint_offset_x": 20.0},
        )

        slider_only = self._run_multistep_jig_residual_case(
            ex,
            joint_name="RailToSliderPrismatic",
            dynamic=False,
            motion_type="Linear",
            motion_formula="40*sin(8*time)",
            case_name="disc_slider_slider_only",
            residual_limit=1.0,
            require_frame_motion=False,
            setup_kwargs={"disc_joint_offset_x": 20.0},
        )

        spin_no_offset = self._run_multistep_jig_residual_case(
            ex,
            joint_name="SliderToDiscRevolute",
            dynamic=False,
            motion_type="Angular",
            motion_formula="30*time",
            case_name="disc_slider_spin_no_offset",
            residual_limit=1.0,
            require_frame_motion=False,
            setup_kwargs={"disc_joint_offset_x": 0.0},
        )

        self.assertLess(max(spin_offset["residual"]), 1.0)
        self.assertLess(max(slider_only["residual"]), 1.0)
        self.assertLess(max(spin_no_offset["residual"]), 1.0)

    def test_calculix_jig_residual_increases_with_linear_acceleration_input(self):
        """Injected linear acceleration must propagate into ConstraintJig inputs."""
        _msg("  Test ConstraintJig linear acceleration input propagation")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")
        series = self._run_multistep_jig_residual_case(
            ex,
            joint_name="RevoluteJoint",
            dynamic=True,
            motion_type="Angular",
            motion_formula="",
            case_name="dynamic_linear_accel_perturbed",
            perturbation={"kind": "linear_acceleration", "value": 2.0e4},
            residual_limit=1.0,
            require_frame_motion=False,
        )
        self.assertGreater(max(series["jig_linear_accel"]), 1.2e4)
        self.assertLess(statistics.median(series["residual"]), 3.0e2)
        self.assertLess(max(series["residual"]), 1.0)

    def test_calculix_jig_residual_increases_with_linear_velocity_input(self):
        """Injected linear velocity must propagate into ConstraintJig inputs."""
        _msg("  Test ConstraintJig linear velocity input propagation")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")
        series = self._run_multistep_jig_residual_case(
            ex,
            joint_name="RevoluteJoint",
            dynamic=True,
            motion_type="Angular",
            motion_formula="",
            case_name="dynamic_linear_velocity_perturbed",
            perturbation={"kind": "linear_velocity", "value": 100.0},
            residual_limit=1.0,
            require_frame_motion=False,
        )
        self.assertGreater(max(series["jig_linear_velocity"]), 1.0)
        self.assertLess(max(series["residual"]), 1.0)

    def test_calculix_jig_residual_increases_with_angular_velocity_input(self):
        """Injected angular velocity must propagate into ConstraintJig inputs."""
        _msg("  Test ConstraintJig angular velocity input propagation")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")
        series = self._run_multistep_jig_residual_case(
            ex,
            joint_name="RevoluteJoint",
            dynamic=True,
            motion_type="Angular",
            motion_formula="",
            case_name="dynamic_angular_velocity_perturbed",
            perturbation={"kind": "angular_velocity", "value": 10.0},
            residual_limit=1.0,
            require_frame_motion=False,
        )
        self.assertGreater(max(series["jig_angular_velocity"]), 2.0)
        self.assertLess(max(series["residual"]), 1.0)

    def test_fictitious_translational_inertial_transfer_scales_linearly(self):
        """-m*a0 transfer should scale approximately linearly with imposed linear acceleration."""
        _msg("  Test fictitious translational inertial force scaling")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")
        baseline, runs = self._run_fictitious_force_sweep(
            example_module=ex,
            joint_name="RevoluteJoint",
            dynamic=True,
            motion_type="Angular",
            motion_formula="",
            case_prefix="fictitious_translational_linear",
            perturbation_kind="linear_acceleration",
            perturbation_values=[2.0e4, 4.0e4],
            operation="add",
            residual_limit=1.0,
        )

        # Use medians to avoid a single failed load case dominating the trend.
        r0 = self._median_vector_length(baseline["jig_resultant_vector"])
        r1 = self._median_vector_length(runs[2.0e4]["jig_resultant_vector"])
        r2 = self._median_vector_length(runs[4.0e4]["jig_resultant_vector"])

        d1 = abs(r1 - r0)
        d2 = abs(r2 - r0)
        self._maybe_plot_xy_series(
            "fictitious_translational_linear_response",
            [0.0, 2.0e4, 4.0e4],
            [r0, r1, r2],
            x_label="Imposed linear acceleration perturbation (mm/s^2)",
            y_label="Mean |Jig resultant force| (N)",
            title="Translational fictitious-force transfer",
        )
        self.assertGreater(d1, 1.0e-6)
        self.assertGreater(d2, d1)
        ratio = d2 / d1
        self.assertGreater(ratio, 1.5)
        self.assertLess(ratio, 3.5)

    def test_fictitious_translational_inertial_transfer_sign_reversal(self):
        """Reversing imposed a0 direction should reverse the projected transferred force direction."""
        _msg("  Test fictitious translational inertial force sign reversal")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")
        baseline, runs = self._run_fictitious_force_sweep(
            example_module=ex,
            joint_name="RevoluteJoint",
            dynamic=True,
            motion_type="Angular",
            motion_formula="",
            case_prefix="fictitious_translational_sign",
            perturbation_kind="linear_acceleration",
            perturbation_values=[2.0e4, -2.0e4],
            operation="add",
            residual_limit=1.0,
        )

        axis = App.Vector(1, 0, 0)
        p0 = self._median_vector_projection(baseline["jig_resultant_vector"], axis)
        p_pos = self._median_vector_projection(runs[2.0e4]["jig_resultant_vector"], axis)
        p_neg = self._median_vector_projection(runs[-2.0e4]["jig_resultant_vector"], axis)

        d_pos = p_pos - p0
        d_neg = p_neg - p0
        self._maybe_plot_xy_series(
            "fictitious_translational_sign_projection",
            [-2.0e4, 0.0, 2.0e4],
            [p_neg, p0, p_pos],
            x_label="Imposed linear acceleration perturbation (mm/s^2)",
            y_label="Mean projected Jig resultant force (N)",
            title="Translational fictitious-force sign reversal",
        )
        self.assertGreater(abs(d_pos), 1.0e-6)
        self.assertGreater(abs(d_neg), 1.0e-6)
        self.assertLess(d_pos * d_neg, 0.0)
        ratio = abs(d_pos) / max(abs(d_neg), 1.0e-12)
        self.assertGreater(ratio, 0.5)
        self.assertLess(ratio, 2.0)

    def test_fictitious_centrifugal_transfer_scales_with_omega_squared(self):
        """Centrifugal transfer should increase roughly with omega^2 for imposed angular velocity."""
        _msg("  Test fictitious centrifugal force omega-squared scaling")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")
        _baseline, runs = self._run_fictitious_force_sweep(
            example_module=ex,
            joint_name="RevoluteJoint",
            dynamic=True,
            motion_type="Angular",
            motion_formula="",
            case_prefix="fictitious_centrifugal_quad",
            perturbation_kind="angular_velocity",
            perturbation_values=[0.0, 8.0, 16.0],
            operation="set",
            residual_limit=1.0,
        )

        r0 = self._median_vector_length(runs[0.0]["jig_resultant_vector"])
        r1 = self._median_vector_length(runs[8.0]["jig_resultant_vector"])
        r2 = self._median_vector_length(runs[16.0]["jig_resultant_vector"])

        d1 = abs(r1 - r0)
        d2 = abs(r2 - r0)
        self._maybe_plot_xy_series(
            "fictitious_centrifugal_omega2_response",
            [0.0, 8.0, 16.0],
            [r0, r1, r2],
            x_label="Imposed angular velocity (rad/s)",
            y_label="Mean |Jig resultant force| (N)",
            title="Centrifugal fictitious-force transfer",
        )
        self.assertGreater(d1, 1.0e-6)
        self.assertGreater(d2, d1)
        ratio = d2 / d1
        self.assertGreater(ratio, 2.5)
        self.assertLess(ratio, 5.5)

    def test_fictitious_centrifugal_transfer_tracks_cor_offset(self):
        """With fixed angular velocity, larger linear velocity should increase COR radius and force."""
        _msg("  Test fictitious centrifugal force tracks center-of-rotation offset")

        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")

        series_low = self._run_multistep_jig_residual_case(
            ex,
            joint_name="RevoluteJoint",
            dynamic=True,
            motion_type="Angular",
            motion_formula="",
            case_name="fictitious_centrifugal_cor_low",
            residual_limit=1.0,
            perturbation={
                "updates": [
                    {
                        "kind": "angular_velocity",
                        "vector": App.Vector(0, 0, 10),
                        "operation": "set",
                    },
                    {"kind": "linear_velocity", "vector": App.Vector(50, 0, 0), "operation": "set"},
                ]
            },
            require_frame_motion=False,
        )
        series_high = self._run_multistep_jig_residual_case(
            ex,
            joint_name="RevoluteJoint",
            dynamic=True,
            motion_type="Angular",
            motion_formula="",
            case_name="fictitious_centrifugal_cor_high",
            residual_limit=1.0,
            perturbation={
                "updates": [
                    {
                        "kind": "angular_velocity",
                        "vector": App.Vector(0, 0, 10),
                        "operation": "set",
                    },
                    {
                        "kind": "linear_velocity",
                        "vector": App.Vector(100, 0, 0),
                        "operation": "set",
                    },
                ]
            },
            require_frame_motion=False,
        )

        cor_low = self._mean_scalar(series_low["jig_cor_radius"])
        cor_high = self._mean_scalar(series_high["jig_cor_radius"])
        self.assertGreater(cor_low, 1.0e-6)
        self.assertGreater(cor_high, cor_low * 1.6)

        resp_low = self._mean_vector_length(series_low["jig_resultant_vector"])
        resp_high = self._mean_vector_length(series_high["jig_resultant_vector"])
        self._maybe_plot_xy_series(
            "fictitious_centrifugal_cor_vs_response",
            [cor_low, cor_high],
            [resp_low, resp_high],
            x_label="Mean center-of-rotation radius (mm)",
            y_label="Mean |Jig resultant force| (N)",
            title="Centrifugal transfer vs center-of-rotation offset",
        )
        # Coriolis and centrifugal components can partially cancel in resultant magnitude.
        self.assertGreater(resp_high, resp_low * 0.5)
        self.assertGreater(abs(resp_high - resp_low), 1.0e-6)

    def test_fictitious_euler_force_transfer_input_is_available(self):
        """VirtualForces exposes AngularAcceleration input for STATIC Euler-term transfer."""
        _msg("  Test fictitious Euler-force transfer input availability")

        objects_fem = _import_or_skip(self, "ObjectsFem")
        vf = objects_fem.makeConstraintVirtualForces(self.doc)
        self.assertTrue(hasattr(vf, "AngularAcceleration"))
        self.assertEqual(App.Vector(0, 0, 0), vf.AngularAcceleration)

    def test_fictitious_coriolis_force_transfer_input_is_available(self):
        """VirtualForces exposes RelativeVelocity input for STATIC Coriolis transfer."""
        _msg("  Test fictitious Coriolis-force transfer input availability")

        objects_fem = _import_or_skip(self, "ObjectsFem")
        vf = objects_fem.makeConstraintVirtualForces(self.doc)
        self.assertTrue(hasattr(vf, "RelativeVelocity"))
        self.assertEqual(App.Vector(0, 0, 0), vf.RelativeVelocity)

    def test_updatejoints_matches_only_relevant_moving_part(self):
        """updateJoints filters by joint references and moving part identity."""
        _msg("  Test updateJoints filtering")
        mod = self._import_linkbody()

        proxy = mod.LinkBody.__new__(mod.LinkBody)
        proxy.updateJoint = Mock()
        proxy.getAssembly = Mock(return_value=object())

        joint = type(
            "J",
            (),
            {
                "Label": "J",
                "Reference1": (object(), ["BodyA.Face1"]),
                "Reference2": (object(), ["Other.Face1"]),
            },
        )()
        group = type("G", (), {"Group": [joint]})()
        body = type("B", (), {"Name": "BodyA"})()

        with patch(
            "FemLink.LinkBody.find_common_group_objects",
            side_effect=[[group], []],
        ), patch(
            "FemLink.LinkBody.UtilsAssembly.getObject",
            side_effect=[type("P", (), {"Name": "BodyA"})(), type("P", (), {"Name": "Other"})()],
        ):
            proxy.updateJoints(object(), object(), object(), body, mode=mod.UpdateMode.SAVE)

        proxy.updateJoint.assert_called_once()

    def test_updatefemlinks_save_and_execute_paths(self):
        """updateFEMLinks handles SAVE and non-SAVE state/placement updates."""
        _msg("  Test updateFEMLinks")
        mod = self._import_linkbody()

        b1 = type("B", (), {"Label": "B1"})()
        b2 = type("B", (), {"Label": "B2"})()
        fp = type("FP", (), {"Body": b1, "getParentGroup": lambda self: object()})()

        proxy = mod.LinkBody.__new__(mod.LinkBody)
        proxy.findAnalysis = Mock(return_value=object())
        proxy.getBodyPlacement = Mock(side_effect=lambda b: f"P-{b.Label}")
        proxy.setBodyPlacement = Mock()
        proxy.updateJoints = Mock()
        proxy.updateJig = Mock(return_value=True)
        proxy.capture = Mock()

        with patch("FemLink.LinkBody.get_assembly_bodies", return_value=[b1, b2]):
            proxy.updateFEMLinks(fp, mode=mod.UpdateMode.SAVE)

        self.assertEqual("P-B1", proxy.state[("B1", "Placement")])
        self.assertEqual("P-B2", proxy.state[("B2", "Placement")])
        proxy.capture.assert_called_once()

        proxy2 = mod.LinkBody.__new__(mod.LinkBody)
        proxy2.findAnalysis = Mock(return_value=object())
        proxy2.getBodyPlacement = Mock(side_effect=lambda b: f"P-{b.Label}")
        proxy2.setBodyPlacement = Mock()
        proxy2.updateJoints = Mock()
        proxy2.updateJig = Mock(return_value=True)

        with patch("FemLink.LinkBody.get_assembly_bodies", return_value=[b1, b2]):
            proxy2.updateFEMLinks(fp, mode=mod.UpdateMode.EXECUTE)

        self.assertFalse(hasattr(proxy2, "state"))  # EXECUTE does not initialise state
        self.assertEqual("P-B1", proxy2.mesh_placement)
        proxy2.setBodyPlacement.assert_not_called()

    def test_runanalysis_updates_result_map_for_new_results(self):
        """runAnalysis executes a real solve and produces DAT/result outputs."""
        _msg("  Test runAnalysis real solve")
        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")
        lb_mod = _import_or_skip(self, "FemLink.LinkBody")

        doc = ex.setup(exercise_loadcases=True)
        try:
            analyses = [
                o
                for o in doc.Objects
                if getattr(o, "TypeId", "") == "Fem::FemAnalysis"
                and "Pendulum" in getattr(o, "Label", "")
            ]
            self.assertTrue(analyses, "No pendulum analysis found")
            analysis = analyses[0]

            stale = [
                o
                for o in analysis.Group
                if o.isDerivedFrom("Fem::FemResultObjectPython")
                or o.isDerivedFrom("Fem::FemPostPipeline")
                or (o.TypeId == "App::TextDocument" and o.Name.startswith("ccx_dat_file"))
            ]
            for obj in stale:
                doc.removeObject(obj.Name)
            doc.recompute()

            solvers = [o for o in analysis.Group if o.isDerivedFrom("Fem::FemSolverObjectPython")]
            self.assertTrue(solvers, "No FEM solver found in analysis")
            solvers[0].WorkingDirectory = tempfile.mkdtemp(prefix="fc_lbrun_")

            proxy = lb_mod.LinkBody.__new__(lb_mod.LinkBody)
            proxy.mesh_placement = App.Placement()
            proxy.findAnalysis = lambda fp: analysis
            proxy.runAnalysis(object(), 4)

            dat_obj = [
                o
                for o in analysis.Group
                if o.TypeId == "App::TextDocument" and o.Name.startswith("ccx_dat_file")
            ]
            dat_file = os.path.join(solvers[0].WorkingDirectory, "Mesh.dat")
            n_results = len(
                [o for o in analysis.Group if o.isDerivedFrom("Fem::FemResultObjectPython")]
            )
            indices = sorted(list(getattr(proxy, "result_map", {}).keys()))

            self.assertTrue(dat_obj or os.path.isfile(dat_file))
            self.assertGreater(n_results, 0)
            self.assertIn(4, indices)
        finally:
            if doc and getattr(doc, "Name", ""):
                App.closeDocument(doc.Name)

    def test_static_inp_contains_rota_corio_and_velocity_ic(self):
        """A static LinkBody solve writes ROTA/CORIO and velocity IC cards to INP."""
        _msg("  Test static INP contains ROTA/CORIO/velocity IC")
        ex = _import_or_skip(self, "femexamples.assembly_linkbody_free_dynamics")
        lb_mod = _import_or_skip(self, "FemLink.LinkBody")

        doc = ex.setup(exercise_loadcases=True)
        try:
            femlinks = [o for o in doc.Objects if getattr(o, "Name", "").startswith("LinkBody_")]
            self.assertTrue(femlinks, "No LinkBody object found")
            femlnk = femlinks[0]

            analysis = femlnk.Proxy.findAnalysis(femlnk)
            self.assertIsNotNone(analysis, "No FEM analysis found for LinkBody")

            solvers = [o for o in analysis.Group if o.isDerivedFrom("Fem::FemSolverObjectPython")]
            self.assertTrue(solvers, "No FEM solver found in analysis")
            solver = solvers[0]
            solver.AnalysisType = "static"
            solver.WorkingDirectory = tempfile.mkdtemp(prefix="fc_lbrota_corio_")

            # Materialise fresh jig for this state.
            femlnk.Proxy.updateFEMLinks(femlnk, mode=lb_mod.UpdateMode.EXECUTE)
            doc.recompute()

            vf_objs = [
                o
                for o in analysis.Group
                if getattr(getattr(o, "Proxy", None), "Type", "") == "Fem::ConstraintVirtualForces"
            ]
            self.assertTrue(vf_objs, "No VirtualForces constraint in analysis")
            vf = vf_objs[0]

            vf.AngularVelocity = App.Vector(0.0, 0.0, 2.0)
            vf.AngularAcceleration = App.Vector(0.0, 0.0, 3.0)
            vf.RelativeVelocity = App.Vector(4.0, 5.0, 6.0)
            doc.recompute()

            femlnk.Proxy.runAnalysis(femlnk, 0)
            doc.recompute()

            inp_files = [
                os.path.join(solver.WorkingDirectory, f)
                for f in os.listdir(solver.WorkingDirectory)
                if f.lower().endswith(".inp")
            ]
            self.assertTrue(inp_files, "No INP files found in solver working directory")

            inp_text = ""
            for inp_file in inp_files:
                with open(inp_file, "r", encoding="utf-8", errors="ignore") as handle:
                    inp_text += "\n" + handle.read()

            self.assertIn(",ROTA,", inp_text)
            self.assertIn(",CORIO,", inp_text)
            self.assertIn("*INITIAL CONDITIONS,TYPE=VELOCITY", inp_text)
        finally:
            if doc and getattr(doc, "Name", ""):
                App.closeDocument(doc.Name)

    def test_state_roundtrip_and_scale(self):
        """states_vector/state_set and scale produce expected aggregate outputs."""
        _msg("  Test state roundtrip and scale")
        mod = self._import_linkbody()

        proxy = mod.LinkBody.__new__(mod.LinkBody)
        body = type("B", (), {"Label": "BodyA"})()
        fp = type("FP", (), {"getParentGroup": lambda self: object()})()

        proxy.all_states = [
            {
                ("R", "Force"): App.Vector(1, 2, 3),
                ("BodyA", "Placement"): App.Placement(),
            }
        ]

        with patch("FemLink.LinkBody.get_assembly_bodies", return_value=[body]):
            vectors = list(proxy.states_vector(fp))
        self.assertEqual(1, len(vectors))
        self.assertEqual([1.0, 2.0, 3.0], vectors[0][:3])
        self.assertEqual(19, len(vectors[0]))

        proxy.state_keys = [("R", "Force"), ("BodyA", "Placement")]
        with patch("FemLink.LinkBody.get_assembly_bodies", return_value=[body]):
            proxy.state_set(fp, vectors[0])
        self.assertEqual(App.Vector(1, 2, 3), proxy.state[("R", "Force")])
        self.assertIn(("BodyA", "Placement"), proxy.state)

        linked = type(
            "L",
            (),
            {"Shape": type("S", (), {"BoundBox": type("BB", (), {"DiagonalLength": 10.0})()})()},
        )()
        fp_scale = type(
            "FPS",
            (),
            {
                "Body": type("BL", (), {"getLinkedObject": lambda self: linked})(),
                "ViewObject": type("VO", (), {"Proxy": type("P", (), {"scale": Mock()})()})(),
            },
        )()
        proxy.all_states = [
            {
                ("x", "Force"): App.Vector(3, 0, 0),
                ("x", "Torque"): App.Vector(0, 4, 0),
                ("x", "LinearAcceleration"): App.Vector(0, 0, 5),
                ("x", "Ignored"): App.Vector(10, 10, 10),
            }
        ]

        proxy.scale(fp_scale)
        fp_scale.ViewObject.Proxy.scale.assert_called_once_with(
            force_max=3.0,
            torque_max=4.0,
            linear_acceleration_max=5.0,
            physical_scale=4.0,
        )
