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
                # Bilinear refinement: solve P(u,v)=proj_point for u,v.
                # P(u,v) = c0 + u*e0 + v*e1 + uv*c_corner
                # Project onto e0_unit: u*A0 + v*B0 + uv*C0 = D0
                # Project onto e1_unit: u*A1 + v*B1 + uv*C1 = D1
                # Eliminating v: u^2*(A0*C1-A1*C0) + u*(A0*B1-A1*B0+D1*C0-D0*C1)
                #   + (D1*B0-D0*B1) = 0
                A0, B0, C0, D0 = e0_norm, np.dot(e1, e0_unit), np.dot(c_corner, e0_unit), np.dot(delta, e0_unit)
                A1, B1, C1, D1 = np.dot(e0, e1_unit), e1_unit_norm, np.dot(c_corner, e1_unit), np.dot(delta, e1_unit)
                a_uv = A0 * C1 - A1 * C0
                b_uv = A0 * B1 - A1 * B0 + D1 * C0 - D0 * C1
                c_uv = D1 * B0 - D0 * B1
                if abs(a_uv) > 1e-15:
                    disc_uv = b_uv * b_uv - 4 * a_uv * c_uv
                    if disc_uv >= 0:
                        u_root = (-b_uv + np.sqrt(disc_uv)) / (2 * a_uv)
                        denom = B1 + u_root * C1
                        if abs(denom) > 1e-15:
                            v_root = (D1 - u_root * A1) / denom
                            u_est, v_est = u_root, v_root
                elif abs(b_uv) > 1e-15:
                    # Degenerate: linear equation
                    u_root = -c_uv / b_uv
                    denom = B1 + u_root * C1
                    if abs(denom) > 1e-15:
                        v_root = (D1 - u_root * A1) / denom
                        u_est, v_est = u_root, v_root
            else:
                u_est = np.dot(delta, e0_unit) / e0_norm
                v_est = np.dot(delta, e1_unit) / e1_unit_norm

            # Interpolate/extrapolate UVs using bilinear basis.
            # Texture coords are in world-space, so we don't restrict to [0,1].
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
        # and project onto the quad plane for a better UV estimate.
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
                # Project onto quad plane using bilinear basis
                e0 = c1 - c0
                e1 = c3 - c0
                c_corner = c2 - c1 - c3 + c0
                e0_norm = np.linalg.norm(e0)
                if e0_norm >= 1e-10:
                    e0_unit = e0 / e0_norm
                    e1_unit = e1 - np.dot(e1, e0_unit) * e0_unit
                    e1_unit_norm = np.linalg.norm(e1_unit)
                    if e1_unit_norm >= 1e-10:
                        e1_unit /= e1_unit_norm
                        delta = proj_point - c0
                        # Planar projection fallback
                        u_planar = np.dot(delta, e0_unit) / e0_norm
                        v_planar = np.dot(delta, e1_unit) / e1_unit_norm
                        # Solve bilinear: u*e0_norm + v*dot(e1,e0_unit) +
                        #   uv*dot(c_corner,e0_unit) = dot(delta,e0_unit)
                        # and: u*dot(e0,e1_unit) + v*e1_unit_norm +
                        #   uv*dot(c_corner,e1_unit) = dot(delta,e1_unit)
                        A0, B0, C0_val, D0 = e0_norm, np.dot(e1, e0_unit), np.dot(c_corner, e0_unit), np.dot(delta, e0_unit)
                        A1, B1, C1, D1 = np.dot(e0, e1_unit), e1_unit_norm, np.dot(c_corner, e1_unit), np.dot(delta, e1_unit)
                        a_uv = A0 * C1 - A1 * C0_val
                        b_uv = A0 * B1 - A1 * B0 + D1 * C0_val - D0 * C1
                        c_uv = D1 * B0 - D0 * B1
                        if abs(a_uv) > 1e-15:
                            disc_uv = b_uv * b_uv - 4 * a_uv * c_uv
                            if disc_uv >= 0:
                                u_root = (-b_uv + np.sqrt(disc_uv)) / (2 * a_uv)
                                denom = B1 + u_root * C1
                                if abs(denom) > 1e-15:
                                    v_root = (D1 - u_root * A1) / denom
                                    best_u, best_v = u_root, v_root
                                else:
                                    # Degenerate v-solve → use planar projection
                                    best_u, best_v = u_planar, v_planar
                            else:
                                # No real root → use planar projection
                                best_u, best_v = u_planar, v_planar
                        elif abs(b_uv) > 1e-15:
                            u_root = -c_uv / b_uv
                            denom = B1 + u_root * C1
                            if abs(denom) > 1e-15:
                                v_root = (D1 - u_root * A1) / denom
                                best_u, best_v = u_root, v_root
                            else:
                                best_u, best_v = u_planar, v_planar
                        else:
                            best_u, best_v = u_planar, v_planar
                    else:
                        best_u, best_v = 0.5, 0.5
                else:
                    best_u, best_v = 0.5, 0.5
            else:
                best_u, best_v = 0.5, 0.5
        else:
            best_u, best_v = 0.5, 0.0

    # Apply offset angle rotation
    if offset_angle_deg:
        ang = np.radians(-offset_angle_deg)
        cos_a, sin_a = np.cos(ang), np.sin(ang)
        best_u, best_v = (
            best_u * cos_a - best_v * sin_a,
            best_u * sin_a + best_v * cos_a,
        )

    return [best_u, best_v]
