# ***************************************************************************
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *                                                                         *
# ***************************************************************************

"""A point load on a tie's shell slave (plan section 11.9).

Dhondt's arrangement: two shell layers tied on the lower face of the upper
one, with a point load on the upper layer.  CalculiX applies a shell point load
through the same expansion MPC a surface tie uses, so whichever expanded node
the tie names can no longer be the dependent term of the load's MPC, and the
tie is dropped at the loaded nodes under a warning FreeCAD classifies as benign
("already constrained").

The mixed face families do not exhibit it (measured in the plan: load and
no-load decks differ by the ``*CLOAD`` block only, ``.nam`` byte-identical), so
this fixture is the two-shell-layer arrangement the plan calls for.
"""

import FreeCAD
import Part
import pytest

import Fem
import ObjectsFem

from femtools import ccxtools
from femtools.ccxtools import tied_mpc_warning_counts

FLAG_PATH = "User parameter:BaseApp/Preferences/Mod/Fem/General"
FLAG_NAME = "AllowMixedShellSolid"

SHELL_THICKNESS = 1.0
TIE_TOLERANCE = 1.0


def two_shell_layers():
    """Two coincident-footprint quads, one layer above the other, node-disjoint.

    The lower layer's reference surface is z=0 and the upper's z=1, so with a
    section thickness of 1 the upper's negative expansion face (S1, at z=0.5)
    meets the lower's positive one (S2, at z=0.5): exactly the "tied on the
    lower face of the upper one" arrangement, and geometrically distinct so the
    reference resolution can tell the two layers apart.
    """
    mesh = Fem.FemMesh()
    for node_id, (x, y) in enumerate(((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)), start=1):
        mesh.addNode(x, y, 0.0, node_id)
    mesh.addFace([1, 2, 3, 4])
    for node_id, (x, y) in enumerate(((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)), start=5):
        mesh.addNode(x, y, 1.0, node_id)
    mesh.addFace([5, 6, 7, 8])
    return mesh


def _two_layer_document(load_on="upper"):
    doc = FreeCAD.newDocument("tie_shell_load")
    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiXCcxTools")
    solver.ReducedIntegration = False
    analysis.addObject(solver)

    material = ObjectsFem.makeMaterialSolid(doc, "Material")
    steel = material.Material
    steel["Name"] = "CalculiX-Steel"
    steel["YoungsModulus"] = "210000 MPa"
    steel["PoissonRatio"] = "0.30"
    material.Material = steel
    analysis.addObject(material)
    analysis.addObject(ObjectsFem.makeElementGeometry2D(doc, SHELL_THICKNESS, "ShellThickness"))

    lower = doc.addObject("Part::Feature", "LowerShell")
    lower.Shape = Part.makePlane(10.0, 10.0)
    upper = doc.addObject("Part::Feature", "UpperShell")
    upper.Shape = Part.makePlane(10.0, 10.0)
    upper.Placement.Base = FreeCAD.Vector(0.0, 0.0, SHELL_THICKNESS)

    mesh_obj = analysis.addObject(ObjectsFem.makeMeshGmsh(doc, "Mesh"))[0]
    mesh_obj.FemMesh = two_shell_layers()

    fixed = ObjectsFem.makeConstraintFixed(doc, "Fixed")
    # Only an edge: the master test loads the lower face, and fixing the whole
    # face would constrain the loaded nodes to zero displacement.
    fixed.References = [(lower, "Edge1")]
    analysis.addObject(fixed)

    force = ObjectsFem.makeConstraintForce(doc, "Force")
    force.References = [(upper if load_on == "upper" else lower, "Face1")]
    force.Force = "100 N"
    analysis.addObject(force)

    tie = ObjectsFem.makeConstraintTie(doc, "Tie")
    tie.References = [(upper, "Face1"), (lower, "Face1")]
    tie.Tolerance = TIE_TOLERANCE
    analysis.addObject(tie)
    doc.recompute()
    return doc, analysis, solver, mesh_obj


@pytest.mark.slow
def test_a_load_on_the_shell_slave_is_refused(tmp_path):
    """The check the plan's section 11.9 asks for.

    A *CLOAD on the tie's shell slave makes CalculiX drop the tie at the loaded
    nodes under a warning FreeCAD reads as benign, so the write has to refuse
    before the surface is written, naming the nodes and the remedy.
    """
    doc, analysis, solver, mesh_obj = _two_layer_document(load_on="upper")
    try:
        fea = ccxtools.FemToolsCcx(analysis=analysis, solver=solver)
        fea.setup_working_dir(str(tmp_path))
        with pytest.raises(ValueError) as excinfo:
            fea.run()
        message = str(excinfo.value)
        self_nodes = {5, 6, 7, 8}
        assert "Tie" in message, message
        assert "CLOAD" in message, message
        assert str(sorted(self_nodes)) in message, message
        assert "Load the master side" in message, message
    finally:
        FreeCAD.closeDocument(doc.Name)


@pytest.mark.slow
def test_a_load_on_the_master_side_writes_and_solves(tmp_path):
    """The remedy: the same model loaded on the master side couples and solves.

    This is the half that shows the refusal is about the load's node, not about
    the tie itself.
    """
    doc, analysis, solver, mesh_obj = _two_layer_document(load_on="lower")
    try:
        fea = ccxtools.FemToolsCcx(analysis=analysis, solver=solver)
        fea.setup_working_dir(str(tmp_path))
        ran = fea.run()
        assert ran, "the master-loaded deck did not solve; see the log above"
        not_coupled, _already_constrained = tied_mpc_warning_counts(fea.ccx_stdout)
        assert not_coupled == 0, "the master-loaded deck left the tie uncoupled"
        results = [
            o for o in analysis.Group if o.isDerivedFrom("Fem::FemResultObject")
        ]
        assert results, "the deck solved but no result was read back"
        displacements = [float(v) for v in results[0].DisplacementLengths]
        assert max(displacements) > 0.0, "the deck solved to zero displacement"
    finally:
        FreeCAD.closeDocument(doc.Name)
