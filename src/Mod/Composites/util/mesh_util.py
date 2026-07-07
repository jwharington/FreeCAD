# SPDX-License-Identifier: LGPL-2.1-or-copyright
# Copyright 2025 John Wharington jwharington@gmail.com

"""Mesh utility functions for fibre analysis.

Provides barycentric-coordinate helpers used by the fibre length and
orientation analysis tools. Mesh tessellation (shape2Mesh) was removed
when NextDrape stopped requiring mesh input.
"""

import numpy as np
from FreeCAD import Vector


def proj(v, vn):
    return Vector(v.dot(vn) * vn)


def perp(v, vn):
    return Vector(v - proj(v, vn))


def triangle_distance(p, a, b, c):
    return np.sum(
        [
            np.linalg.norm(p - a),
            np.linalg.norm(p - b),
            np.linalg.norm(p - c),
        ]
    )


def eval_lam(lam, tri):
    return lam[0] * tri[0] + lam[1] * tri[1] + lam[2] * tri[2]


def axes_mapped(lam, tri_a, tri_b):
    a0 = eval_lam(lam, tri_a)
    b0 = eval_lam(lam, tri_b)

    def deriv(axis):
        delta = 1.0e-4
        b1 = b0 + delta * axis
        lam1 = calc_lambda_vec(b1, tri_b)
        a1 = eval_lam(lam1, tri_a)
        return Vector((a1 - a0) / delta)

    return [
        deriv(axis)
        for axis in [
            Vector(1, 0, 0),
            Vector(0, 1, 0),
        ]
    ]


def calc_lambda_vec(
    p: Vector,
    tri: list[Vector],
):
    vn = ((tri[1] - tri[0]).cross(tri[2] - tri[0])).normalize()

    a = perp(tri[0], vn)
    b = perp(tri[1], vn)
    c = perp(tri[2], vn)
    po = perp(p, vn)

    # Robust barycentric solve in 3D projected plane coordinates.
    # This avoids relying on global-Z signed areas, which becomes unstable
    # for triangles not aligned with the world XY plane.
    v0 = b - a
    v1 = c - a
    v2 = po - a

    d00 = v0.dot(v0)
    d01 = v0.dot(v1)
    d11 = v1.dot(v1)
    d20 = v2.dot(v0)
    d21 = v2.dot(v1)

    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1.0e-16:
        raise ValueError("zero area triangle")

    lam1 = (d11 * d20 - d01 * d21) / denom
    lam2 = (d00 * d21 - d01 * d20) / denom
    lam0 = 1.0 - lam1 - lam2

    return np.array([lam0, lam1, lam2])
