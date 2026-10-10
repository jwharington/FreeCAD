# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Mass from the deck's own *SHELL SECTION plies and *DENSITY cards.

The number has to be the one ccx would use, so the arithmetic is pinned against
a hand-computed product: area times ``Σ(ρ·t)`` in mm and Mg.  The member areas
and the member-to-section mapping are passed in here, as a caller would, rather
than reached for in a document.
"""

import re

import pytest

from femtools import modelmass

_STEEL = 7.85e-09  # Mg/mm³
_CORE = 5.0e-11

_DECK = """*Material, NAME=Steel:00: LAMINA
*Density
7.85E-09,
*Material, NAME=Core:00: LAMINA
*Density
5.0E-11,
*Elset, ELSET=MaterialPanel_Section_1
1,
*Shell Section, ELSET=MaterialPanel_Section_1, COMPOSITE
1.000,,Steel:00: LAMINA
2.000,,Core:00: LAMINA
"""

_PLAIN = """*Material, NAME=Steel
*Density
7.85E-09,
*Elset, ELSET=MaterialPanel_Section
1,
*Shell Section, ELSET=MaterialPanel_Section, MATERIAL=Steel
1.000,,
"""


_SECTION = re.compile(r"^Material(.+_Section)(?:_\d+)?$")


def _section_of(elset):
    match = _SECTION.match(elset)
    return match.group(1) if match else None


def test_densities_come_from_the_decks_own_cards():
    assert modelmass.densities_by_card(_DECK) == {
        "Steel:00: LAMINA": _STEEL, "Core:00: LAMINA": _CORE}


def test_a_layered_section_is_a_stack_of_rho_and_thickness():
    stacks = modelmass.stacks_by_section(_DECK, _section_of)
    assert stacks == {"Panel_Section": [(_STEEL, 1.0), (_CORE, 2.0)]}


def test_a_plain_section_is_one_layer():
    stacks = modelmass.stacks_by_section(_PLAIN, _section_of)
    assert stacks == {"Panel_Section": [(_STEEL, 1.0)]}


def test_a_ply_without_a_density_card_is_refused():
    text = _DECK.replace(
        "*Material, NAME=Steel:00: LAMINA\n*Density\n7.85E-09,\n", "")
    with pytest.raises(RuntimeError, match=r"no \*DENSITY card"):
        modelmass.stacks_by_section(text, _section_of)


def test_two_stacks_for_one_section_are_refused():
    text = _PLAIN + ("*Elset, ELSET=MaterialPanel_Section_2\n2,\n"
                     "*Shell Section, ELSET=MaterialPanel_Section_2, MATERIAL=Steel\n"
                     "2.000,,\n")
    with pytest.raises(RuntimeError, match=r"two different ply stacks"):
        modelmass.stacks_by_section(text, _section_of)


def test_mass_is_area_times_the_areal_density():
    stacks = modelmass.stacks_by_section(_DECK, _section_of)
    by_member = modelmass.masses({"Skin": 1000.0}, {"Skin": "Panel_Section"},
                                 stacks)
    # 1000 mm² × (7.85e-9·1 + 5e-11·2) Mg/mm² = 7.95e-3 g → ×1e6
    assert by_member["Skin"]["mass_g"] == pytest.approx(7.95)
    assert by_member["Skin"]["thickness"] == pytest.approx(3.0)


def test_a_member_no_section_owns_is_refused():
    stacks = modelmass.stacks_by_section(_DECK, _section_of)
    with pytest.raises(RuntimeError, match=r"no section references it"):
        modelmass.masses({"Skin": 1000.0, "Spare": 1.0},
                         {"Skin": "Panel_Section"}, stacks)


def test_a_section_the_deck_does_not_write_is_refused():
    with pytest.raises(RuntimeError, match=r"the deck does not write"):
        modelmass.masses({"Skin": 1000.0}, {"Skin": "Panel_Section"}, {})


def test_layups_and_summary_agree_with_the_mass():
    stacks = modelmass.stacks_by_section(_DECK, _section_of)
    blocks_by_section = {"Panel_Section": {"layered": True, "plies": [1.0, 2.0],
                                           "cards": ["Steel:00: LAMINA",
                                                     "Core:00: LAMINA"],
                                           "material": ""}}
    layup_table = modelmass.layups({"Skin": "Panel_Section"},
                                   blocks_by_section, "deck.inp")
    assert layup_table["Skin"]["total_mm"] == pytest.approx(3.0)
    assert layup_table["Skin"]["plies"][1] == [2.0, "Core:00: LAMINA"]
    by_member = modelmass.masses({"Skin": 1000.0}, {"Skin": "Panel_Section"},
                                 stacks)
    summary = modelmass.summarize(by_member, layup_table)
    assert summary["total_g"] == pytest.approx(7.95)
    assert summary["by_laminate"] == {"Panel": pytest.approx(7.95)}
