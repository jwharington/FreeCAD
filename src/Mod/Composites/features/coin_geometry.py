# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Coin3D scene-graph helpers for draped mesh geometry injection.

These functions build and manage Coin3D nodes (SoSeparator, SoCoordinate3,
SoIndexedFaceSet) that represent the draped fabric mesh. They are kept
separate from the feature/view-provider classes so they can be reused
and tested independently.
"""

from __future__ import annotations

from pivy import coin


def build_support_surface_coin(shape, deflection=1.0):
    """Build Coin3D geometry from a FreeCAD Part.Shape.

    Uses Shape.tessellate() to convert the shape into a triangle mesh,
    then builds SoCoordinate3 + SoIndexedFaceSet.

    Args:
        shape: FreeCAD Part.Shape object
        deflection: tessellation deflection tolerance (lower = finer mesh)

    Returns:
        SoSeparator with SoCoordinate3 + SoIndexedFaceSet
    """
    verts, tris = shape.tessellate(deflection)

    # Build vertex coordinates
    coords = coin.SoCoordinate3()
    pts = [coin.SbVec3f(float(v[0]), float(v[1]), float(v[2])) for v in verts]
    coords.point.setValues(0, len(pts), pts)

    # Build triangle indices (SoIndexedFaceSet expects -1 separators)
    face_set = coin.SoIndexedFaceSet()
    indices: list[int] = []
    for tri in tris:
        indices.extend([int(tri[0]), int(tri[1]), int(tri[2]), -1])
    indices.append(-1)
    face_set.coordIndex.setValues(0, len(indices), indices)

    sep = coin.SoSeparator()
    sep.addChild(coords)
    sep.addChild(face_set)
    return sep


def build_support_surface_coin(shape):
    """Build Coin3D geometry from a FreeCAD Part.Shape.

    Uses Shape.tessellate() to convert the shape into a triangle mesh,
    then builds SoCoordinate3 + SoIndexedFaceSet.

    Parameters
    ----------
    shape : FreeCAD.Part.Shape
        The shape to tessellate and convert to Coin3D geometry.

    Returns
    -------
    SoSeparator
        A separator containing SoCoordinate3 + SoIndexedFaceSet.
    """
    # Tessellate the shape into triangles
    # Returns (vertices, triangles) where:
    #   vertices: list of (x, y, z) tuples
    #   triangles: list of (i0, i1, i2) index triples
    verts, tris = shape.tessellate(1.0)  # deflection tolerance

    # Build Coin3D coordinate data
    coords = coin.SoCoordinate3()
    pts = [coin.SbVec3f(float(v[0]), float(v[1]), float(v[2])) for v in verts]
    coords.point.setValues(0, len(pts), pts)

    # Build Coin3D face indices (triangles, not quads)
    face_set = coin.SoIndexedFaceSet()
    indices: list[int] = []
    for tri in tris:
        indices.extend([int(i) for i in tri])
        indices.append(-1)  # End of face
    indices.append(-1)  # End of all faces
    face_set.coordIndex.setValues(0, len(indices), indices)

    # Build separator
    sep = coin.SoSeparator()
    sep.addChild(coords)
    sep.addChild(face_set)
    return sep


def build_drapecd_coin(node_positions, quads, wireframe=False):
    """Build Coin3D geometry from draper node_positions and quads.

    Preserves 1:1 mapping: vertex i = node_positions[i].
    No deduplication.

    Args:
        node_positions: list of (x, y, z) tuples
        quads: list of quad connectivity [N, 4]
        wireframe: if True, render as wireframe (lines only)

    Returns:
        SoSeparator with SoCoordinate3 + SoIndexedFaceSet (+ SoDrawStyle if wireframe).
    """
    coords = coin.SoCoordinate3()
    pts = [coin.SbVec3f(float(p[0]), float(p[1]), float(p[2])) for p in node_positions]
    coords.point.setValues(0, len(pts), pts)

    face_set = coin.SoIndexedFaceSet()
    indices: list[int] = []
    material_indices: list[int] = []
    for quad_idx, q in enumerate(quads):
        i0, i1, i2, i3 = [int(idx) for idx in q]
        indices.extend([i0, i1, i2, -1])
        indices.extend([i0, i2, i3, -1])
        material_indices.extend([quad_idx, -1, quad_idx, -1])
    indices.append(-1)
    material_indices.append(-1)
    face_set.coordIndex.setValues(0, len(indices), indices)
    face_set.materialIndex.setValues(0, len(material_indices), material_indices)

    sep = coin.SoSeparator()
    sep.addChild(coords)
    if wireframe:
        ds = coin.SoDrawStyle()
        ds.style.setValue(coin.SoDrawStyle.LINES)
        sep.addChild(ds)
    sep.addChild(face_set)
    return sep


def find_switch(node):
    """Find the first Switch child inside *node* (non-recursive).

    Returns the Switch node or None.
    """
    children = node.getChildren()
    if children is None:
        return None
    for i in range(int(children.getLength())):
        c = children[i]
        if c and "Switch" in str(c.getTypeId().getName()):
            return c
    return None


GEOMETRY_NAME = "DrapedMeshGeometry"


def remove_existing_coin_geometry(root) -> None:
    """Remove any previously injected Coin3D geometry from *root*."""
    children = root.getChildren()
    if children is None:
        return
    for i in range(int(children.getLength()) - 1, -1, -1):
        c = children[i]
        if c is None:
            continue
        if c.getName() == GEOMETRY_NAME:
            root.removeChild(i)


def inject_coin_geometry(root, coin_geo) -> None:
    """Inject Coin3D geometry as a named child of *root*."""
    coin_geo.setName(GEOMETRY_NAME)
    root.addChild(coin_geo)


def inject_cut_edges(root, cut_edges: list) -> None:
    """Inject cut-edge line geometry as visible red overlays."""
    if not cut_edges:
        return

    sep = coin.SoSeparator()

    for walk in cut_edges:
        pc = len(walk)
        if pc < 2:
            continue
        wire_sep = coin.SoSeparator()
        wire_mat = coin.SoMaterial()
        wire_mat.diffuseColor.setValue(1.0, 0.0, 0.0)
        wire_sep.addChild(wire_mat)
        wire_coords = coin.SoCoordinate3()
        pts: list[coin.SbVec3f] = [
            coin.SbVec3f(float(p[0]), float(p[1]), float(p[2]))
            for p in walk
        ]
        wire_coords.point.setValues(0, pc, pts)
        wire_sep.addChild(wire_coords)
        line_set = coin.SoLineSet()
        wire_sep.addChild(line_set)
        sep.addChild(wire_sep)

    root.addChild(sep)


def remove_cut_edges(root) -> None:
    """Remove previously injected cut-edge separator from *root*."""
    children = root.getChildren()
    if children is None or children.getLength() == 0:
        return
    last = children[children.getLength() - 1]
    if (
        last
        and str(last.getTypeId().getName())
        not in ("Separator", "Switch", "Path", "Group")
    ):
        return
    sub = last.getChildren() if last else None
    if sub and sub.getLength() >= 2:
        has_coord = has_lineset = False
        for j in range(int(sub.getLength())):
            sc = sub[j]
            if sc is None:
                continue
            st = str(sc.getTypeId().getName())
            if st == "Coordinate3":
                has_coord = True
            if "LineSet" in st:
                has_lineset = True
        if has_coord and has_lineset:
            root.removeChild(int(children.getLength()) - 1)
