# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Reading a written deck, and proving the loads in it are the right ones.

A deck with an element that carries no section solves with zero thickness, and
a batch step that forgot ``OP=NEW`` solves the previous case without saying so.
Both are checked here against small decks written the way the ccx writer
writes them.
"""

import FreeCAD
import Fem
import pytest

from femtools import deckcheck

_DECK = """*Node
1, 0.0, 0.0, 0.0
2, 1.0, 0.0, 0.0
*Element, TYPE=S4, ELSET=Efaces
1, 1, 2, 2, 1
*Elset, ELSET=Eall
1,
*Shell Section, ELSET=Eall
0.500,,
"""


@pytest.fixture
def write(tmp_path):
    def writer(text, name="deck.inp"):
        path = tmp_path / name
        path.write_text(text)
        return str(path)
    return writer


def _line_mesh(points):
    mesh = Fem.FemMesh()
    for node_id, (x, y, z) in enumerate(points, start=1):
        mesh.addNode(x, y, z, node_id)
    return mesh


# --- parsing ----------------------------------------------------------------


def test_parse_inp_collects_elements_elsets_and_sections():
    deck = deckcheck.parse_inp(_DECK)
    assert deck["elements"] == {1: [1, 2, 2, 1]}
    assert deck["elsets"] == {"Efaces": {1}, "Eall": {1}}
    assert deck["section_elsets"] == {"Eall"}
    assert deck["sections"] == [{"elset": "Eall", "material": "",
                                 "layered": False, "plies": [0.5],
                                 "cards": []}]


def test_wrapped_element_lines_are_joined_by_the_type():
    text = ("*Element, TYPE=C3D8, ELSET=Solid\n"
            "1, 1, 2, 3, 4,\n"
            "5, 6, 7, 8\n")
    assert deckcheck.parse_inp(text)["elements"] == {1: [1, 2, 3, 4, 5, 6, 7, 8]}


def test_parse_inp_collects_node_positions_and_solid_sections():
    text = ("*Node\n1, 0.0, 0.0, 0.0\n2, 1.0, 2.0, 3.0\n"
            "*Element, TYPE=C3D4, ELSET=Solid\n1, 1, 2, 2, 2\n"
            "*Solid Section, ELSET=Solid\n")
    deck = deckcheck.parse_inp(text)
    assert deck["nodes"] == {1: (0.0, 0.0, 0.0), 2: (1.0, 2.0, 3.0)}
    assert deck["section_elsets"] == {"Solid"}


def test_owned_by_element_names_every_claimant():
    deck = deckcheck.parse_inp(_DECK)
    assert deckcheck.owned_by_element(deck) == {1: {"Efaces", "Eall"}}


# --- coverage and material checks -------------------------------------------


def test_an_element_without_a_section_is_found():
    text = _DECK.replace("*Shell Section, ELSET=Eall\n0.500,,\n", "")
    problems = deckcheck.coverage_problems(deckcheck.parse_inp(text))
    assert any("carry no section" in problem for problem in problems)


def test_an_element_in_two_sections_is_found():
    text = _DECK + "*Elset, ELSET=Eother\n1,\n*Shell Section, ELSET=Eother\n0.500,,\n"
    problems = deckcheck.coverage_problems(deckcheck.parse_inp(text))
    assert any("sections at once" in problem for problem in problems)


def test_a_deck_with_one_section_per_element_is_clean():
    assert deckcheck.coverage_problems(deckcheck.parse_inp(_DECK)) == []


def test_a_duplicate_material_card_is_found():
    text = ("*Material, NAME=Steel\n*Elastic\n210000.0, 0.3\n"
            "*Material, NAME=Steel\n*Elastic\n210000.0, 0.3\n")
    problems = deckcheck.material_problems(text)
    assert len(problems) == 1
    assert "Steel appears 2 times" in problems[0]


# --- load resultant verification --------------------------------------------


def test_a_single_case_resultant_is_verified(write):
    text = ("*Node\n1, 0, 0, 0\n2, 10, 0, 0\n"
            "*Cload\n1, 3, 100.0\n2, 3, 50.0\n")
    target = {"Fx": 0.0, "Fy": 0.0, "Fz": 150.0,
              "Mx": 0.0, "My": -500.0, "Mz": 0.0}
    deckcheck.verify_loads(write(text), _line_mesh([(0, 0, 0), (10, 0, 0)]),
                           FreeCAD.Vector(0, 0, 0), "", ["lc01"],
                           {"lc01": target})


def test_a_wrong_single_case_resultant_is_refused(write):
    text = "*Node\n1, 0, 0, 0\n*Cload\n1, 3, 100.0\n"
    target = {"Fx": 0.0, "Fy": 0.0, "Fz": 100.0,
              "Mx": 0.0, "My": 0.0, "Mz": 0.0}
    with pytest.raises(RuntimeError, match=r"resultant mismatch"):
        deckcheck.verify_loads(write(text), _line_mesh([(0, 0, 0)]),
                               FreeCAD.Vector(0, 0, 0), "", ["lc01"],
                               {"lc01": dict(target, Fz=999.0)})


def test_a_batch_step_without_op_new_is_refused(write):
    text = ("*Node\n1, 0, 0, 0\n2, 0, 0, 0\n"
            "*Step\n*Cload, OP=NEW\n1, 3, 100.0\n"
            "*Step\n*Cload\n2, 3, 100.0\n")
    target = {"Fx": 0.0, "Fy": 0.0, "Fz": 100.0,
              "Mx": 0.0, "My": 0.0, "Mz": 0.0}
    targets = {"lc01": target, "lc03": target}
    with pytest.raises(RuntimeError, match=r"without OP=NEW"):
        deckcheck.verify_loads(write(text), _line_mesh([(0, 0, 0), (0, 0, 0)]),
                               FreeCAD.Vector(0, 0, 0), "", ["lc01", "lc03"],
                               targets)


def test_a_batch_with_matching_steps_and_op_new_passes(write):
    text = ("*Node\n1, 0, 0, 0\n2, 0, 0, 0\n"
            "*Step\n*Cload, OP=NEW\n1, 3, 100.0\n"
            "*Step\n*Cload, OP=NEW\n2, 3, 50.0\n")
    target = {"Fx": 0.0, "Fy": 0.0, "Fz": 100.0,
              "Mx": 0.0, "My": 0.0, "Mz": 0.0}
    other = dict(target, Fz=50.0)
    deckcheck.verify_loads(write(text), _line_mesh([(0, 0, 0), (0, 0, 0)]),
                           FreeCAD.Vector(0, 0, 0), "", ["lc01", "lc03"],
                           {"lc01": target, "lc03": other})


def test_a_batch_with_a_step_count_mismatch_is_refused(write):
    text = ("*Node\n1, 0, 0, 0\n"
            "*Step\n*Cload, OP=NEW\n1, 3, 100.0\n")
    target = {"Fx": 0.0, "Fy": 0.0, "Fz": 100.0,
              "Mx": 0.0, "My": 0.0, "Mz": 0.0}
    with pytest.raises(RuntimeError, match=r"\*STEP blocks for 2 load cases"):
        deckcheck.verify_loads(write(text), _line_mesh([(0, 0, 0)]),
                               FreeCAD.Vector(0, 0, 0), "", ["lc01", "lc03"],
                               {"lc01": target, "lc03": target})


def test_an_element_is_appended_to_its_elset(write):
    path = write("*Elset, ELSET=Eall\n1,\n*Shell Section, ELSET=Eall\n0.500,,\n")
    deckcheck.append_to_elsets(path, [(2, "Eall", "Eall")])
    with open(path) as handle:
        assert deckcheck.parse_inp(handle.read())["elsets"]["Eall"] == {1, 2}


def test_a_load_on_a_synthetic_node_is_found(write):
    text = ("*Node\n99, 5, 0, 0\n"
            "*Cload\n99, 3, 20.0\n")
    target = {"Fx": 0.0, "Fy": 0.0, "Fz": 20.0,
              "Mx": 0.0, "My": -100.0, "Mz": 0.0}
    deckcheck.verify_loads(write(text), _line_mesh([]),
                           FreeCAD.Vector(0, 0, 0), "", ["lc01"],
                           {"lc01": target})
