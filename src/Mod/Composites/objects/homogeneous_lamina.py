# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

from dataclasses import dataclass, field

from ..mechanics.material_properties import (
    is_orthotropic,
)
from ..util.geometry_util import (
    format_orientation,
)
from .ply import Ply


@dataclass
class HomogeneousLamina(Ply):
    # e.g. core foam, aluminium, etc, or merged
    material: dict = field(default_factory=dict)
    orientation_display: float = 0
    # residuals of the quasi-isotropic validation that produced this layer
    # (empty for non-QI merges)
    qi_residuals: dict = field(default_factory=dict)
    # Full 6x6 stiffness in the layer frame for a rotated (off-axis)
    # orthotropic ply.  The engineering-constant form cannot carry the
    # normal-shear coupling of a rotated ply, so the FEM writer needs the
    # tensor itself (np.ndarray); None for isotropic / unrotated layers.
    stiffness: object = None

    @property
    def description(self) -> str:
        desc = self.material["Name"]
        if is_orthotropic(self.material):
            return desc + format_orientation(self.orientation)
        else:
            return desc

    def get_product(self):
        return [(f"{self.description} {self.thickness}", 0)]

    def get_fibres(self):
        return None
