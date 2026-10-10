# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Deck geography: which node sits where, and which laminate owns it.

The naming that turns a section's elset into a laminate is the caller's, so
these tests pass one in, exactly as a workbench would.  The lookup caches are
explicit: a deck edited between calls must be seen when no cache is held.
"""

import re

import pytest

from femtools import decknodes

_DECK = """*Node
1, 0.0, 0.0, 0.0
2, 1.0, 0.0, 0.0
3, 0.0, 1.0, 0.0
*Element, TYPE=S3, ELSET=MaterialSkin_Section_1
1, 1, 2, 3
*Shell Section, ELSET=MaterialSkin_Section_1
1.000,,
"""

_SECTION = re.compile(r"^Material(.+_Section)(?:_\d+)?$")


def section_of(elset):
    match = _SECTION.match(elset)
    return match.group(1) if match else None


@pytest.fixture
def deck(tmp_path):
    path = tmp_path / "deck.inp"
    path.write_text(_DECK)
    return str(path)


def test_zones_and_coordinates_come_from_the_deck(deck):
    zones, coords = decknodes.zones_by_node(deck, section_of)
    assert zones == {1: "Skin_Section", 2: "Skin_Section", 3: "Skin_Section"}
    assert coords[2] == (1.0, 0.0, 0.0)


def test_a_position_resolves_to_its_node_and_zone(deck):
    index = decknodes.position_index(deck, section_of)
    assert index[decknodes.position_key((0.0, 0.0, 0.0))] == ([1], "Skin_Section")


def test_node_at_a_position(deck):
    assert decknodes.node_at((1.0, 0.0, 0.0), deck, section_of) == (
        [2], "Skin_Section")


def test_zone_of_a_node_that_is_not_there_is_none(deck):
    assert decknodes.zone_of_node(1, deck, section_of) == "Skin_Section"
    assert decknodes.zone_of_node(99, deck, section_of) is None


def test_nearest_part_names_the_laminate_of_the_nearest_node(deck):
    assert decknodes.nearest_part((0.1, 0.0, 0.0), deck, section_of) == (
        [1], "Skin_Section")


def test_a_missing_deck_gives_no_geography(tmp_path):
    zones, coords = decknodes.zones_by_node(str(tmp_path / "absent.inp"),
                                            section_of)
    assert zones == {} and coords == {}


def test_a_deck_edited_between_calls_is_seen(tmp_path):
    path = tmp_path / "deck.inp"
    path.write_text(_DECK)
    assert decknodes.zones_by_node(str(path), section_of)[1].keys() == {1, 2, 3}
    path.write_text(_DECK + "*Node\n4, 5.0, 5.0, 5.0\n")
    # No cache is held, so the second call reads the deck again rather than
    # answering from the first call's geography.
    assert decknodes.zones_by_node(str(path), section_of)[1].keys() == {1, 2, 3, 4}
