# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail

from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from ..objects.symmetry_type import SymmetryType


import hashlib


def shape_fingerprint(shape) -> str:
    """Compute a structural hash of a FreeCAD shape.

    Primary signature is ``shape.hashCode()`` as requested.
    Falls back to ``BOPTools.Utils.HashableShape_Deep`` for composed
    shapes where a direct hashCode call may be unavailable.

    Parameters
    ----------
    shape : FreeCAD.Shape
        The shape to fingerprint.

    Returns
    -------
    str
        A hex digest (first 16 chars) suitable for equality comparison.
    """
    h = hashlib.sha256()
    h.update(b"shape:v1:")

    try:
        h.update(str(shape.hashCode()).encode())
        return h.hexdigest()[:16]
    except Exception:
        pass

    try:
        from BOPTools.Utils import HashableShape_Deep

        h.update(str(hash(HashableShape_Deep(shape))).encode())
        return h.hexdigest()[:16]
    except Exception:
        pass

    return "fallback:"


def expand_symmetry(
    li: List,
    sym: Optional["SymmetryType"] = None,
):
    from ..objects.symmetry_type import SymmetryType

    if sym is None:
        sym = SymmetryType.Assymmetric
    if SymmetryType.Assymmetric == sym:
        return li
    elif SymmetryType.Odd == sym:
        return li + li[::-1][1:]
    else:
        return li + li[::-1]


def normalise_orientation(raw: float):
    return (raw + 90) % 180 - 90


def format_orientation(orientation):
    return f"[{int(orientation):+03d}]"


def format_layer(p, k):
    return f"{p}{int(k):03d}"


