# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Geometry references for mixed shell + solid coupling.

A constraint names geometry as ``(object, "FaceN")``, and a mixed model needs
two of those that meet: the shell face and the solid face it is bonded to.
Finding them is geometry, not policy, so it lives here rather than in whichever
example needed it first - this is where ``paired_faces_by_plane`` gets its
shape lookups, and what the mixed fixtures, examples and probes used to
re-implement once per file.

Nothing here meshes, writes or solves: these functions turn geometry into
references, and nothing else.
"""

import FreeCAD

COINCIDENT_TOLERANCE = 1e-6
_ROUND_DIGITS = 6


def _component(vector, axis):
    """``vector``'s component ``axis``, named ("z") or indexed (2)."""
    return vector[axis] if isinstance(axis, int) else getattr(vector, axis)


def face_normal(face):
    """Return the outward normal of a planar face, sampled away from its rim."""
    u0, u1, v0, v1 = face.ParameterRange
    return face.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))


def plane_offset(face):
    """Return the signed distance of a planar face's plane from the origin."""
    return face.CenterOfMass.dot(face_normal(face))


def find_face_reference(obj, normal, offset, tolerance=COINCIDENT_TOLERANCE):
    """Return ``(obj, "FaceN")`` for the face whose plane is ``normal`` at ``offset``."""
    wanted = FreeCAD.Vector(*normal).normalize()
    for index, face in enumerate(obj.Shape.Faces, start=1):
        if face_normal(face).dot(wanted) < 1.0 - tolerance:
            continue
        if abs(plane_offset(face) - offset) <= tolerance:
            return (obj, f"Face{index}")
    raise ValueError(f"no face of {obj.Name} lies on {normal} at {offset}")


def face_reference_on_axis(
    obj, axis, value, tolerance=COINCIDENT_TOLERANCE, planar_only=False
):
    """Return ``(obj, "FaceN")`` for the face centred on ``axis`` = ``value``.

    ``planar_only`` skips a curved face whose centre happens to land there,
    which is what a flat interface or a load on a plane wants.
    """
    for index, face in enumerate(obj.Shape.Faces, start=1):
        if planar_only and face.Surface.TypeId != "Part::GeomPlane":
            continue
        if abs(_component(face.CenterOfMass, axis) - value) <= tolerance:
            return (obj, f"Face{index}")
    raise ValueError(f"{obj.Name} has no face on {axis}={value}")


def extreme_face_reference(obj, axis, sign):
    """Return ``(obj, "FaceN")`` for the face furthest along ``axis`` in ``sign``."""
    best_index = None
    best_value = None
    for index, face in enumerate(obj.Shape.Faces, start=1):
        value = _component(face.CenterOfMass, axis) * sign
        if best_value is None or value > best_value:
            best_index, best_value = index, value
    if best_index is None:
        raise ValueError(f"{obj.Name} has no faces")
    return (obj, f"Face{best_index}")


def find_edge_reference(obj, point_a, point_b):
    """Return ``(obj, "EdgeN")`` for the edge running between two points."""
    wanted = _endpoint_key(point_a, point_b)
    for index, edge in enumerate(obj.Shape.Edges, start=1):
        if _edge_endpoints(edge) == wanted:
            return (obj, f"Edge{index}")
    raise ValueError(f"no edge of {obj.Name} runs between {point_a} and {point_b}")


def edge_reference_at(obj, *, x=None, y=None, z=None, tolerance=COINCIDENT_TOLERANCE):
    """Return ``(obj, "EdgeN")`` for the edge centred on the coordinates given."""
    wanted = {"x": x, "y": y, "z": z}
    for index, edge in enumerate(obj.Shape.Edges, start=1):
        centre = edge.CenterOfMass
        if all(
            value is None or abs(getattr(centre, name) - value) <= tolerance
            for name, value in wanted.items()
        ):
            return (obj, f"Edge{index}")
    raise ValueError(f"{obj.Name} has no edge at {wanted}")


def extreme_edge_reference(obj, axis, sign):
    """Return ``(obj, "EdgeN")`` for the edge furthest along ``axis`` in ``sign``."""
    best_index = None
    best_value = None
    for index, edge in enumerate(obj.Shape.Edges, start=1):
        value = _component(edge.CenterOfMass, axis) * sign
        if best_value is None or value > best_value:
            best_index, best_value = index, value
    if best_index is None:
        raise ValueError(f"{obj.Name} has no edges")
    return (obj, f"Edge{best_index}")


def paired_faces_by_plane(solid_shape, shell_shape, tolerance):
    """Pairs the shell faces to the solid faces they lie on or over, by plane.

    A pair is a shell face and a solid face whose normals are parallel and whose
    planes are no further apart than ``tolerance``. This is the interface a face
    coupling is tied over, and it ignores the solid faces the shell does not
    reach.
    """
    pairs = []
    for solid_index, solid_face in enumerate(solid_shape.Faces, start=1):
        solid_normal = face_normal(solid_face)
        for shell_index, shell_face in enumerate(shell_shape.Faces, start=1):
            if face_normal(shell_face).dot(solid_normal) < 1.0 - COINCIDENT_TOLERANCE:
                continue
            gap = abs((shell_face.CenterOfMass - solid_face.CenterOfMass).dot(solid_normal))
            if gap <= tolerance:
                pairs.append((f"Face{shell_index}", f"Face{solid_index}"))
    return pairs


def _edge_endpoints(edge):
    vertices = edge.Vertexes
    if len(vertices) != 2:
        return None
    return _endpoint_key(vertices[0].Point, vertices[1].Point)


def _endpoint_key(point_a, point_b):
    return tuple(sorted((_rounded(point_a), _rounded(point_b))))


def _rounded(point):
    vector = point if isinstance(point, FreeCAD.Vector) else FreeCAD.Vector(*point)
    return (
        round(vector.x, _ROUND_DIGITS),
        round(vector.y, _ROUND_DIGITS),
        round(vector.z, _ROUND_DIGITS),
    )
