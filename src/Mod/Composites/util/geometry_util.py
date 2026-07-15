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


def tex_coord_nearest_quad_fallback(point, node_positions, quads, tex_coords):
    """Bilinear tex coord at *point* using the nearest quad (clamped u,v).

    Used by draper backends when no quad strictly contains the projected
    point (common at drape boundaries and quad edges, and after a re-drape
    at a candidate rosette angle). Mirrors the robustness of
    ``get_lcs_at_point`` (nearest-by-centroid) so ``get_tex_coord_at_point``
    never returns ``None`` for points on the draped surface.

    Parameters are numpy arrays / indexable sequences as used by the
    backends: ``node_positions`` (N,3), ``quads`` list of [i0,i1,i2,i3],
    ``tex_coords`` (N,2). Returns ``[u, v]`` or ``None`` if no quad is
    within 5 mm of the surface plane.
    """
    import numpy as np

    cp = np.asarray([float(point[0]), float(point[1]), float(point[2])])
    near_quad = None
    near_dist = float("inf")
    for q in quads:
        i0, i1, i2, i3 = [int(idx) for idx in q]
        c0 = node_positions[i0]
        c1 = node_positions[i1]
        c2 = node_positions[i2]
        c3 = node_positions[i3]
        normal = np.cross(c1 - c0, c3 - c0)
        norm_len = np.linalg.norm(normal)
        if norm_len < 1e-10:
            continue
        normal /= norm_len
        centroid = (c0 + c1 + c2 + c3) / 4.0
        to_point = cp - centroid
        if abs(float(np.dot(to_point, normal))) > 5.0:
            continue
        d = float(np.linalg.norm(to_point))
        if d < near_dist:
            near_dist = d
            near_quad = q
    if near_quad is None:
        return None

    i0, i1, i2, i3 = [int(idx) for idx in near_quad]
    c0 = node_positions[i0]
    c1 = node_positions[i1]
    c2 = node_positions[i2]
    c3 = node_positions[i3]
    centroid = (c0 + c1 + c2 + c3) / 4.0
    normal = np.cross(c1 - c0, c3 - c0)
    normal /= np.linalg.norm(normal)
    to_point = cp - centroid
    proj = cp - normal * float(np.dot(to_point, normal))

    e0 = c1 - c0
    e0_norm = float(np.linalg.norm(e0))
    if e0_norm < 1e-10:
        return None
    e0_unit = e0 / e0_norm
    e1 = c3 - c0
    e1_unit = e1 - np.dot(e1, e0_unit) * e0_unit
    e1_unit_norm = float(np.linalg.norm(e1_unit))
    if e1_unit_norm < 1e-10:
        return None
    e1_unit /= e1_unit_norm

    delta = proj - c0
    u = float(np.clip(np.dot(delta, e0_unit) / e0_norm, 0.0, 1.0))
    v = float(np.clip(np.dot(delta, e1_unit) / e1_unit_norm, 0.0, 1.0))

    tc0 = tex_coords[i0]
    tc1 = tex_coords[i1]
    tc2 = tex_coords[i2]
    tc3 = tex_coords[i3]
    uv = (
        (1 - u) * (1 - v) * tc0
        + u * (1 - v) * tc1
        + u * v * tc2
        + (1 - u) * v * tc3
    )
    return [float(uv[0]), float(uv[1])]
