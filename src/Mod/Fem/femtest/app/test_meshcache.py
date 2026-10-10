# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""A cached mesh must come back the same mesh, node numbering included.

The deck's element blocks and the results' node IDs are read positionally, so
a restore that renumbers nodes reports a displacement belonging to the wrong
node.  The cache root is always an argument, and a cache read must give the
run its own active document back.
"""

import os

import Fem
import FreeCAD
import pytest

from femmesh import meshcache

_DIGEST = "0123456789abcdef"


@pytest.fixture
def document():
    doc = FreeCAD.newDocument("MeshCacheTest")
    yield doc
    if doc.Name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(doc.Name)


def _tiny_mesh():
    mesh = Fem.FemMesh()
    for node_id, (x, y, z) in enumerate(
            ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)), start=1):
        mesh.addNode(x, y, z, node_id)
    mesh.addFace([1, 2, 3, 4])
    return mesh


def test_a_stored_mesh_loads_back_unchanged(document, tmp_path):
    cache_root = str(tmp_path / "cache")
    mesh = _tiny_mesh()
    meshcache.store(cache_root, _DIGEST, mesh, {"shapes": "abc"})
    target = document.addObject("Fem::FemMeshObject", "Restored")
    found, nodes, elements = meshcache.load(cache_root, _DIGEST, target)
    assert (found, nodes, elements) == (True, 4, 1)
    assert target.FemMesh.NodeCount == 4
    assert target.FemMesh.FaceCount == 1
    assert target.FemMesh.Nodes[3] == FreeCAD.Vector(1, 1, 0)


def test_a_missing_mesh_is_a_miss_not_an_error(document, tmp_path):
    target = document.addObject("Fem::FemMeshObject", "Restored")
    assert meshcache.load(str(tmp_path / "cache"), _DIGEST, target) == (False, 0, 0)


def test_the_components_come_back_with_the_mesh(document, tmp_path):
    cache_root = str(tmp_path / "cache")
    meshcache.store(cache_root, _DIGEST, _tiny_mesh(), {"shapes": "abc"})
    assert meshcache.components_of(cache_root, _DIGEST) == {"shapes": "abc"}


def test_the_last_run_is_remembered(document, tmp_path):
    cache_root = str(tmp_path / "cache")
    mesh = _tiny_mesh()
    assert meshcache.latest(cache_root) is None
    meshcache.note(cache_root, _DIGEST, {"shapes": "abc"}, mesh, "miss")
    remembered = meshcache.latest(cache_root)
    assert remembered["digest"] == _DIGEST
    assert remembered["components"] == {"shapes": "abc"}
    assert remembered["outcome"] == "miss"


def test_a_cache_read_gives_the_run_its_document_back(document, tmp_path):
    cache_root = str(tmp_path / "cache")
    meshcache.store(cache_root, _DIGEST, _tiny_mesh(), {"shapes": "abc"})
    assert FreeCAD.ActiveDocument.Name == document.Name
    target = document.addObject("Fem::FemMeshObject", "Restored")
    meshcache.load(cache_root, _DIGEST, target)
    assert FreeCAD.ActiveDocument.Name == document.Name


def test_no_half_written_mesh_is_left_behind(document, tmp_path):
    cache_root = str(tmp_path / "cache")
    meshcache.store(cache_root, _DIGEST, _tiny_mesh(), {"shapes": "abc"})
    staging = os.path.join(cache_root, meshcache.STAGING)
    assert os.listdir(staging) == []
