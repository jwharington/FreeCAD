# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com


from typing import List

import numpy as np

from ..objects.homogeneous_lamina import HomogeneousLamina
from ..objects.lamina import Lamina
from ..util.geometry_util import normalise_orientation
from .material_properties import (
    common_material2dict,
    material_from_dict,
)
from .shell_model import (
    material_rotate,
    material_shell_properties,
    stiffness_matrix_to_engineering_properties,
)

# QI balance tolerances (PRD quasi_isotropic_laminate.md §4.2): the exact
# tier enforces to round-off; the approximate tier admits a coarse
# residual budget. Widening either requires explicit user confirmation.
TOL_QUASI_ISOTROPIC = 1e-6
BUDGET_APPROXIMATE_QUASI_ISOTROPIC = 0.05


class QuasiIsotropicError(ValueError):
    """A stack declared isotropic-presenting failed its balance validation."""


_MEMBRANE_INDICES = (0, 1, 5)
_QI_HINTS = {
    "A11-A22": "ply balance (equal counts at 0 and 90 degrees?)",
    "A16": "angle set not evenly spaced?",
    "A26": "angle set not evenly spaced?",
    "A66": "shear coupling balance?",
    "B": "stack not symmetric?",
}


def quasi_isotropic_residuals(A: np.ndarray, B: np.ndarray) -> dict:
    """Scale-relative quasi-isotropy residuals (magnitude only).

    A is the merged CLT extensional matrix, B the coupling matrix; every
    residual is normalised by A11 (PRD quasi_isotropic_laminate.md §4.2).
    """
    A11 = A[0, 0]
    return {
        "A11-A22": abs(A[0, 0] - A[1, 1]) / A11,
        "A16": abs(A[0, 2]) / A11,
        "A26": abs(A[1, 2]) / A11,
        "A66": abs(A[2, 2] - (A[0, 0] - A[0, 1]) / 2) / A11,
        "B": float(np.max(np.abs(B))) / A11,
    }


def validate_quasi_isotropic(
    A: np.ndarray,
    B: np.ndarray,
    tol: float = TOL_QUASI_ISOTROPIC,
    budget: float = BUDGET_APPROXIMATE_QUASI_ISOTROPIC,
    approximate: bool = False,
    check_symmetry: bool = True,
) -> dict:
    """Validate a merged stack as quasi-isotropic; raise on failure.

    Returns the residual dict (quasi_isotropic_residuals) so callers can
    record the approximate tier's deviation. The exact tier enforces
    `tol`; the approximate tier (declared, D1) enforces `budget`.
    `check_symmetry` drops the B gate for derived combined records
    (D8): their asymmetric literal concat is physical — isotropy of
    presentation is the membrane (A) property there.
    """
    residuals = quasi_isotropic_residuals(A, B)
    if not check_symmetry:
        del residuals["B"]
    threshold = budget if approximate else tol
    offenders = [
        (name, residual)
        for name, residual in residuals.items()
        if residual > threshold
    ]
    if offenders:
        raise QuasiIsotropicError(
            "not quasi-isotropic: "
            + "; ".join(
                f"|{name}|/A11 = {residual:.3e} exceeds {threshold:g} "
                f"({_QI_HINTS[name]})"
                for name, residual in offenders
            )
        )
    return residuals


# Refer:
# - https://nilspv.folk.ntnu.no/TMM4175/computational-procedures.html
# - lamprop
# - Barbero


def calc_z(layers: List[Lamina]):
    thicknesses = [lay.thickness for lay in layers]
    total_thickness = sum(thicknesses)

    zbar = []
    z0 = -total_thickness / 2
    for lay in layers:
        t = lay.thickness
        zbar.append(z0 + t / 2)
        z0 += t
    return zbar, total_thickness


def layer_density(layer: Lamina):
    mat = common_material2dict(layer.material)
    density = mat["Density"]
    assert density, f"density must be positive {density}"
    return density


