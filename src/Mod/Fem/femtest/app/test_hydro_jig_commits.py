# ***************************************************************************
# *   Copyright (c) 2026                                                     *
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

__title__ = "Hydro/Jig commit coverage tests"
__author__ = "FreeCAD contributors"
__url__ = "https://www.freecad.org"

import math
import re
import unittest
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import FreeCAD
import numpy as np
import ObjectsFem
from femmesh import meshsetsgetter
from femobjects.constraint_hydrostaticpressure import (
    ConstraintHydrostaticPressure,
)
from femobjects.constraint_jig321 import ConstraintJig321
from femobjects.constraint_reaction import ConstraintReaction
from femobjects.constraint_virtualforces import ConstraintVirtualForces
from femsolver.calculix import (
    write_constraint_jig321,
    write_constraint_pressure,
    write_constraint_pressure_reaction,
    write_constraint_virtualforces,
    write_step_output,
)
from femsolver.calculix import (
    writer as calculix_writer,
)
from femtools import checksanalysis
from femtools.membertools import AnalysisMember
from FreeCAD import Vector


class TestHydroJigCommits(unittest.TestCase):
    # ********************************************************************************************
    def setUp(self):
        self.document = FreeCAD.newDocument(self.__class__.__name__)

    # ********************************************************************************************
    def tearDown(self):
        FreeCAD.closeDocument(self.document.Name)

    # ********************************************************************************************
    def test_checksanalysis_accepts_jig321_as_static_boundary(self):
        doc = self.document

        analysis = ObjectsFem.makeAnalysis(doc)
        solver = ObjectsFem.makeSolverCalculiX(doc)
        solver.AnalysisType = "static"

        material = ObjectsFem.makeMaterialSolid(doc)
        jig321 = ObjectsFem.makeConstraintJig321(doc)

        analysis.addObject(material)
        analysis.addObject(jig321)

        member = AnalysisMember(analysis)
        msg = checksanalysis.check_member_for_solver_calculix(
            analysis,
            solver,
            None,
            member,
        )

        self.assertNotIn(
            "Static analysis: No mechanical boundary conditions defined.",
            msg,
        )

    # ********************************************************************************************
    def test_write_step_output_writes_jig321_reaction_sets(self):
        # Keep this writer test small and focused by using
        # a minimal writer stub.
        member = SimpleNamespace(
            geos_beamsection=[],
            geos_shellthickness=[],
            geos_fluidsection=[],
            cons_fixed=[],
            cons_displacement=[],
            cons_jig321=[{"Object": SimpleNamespace(Name="Jig321")}],
            cons_rigidbody=[],
            cons_contact=[],
        )
        solver_obj = SimpleNamespace(
            Output3d=False,
            MaterialNonlinearity=False,
            OutputFrequency=1,
        )
        ccxwriter = SimpleNamespace(
            member=member,
            solver_obj=solver_obj,
            analysis_type="static",
        )

        buf = StringIO()
        write_step_output.write_step_output(buf, ccxwriter)
        out = buf.getvalue()

        self.assertIn("reaction forces for Constraint jig321", out)
        self.assertIn("*NODE PRINT, NSET=Jig321-0, TOTALS=ONLY", out)
        self.assertIn("*NODE PRINT, NSET=Jig321-1, TOTALS=ONLY", out)
        self.assertIn("*NODE PRINT, NSET=Jig321-2, TOTALS=ONLY", out)

    # ********************************************************************************************
    def test_writer_step_context_uses_index_aligned_batch_step_state(self):
        writer = calculix_writer.FemInputWriterCcx.__new__(calculix_writer.FemInputWriterCcx)
        writer.batch_step_states = [
            SimpleNamespace(index=0),
            SimpleNamespace(index=1),
            SimpleNamespace(index=2),
        ]

        writer._set_current_step_context(1)

        self.assertEqual(1, writer._current_step_index)
        self.assertIsNotNone(writer._current_batch_step_state)
        self.assertEqual(1, writer._current_batch_step_state.index)

    # ********************************************************************************************
    def test_writer_step_context_rejects_misaligned_batch_step_state(self):
        writer = calculix_writer.FemInputWriterCcx.__new__(calculix_writer.FemInputWriterCcx)
        writer.batch_step_states = [
            SimpleNamespace(index=0),
            SimpleNamespace(index=5),
        ]

        writer._set_current_step_context(1)

        self.assertEqual(1, writer._current_step_index)
        self.assertIsNone(writer._current_batch_step_state)

    # ********************************************************************************************
    def test_apply_virtualforces_snapshot_prefers_batch_step_state_snapshot(self):
        writer = calculix_writer.FemInputWriterCcx.__new__(calculix_writer.FemInputWriterCcx)
        vf_obj = SimpleNamespace(
            Name="VirtualForces",
            CenterOfMass=Vector(0.0, 0.0, 0.0),
        )
        writer.member = SimpleNamespace(cons_virtualforces=[{"Object": vf_obj}])
        writer.batch_step_states = [
            SimpleNamespace(
                index=0,
                vf_snapshot={"VirtualForces": {"CenterOfMass": Vector(1.0, 2.0, 3.0)}},
                reaction_snapshot={},
            )
        ]
        writer.vf_snapshots = [{"VirtualForces": {"CenterOfMass": Vector(9.0, 9.0, 9.0)}}]

        writer._apply_virtualforces_snapshot(0)

        self.assertEqual(Vector(1.0, 2.0, 3.0), vf_obj.CenterOfMass)

    # ********************************************************************************************
    def test_apply_reaction_snapshot_falls_back_to_legacy_arrays(self):
        writer = calculix_writer.FemInputWriterCcx.__new__(calculix_writer.FemInputWriterCcx)
        reaction_obj = SimpleNamespace(
            Name="ConstraintReaction",
            Proxy=SimpleNamespace(Type="Fem::ConstraintReaction"),
            Force=Vector(0.0, 0.0, 0.0),
        )
        writer.member = SimpleNamespace(cons_pressure=[{"Object": reaction_obj}])
        writer.batch_step_states = []
        writer.reaction_snapshots = [{"ConstraintReaction": {"Force": Vector(4.0, 5.0, 6.0)}}]

        writer._apply_reaction_snapshot(0)

        self.assertEqual(Vector(4.0, 5.0, 6.0), reaction_obj.Force)

    # ********************************************************************************************
    def test_write_constraint_virtualforces_emits_static_dalembert_terms(self):
        femobj = {"BodyNodes": [1, 2, 3, 4]}
        vf_obj = SimpleNamespace(
            Name="VirtualForces",
            LinearAcceleration=Vector(0.0, 0.0, -9.81),
            AngularVelocity=Vector(0.0, 0.0, 2.0),
            AngularAcceleration=Vector(0.0, 0.0, 3.0),
            RelativeVelocity=Vector(4.0, 5.0, 6.0),
            LinearVelocity=Vector(0.0, 0.0, 0.0),
            CenterOfRotation=Vector(1.0, 2.0, 3.0),
            InertialCorrectionFactor=1.0,
        )
        femmesh = SimpleNamespace(
            Nodes={
                1: (0.0, 0.0, 0.0),
                2: (1.0, 0.0, 0.0),
                3: (0.0, 1.0, 0.0),
                4: (0.0, 0.0, 1.0),
            }
        )
        ccxwriter = SimpleNamespace(
            mesh_object=SimpleNamespace(FemMesh=femmesh),
            ccx_eall="Eall",
            ccx_nall="Nall",
            analysis_type="static",
        )

        with patch.object(write_constraint_virtualforces, "VF_DECOMPOSE_ACCEL", True):
            buf = StringIO()
            write_constraint_virtualforces.write_meshdata_constraint(buf, femobj, vf_obj, ccxwriter)
            write_constraint_virtualforces.write_constraint(buf, femobj, vf_obj, ccxwriter)
            out = buf.getvalue()

        self.assertIn("*NSET,NSET=VirtualForces-BODY", out)
        self.assertIn("Eall,GRAV,", out)
        self.assertIn("Eall,CENTRIF,4", out)
        self.assertIn("Eall,ROTA,3", out)
        self.assertIn("*INITIAL CONDITIONS,TYPE=VELOCITY", out)
        self.assertIn("VirtualForces-BODY,1,4", out)
        self.assertIn("VirtualForces-BODY,2,5", out)
        self.assertIn("VirtualForces-BODY,3,6", out)
        self.assertIn("Eall,CORIO,4", out)

    # ********************************************************************************************
    def test_write_constraint_virtualforces_applies_inertial_correction_factor(self):
        def _render_with_factor(factor):
            vf_obj = SimpleNamespace(
                Name="VirtualForces",
                LinearAcceleration=Vector(0.0, 0.0, -9.81),
                AngularVelocity=Vector(0.0, 0.0, 2.0),
                AngularAcceleration=Vector(0.0, 0.0, 3.0),
                RelativeVelocity=Vector(4.0, 5.0, 6.0),
                LinearVelocity=Vector(0.0, 0.0, 0.0),
                CenterOfRotation=Vector(1.0, 2.0, 3.0),
                InertialCorrectionFactor=factor,
            )
            buf = StringIO()
            with patch.object(write_constraint_virtualforces, "VF_DECOMPOSE_ACCEL", True):
                write_constraint_virtualforces.write_meshdata_constraint(
                    buf,
                    femobj,
                    vf_obj,
                    ccxwriter,
                )
                write_constraint_virtualforces.write_constraint(buf, femobj, vf_obj, ccxwriter)
            return buf.getvalue()

        def _extract_magnitudes(text):
            mags = {}
            for line in text.splitlines():
                if not line.startswith("Eall,"):
                    continue
                parts = line.split(",")
                if len(parts) < 3:
                    continue
                label = parts[1]
                if label in {"GRAV", "CENTRIF", "ROTA", "CORIO"}:
                    mags[label] = float(parts[2])
            return mags

        femobj = {"BodyNodes": [1, 2, 3, 4]}
        femmesh = SimpleNamespace(
            Nodes={
                1: (0.0, 0.0, 0.0),
                2: (1.0, 0.0, 0.0),
                3: (0.0, 1.0, 0.0),
                4: (0.0, 0.0, 1.0),
            }
        )
        ccxwriter = SimpleNamespace(
            mesh_object=SimpleNamespace(FemMesh=femmesh),
            ccx_eall="Eall",
            ccx_nall="Nall",
            analysis_type="static",
        )

        out_base = _render_with_factor(1.0)
        out_scaled = _render_with_factor(2.0)
        mags_base = _extract_magnitudes(out_base)
        mags_scaled = _extract_magnitudes(out_scaled)

        self.assertAlmostEqual(mags_scaled["GRAV"], 2.0 * mags_base["GRAV"])
        self.assertAlmostEqual(mags_scaled["CENTRIF"], 2.0 * mags_base["CENTRIF"])
        self.assertAlmostEqual(mags_scaled["ROTA"], 2.0 * mags_base["ROTA"])
        self.assertAlmostEqual(mags_scaled["CORIO"], 2.0 * mags_base["CORIO"])

    # ********************************************************************************************
    def test_write_constraint_virtualforces_coriolis_velocity_falls_back_to_linear_velocity(self):
        femobj = {}
        vf_obj = SimpleNamespace(
            Name="VirtualForces",
            LinearAcceleration=Vector(0.0, 0.0, 0.0),
            AngularVelocity=Vector(0.0, 0.0, 2.0),
            AngularAcceleration=Vector(0.0, 0.0, 0.0),
            RelativeVelocity=Vector(0.0, 0.0, 0.0),
            LinearVelocity=Vector(7.0, 8.0, 9.0),
            CenterOfRotation=Vector(0.0, 0.0, 0.0),
        )
        femmesh = SimpleNamespace(
            Nodes={
                1: (0.0, 0.0, 0.0),
                2: (1.0, 0.0, 0.0),
                3: (0.0, 1.0, 0.0),
            }
        )
        ccxwriter = SimpleNamespace(
            mesh_object=SimpleNamespace(FemMesh=femmesh),
            ccx_eall="Eall",
            ccx_nall="Nall",
            analysis_type="static",
        )

        with patch.dict(
            "os.environ",
            {
                "FREECAD_FEM_JIG321_CORIO_ALLOW_LINEAR_FALLBACK": "1",
                "FREECAD_FEM_JIG321_CORIO_REQUIRE_RELVEL_DIFFERENT_FROM_LINEAR": "0",
            },
            clear=False,
        ):
            buf = StringIO()
            write_constraint_virtualforces.write_constraint(buf, femobj, vf_obj, ccxwriter)
            out = buf.getvalue()

        self.assertIn("*INITIAL CONDITIONS,TYPE=VELOCITY", out)
        self.assertIn("Nall,1,7", out)
        self.assertIn("Nall,2,8", out)
        self.assertIn("Nall,3,9", out)
        self.assertIn("Eall,CORIO,4", out)

    # ********************************************************************************************
    def test_write_constraint_virtualforces_rota_and_corio_are_static_only(self):
        femobj = {"BodyNodes": [1, 2, 3]}
        vf_obj = SimpleNamespace(
            Name="VirtualForces",
            LinearAcceleration=Vector(0.0, 0.0, -9.81),
            AngularVelocity=Vector(0.0, 0.0, 2.0),
            AngularAcceleration=Vector(0.0, 0.0, 3.0),
            RelativeVelocity=Vector(4.0, 5.0, 6.0),
            LinearVelocity=Vector(0.0, 0.0, 0.0),
            CenterOfRotation=Vector(1.0, 2.0, 3.0),
        )
        femmesh = SimpleNamespace(
            Nodes={
                1: (0.0, 0.0, 0.0),
                2: (1.0, 0.0, 0.0),
                3: (0.0, 1.0, 0.0),
            }
        )
        ccxwriter = SimpleNamespace(
            mesh_object=SimpleNamespace(FemMesh=femmesh),
            ccx_eall="Eall",
            ccx_nall="Nall",
            analysis_type="thermomech",
        )

        with patch.object(write_constraint_virtualforces, "VF_DECOMPOSE_ACCEL", True):
            buf = StringIO()
            write_constraint_virtualforces.write_constraint(buf, femobj, vf_obj, ccxwriter)
            out = buf.getvalue()

        self.assertIn("Eall,GRAV,", out)
        self.assertIn("Eall,CENTRIF,4", out)
        self.assertNotIn(",ROTA,", out)
        self.assertNotIn(",CORIO,", out)
        self.assertNotIn("*INITIAL CONDITIONS,TYPE=VELOCITY", out)

    # ********************************************************************************************
    def test_membertools_collects_hydrostatic_with_pressure(self):
        doc = self.document

        analysis = ObjectsFem.makeAnalysis(doc)
        pressure = ObjectsFem.makeConstraintPressure(doc)
        hydro = ObjectsFem.makeConstraintHydrostaticPressure(doc)

        analysis.addObject(pressure)
        analysis.addObject(hydro)

        member = AnalysisMember(analysis)

        self.assertEqual(2, len(member.cons_pressure))
        types = [entry["Object"].TypeId for entry in member.cons_pressure]
        self.assertIn("Fem::ConstraintPressure", types)
        self.assertIn("Fem::ConstraintPython", types)
        hydro_entry = [
            entry["Object"] for entry in member.cons_pressure if entry["Object"] == hydro
        ][0]
        self.assertEqual("Fem::ConstraintHydrostaticPressure", hydro_entry.Proxy.Type)

    # ********************************************************************************************
    def test_membertools_collects_reaction_with_pressure(self):
        doc = self.document

        analysis = ObjectsFem.makeAnalysis(doc)
        pressure = ObjectsFem.makeConstraintPressure(doc)
        hydro = ObjectsFem.makeConstraintHydrostaticPressure(doc)
        reaction = ObjectsFem.makeConstraintReaction(doc)

        analysis.addObject(pressure)
        analysis.addObject(hydro)
        analysis.addObject(reaction)

        member = AnalysisMember(analysis)

        self.assertEqual(3, len(member.cons_pressure))
        reaction_entry = [
            entry["Object"] for entry in member.cons_pressure if entry["Object"] == reaction
        ][0]
        self.assertEqual("Fem::ConstraintReaction", reaction_entry.Proxy.Type)

    # ********************************************************************************************
    def test_virtualforces_center_of_rotation_is_recomputed(self):
        doc = self.document

        vf = ObjectsFem.makeConstraintVirtualForces(doc)
        vf.CenterOfMass = Vector(1.0, 2.0, 3.0)
        vf.LinearVelocity = Vector(0.0, 0.0, 0.0)
        vf.AngularVelocity = Vector(0.0, 1.0, 0.0)

        # execute is called during recompute and updates CenterOfRotation
        # from current kinematics.
        doc.recompute()

        self.assertEqual(vf.CenterOfMass, vf.CenterOfRotation)

    # ********************************************************************************************
    def test_virtualforces_inertial_correction_factor_defaults_to_one(self):
        vf = ObjectsFem.makeConstraintVirtualForces(self.document)

        self.assertTrue(hasattr(vf, "InertialCorrectionFactor"))
        self.assertEqual(1.0, float(vf.InertialCorrectionFactor))

    # ********************************************************************************************
    def test_hydrostatic_clip_negative_interpolator(self):
        obj = self.document.addObject("Fem::ConstraintPython", "Hydro")
        proxy = ConstraintHydrostaticPressure(obj)

        obj.ModelType = "Hydrostatic"
        obj.ClipNegative = True

        _, interp = proxy.get_interpolator(obj)

        self.assertEqual(0.0, interp([0.0, 0.0, -5.0])[0])
        self.assertEqual(5.0, interp([0.0, 0.0, 5.0])[0])

    # ********************************************************************************************
    def test_hydrostatic_pressure_field_varies_with_depth(self):
        con_hydro = ObjectsFem.makeConstraintHydrostaticPressure(self.document)
        con_hydro.ModelType = "Hydrostatic"
        self.document.recompute()

        scale = con_hydro.Proxy.get_scale(con_hydro, base=False)
        elem_info = {
            "elem": [0, 1, 2],
            "centroid": {
                0: Vector(0.0, 0.0, 0.0),
                1: Vector(0.0, 0.0, 500.0),
                2: Vector(0.0, 0.0, 1000.0),
            },
            "rev": {0: 1.0, 1: 1.0, 2: 1.0},
            "pressure": {},
        }

        ok = con_hydro.Proxy.get_pressure_field(con_hydro, elem_info)

        self.assertTrue(ok)
        self.assertEqual(0.0, elem_info["pressure"][0])
        self.assertAlmostEqual(scale * 500.0, elem_info["pressure"][1])
        self.assertAlmostEqual(scale * 1000.0, elem_info["pressure"][2])
        self.assertIs(con_hydro.Proxy.elem_info, elem_info)

    # ********************************************************************************************
    def test_hydrostatic_pressure_field_clips_negative_in_local_coordinates(self):
        con_hydro = ObjectsFem.makeConstraintHydrostaticPressure(self.document)
        con_hydro.ModelType = "Hydrostatic"
        con_hydro.ClipNegative = True

        proxy = con_hydro.Proxy
        proxy.scale, proxy.interp = proxy.get_interpolator(con_hydro)
        proxy.map_coord = FreeCAD.Placement(Vector(0.0, 0.0, 10.0), FreeCAD.Rotation()).inverse()

        elem_info = {
            "elem": [0, 1, 2],
            "centroid": {
                0: Vector(0.0, 0.0, 5.0),
                1: Vector(0.0, 0.0, 12.0),
                2: Vector(0.0, 0.0, 15.0),
            },
            "rev": {0: 1.0, 1: -1.0, 2: 1.0},
            "pressure": {},
        }

        ok = proxy.get_pressure_field(con_hydro, elem_info)

        self.assertTrue(ok)
        self.assertEqual(0.0, elem_info["pressure"][0])
        self.assertAlmostEqual(-proxy.scale * 2.0, elem_info["pressure"][1])
        self.assertAlmostEqual(proxy.scale * 5.0, elem_info["pressure"][2])

    # ********************************************************************************************
    def test_write_constraint_pressure_skips_malformed_pressurefaces_entry(self):
        femobj = {
            "PressureFaces": [(False,)],
            "PressureFaceInfo": {},
            "PressureNodeInfo": {},
        }
        prs_obj = SimpleNamespace(
            EnableAmplitude=False,
            Reversed=False,
            Name="ConstraintReaction",
            Proxy=SimpleNamespace(get_pressure_field=lambda _obj, _elem_info: True),
        )
        ccxwriter = SimpleNamespace(
            mesh_object=SimpleNamespace(FemMesh=SimpleNamespace(Faces=())),
        )

        buf = StringIO()
        write_constraint_pressure.write_meshdata_constraint(buf, femobj, prs_obj, ccxwriter)

        self.assertIn("*DLOAD", buf.getvalue())

    # ********************************************************************************************
    def test_write_constraint_pressure_handles_missing_faceinfo_for_subface_list(self):
        class _FakeFemMesh:
            Faces = (1,)
            Nodes = {
                10: Vector(0, 0, 0),
                11: Vector(1, 0, 0),
                12: Vector(0, 1, 0),
            }

            def getElementNodes(self, _elem_id):
                return (10, 11, 12)

        femobj = {
            "PressureFaces": [((None, ("Face1",)), [[1, 1]], True)],
            "PressureFaceInfo": {},
            "PressureNodeInfo": {},
        }
        prs_obj = SimpleNamespace(
            EnableAmplitude=False,
            Reversed=False,
            Name="ConstraintReaction",
            Proxy=SimpleNamespace(),
            Pressure=SimpleNamespace(getValueAs=lambda _unit: SimpleNamespace(Value=1.0)),
        )
        ccxwriter = SimpleNamespace(
            mesh_object=SimpleNamespace(FemMesh=_FakeFemMesh()),
        )

        buf = StringIO()
        write_constraint_pressure.write_meshdata_constraint(buf, femobj, prs_obj, ccxwriter)

        out = buf.getvalue()
        self.assertIn("*DLOAD", out)
        self.assertIn("1,P1,1", out)

    # ********************************************************************************************
    def test_meshsetsgetter_pressure_info_keys_cover_all_surface_entries(self):
        getter = meshsetsgetter.MeshSetsGetter.__new__(meshsetsgetter.MeshSetsGetter)

        getter.member = SimpleNamespace(cons_pressure=[])
        getter.face_masks = {
            "mask_tetra4": {0b0111: 1, 0b1011: 2, 0b1101: 3, 0b1110: 4},
            "mask_tetra10": {},
            "mask_hexa8": {},
            "mask_hexa20": {},
            "mask_penta6": {},
            "mask_penta15": {},
        }
        getter.femelement_table = {42: (1, 2, 3, 4)}
        getter.femnodes_mesh = {
            1: Vector(0, 0, 0),
            2: Vector(1, 0, 0),
            3: Vector(0, 1, 0),
            4: Vector(0, 0, 1),
        }
        getter.femmesh = SimpleNamespace()

        constraint_obj = SimpleNamespace(Name="ConstraintReaction", References=[])
        feature = (constraint_obj, ("Face7",))
        femobj = {"Object": constraint_obj}
        getter.member.cons_pressure = [femobj]
        getter._get_elements = lambda _obj: [(feature, [[42, 1], [42, 2], [42, 3], [42, 4]], True)]

        meshsetsgetter.MeshSetsGetter.get_constraints_pressure_faces(getter)

        expected_keys = {(42, 1), (42, 2), (42, 3), (42, 4)}
        self.assertEqual(expected_keys, set(femobj["PressureFaceInfo"].keys()))
        self.assertEqual(expected_keys, set(femobj["PressureNodeInfo"].keys()))

        # Ensure local face numbering maps to oriented local nodes (tetra4 face 2).
        self.assertEqual([1, 4, 2], femobj["PressureNodeInfo"][(42, 2)])

    # ********************************************************************************************
    def test_reaction_get_contact_unknown_model_raises(self):
        obj = SimpleNamespace(ModelType="NotAContactModel")
        proxy = ConstraintReaction.__new__(ConstraintReaction)

        with self.assertRaises(NotImplementedError):
            proxy.get_contact(obj, Vector(0, 0, 1), Vector(0, 0, -1))

    # ********************************************************************************************
    def test_reaction_display_pressure_uses_nodal_weighting(self):
        con_reaction = ObjectsFem.makeConstraintReaction(self.document)
        con_reaction.ModelType = "Cosine"
        con_reaction.Force = Vector(0, 0, -1)
        con_reaction.Torque = Vector(0, 0, 0)
        proxy = con_reaction.Proxy

        elem_info = {
            "elem": [0, 1],
            "normal": [Vector(0, 0, 1), Vector(0, 0, 1)],
            "area": [2.0, 1.0],
            "face_nodes": [[1, 2, 3], [1, 3, 4]],
            "pressure": [0.0, 0.0],
        }

        ok = proxy.get_pressure_field(con_reaction, elem_info)

        self.assertTrue(ok)
        self.assertAlmostEqual(8.0 / 9.0, elem_info["pressure"][0])
        self.assertAlmostEqual(7.0 / 9.0, elem_info["pressure"][1])
        self.assertIs(proxy.elem_info, elem_info)

    # ********************************************************************************************
    def test_reaction_display_pressure_falls_back_to_area_weighting(self):
        con_reaction = ObjectsFem.makeConstraintReaction(self.document)
        con_reaction.ModelType = "Cosine"
        # Positive normal-load projection means separation => zero contact.
        con_reaction.Force = Vector(0, 0, 1)
        con_reaction.Torque = Vector(0, 0, 0)
        proxy = con_reaction.Proxy

        elem_info = {
            "elem": [0, 1],
            "normal": [Vector(0, 0, 1), Vector(0, 0, 1)],
            "area": [2.0, 1.0],
            "face_nodes": [[1, 2, 3], [1, 3, 4]],
            "pressure": [0.0, 0.0],
        }

        ok = proxy.get_pressure_field(con_reaction, elem_info)

        self.assertTrue(ok)
        self.assertAlmostEqual(8.0 / 9.0, elem_info["pressure"][0])
        self.assertAlmostEqual(7.0 / 9.0, elem_info["pressure"][1])
        self.assertIs(proxy.elem_info, elem_info)

    # ********************************************************************************************
    def test_reaction_moment_transfer_helper_maps_wrench_between_points(self):
        force = Vector(2.0, -3.0, 5.0)
        moment_origin = Vector(7.0, 11.0, 13.0)
        origin = Vector(10.0, 20.0, 30.0)
        reference = Vector(-4.0, 6.0, 8.0)

        got = write_constraint_pressure_reaction._moment_at_reference(
            force,
            moment_origin,
            origin,
            reference,
        )
        expected = moment_origin + (origin - reference).cross(force)

        self.assertAlmostEqual(expected.x, got.x)
        self.assertAlmostEqual(expected.y, got.y)
        self.assertAlmostEqual(expected.z, got.z)

    # ********************************************************************************************
    def test_reaction_distributing_coupling_uses_cached_reference_moment_transfer(self):
        prs_obj = SimpleNamespace(
            Name="ConstraintReaction",
            Origin=SimpleNamespace(Base=Vector(0.0, 10.0, 0.0)),
            Force=Vector(10.0, 0.0, 0.0),
            Torque=Vector(0.0, 0.0, 0.0),
            EnableAmplitude=False,
            Proxy=SimpleNamespace(),
        )
        elem_info = {
            "elem": [1],
            "area": [1.0],
            "face_nodes": [[1, 2, 3]],
            "normal": [Vector(0.0, 0.0, 1.0)],
        }
        femmesh = SimpleNamespace(
            Nodes={
                1: Vector(1.0, 0.0, 0.0),
                2: Vector(0.0, 1.0, 0.0),
                3: Vector(0.0, 0.0, 1.0),
            },
            Volumes=[1],
            Faces=[1],
            Edges=[],
        )
        ccxwriter = SimpleNamespace(
            member=SimpleNamespace(cons_jig321=[]),
            analysis=SimpleNamespace(Group=[prs_obj]),
            _reaction_coupling_cache={
                "ConstraintReaction": {
                    "ref_node_id": 999,
                    "elset_name": "RDCPL_TEST_EL",
                    "ref_base": Vector(0.0, 0.0, 0.0),
                }
            },
        )

        messages = []
        console = SimpleNamespace(
            PrintMessage=lambda msg: messages.append(msg),
            PrintWarning=lambda _msg: None,
        )

        buf = StringIO()
        write_constraint_pressure_reaction.write_reaction_distributing_coupling(
            buf,
            prs_obj,
            ccxwriter,
            femmesh,
            elem_info,
            reaction_coupling_shift_free_m_limit=1.0,
            reaction_coupling_shift_scale=1.0,
            Console=console,
            op_new=False,
        )

        out = buf.getvalue()
        self.assertIn("*CLOAD", out)
        # Cached reference node carries force (999), face nodes carry moment-equivalent couple.
        self.assertRegex(out, r"\n999,1,")
        self.assertRegex(out, r"\n[123],")

        merged_messages = "".join(messages)
        self.assertIn(
            "ConstraintReaction ConstraintReaction: wrote distributing coupling",
            merged_messages,
        )
        match = re.search(r"\|M\|=([0-9eE+\-.]+)", merged_messages)
        self.assertIsNotNone(match)
        self.assertGreater(float(match.group(1)), 1.0e-6)

    # ********************************************************************************************
    def test_reaction_distributing_coupling_batch_uses_nodal_cloads(self):
        prs_obj = SimpleNamespace(
            Name="ConstraintReaction",
            Origin=SimpleNamespace(Base=Vector(0.0, 0.0, 0.0)),
            Force=Vector(10.0, 0.0, 0.0),
            Torque=Vector(0.0, 0.0, 0.0),
            EnableAmplitude=False,
            Proxy=SimpleNamespace(),
        )
        elem_info = {
            "elem": [1],
            "area": [1.0],
            "face_nodes": [[1, 2, 3]],
            "normal": [Vector(0.0, 0.0, 1.0)],
        }
        femmesh = SimpleNamespace(
            Nodes={
                1: Vector(1.0, 0.0, 0.0),
                2: Vector(0.0, 1.0, 0.0),
                3: Vector(0.0, 0.0, 1.0),
            },
            Volumes=[1],
            Faces=[1],
            Edges=[],
        )
        ccxwriter = SimpleNamespace(
            member=SimpleNamespace(cons_jig321=[]),
            analysis=SimpleNamespace(Group=[prs_obj]),
            _reaction_coupling_cache={},
            _current_step_index=0,
        )

        console = SimpleNamespace(
            PrintMessage=lambda _msg: None,
            PrintWarning=lambda _msg: None,
        )

        out_step0 = StringIO()
        write_constraint_pressure_reaction.write_reaction_distributing_coupling(
            out_step0,
            prs_obj,
            ccxwriter,
            femmesh,
            elem_info,
            reaction_coupling_shift_free_m_limit=1.0,
            reaction_coupling_shift_scale=1.0,
            Console=console,
            op_new=False,
        )

        out0 = out_step0.getvalue()
        self.assertIn("*CLOAD", out0)
        self.assertNotIn("*NODE", out0)
        self.assertNotIn("*ELEMENT,TYPE=DCOUP3D", out0)
        self.assertNotIn("*DISTRIBUTING COUPLING", out0)
        self.assertTrue(
            any(
                line.startswith("1,") or line.startswith("2,") or line.startswith("3,")
                for line in out0.splitlines()
            )
        )

    # ********************************************************************************************
    def test_reaction_get_pressure_field_populates_tables(self):
        con_reaction = ObjectsFem.makeConstraintReaction(self.document)
        con_reaction.ModelType = "Cosine"
        con_reaction.Origin.Base = Vector(0, 0, 0)
        con_reaction.Force = Vector(0, 0, 0)
        con_reaction.Torque = Vector(0, 0, 0)
        proxy = con_reaction.Proxy
        load_vec = np.array([0.0, -2.0, -3.0, 0.0, 0.0, 0.0])
        load_len = (13.0) ** 0.5

        elem_info = {
            "elem": [0, 1],
            "normal": {0: Vector(0, 0, 1), 1: Vector(0, 1, 0)},
            "area": {0: 2.0, 1: 1.5},
            "centroid": {0: Vector(0, 0, 1), 1: Vector(1, 0, 0)},
            "rev": {0: -1.0, 1: 1.0},
            "pressure": {},
        }

        def fake_root(fun, _x0, method=None):
            self.assertEqual("hybr", method)
            _ = fun(load_vec)
            return SimpleNamespace(success=True)

        with patch("femobjects.constraint_reaction.root", side_effect=fake_root):
            ok = proxy.get_pressure_field(con_reaction, elem_info)

        self.assertTrue(ok)
        self.assertAlmostEqual(3.0 / load_len, elem_info["contact"][0])
        self.assertAlmostEqual(2.0 / load_len, elem_info["contact"][1])
        self.assertAlmostEqual(load_len, elem_info["load"][0])
        self.assertAlmostEqual(load_len, elem_info["load"][1])
        self.assertEqual(-3.0, elem_info["pressure"][0])
        self.assertEqual(2.0, elem_info["pressure"][1])
        self.assertEqual(Vector(0, 0, 1), elem_info["prel"][0])
        self.assertEqual(Vector(1, 0, 0), elem_info["prel"][1])
        self.assertIs(proxy.elem_info, elem_info)

    # ********************************************************************************************
    def test_reaction_parabolic_pressure_field_squares_contact_factor(self):
        con_reaction = ObjectsFem.makeConstraintReaction(self.document)
        con_reaction.ModelType = "Parabolic"
        con_reaction.Origin.Base = Vector(0, 0, 0)
        con_reaction.Force = Vector(0, 0, 0)
        con_reaction.Torque = Vector(0, 0, 0)
        proxy = con_reaction.Proxy

        elem_info = {
            "elem": [0, 1],
            "normal": {0: Vector(0, 0, 1), 1: Vector(1, 0, 0)},
            "area": {0: 1.0, 1: 1.0},
            "centroid": {0: Vector(0, 0, 1), 1: Vector(0, 0, 2)},
            "rev": {0: 1.0, 1: 1.0},
            "pressure": {},
        }

        def fake_root(fun, _x0, method=None):
            self.assertEqual("hybr", method)
            _ = fun(np.array([0.0, 0.0, -4.0, 0.0, 0.0, 0.0]))
            return SimpleNamespace(success=True)

        with patch("femobjects.constraint_reaction.root", side_effect=fake_root):
            ok = proxy.get_pressure_field(con_reaction, elem_info)

        self.assertTrue(ok)
        self.assertEqual(1.0, elem_info["contact"][0])
        self.assertEqual(4.0, elem_info["load"][0])
        self.assertEqual(4.0, elem_info["pressure"][0])
        self.assertEqual(0.0, elem_info["contact"][1])
        self.assertEqual(4.0, elem_info["load"][1])
        self.assertEqual(0.0, elem_info["pressure"][1])

    # ********************************************************************************************
    def test_reaction_onchanged_and_restore_callbacks(self):
        proxy = ConstraintReaction.__new__(ConstraintReaction)
        fp = SimpleNamespace(ModelType="Cosine", recompute=Mock())

        proxy.onChanged(fp, "Force")
        fp.recompute.assert_not_called()

        proxy.onChanged(fp, "ModelType")
        fp.recompute.assert_called_once()

        restored = SimpleNamespace(recompute=Mock())
        proxy.onDocumentRestored(restored)
        restored.recompute.assert_called_once()

    # ********************************************************************************************
    def test_reaction_save_reactioninfo_writes_one_row(self):
        proxy = ConstraintReaction.__new__(ConstraintReaction)
        elem_info = {
            "pressure": {0: 7.0},
            "centroid": {0: Vector(1, 2, 3)},
            "normal": {0: Vector(0, 0, 1)},
            "prel": {0: Vector(4, 5, 6)},
            "area": {0: 2.0},
            "contact": {0: 0.5},
            "load": {0: 10.0},
        }

        with patch("builtins.open", create=True) as open_mock:
            file_mock = Mock()
            open_mock.return_value.__enter__.return_value = file_mock
            proxy.save_reactioninfo(elem_info)

        writes = "".join(call.args[0] for call in file_mock.write.call_args_list)
        self.assertIn("1.0 2.0 3.0", writes)
        self.assertIn("0.0 0.0 1.0", writes)
        self.assertIn("7.0", writes)

    # ********************************************************************************************
    def test_virtualforces_center_of_rotation_nontrivial_branch(self):
        vf = ObjectsFem.makeConstraintVirtualForces(self.document)
        vf.CenterOfMass = Vector(1.0, 2.0, 3.0)
        vf.LinearVelocity = Vector(4.0, 0.0, 0.0)
        vf.AngularVelocity = Vector(0.0, 0.0, 2.0)

        self.document.recompute()

        self.assertEqual(Vector(1.0, 4.0, 3.0), vf.CenterOfRotation)

    # ********************************************************************************************
    def test_virtualforces_onchanged_respects_restore_and_triggers(self):
        proxy = ConstraintVirtualForces.__new__(ConstraintVirtualForces)
        fp = SimpleNamespace(recompute=Mock())

        with patch("femobjects.constraint_virtualforces.App.isRestoring", return_value=True):
            proxy.onChanged(fp, "CenterOfMass")
        fp.recompute.assert_not_called()

        with patch("femobjects.constraint_virtualforces.App.isRestoring", return_value=False):
            proxy.onChanged(fp, "CenterOfMass")
            proxy.onChanged(fp, "LinearAcceleration")
        fp.recompute.assert_called_once()

    # ********************************************************************************************
    def test_jig321_find_largest_triangle_insufficient_nodes(self):
        proxy = ConstraintJig321.__new__(ConstraintJig321)
        fp = SimpleNamespace(Supports=[Vector(1, 1, 1)])
        femmesh = SimpleNamespace(Nodes={1: (0, 0, 0), 2: (1, 0, 0)})

        out = proxy.find_largest_triangle(fp, femmesh, [1, 1, 2, 2])

        self.assertEqual([], out)
        self.assertEqual([], fp.Supports)

    # ********************************************************************************************
    def test_jig321_find_largest_triangle_success(self):
        proxy = ConstraintJig321.__new__(ConstraintJig321)
        fp = SimpleNamespace(Supports=[])
        femmesh = SimpleNamespace(
            Nodes={
                10: (0.0, 0.0, 0.0),
                11: (1.0, 0.0, 0.0),
                12: (0.0, 1.0, 0.0),
                13: (1.0, 1.0, 0.0),
            }
        )

        hull = SimpleNamespace(
            points=[
                femmesh.Nodes[10],
                femmesh.Nodes[11],
                femmesh.Nodes[12],
                femmesh.Nodes[13],
            ],
            vertices=[0, 1, 2, 3],
        )

        with patch("scipy.spatial.ConvexHull", return_value=hull):
            out = proxy.find_largest_triangle(fp, femmesh, [10, 11, 12, 13])

        self.assertEqual(3, len(out))
        self.assertTrue(set(out).issubset({10, 11, 12, 13}))
        self.assertEqual(3, len(fp.Supports))

    # ********************************************************************************************
    def test_dynamic_pendulum_reports_nonzero_jig_forces_in_dat(self):
        """Run dynamic LinkBody pendulum and verify Jig reaction totals are non-zero."""
        try:
            import AssemblyApp  # noqa: F401
            from femexamples.assembly_linkbody_free_dynamics import setup
            from FemLink import LinkBody as _LinkBody  # noqa: F401
        except Exception as exc:
            self.skipTest(f"Dynamic pendulum prerequisites unavailable: {exc}")

        # Reuse the test document to avoid GUI/editor coupling with ActiveDocument.
        setup(doc=self.document, solvertype="ccxtools", exercise_loadcases=True)

        dat_docs = [
            obj
            for obj in self.document.Objects
            if getattr(obj, "TypeId", "") == "App::TextDocument"
            and obj.Name.startswith("ccx_dat_file")
        ]
        self.assertTrue(dat_docs, "No ccx_dat_file text document found after simulation run.")

        dat_text = dat_docs[-1].Text
        self.assertTrue(dat_text, "ccx_dat_file is empty.")

        set_re = re.compile(
            r"total force \(fx,fy,fz\) for set\s+(\S+)\s+and time",
            re.IGNORECASE,
        )
        vec_re = re.compile(r"([-+0-9.Ee]+)\s+([-+0-9.Ee]+)\s+([-+0-9.Ee]+)")

        jig_forces = []
        lines = dat_text.splitlines()
        for i, line in enumerate(lines):
            match = set_re.search(line)
            if not match:
                continue

            set_name = match.group(1).upper()
            if "CONSTRAINTJIG" not in set_name:
                continue

            vec_line = ""
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    vec_line = lines[j]
                    break

            vec_match = vec_re.search(vec_line)
            if not vec_match:
                continue

            fx, fy, fz = (float(vec_match.group(k)) for k in (1, 2, 3))
            jig_forces.append((set_name, fx, fy, fz))

        self.assertTrue(jig_forces, "No CONSTRAINTJIG force totals parsed from ccx_dat_file.")

        # There should be only one Jig constraint family for this analysis.
        jig_set_families = {set_name.rsplit("-", 1)[0] for set_name, *_ in jig_forces}
        self.assertEqual(
            1,
            len(jig_set_families),
            f"Expected one CONSTRAINTJIG family, got: {sorted(jig_set_families)}",
        )

        # Real dynamic load transfer must produce at least one non-zero support total.
        self.assertTrue(
            any(math.sqrt(fx * fx + fy * fy + fz * fz) > 1.0e-6 for _, fx, fy, fz in jig_forces),
            "All parsed CONSTRAINTJIG force totals are zero.",
        )

    # ********************************************************************************************
    def test_compound_pendulum_setup_creates_multimaterial_linkbody(self):
        """Compound LinkBody example should build two solid regions with distinct materials."""
        try:
            import AssemblyApp  # noqa: F401
            from femexamples.assembly_linkbody_free_dynamics_compound_materials import (
                setup,
            )
            from FemLink import LinkBody as _LinkBody  # noqa: F401
        except Exception as exc:
            self.skipTest(f"Compound pendulum prerequisites unavailable: {exc}")

        setup(doc=self.document, solvertype="ccxtools", exercise_loadcases=False)

        pendulum_links = [
            obj
            for obj in self.document.Objects
            if getattr(obj, "TypeId", "") == "App::Link" and getattr(obj, "Name", "") == "Pendulum"
        ]
        self.assertTrue(pendulum_links, "No Pendulum App::Link found in compound example")

        shape_obj = pendulum_links[0].getLinkedObject()
        solids = list(getattr(shape_obj.Shape, "Solids", []))
        self.assertGreaterEqual(len(solids), 2, "Compound pendulum should expose at least 2 solids")

        # Ensure the compound example actually produced multiple material regions.
        material_objs = [
            obj
            for obj in self.document.Objects
            if getattr(obj, "TypeId", "") == "App::MaterialObjectPython"
        ]
        self.assertGreaterEqual(len(material_objs), 2, "Expected at least two FEM material objects")

        solid_refs = set()
        for mat_obj in material_objs:
            for ref in getattr(mat_obj, "References", []) or []:
                if not isinstance(ref, (list, tuple)) or len(ref) != 2:
                    continue
                ref_sub = ref[1]
                if isinstance(ref_sub, (list, tuple)):
                    for sub in ref_sub:
                        if isinstance(sub, str) and sub.startswith("Solid"):
                            solid_refs.add(sub)
                elif isinstance(ref_sub, str) and ref_sub.startswith("Solid"):
                    solid_refs.add(ref_sub)

        self.assertGreaterEqual(
            len(solid_refs),
            2,
            "Expected references to at least two SolidN regions for compound pendulum",
        )

        densities = []
        for mat_obj in material_objs:
            material_map = getattr(mat_obj, "Material", {}) or {}
            if not isinstance(material_map, dict):
                continue
            density = str(material_map.get("Density", "")).strip()
            if density:
                densities.append(density)

        self.assertGreaterEqual(
            len(set(densities)),
            2,
            "Expected at least two distinct material densities for compound pendulum",
        )
