# SPDX-License-Identifier: LGPL-2.1-or-later

"""A section must name geometry the mesh was made from.

A section whose reference is a face of some other object writes an elset no
element joins, and CalculiX then reads a deck describing an article that is not
the one that was meshed.  ``check_sections_reference_the_mesh`` is the check a
driver asks for, so it must pass a section on the mesh and refuse one outside
it.  It is deliberately not part of the default prerequisite path, so nothing
here asserts a change to an ordinary analysis.
"""

import FreeCAD
import Part
import Fem
import pytest

from femtools import checksanalysis
import ObjectsFem


@pytest.fixture
def document():
    doc = FreeCAD.newDocument("SectionMeshReferenceTest")
    yield doc
    if doc.Name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(doc.Name)


def _unit_square_at_z1():
    """A quad on the top of the unit box."""
    mesh = Fem.FemMesh()
    for node_id, (x, y, z) in enumerate(
            ((0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0)), start=1):
        mesh.addNode(x, y, z, node_id)
    mesh.addFace([1, 2, 3, 4])
    return mesh


def _box(document, name, x=0.0):
    box = document.addObject("Part::Box", name)
    box.Length = box.Width = box.Height = 1.0
    box.Placement.Base = FreeCAD.Vector(x, 0.0, 0.0)
    box.recompute()
    return box


def _upward_face_name(box):
    for index, face in enumerate(box.Shape.Faces, start=1):
        if face.normalAt(0, 0).z > 0.9:
            return f"Face{index}"
    raise AssertionError(f"no upward face on {box.Name}")


def _analysis_with_mesh(document, mesh):
    analysis = ObjectsFem.makeAnalysis(document)
    mesh_obj = document.addObject("Fem::FemMeshObject", "Mesh")
    mesh_obj.FemMesh = mesh
    analysis.addObject(mesh_obj)
    return analysis, mesh_obj


def _section(document, analysis, ref_obj):
    section = ObjectsFem.makeElementGeometry2D(document)
    section.References = [(ref_obj, [_upward_face_name(ref_obj)])]
    analysis.addObject(section)
    return section


def test_a_section_on_the_meshed_face_is_accepted(document):
    analysis, mesh_obj = _analysis_with_mesh(document, _unit_square_at_z1())
    _section(document, analysis, _box(document, "Plate"))
    assert checksanalysis.check_sections_reference_the_mesh(analysis, mesh_obj) == ""


def test_a_section_outside_the_mesh_is_reported(document):
    analysis, mesh_obj = _analysis_with_mesh(document, _unit_square_at_z1())
    _section(document, analysis, _box(document, "Plate"))
    outside = _section(document, analysis, _box(document, "Elsewhere", x=100.0))
    message = checksanalysis.check_sections_reference_the_mesh(analysis, mesh_obj)
    assert outside.Name in message


def test_a_section_with_no_references_is_accepted(document):
    analysis, mesh_obj = _analysis_with_mesh(document, _unit_square_at_z1())
    analysis.addObject(ObjectsFem.makeElementGeometry2D(document, name="Everywhere"))
    assert checksanalysis.check_sections_reference_the_mesh(analysis, mesh_obj) == ""


def test_without_a_mesh_there_is_nothing_to_compare(document):
    analysis = ObjectsFem.makeAnalysis(document)
    _section(document, analysis, _box(document, "Plate"))
    assert checksanalysis.check_sections_reference_the_mesh(analysis, None) == ""