def merge_clt(
    prefix: str,
    layers: List[Lamina],
    sandwich: bool = False,
) -> HomogeneousLamina:
    zbar, total_thickness = calc_z(layers)

    # initialise accumulators
    A = np.zeros((3, 3))
    B = np.zeros((3, 3))
    D = np.zeros((3, 3))
    H = np.zeros((2, 2))
    C = np.zeros((6, 6))
    density = 0

    def accumulate_ABD(t_k, zbar_k, Qbar_k, is_core: bool):
        # Barbero eq 3.9
        s = zbar_k**2 + t_k**2 / 12

        def ind(i):
            if i == 2:
                return 5
            return i

        coords = [0, 1, 2]
        for i in coords:
            for j in coords:
                Qbar_t = Qbar_k[ind(i), ind(j)] * t_k

                A[i, j] += Qbar_t
                B[i, j] += Qbar_t * zbar_k
                D[i, j] += Qbar_t * s

    def accumulate_H(t_k, zbar_k, Qbar_k, is_core: bool):
        s = zbar_k**2 + t_k**2 / 12
        if sandwich:
            if is_core:
                h = t_k
            else:
                h = 0
        else:
            h = (5.0 / 4) * t_k * (1.0 - 4 / total_thickness**2 * s)

        def ind(i):
            return i - 3

        coords = [3, 4]
        for i in coords:
            for j in coords:
                # TODO: Qbarstar
                H[ind(i), ind(j)] += Qbar_k[i, j] * h

    # iterate through layers
    for k, (zbar_k, lay) in enumerate(zip(zbar, layers)):
        t_k = lay.thickness
        p_k = t_k / total_thickness

        C_k, Qbar_k = material_shell_properties(
            lay.material,
            np.radians(lay.orientation),
        )
        C += p_k * C_k

        density += p_k * layer_density(lay)

        is_core = lay.core and sandwich

        accumulate_ABD(t_k, zbar_k, Qbar_k, is_core)
        accumulate_H(t_k, zbar_k, Qbar_k, is_core)

    # assemble full matrix
    ABD = np.block(
        [
            [A, B],
            [B, D],
        ]
    )

    def delete_row_col(row: int, col: int):
        a1 = np.delete(ABD, row, axis=0)
        return np.delete(a1, col, axis=1)

    def det_red(i, j):
        return np.linalg.det(delete_row_col(i, j))

    mat = {}
    det_ABD = np.linalg.det(ABD)

    dets = [det_red(i, i) for i in range(3)]
    mat["YoungsModulusX"] = det_ABD / (dets[0] * total_thickness)
    mat["YoungsModulusY"] = det_ABD / (dets[1] * total_thickness)
    mat["ShearModulusXY"] = det_ABD / (dets[2] * total_thickness)
    mat["PoissonRatioXY"] = det_red(0, 1) / dets[0]  # negative?
    mat["PoissonRatioYX"] = det_red(1, 0) / dets[1]  # negative?
    mat["ShearModulusYZ"] = H[0, 0] / total_thickness
    mat["ShearModulusXZ"] = H[1, 1] / total_thickness

    mat_thin = stiffness_matrix_to_engineering_properties(C)

    mat["Density"] = density
    mat["YoungsModulusZ"] = mat_thin["YoungsModulusZ"]
    mat["PoissonRatioXZ"] = mat_thin["PoissonRatioXZ"]  # ?
    mat["PoissonRatioYZ"] = mat_thin["PoissonRatioYZ"]  # ?

    del mat["PoissonRatioYX"]

    material = material_from_dict(mat, orthotropic=True)
    material["Name"] = prefix
    return HomogeneousLamina(
        material=material,
        thickness=total_thickness,
        orientation=0,
        orientation_display=0,
    )


def merge_clt_isotropic(
    prefix: str,
    layers: List[Lamina],
    approximate: bool = False,
    check_symmetry: bool = True,
) -> HomogeneousLamina:
    """Collapse a quasi-isotropic stack into one equivalent isotropic layer.

    Validates the merged A/B matrices (PRD quasi_isotropic_laminate.md
    §4.2), then derives the equivalent constants from A (§4.1/D3):
    nu = A12/A11, E = (A11-A12)(A11+A12)/(A11 h), G = (A11-A12)/(2 h).
    Through-thickness properties are retained from the C/H path so the
    layer stays usable for solid-element FEM.
    """
    for lay in layers:
        if lay.core:
            raise QuasiIsotropicError(
                "core plies are excluded from isotropic presentation "
                "(sandwich substitution is a separate decision, PRD OQ-7)"
            )

    zbar, total_thickness = calc_z(layers)

    # initialise accumulators
    A = np.zeros((3, 3))
    B = np.zeros((3, 3))
    C = np.zeros((6, 6))
    H = np.zeros((2, 2))
    density = 0

    for zbar_k, lay in zip(zbar, layers):
        t_k = lay.thickness
        p_k = t_k / total_thickness
        C_k, Qbar_k = material_shell_properties(
            lay.material,
            np.radians(lay.orientation),
        )
        Qbar_membrane = Qbar_k[np.ix_(_MEMBRANE_INDICES, _MEMBRANE_INDICES)]
        A += Qbar_membrane * t_k
        B += Qbar_membrane * t_k * zbar_k
        s = zbar_k**2 + t_k**2 / 12
        h_k = (5.0 / 4) * t_k * (1.0 - 4 / total_thickness**2 * s)
        H += Qbar_k[3:5, 3:5] * h_k
        C += p_k * C_k
        density += p_k * layer_density(lay)

    residuals = validate_quasi_isotropic(
        A,
        B,
        approximate=approximate,
        check_symmetry=check_symmetry,
    )

    A11 = A[0, 0]
    A12 = A[0, 1]
    nu = A12 / A11
    E = (A11 - A12) * (A11 + A12) / (A11 * total_thickness)
    G = (A11 - A12) / (2 * total_thickness)

    mat = {
        "YoungsModulus": E,
        "PoissonRatio": nu,
        "Density": density,
    }
    material = material_from_dict(mat, orthotropic=False)
    material["ShearModulus"] = f"{G} MPa"
    mat_thin = stiffness_matrix_to_engineering_properties(C)
    material["YoungsModulusZ"] = f"{mat_thin['YoungsModulusZ']} MPa"
    material["PoissonRatioXZ"] = str(mat_thin["PoissonRatioXZ"])
    material["PoissonRatioYZ"] = str(mat_thin["PoissonRatioYZ"])
    material["ShearModulusXZ"] = f"{H[1, 1] / total_thickness} MPa"
    material["ShearModulusYZ"] = f"{H[0, 0] / total_thickness} MPa"

    angles = "/".join(
        str(int(round(normalise_orientation(lay.orientation)))) for lay in layers
    )
    material["Name"] = f"{prefix} QI [{angles}]"
    return HomogeneousLamina(
        material=material,
        thickness=total_thickness,
        orientation=0,
        orientation_display=0,
        qi_residuals=residuals,
    )


def merge_single(
    prefix: str,
    layer: Lamina,
) -> HomogeneousLamina:
    # if not hasattr(layer, "orientation") or (layer.orientation == 0):
    #     return layer

    material = material_rotate(
        layer.material,
        np.radians(layer.orientation),
    )
    material["Name"] = prefix + ": " + layer.description
    return HomogeneousLamina(
        material=material,
        thickness=layer.thickness,
        orientation=0,
        orientation_display=layer.orientation,
    )