def tex_coord_at_point(node_positions, quads, tex_coords, point, offset_angle_deg=0.0):
    """Bilinear UV at a 3D point via quad containment + refinement.

    Finds the quad containing the projected 3D point and interpolates
    the UV coordinates from the four corner nodes. For points outside
    the mesh, uses the nearest quad with clamped UV.

    Parameters
    ----------
    node_positions : array-like (N, 3)
        Node positions in world space.
    quads : list of list of int
        Quad connectivity as lists of four vertex indices.
    tex_coords : array-like (N, 2)
        Texture (UV) coordinates per node.
    point : sequence of 3 floats
        Query point in world space.
    offset_angle_deg : float
        Optional rotation of UV coordinates (for rosette stacking).

    Returns
    -------
    list[float, float] or None
        UV coordinates, or None if no quad is reachable.
    """
    import numpy as np

    node_positions = np.asarray(node_positions)
    tex_coords = np.asarray(tex_coords)

    if not quads or len(node_positions) == 0:
        return None

    px, py, pz = float(point[0]), float(point[1]), float(point[2])

    best_quad = None
    best_dist = float("inf")
    best_u, best_v = 0.0, 0.0
    nearest_quad = None
    nearest_centroid = None

    for q in quads:
        i0, i1, i2, i3 = [int(idx) for idx in q]
        c0 = node_positions[i0]
        c1 = node_positions[i1]
        c2 = node_positions[i2]
        c3 = node_positions[i3]

        centroid = (c0 + c1 + c2 + c3) / 4.0
        v1 = c1 - c0
        v2 = c3 - c0
        normal = np.cross(v1, v2)
        norm_len = np.linalg.norm(normal)
        if norm_len < 1e-10:
            continue
        normal /= norm_len

        to_point = np.array([px, py, pz]) - centroid
        dist_to_plane = abs(np.dot(to_point, normal))

        # Track nearest quad by centroid distance (for fallback)
        dist_to_centroid = float(np.linalg.norm(to_point))
        if dist_to_centroid < best_dist:
            best_dist = dist_to_centroid
            nearest_quad = q
            nearest_centroid = centroid

        proj_point = np.array([px, py, pz]) - normal * dist_to_plane * np.sign(
            np.dot(to_point, normal)
        )

        e0 = c1 - c0
        e1 = c3 - c0
        e0_norm = np.linalg.norm(e0)
        e1_norm = np.linalg.norm(e1)
        if e0_norm < 1e-10 or e1_norm < 1e-10:
            continue
        e0_unit = e0 / e0_norm
        e1_unit = e1 - np.dot(e1, e0_unit) * e0_unit
        e1_unit_norm = np.linalg.norm(e1_unit)
        if e1_unit_norm < 1e-10:
            continue
        e1_unit /= e1_unit_norm

        delta = proj_point - c0
        u_est = np.dot(delta, e0_unit) / e0_norm
        v_est = np.dot(delta, e1_unit) / e1_unit_norm

        if -0.05 <= u_est <= 1.05 and -0.05 <= v_est <= 1.05:
            c_corner = c2 - c1 - c3 + c0
            if np.linalg.norm(c_corner) > 1e-10:
                a_u = np.dot(c_corner, e0_unit)
                b_u = np.dot(e0, e0_unit) + np.dot(c_corner, e1_unit) * v_est - np.dot(delta, e0_unit)
                c_u = np.dot(e0, e0_unit) * v_est + np.dot(c0, e0_unit) - np.dot(delta, e0_unit)
                if abs(a_u) > 1e-15:
                    disc = b_u * b_u - 4 * a_u * c_u
                    if disc >= 0:
                        u_est = (-b_u + np.sqrt(disc)) / (2 * a_u)
                        if 0 <= u_est <= 1:
                            a_v = np.dot(c_corner, e1_unit)
                            b_v = np.dot(e1, e1_unit) + np.dot(c_corner, e0_unit) * u_est - np.dot(delta, e1_unit)
                            c_v = np.dot(e1, e1_unit) * u_est + np.dot(c0, e1_unit) - np.dot(delta, e1_unit)
                            if abs(a_v) > 1e-15:
                                disc_v = b_v * b_v - 4 * a_v * c_v
                                if disc_v >= 0:
                                    v_est = (-b_v + np.sqrt(disc_v)) / (2 * a_v)
            else:
                u_est = np.dot(delta, e0_unit) / e0_norm
                v_est = np.dot(delta, e1_unit) / e1_unit_norm

            if 0 <= u_est <= 1 and 0 <= v_est <= 1:
                uv = (
                    (1 - u_est) * (1 - v_est) * tex_coords[i0]
                    + u_est * (1 - v_est) * tex_coords[i1]
                    + u_est * v_est * tex_coords[i2]
                    + (1 - u_est) * v_est * tex_coords[i3]
                )
                dist = np.linalg.norm(proj_point - (c0 + u_est * (c1 - c0) + v_est * (c3 - c0)))
                if dist < best_dist:
                    best_dist = dist
                    best_quad = q
                    best_u, best_v = uv[0], uv[1]

    if best_quad is None:
        # No quad contained the projected point — use nearest quad
        # and clamp UV to [0,1] for a sensible fallback.
        if nearest_quad is not None:
            i0, i1, i2, i3 = [int(idx) for idx in nearest_quad]
            c0, c1, c2, c3 = node_positions[i0], node_positions[i1], node_positions[i2], node_positions[i3]
            v1, v2 = c1 - c0, c3 - c0
            normal = np.cross(v1, v2)
            norm_len = np.linalg.norm(normal)
            if norm_len >= 1e-10:
                normal /= norm_len
                to_point = np.array([px, py, pz]) - nearest_centroid
                proj_point = np.array([px, py, pz]) - normal * dist_to_plane * np.sign(
                    np.dot(to_point, normal)
                )
                e0 = c1 - c0
                e1 = c3 - c0
                e0_norm = np.linalg.norm(e0)
                e1_norm = np.linalg.norm(e1)
                if e0_norm >= 1e-10 and e1_norm >= 1e-10:
                    e0_unit = e0 / e0_norm
                    e1_unit = e1 - np.dot(e1, e0_unit) * e0_unit
                    e1_unit_norm = np.linalg.norm(e1_unit)
                    if e1_unit_norm >= 1e-10:
                        e1_unit /= e1_unit_norm
                        delta = proj_point - c0
                        u_est = np.dot(delta, e0_unit) / e0_norm
                        v_est = np.dot(delta, e1_unit) / e1_norm
                        best_u = max(0.0, min(1.0, u_est))
                        best_v = max(0.0, min(1.0, v_est))
                else:
                    best_u, best_v = 0.0, 0.0
            else:
                best_u, best_v = 0.0, 0.0
        else:
            best_u, best_v = 0.0, 0.0

    # Apply offset angle rotation
    if offset_angle_deg:
        ang = np.radians(-offset_angle_deg)
        cos_a, sin_a = np.cos(ang), np.sin(ang)
        best_u, best_v = (
            best_u * cos_a - best_v * sin_a,
            best_u * sin_a + best_v * cos_a,
        )

    return [best_u, best_v]
