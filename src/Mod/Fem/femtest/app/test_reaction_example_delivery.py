# ***************************************************************************
# *   Copyright (c) 2026 I. M. Wang <jmw@earendil-works.dev>                *
# *                                                                         *
# *   This file is part of the FreeCAD FEM workbench.                       *
# *                                                                         *
# ***************************************************************************
"""Writer-level check of the ConstraintReaction example's delivered load.

The femexamples.constraint_reaction model is the only committed consumer
of the reaction delivery path besides the LS8e fuselage work.  This test
builds the example document, writes the CalculiX input (no solve), and
reconstructs the resultant force and moment of every written *CLOAD
entry about the reaction Origin.  It must equal the writer's target
(-Force, -Torque of the object) exactly — the wrench-shift cross-order
bug (delivered moment negated) shipped unnoticed because no test
consumed this example.
"""

import FreeCAD
import pytest

from femexamples import constraint_reaction as reaction_example
from femtest.app import support_utils

Vector = FreeCAD.Vector


@pytest.mark.slow
def test_reaction_example_written_resultant(tmp_path):
    doc = reaction_example.setup()
    try:
        analysis = doc.getObject("Analysis")
        solver = next(o for o in analysis.Group
                      if o.isDerivedFrom("Fem::FemSolverObject"))
        mesh_obj = next(o for o in analysis.Group
                        if o.isDerivedFrom("Fem::FemMeshObject"))
        solver.WorkingDir = str(tmp_path)

        from femtools.ccxtools import FemToolsCcx

        fem = FemToolsCcx(analysis=analysis, solver=solver)
        fem.update_objects()
        fem.set_inp_file_name()
        fem.write_inp_file()
        inp = fem.inp_file_name

        reaction = doc.getObject("ConstraintReaction")
        origin = reaction.Origin.Base
        nodes, preamble, steps = support_utils.parse_calculix_deck(inp)
        entries = preamble["entries"] + [
            e for step in steps for e in step["entries"]]
        assert entries, "no *CLOAD written — reaction never reached the input"
        force, moment = support_utils.cload_resultant(entries, nodes, origin)
        # reaction convention: the writer delivers -Force, -Torque of
        # the object (the example stores F=(0,0,-2000), T=(10,0,0))
        assert (force - Vector(0, 0, 2000.0)).Length < 1e-6, force
        assert (moment - Vector(-10.0, 0, 0)).Length < 1e-3, moment
    finally:
        FreeCAD.closeDocument(doc.Name)
