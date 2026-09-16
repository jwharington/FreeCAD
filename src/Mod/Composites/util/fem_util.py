# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

from typing import List

from ..mechanics.material_properties import (
    is_orthotropic,
    iso_material2dict,
    ortho_material2dict,
)
from ..mechanics.stack_model import merge_single
from ..mechanics.stack_model_type import StackModelType
from ..objects.homogeneous_lamina import HomogeneousLamina
from ..objects.laminate import Laminate

debug = False


def get_layers_ccx(
    laminate: Laminate,
    model_type: StackModelType = StackModelType.Discrete,
):
    if not laminate:
        return []

    layers = laminate.get_layers(model_type=model_type)
    n = len(layers)

    def merge(k, lay):
        if n < 100:
            prefix = f"{k:02d}"
        else:
            prefix = f"{k:03d}"
        return merge_single(prefix, lay)

    return [merge(k, lay) for k, lay in enumerate(layers)]


def format_material_name(name: str, prefix: str = ""):
    if len(name) >= 80:
        raise ValueError(
            f"Name '{name}' invalid, exceeds maximum length 80 chars",
        )
    if "." in name:
        raise ValueError(
            f"Name {name} contains invalid character",
        )
    return f"{prefix}:{name}".upper()


# CalculiX *ELASTIC,TYPE=ANISOTROPIC constant order: the upper triangle of
# the 6x6 stiffness (engineering shear), components 11,22,33,12,13,23 —
# verified against CalculiX's test/aniso.inp and umat.f.
_ANISO_UPPER_TRIANGLE = (
    (0, 0), (0, 1), (1, 1), (0, 2), (1, 2), (2, 2),
    (0, 3), (1, 3), (2, 3), (3, 3),
    (0, 4), (1, 4), (2, 4), (3, 4), (4, 4),
    (0, 5), (1, 5), (2, 5), (3, 5), (4, 5), (5, 5),
)

# shell_model's stiffness tensor orders the shear components
# (11,22,33,23,13,12); CalculiX uses (11,22,33,12,13,23).  Map the former
# to the latter before emitting the constants.
_CCX_FROM_CODE_INDEX = (0, 1, 2, 5, 4, 3)


def _aniso_constants_ccx(stiffness):
    order = _CCX_FROM_CODE_INDEX
    ccx = [
        [float(stiffness[order[i]][order[j]]) for j in range(6)]
        for i in range(6)
    ]
    vals = [ccx[i][j] for i, j in _ANISO_UPPER_TRIANGLE]
    lines = [
        ",".join(f"{v:.12G}" for v in vals[0:8]),
        ",".join(f"{v:.12G}" for v in vals[8:16]),
        ",".join(f"{v:.12G}" for v in vals[16:21]),
    ]
    return "\n".join(lines) + "\n\n"


def write_lamina_material_ccx(
    layer: HomogeneousLamina,
    prefix: str = "",
):
    material_name = format_material_name(layer.description, prefix)
    res = f"*MATERIAL,NAME={material_name}\n"
    stiffness = getattr(layer, "stiffness", None)
    if is_orthotropic(layer.material) and stiffness is not None:
        # A rotated (off-axis) ply is monoclinic: its engineering-constant
        # form drops the normal-shear coupling, so emit the full rotated
        # stiffness.  The section *ORIENTATION* then maps this tensor from
        # the fabric frame to global.
        mat = ortho_material2dict(layer.material)
        res += "*ELASTIC,TYPE=ANISOTROPIC\n"
        res += _aniso_constants_ccx(stiffness)
    elif is_orthotropic(layer.material):
        mat = ortho_material2dict(layer.material)
        res += "*ELASTIC,"
        res += "TYPE=ENGINEERING CONSTANTS\n"
        res += f"{mat['YoungsModulusX']:.12G},"
        res += f"{mat['YoungsModulusY']:.12G},"
        res += f"{mat['YoungsModulusZ']:.12G},"
        res += f"{mat['PoissonRatioXY']:.12G},"
        res += f"{mat['PoissonRatioXZ']:.12G},"
        res += f"{mat['PoissonRatioYZ']:.12G},"
        res += f"{mat['ShearModulusXY']:.12G},"
        res += f"{mat['ShearModulusXZ']:.12G},\n"
        res += f"{mat['ShearModulusYZ']:.12G},"
        res += "293.15\n\n"
    else:
        mat = iso_material2dict(layer.material)
        res += "*ELASTIC,"
        res += "TYPE=ISO\n"
        res += f"{mat['YoungsModulus']:.12G},"
        res += f"{mat['PoissonRatio']:.12G},"
        res += "293.15\n\n"

    res += "*DENSITY\n"
    res += f"{mat['Density']:.12G}\n"
    return res


def write_lamina_materials_ccx(
    layers: List[HomogeneousLamina],
    prefix: str = "",
):
    res = ""
    for la in layers:
        res += write_lamina_material_ccx(la, prefix=prefix)
    return res


def write_shell_section_ccx(
    prefix: str,
    layers: List[HomogeneousLamina],
):
    res = ""
    for layer in layers:
        res += f"{layer.thickness:.13G}"
        material_name = format_material_name(
            layer.description,
            prefix=prefix,
        )
        res += f",,{material_name}\n"
    res += "\n"
    return res


def test_ccx(
    la: Laminate,
    model_type: StackModelType = StackModelType.Discrete,
    prefix: str = "",
):
    res = ""
    layers = get_layers_ccx(la, model_type=model_type)
    res += write_lamina_materials_ccx(
        layers,
        prefix=prefix,
    )
    # this happens for each element and orientation
    res += write_shell_section_ccx(
        prefix=prefix,
        layers=layers,
    )
    if debug:
        print(res)


# composite only used if more than one

# name of the material to be used for this layer (required)
# name of the orientation to be used for this layer (optional)
