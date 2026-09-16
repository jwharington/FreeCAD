# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Ply-rotation verification: code transformations vs standard analytic.

Diagnostics for the draped-export cross-validation gap (§7.6 of
docs/quasi_isotropic_laminate.md).  Compares, for a UD ply rotated to
45 deg:

- ``Q66'(45)`` from ``material_shell_properties`` — the rotation the CLT
  merge (``merge_clt`` / ``merge_clt_isotropic``) accumulates,
- ``G12'(45)`` from ``material_rotate`` — the rotation the FEM export
  (``write_lamina_material_ccx``) ships as engineering constants,

against the standard analytic transformation
``Q66'(θ) = c²s²(Q11 + Q22 − 2·Q12) + (c² − s²)²·Q66``, and reports the
merged A66 of a QI angle set under the code rotation vs analytic.

Run headless:
    FreeCADCmd -c "exec(open('src/Mod/Composites/compositestests/inspect_rotation_check.py').read())"
"""

import math
from pathlib import Path

import numpy as np

from Composites.mechanics.shell_model import (  # noqa: E402
    material_rotate,
    material_shell_properties,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

CARBON_UD = {
    "Name": "Carbon",
    "Density": "1750.0 kg/m^3",
    "PoissonRatioXY": "0.27",
    "PoissonRatioXZ": "0.27",
    "PoissonRatioYZ": "0.45",
    "ShearModulusXY": "5000 MPa",
    "ShearModulusXZ": "5000 MPa",
    "ShearModulusYZ": "3500 MPa",
    "YoungsModulusX": "135 GPa",
    "YoungsModulusY": "9.5 GPa",
    "YoungsModulusZ": "9.5 GPa",
}


def analytic_q16(theta_rad, q11, q22, q12, q66):
    """Standard engineering-notation Q16', computed via the pure tensor
    route (independent of shell_model's transformation code): rotate the
    3x3 tensor stiffness with the tensor rotation matrix, then read the
    engineering coupling constant off the rotated tensor."""
    c = math.cos(theta_rad)
    s = math.sin(theta_rad)
    qt = np.array([[q11, q12, 0.0], [q12, q22, 0.0], [0.0, 0.0, 2.0 * q66]])
    # tensor shear convention: eps12 (not gamma); rotation is orthogonal
    T = np.array([[c * c, s * s, -c * s],
                  [s * s, c * c, c * s],
                  [2 * c * s, -2 * c * s, c * c - s * s]])
    qr = T @ qt @ T.T
    # engineering coupling: sigma1 per gamma12 = sigma1 per 2*eps12(t)
    # = Q'_tensor[0,2]  (the gamma12' coefficient of sigma1')
    return qr[0][2]


def analytic_q26(theta_rad, q11, q22, q12, q66):
    c = math.cos(theta_rad)
    s = math.sin(theta_rad)
    qt = np.array([[q11, q12, 0.0], [q12, q22, 0.0], [0.0, 0.0, 2.0 * q66]])
    T = np.array([[c * c, s * s, -c * s],
                  [s * s, c * c, c * s],
                  [2 * c * s, -2 * c * s, c * c - s * s]])
    qr = T @ qt @ T.T
    return qr[1][2]


def analytic_q66(theta_rad, q11, q22, q12, q66):
    c = math.cos(theta_rad)
    s = math.sin(theta_rad)
    return c * c * s * s * (q11 + q22 - 2 * q12) + (c * c - s * s) ** 2 * q66


def main():
    theta = math.radians(45.0)

    # Merge path: rotated reduced stiffness, Q66' at row/col 5.
    _, qbar = material_shell_properties(CARBON_UD, theta)
    q66_merge = float(qbar[5][5])

    # Export path: material_rotate returns engineering constants.
    rotated = material_rotate(CARBON_UD, theta)
    g12_export = float(str(rotated["ShearModulusXY"]).split()[0])

    # Independent Q11/Q22/Q12 for the analytic formula: the unrotated
    # reduced stiffness from the same code path at theta = 0.
    _, qbar0 = material_shell_properties(CARBON_UD, 0.0)
    q11, q22, q12, q66 = (float(qbar0[i][j])
                          for i, j in ((0, 0), (1, 1), (0, 1), (5, 5)))

    expected = analytic_q66(theta, q11, q22, q12, q66)

    print(f"Q11={q11:.1f} Q22={q22:.1f} Q12={q12:.1f} Q66={q66:.1f} MPa")
    print(f"Q66'(45)  analytic standard : {expected:9.1f} MPa")
    print(f"Q66'(45)  merge path        : {q66_merge:9.1f} MPa")
    print(f"G12'(45)  export (mat_rot)  : {g12_export:9.1f} MPa")

    # Merged A66 of the QI angle set {0, 45, -45, 90} under the code
    # rotation vs the analytic set mean.
    angles = (0.0, theta, -theta, math.pi / 2)
    a66_merge = sum(
        float(material_shell_properties(CARBON_UD, a)[1][5][5]) for a in angles
    ) / len(angles)
    a66_analytic = sum(
        analytic_q66(a, q11, q22, q12, q66) for a in angles
    ) / len(angles)
    print(f"A66(QI set) code vs analytic: {a66_merge:9.1f} vs {a66_analytic:9.1f} MPa")

    # Coupling entries: odd in theta — the sign decided by the transform
    # convention, checked against the independent tensor route.
    q16_code = float(qbar[0][5])
    q26_code = float(qbar[1][5])
    q16_analytic = analytic_q16(theta, q11, q22, q12, q66)
    q26_analytic = analytic_q26(theta, q11, q22, q12, q66)
    print(f"Q16'(45)  code vs tensor route: {q16_code:9.1f} vs {q16_analytic:9.1f} MPa")
    print(f"Q26'(45)  code vs tensor route: {q26_code:9.1f} vs {q26_analytic:9.1f} MPa")


main()
