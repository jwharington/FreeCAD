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

import unittest
from io import StringIO
from types import SimpleNamespace

import FreeCAD
import ObjectsFem
from femsolver.calculix import write_step_output
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
        self.assertIn("Fem::ConstraintHydrostaticPressure", types)

    # ********************************************************************************************
    def test_jig321_center_of_rotation_is_recomputed(self):
        doc = self.document

        jig = ObjectsFem.makeConstraintJig321(doc)
        jig.CenterOfMass = Vector(1.0, 2.0, 3.0)
        jig.LinearVelocity = Vector(0.0, 0.0, 0.0)
        jig.AngularVelocity = Vector(0.0, 1.0, 0.0)

        # execute is called during recompute and updates CenterOfRotation
        # from current kinematics.
        doc.recompute()

        self.assertEqual(jig.CenterOfMass, jig.CenterOfRotation)
