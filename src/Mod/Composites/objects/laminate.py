# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

from dataclasses import dataclass, field
from typing import List

from ..mechanics.stack_expansion import calc_stack_model
from ..mechanics.stack_model import QuasiIsotropicError, merge_clt_isotropic
from ..mechanics.stack_model_type import StackModelType
from ..util.geometry_util import expand_symmetry
from .lamina import Lamina
from .symmetry_type import SymmetryType


@dataclass
class Laminate(Lamina):
    name: str = "Laminate"
    layers: List[Lamina] = field(default_factory=list)
    symmetry: SymmetryType = SymmetryType.Assymmetric
    # isotropic presentation (PRD quasi_isotropic_laminate.md D1): declared
    # then verified; approximate tier records its residuals in qi_residuals
    isotropic_equivalent: bool = False
    approximate_isotropic_equivalent: bool = False
    qi_residuals: dict = field(default_factory=dict)

    def get_layers(
        self,
        model_type: StackModelType = StackModelType.Discrete,
    ):
        if self.isotropic_equivalent and self.approximate_isotropic_equivalent:
            raise QuasiIsotropicError(
                "IsotropicEquivalent and ApproximateIsotropicEquivalent "
                "are mutually exclusive declarations"
            )
        if self.isotropic_equivalent or self.approximate_isotropic_equivalent:
            if any(isinstance(lay, Laminate) for lay in self.layers):
                raise QuasiIsotropicError(
                    "nested laminates are rejected in isotropic presentation "
                    "(phase 1)"
                )
        layers = [lay.get_layers(model_type) for lay in self.layers]
        expanded_layers = expand_symmetry(layers, self.symmetry)
        if self.isotropic_equivalent or self.approximate_isotropic_equivalent:
            model = self._merge_isotropic(expanded_layers)
        else:
            prefix = StackModelType.merged_name(model_type)
            model = calc_stack_model(
                prefix,
                model_type,
                expanded_layers,
            )
        self.thickness = sum([layer.thickness for layer in model])
        return model

    def _flatten_layers(self, layers) -> List[Lamina]:
        for lay in layers:
            if isinstance(lay, list):
                yield from self._flatten_layers(lay)
            else:
                yield lay

    def _merge_isotropic(self, expanded_layers) -> List[Lamina]:
        merged = merge_clt_isotropic(
            StackModelType.merged_name(StackModelType.Smeared),
            list(self._flatten_layers(expanded_layers)),
            approximate=(
                self.approximate_isotropic_equivalent
                and not self.isotropic_equivalent
            ),
        )
        self.qi_residuals = merged.qi_residuals
        return [merged]

    def get_product(self):
        res = []
        expanded_layers = expand_symmetry(self.layers, self.symmetry)
        for lay in expanded_layers:
            if product := lay.get_product():
                res.extend(product)
        return res

    def get_fibres(self):
        res = []
        expanded_layers = expand_symmetry(self.layers, self.symmetry)
        for lay in expanded_layers:
            if product := lay.get_fibres():
                res.extend(product)
        return res
