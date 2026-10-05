# ***************************************************************************
# *   Copyright (c) 2026 I. M. Wang <jmw@earendil-works.dev>                *
# *                                                                         *
# *   This file is part of the FreeCAD FEM workbench.                       *
# *                                                                         *
# ***************************************************************************
"""Regression test: junction-tolerant face node queries in meshtools.

At multi-boolean junctions a mesh node born on one trim curve can sit
~1e-4 mm off a coincident face's own curve, so the strict
FemMesh.getNodesByFace rejects the node and the element reaches the
solver with no material elset.  get_nodes_by_face_with_fallback now
retries with a widened tolerance (JUNCTION_TOL) and only when that
recovers nodes.

Tests use two overlapping plans (offset ~1e-5, well inside JUNCTION_TOL
but far outside the default 1e-7 face tolerance) and a mesh whose nodes
sit on the *other* plan.
"""

import FreeCAD
import Part
import pytest

from femmesh import meshtools


@pytest.fixture(name="offset_mesh_and_face")
def fixture_offset_mesh_and_face():
    """Mesh a planar face whose nodes lie on a parallel planar face
    offset by ~1e-5 mm.  Face under query: the second plan (its own
    nodes are elsewhere, so only tolerance recovers the queried nodes)."""
    face_a = Part.Face(Part.makePlane(100, 100, FreeCAD.Vector(0, 0, 0)))
    # nodes live on plane A; query face B at dz = 1e-5 (<= JUNCTION_TOL)
    face_b = Part.Face(Part.makePlane(100, 100, FreeCAD.Vector(0, 0, 1e-5)))
    face_b.Tolerance = 1e-7

    import Fem
    mesh = Fem.FemMesh()
    pts = [FreeCAD.Vector(x, y, 0) for x in (0.0, 50.0, 100.0)
           for y in (0.0, 50.0, 100.0)]
    node_ids = [mesh.addNode(pt.x, pt.y, pt.z) for pt in pts]
    mesh.addFace([node_ids[0], node_ids[1], node_ids[3], node_ids[4]])
    mesh.addFace([node_ids[1], node_ids[2], node_ids[4], node_ids[5]])
    mesh.addFace([node_ids[3], node_ids[4], node_ids[6], node_ids[7]])
    mesh.addFace([node_ids[4], node_ids[5], node_ids[7], node_ids[8]])
    return mesh, face_a, face_b


def test_strict_query_misses_offset_nodes(offset_mesh_and_face):
    """The native strict query must NOT see plane A's nodes — otherwise
    the fixture does not reproduce the junction residual."""
    mesh, _, face_b = offset_mesh_and_face
    face_b.Tolerance = 1e-7
    strict = mesh.getNodesByFace(face_b)
    assert not strict, "fixture broken: strict query saw the offset nodes"


def test_tolerant_fallback_recovers_nodes(offset_mesh_and_face):
    """get_nodes_by_face_with_fallback recovers the nodes via the
    widened-tolerance retry (the junction remedy)."""
    mesh, _, face_b = offset_mesh_and_face
    nodes = meshtools.get_nodes_by_face_with_fallback(mesh, face_b)
    assert nodes, "tolerant retry recovered nothing"


def test_tol_argument_geometric_fallback_respects_tol(offset_mesh_and_face):
    """The geometric fallback path still honours its tol parameter."""
    mesh, face_a, _ = offset_mesh_and_face
    nodes = meshtools.get_nodes_by_face_geometric(mesh, face_a, tol=1e-7)
    assert len(nodes) == 9, "geometric fallback lost nodes on its own plane"
    nodes_wide = meshtools.get_nodes_by_face_geometric(mesh, face_a, tol=1e-3)
    assert len(nodes_wide) >= len(nodes)


def test_junction_tol_below_geometry_scale():
    """JUNCTION_TOL must stay far below real mesh feature sizes so the
    widened query can never claim nodes of genuinely neighbouring
    geometry."""
    assert meshtools.JUNCTION_TOL <= 1e-3
