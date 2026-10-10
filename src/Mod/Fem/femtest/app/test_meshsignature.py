# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""The mesh signature must move when the mesh would, and only then.

A signature that misses a real change reuses a stale mesh; a signature that
moves for a layup only throws away a good mesh.  These tests pin both: the
digest of a shape is its content, the digest of a structure ignores iteration
order, and a changed mesh parameter is a changed signature.
"""

import FreeCAD
import ObjectsFem
import Part
import pytest

from femmesh import meshsignature


@pytest.fixture
def document():
    doc = FreeCAD.newDocument("MeshSignatureTest")
    yield doc
    if doc.Name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(doc.Name)


def test_same_shape_digests_the_same():
    assert (meshsignature.shape_digest(Part.makeBox(10, 10, 10))
            == meshsignature.shape_digest(Part.makeBox(10, 10, 10)))


def test_a_changed_shape_changes_its_digest():
    assert (meshsignature.shape_digest(Part.makeBox(10, 10, 10))
            != meshsignature.shape_digest(Part.makeBox(10, 10, 11)))


def test_a_structure_does_not_depend_on_iteration_order():
    parts = {"skin": Part.makeBox(10, 10, 10), "core": Part.makeBox(5, 5, 5)}
    reversed_parts = {name: parts[name] for name in reversed(list(parts))}
    assert (meshsignature.parts_digest(parts)
            == meshsignature.parts_digest(reversed_parts))


def test_a_moved_part_changes_the_structure_digest():
    parts = {"skin": Part.makeBox(10, 10, 10)}
    moved = {"skin": Part.makeBox(10, 10, 10).translate(FreeCAD.Vector(1, 0, 0))}
    assert meshsignature.parts_digest(parts) != meshsignature.parts_digest(moved)


def test_arguments_are_hashed_in_a_fixed_order():
    arguments = {"band": 40, "schedule": "b"}
    reversed_arguments = {"schedule": "b", "band": 40}
    assert (meshsignature.geometry_arguments_digest(arguments)
            == meshsignature.geometry_arguments_digest(reversed_arguments))
    arguments["band"] = 50
    assert (meshsignature.geometry_arguments_digest(arguments)
            != meshsignature.geometry_arguments_digest({"band": 40, "schedule": "b"}))


def test_builder_digest_reads_the_text_not_a_hash(tmp_path):
    builder = tmp_path / "builder.py"
    builder.write_text("size = 1\n")
    first = meshsignature.builder_digest(str(builder))
    builder.write_text("size = 2\n")
    assert meshsignature.builder_digest(str(builder)) != first


def test_a_changed_mesh_parameter_changes_the_signature(document):
    mesh = ObjectsFem.makeMeshGmsh(document, "Mesh")
    mesh.CharacteristicLengthMax = "10.0 mm"
    coarse = meshsignature.mesh_parameters_digest(mesh)
    mesh.CharacteristicLengthMax = "2.5 mm"
    assert meshsignature.mesh_parameters_digest(mesh) != coarse


def test_geometry_components_names_the_builder(tmp_path):
    builder = tmp_path / "builder.py"
    builder.write_text("size = 1\n")
    components = meshsignature.geometry_components(
        {"skin": Part.makeBox(10, 10, 10)}, {"band": 40}, str(builder))
    assert set(components) == {"shapes", "arguments", "versions", "builder"}


def test_explain_names_only_what_moved():
    earlier = {"shapes": "1111aaaa", "arguments": "2222bbbb"}
    later = {"shapes": "1111aaaa", "arguments": "3333cccc"}
    said = meshsignature.explain(earlier, later)
    assert "arguments 2222..->3333.." in said
    assert "shapes" not in said
