# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Does the frd reader put an expanded frd mesh back onto the model mesh?

A layered COMPOSITE *SHELL SECTION makes CalculiX expand every shell into
solids in the .frd no matter what OUTPUT is set to, so the imported result mesh
can be several times the model.  The reader now prefers the analysis's own mesh
when the frd's nodes are a strict superset, and these tests pin the choice: the
model mesh is taken, a result mesh is never mistaken for the model, a model node
the frd does not carry blocks the switch, and a result row set that does not
span the model blocks it too.
"""

import FreeCAD

import ObjectsFem
from feminout import importCcxFrdResults as frd


def _mesh_with_nodes(node_ids):
    import Fem

    mesh = Fem.FemMesh()
    for node_id in node_ids:
        mesh.addNode(float(node_id), 0.0, 0.0, node_id)
    return mesh


def _mesh_object(doc, name, node_ids):
    obj = ObjectsFem.makeMeshResult(doc, name)
    obj.FemMesh = _mesh_with_nodes(node_ids)
    return obj


def test_model_mesh_is_taken_when_the_frd_is_a_strict_superset():
    doc = FreeCAD.newDocument("mapping")
    try:
        analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
        model = _mesh_object(doc, "ModelMesh", [1, 2, 3])
        analysis.addObject(model)
        picked = frd._model_femmesh(analysis, {1, 2, 3, 4, 5})
        assert picked.NodeCount == 3
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_a_result_mesh_is_never_taken_as_the_model():
    doc = FreeCAD.newDocument("mapping")
    try:
        analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
        model = _mesh_object(doc, "ModelMesh", [1, 2, 3])
        result_mesh = _mesh_object(doc, "ResultMesh", [1, 2, 3, 4, 5])
        result = ObjectsFem.makeResultMechanical(doc, "Result")
        result.Mesh = result_mesh
        analysis.addObject(model)
        analysis.addObject(result)
        picked = frd._model_femmesh(analysis, {1, 2, 3, 4, 5})
        assert picked.NodeCount == 3
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_a_model_node_the_frd_lacks_blocks_the_mapping():
    doc = FreeCAD.newDocument("mapping")
    try:
        analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
        model = _mesh_object(doc, "ModelMesh", [1, 2, 3])
        analysis.addObject(model)
        assert frd._model_femmesh(analysis, {1, 2, 4}) is None
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_result_rows_must_span_the_display_mesh():
    covered = [{"number": float("nan"), "disp": {1: (0, 0, 0), 2: (0, 0, 0)}}]
    missing = [{"disp": {1: (0, 0, 0)}}]
    assert frd._results_cover_nodes(covered, {1, 2}) is True
    assert frd._results_cover_nodes(missing, {1, 2}) is False
