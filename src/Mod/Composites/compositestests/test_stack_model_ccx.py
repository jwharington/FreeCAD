# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Every StackModelType must survive the deck-writing round trip.

The workbench's stack-model unit tests (test_mechanics) pin what each model
means at the laminate-representation level, but nothing verified that a
merged stack (SmearedFabric in particular) survives the provider →
write_shell_section path into a deck CalculiX accepts.  The first real
model to walk that leg failed at solve time with ``*ERROR in gen3dnor``
— a deck-content failure, not a solver limit — with no test to catch it.

This module runs the §7.6 QI plate (the smallest deck the ccx round trip
is already known to work on, per test_quasi_iso_fem) once per
StackModelType member, asserting:

- the solve succeeds (a deck CalculiX cannot expand aborts before any
  step, with an empty .sta),
- the deck is self-consistent before any solver opinion: every material
  named on a COMPOSITE layer line has a matching ``*MATERIAL,NAME=`` card,
  and each section's layer thicknesses sum to the laminate thickness (a
  merge that loses material hides here),
- the merged presentation solves to the same physical answer as the
  Discrete export, within the §7.6 cross-validation tolerance — the models
  are presentations of one stack, so their free-edge ux must agree.

One solve per member on the coarse §7.6 mesh; each takes seconds of ccx.
"""

import re
import unittest

import FreeCAD

from Composites.mechanics.stack_model_type import StackModelType

from .test_quasi_iso_fem import (
    QI_CROSS_VALIDATION_TOLERANCE,
    TestQuasiIsoFemCrossValidation,
)

# Composite layer lines carry <thickness>,,<material>[,<orientation>];
# material cards carry *MATERIAL,NAME=<name>.  A homogeneous section names
# its single material in the section header instead.
_LAYER_RE = re.compile(r"^([0-9.eE+-]+),,([^,\n]+)", re.M)
_MATERIAL_RE = re.compile(r"^\*MATERIAL,NAME=([^,\n]+)", re.M)
_MATERIAL_FIELD_RE = re.compile(r"MATERIAL=([^,\n]+)")

# %.13G formatting makes deck thicknesses exact to 13 significant digits;
# anything looser than 1e-6 relative is a lost or duplicated layer.
_THICKNESS_TOLERANCE = 1e-6


def _shell_section_blocks(deck):
    """[[(thickness, material name), ...]] per shell section.

    A COMPOSITE section lists one entry per layer on the lines below it; a
    homogeneous section names one material in the header and lists one
    thickness line.
    """
    blocks = []
    lines = deck.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("*SHELL SECTION"):
            continue
        layers = []
        j = i + 1
        first = lines[j] if j < len(lines) else ""
        if "COMPOSITE" in line:
            while j < len(lines) and lines[j].strip() and not lines[j].startswith("*"):
                match = _LAYER_RE.match(lines[j])
                if match:
                    layers.append((float(match.group(1)), match.group(2)))
                j += 1
        elif first.strip() and not first.startswith("*"):
            material = _MATERIAL_FIELD_RE.search(line)
            layers.append(
                (float(first.split(",")[0]),
                 material.group(1) if material else None)
            )
        blocks.append(layers)
    return blocks


def _deck_faults(deck):
    """Material names the deck references but never defines."""
    defined = set(_MATERIAL_RE.findall(deck))
    referenced = {
        name
        for layers in _shell_section_blocks(deck)
        for _, name in layers
        if name is not None
    }
    return sorted(referenced - defined)


class TestStackModelCcxRoundTrip(TestQuasiIsoFemCrossValidation):
    """Each StackModelType, through the full deck → CalculiX path."""

    save_fcstd = False

    # The §7.6 default mesh is four elements — a degenerate corner where
    # the solver's expansion estimate trips on the merged single-layer
    # presentation (form-identical decks solve at article scale, and at
    # this scale with ≥2 layers).  The round trip is exercised on the same
    # mesh density the §7.6 cross-validation uses for its tolerance
    # comparison, so the fixture reflects the article's meshing regime.
    MESH_MAX_SIZE = 5.0

    def _case(self, stack_model):
        return self._build_and_solve(
            isotropic=False,
            name=f"StackModel{stack_model}",
            stack_model=stack_model,
            mesh_max_size=self.MESH_MAX_SIZE,
        )

    def test_every_stack_model_solves(self):
        """The deck each model produces is accepted by CalculiX."""
        for member in StackModelType:
            self._case(member.name)

    def test_deck_round_trip_consistency(self):
        """Layer materials are defined; layer thicknesses sum to the stack.

        Checked on the deck text itself: a merge that drops a layer or
        emits an undefined material name fails here with the offending
        numbers in the message, not as a gen3dnor abort with an empty
        .sta.
        """
        for member in StackModelType:
            case = self._case(member.name)
            deck = case["solver_input"]
            faults = _deck_faults(deck)
            self.assertFalse(
                faults,
                f"{member.name}: deck references undefined materials "
                f"{faults}",
            )
            blocks = _shell_section_blocks(deck)
            self.assertTrue(
                blocks, f"{member.name}: no shell section in deck"
            )
            self.assertEqual(
                len({len(block) for block in blocks}), 1,
                f"{member.name}: sections disagree on layer count "
                f"{[len(b) for b in blocks]}",
            )
            declared = FreeCAD.Units.Quantity(
                case["laminate"].Thickness
            ).getValueAs("mm")
            sums = [sum(t for t, _ in block) for block in blocks]
            for total in sums:
                self.assertAlmostEqual(
                    total, declared,
                    delta=_THICKNESS_TOLERANCE * abs(declared),
                    msg=(
                        f"{member.name}: deck layer thicknesses sum "
                        f"{total} vs laminate thickness {declared}"
                    ),
                )

    def test_merged_models_match_discrete_response(self):
        """Same physical laminate: every model within §7.6 tolerance.

        The stack models are presentations of one stack, so the solved
        response (mean free-edge ux) must agree with the Discrete export
        within the §7.6 cross-validation tolerance — the same gate the
        QI isotropic presentation is held to.
        """
        reference = self._case(StackModelType.Discrete.name)
        for member in StackModelType:
            if member is StackModelType.Discrete:
                continue
            case = self._case(member.name)
            relative = abs(
                reference["displacement"] - case["displacement"]
            ) / case["displacement"]
            self.assertLessEqual(
                relative,
                QI_CROSS_VALIDATION_TOLERANCE,
                f"{member.name} response differs {relative:.2%} from "
                f"Discrete (§7.6 tolerance "
                f"{QI_CROSS_VALIDATION_TOLERANCE:.0%})",
            )


if __name__ == "__main__":
    unittest.main()
