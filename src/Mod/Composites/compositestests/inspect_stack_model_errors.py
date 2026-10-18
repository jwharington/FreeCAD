# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""A/B/D error of each merged stack presentation against the Discrete stack.

Measures what a StackModelType actually costs: the presented section is
turned back into laminate matrices and compared with the ply-by-ply
reference.  This is the evidence behind docs/plan-stack-model-grouped.md
and the recorded numbers in test_mechanics.TestSmearedGroups.

The presentation model is the one the solver sees.  Each layer of the
presentation contributes its plane-stress stiffness at its own z, so

    A = sum Q_k t_k            B = sum Q_k t_k z_k
    D = sum Q_k (z_k^2 t_k + t_k^3 / 12)          (Barbero eq 3.9)

A merged layer carries its thickness-averaged 6x6 as ``layer.stiffness``
(the tensor the deck exports as TYPE=ANISOTROPIC), so its Q is the
plane-stress reduction of that; a discrete ply uses the reduced stiffness
of its rotated material.  The ``ctrl`` row is a self-check: with one ply
per band the merge must reproduce Discrete exactly.

Run from the FreeCAD source root (the exec form has to supply __file__,
which the sys.path bootstrap below relies on):

    FreeCADCmd -c "p='src/Mod/Composites/compositestests/inspect_stack_model_errors.py'; \
        exec(compile(open(p).read(), p, 'exec'), {'__file__': p, '__name__': '__main__'})"
"""

import math
import os
import sys

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import numpy as np

# objects before mechanics: the object modules import the mechanics ones,
# so entering from the mechanics side is a circular import.
import Composites  # noqa: E402, F401
import Composites.objects  # noqa: E402, F401

from Composites.mechanics.stack_expansion import calc_stack_model  # noqa: E402
from Composites.mechanics.stack_model import calc_z  # noqa: E402
from Composites.mechanics.stack_model_type import StackModelType  # noqa: E402
from Composites.mechanics.shell_model import (  # noqa: E402
    material_shell_properties,
)
from Composites.objects.homogeneous_lamina import HomogeneousLamina  # noqa: E402

GLASS = {
    "Name": "Glass",
    "Density": "2580.0 kg/m^3",
    "PoissonRatioXY": "0.28",
    "PoissonRatioXZ": "0.28",
    "PoissonRatioYZ": "0.50",
    "ShearModulusXY": "4500 MPa",
    "ShearModulusXZ": "4500 MPa",
    "ShearModulusYZ": "3500 MPa",
    "YoungsModulusX": "130 GPa",
    "YoungsModulusY": "10 GPa",
    "YoungsModulusZ": "10 GPa",
}

PLY_THICKNESS = 0.141

_MEMBRANE = (0, 1, 5)
_OUT_OF_PLANE = (2, 3, 4)


def ply(angle, thickness=PLY_THICKNESS, core=False):
    layer = HomogeneousLamina(
        material=GLASS,
        thickness=thickness,
        orientation=angle,
        orientation_display=angle,
    )
    layer.core = core
    return layer


def plane_stress_Q(stiffness):
    """Plane-stress reduction of a 6x6 stiffness.

    The code's ordering is (11, 22, 33, 23, 13, 12), so the out-of-plane
    block a shell eliminates is indices 2, 3, 4.
    """
    membrane = stiffness[np.ix_(_MEMBRANE, _MEMBRANE)]
    out = stiffness[np.ix_(_OUT_OF_PLANE, _OUT_OF_PLANE)]
    cross = stiffness[np.ix_(_MEMBRANE, _OUT_OF_PLANE)]
    return membrane - cross @ np.linalg.solve(out, cross.T)


def presentation_ABD(layers):
    zbar, _ = calc_z(layers)
    A = np.zeros((3, 3))
    B = np.zeros((3, 3))
    D = np.zeros((3, 3))
    for z, layer in zip(zbar, layers):
        if layer.stiffness is not None:
            Q = plane_stress_Q(layer.stiffness)
        else:
            _, Qbar = material_shell_properties(
                layer.material, math.radians(layer.orientation)
            )
            Q = Qbar[np.ix_(_MEMBRANE, _MEMBRANE)]
        t = layer.thickness
        A += Q * t
        B += Q * t * z
        D += Q * (z**2 * t + t**3 / 12)
    return A, B, D


def model_ABD(nested_layers, model_type):
    return presentation_ABD(calc_stack_model("", model_type, nested_layers))


def relative_errors(nested_layers, model_type):
    A_d, B_d, D_d = model_ABD(nested_layers, StackModelType.Discrete)
    A, B, D = model_ABD(nested_layers, model_type)
    return {
        "A": np.linalg.norm(A - A_d) / np.linalg.norm(A_d),
        "B": np.linalg.norm(B - B_d) / np.linalg.norm(A_d),
        "D": np.linalg.norm(D - D_d) / np.linalg.norm(D_d),
        "D11": abs(D[0, 0] - D_d[0, 0]) / D_d[0, 0],
        "layers": len(calc_stack_model("", model_type, nested_layers)),
    }


def _repeating(blocks):
    half = [0, 45, -45, 90] * blocks
    return [ply(angle) for angle in half + half[::-1]]


def stacks():
    return {
        "ctrl4 (4x0deg)": [[ply(0) for _ in range(4)]],
        "qi8 [0/45/-45/90]s": [
            [ply(a) for a in [0, 45, -45, 90] * 1 + [90, -45, 45, 0]]
        ],
        "p48 repeating": [_repeating(6)],
        "p49 +0 mid": [
            [
                ply(a)
                for a in [0, 45, -45, 90] * 6 + [0] + ([0, 45, -45, 90] * 6)[::-1]
            ]
        ],
        # strong through-thickness stiffness gradient: stiff 0 deg skins,
        # soft 90 deg core plies
        "gradient [0x4/90x4]s": [
            [
                ply(a)
                for a in [0] * 4 + [90] * 4 + [90] * 4 + [0] * 4
            ]
        ],
    }


def main():
    models = (
        StackModelType.SmearedGroups,
        StackModelType.Smeared,
        StackModelType.SmearedCore,
    )
    header = f"{'stack':24s} {'model':14s} {'n':>2s} " + " ".join(
        f"{k:>9s}" for k in ("A", "B", "D", "D11")
    )
    print(header)
    print("-" * len(header))
    for name, layers in stacks().items():
        for model in models:
            try:
                err = relative_errors(layers, model)
            except Exception as exc:  # a model may refuse this stack
                print(f"{name:24s} {model.name:14s}  {exc}")
                continue
            print(
                f"{name:24s} {model.name:14s} {err['layers']:>2d} "
                + " ".join(
                    f"{err[k]:>9.2e}" for k in ("A", "B", "D", "D11")
                )
            )
        print()


if __name__ == "__main__":
    main()
