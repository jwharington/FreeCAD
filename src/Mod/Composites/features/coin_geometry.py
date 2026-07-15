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

import numpy as np


def build_support_surface_coin(shape, deflection=1.0, draper=None):
    """Build Coin3D geometry from a FreeCAD Part.Shape with UV coordinates.

    Uses Shape.tessellate() to convert the shape into a triangle mesh,
    then builds SoCoordinate3 + SoIndexedFaceSet with UV coordinates.

    UV coordinates are mapped from the drape mesh to the support surface
    via the draper's get_tex_coord_at_point() (quad containment + refinement,
    with nearest-quad fallback only for points outside the mesh).

    Args:
        shape: FreeCAD Part.Shape object
        deflection: tessellation deflection tolerance (lower = finer mesh)
        draper: CompositeShell instance (provides get_tex_coord_at_point)

    Returns:
        SoSeparator with SoCoordinate3 + SoIndexedFaceSet + SoTextureCoordinate3
    """
    verts, tris = shape.tessellate(deflection)

    # Map UV coordinates from drape mesh to support surface
    uv_coords = _map_uv_to_support(draper, verts)

    # Build vertex coordinates
    coords = coin.SoCoordinate3()
    pts = [coin.SbVec3f(float(v[0]), float(v[1]), float(v[2])) for v in verts]
    coords.point.setValues(0, len(pts), pts)

    # Build UV coordinates
    tex_coords = coin.SoTextureCoordinate3()
    uv_pts = [coin.SbVec2f(float(u[0]), float(u[1])) for u in uv_coords]
    tex_coords.point.setValues(0, len(uv_pts), uv_pts)

    # Build triangle indices (SoIndexedFaceSet expects -1 separators)
    face_set = coin.SoIndexedFaceSet()
    indices: list[int] = []
    for tri in tris:
        indices.extend([int(tri[0]), int(tri[1]), int(tri[2]), -1])
    indices.append(-1)
    face_set.coordIndex.setValues(0, len(indices), indices)
    # Set texture coord indices (indexed, matching coordIndex)
    face_set.textureCoordIndex.setValues(0, len(indices), indices)

    sep = coin.SoSeparator()
    sep.addChild(coords)
    sep.addChild(tex_coords)
    sep.addChild(face_set)
    return sep


def _map_uv_to_support(draper, support_verts):
    """Map UV coordinates from drape mesh to support surface.

    Delegates to the draper backend's get_tex_coord_at_point() for each
    vertex, which performs proper quad containment checking + refinement,
    falling back to nearest-quad only for points outside the mesh.

    Args:
        draper: CompositeShell FP object (provides _backend)
        support_verts: list of (x, y, z) tuples from tessellation

    Returns:
        Array of (u, v) coordinates for support surface vertices
    """
    if draper is None or not hasattr(draper, "_backend") or draper._backend is None:
        return np.zeros((len(support_verts), 2), dtype=np.float32)

    backend = draper._backend
    uv_coords = []
    for vert in support_verts:
        uv = backend.get_tex_coord_at_point(vert, 0)
        if uv is not None:
            uv_coords.append(uv)
        else:
            uv_coords.append([0.0, 0.0])

    return np.array(uv_coords, dtype=np.float32)


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
    for quad_idx, q in enumerate(quads):
        i0, i1, i2, i3 = [int(idx) for idx in q]
        indices.extend([i0, i1, i2, -1])
        indices.extend([i0, i2, i3, -1])
    indices.append(-1)
    face_set.coordIndex.setValues(0, len(indices), indices)
    # Don't set materialIndex – causes "index out of bounds" warnings when
    # no SoMaterial node with multiple materials exists in the scene graph.

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
