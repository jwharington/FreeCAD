# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Mass from the deck's own *SHELL SECTION plies and *DENSITY cards.

The number has to be the one ccx would use, so the arithmetic is pinned against
a hand-computed product: area times ``Σ(ρ·t)`` in mm and Mg.  The member areas
and the member-to-section mapping are passed in here, as a caller would, rather
than reached for in a document.
"""

import re

import FreeCAD
import Part
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


# --- centre of gravity and inertia ------------------------------------------


def _shape_members(shapes, sigma):
    """``masses`` output plus the geometry it cannot supply, for shapes."""
    areas = {name: shape.Area for name, shape in shapes.items()}
    owners = {name: "%s_Section" % name for name in shapes}
    stacks = {"%s_Section" % name: [(sigma, 1.0)] for name in shapes}
    by_member = modelmass.masses(areas, owners, stacks)
    centroids = {name: shape.CenterOfMass for name, shape in shapes.items()}
    inertia = {name: shape.MatrixOfInertia for name, shape in shapes.items()}
    return by_member, centroids, inertia


def test_inertia_of_a_plate_is_its_analytic_second_moment():
    width, height, sigma = 10.0, 20.0, 5e-7
    plate = Part.makePlane(width, height)
    by_member, centroids, inertia = _shape_members({"Plate": plate}, sigma)
    props = modelmass.mass_properties(by_member, centroids, inertia)
    assert props["center_of_mass"].x == pytest.approx(plate.CenterOfMass.x)
    assert props["center_of_mass"].y == pytest.approx(plate.CenterOfMass.y)
    ixx = sigma * (width * height ** 3 / 12.0) * 1e6
    iyy = sigma * (height * width ** 3 / 12.0) * 1e6
    assert props["inertia"].A11 == pytest.approx(ixx)
    assert props["inertia"].A22 == pytest.approx(iyy)
    assert props["inertia"].A33 == pytest.approx(ixx + iyy)
    assert props["total_g"] == pytest.approx(width * height * sigma * 1e6)


def test_parallel_axis_shifts_inertia_to_the_combined_centroid():
    width, height, sigma = 10.0, 20.0, 5e-7
    left = Part.makePlane(width, height)
    # A fresh plane: TopoShape.translate mutates in place, so translating the
    # left plate's shape would move that one too.
    right = Part.makePlane(width, height).translate(FreeCAD.Vector(100.0, 0.0, 0.0))
    by_member, centroids, inertia = _shape_members(
        {"Left": left, "Right": right}, sigma)
    props = modelmass.mass_properties(by_member, centroids, inertia)
    assert props["center_of_mass"].x == pytest.approx(55.0)
    assert props["center_of_mass"].y == pytest.approx(10.0)
    mass_g = width * height * sigma * 1e6
    offset = 50.0
    ixx = 2 * sigma * (width * height ** 3 / 12.0) * 1e6
    iyy = 2 * sigma * (height * width ** 3 / 12.0) * 1e6 + 2 * mass_g * offset ** 2
    izz = (2 * sigma * ((width * height ** 3 + height * width ** 3) / 12.0) * 1e6
           + 2 * mass_g * offset ** 2)
    assert props["inertia"].A11 == pytest.approx(ixx)
    assert props["inertia"].A22 == pytest.approx(iyy)
    assert props["inertia"].A33 == pytest.approx(izz)
    assert props["inertia"].A12 == pytest.approx(0.0, abs=1e-9)


def test_an_origin_shifts_the_moments_by_the_parallel_axis_theorem():
    width, height, sigma = 10.0, 20.0, 5e-7
    plate = Part.makePlane(width, height)
    by_member, centroids, inertia = _shape_members({"Plate": plate}, sigma)
    about_cog = modelmass.mass_properties(by_member, centroids, inertia)
    about_origin = modelmass.mass_properties(
        by_member, centroids, inertia, origin=FreeCAD.Vector(0.0, 0.0, 0.0))
    mass_g = width * height * sigma * 1e6
    cog = about_cog["center_of_mass"]
    assert about_origin["inertia"].A22 == pytest.approx(
        about_cog["inertia"].A22 + mass_g * (cog.x ** 2 + cog.z ** 2))
    assert about_origin["inertia"].A11 == pytest.approx(
        about_cog["inertia"].A11 + mass_g * (cog.y ** 2 + cog.z ** 2))


def test_a_compound_of_faces_combines_their_centroids_and_inertia():
    width, height = 10.0, 20.0
    left = Part.makePlane(width, height)
    right = Part.makePlane(width, height).translate(
        FreeCAD.Vector(100.0, 0.0, 0.0))
    compound = Part.makeCompound([left, right])
    area, centroid, inertia = modelmass.surface_properties(compound)
    assert area == pytest.approx(2 * width * height)
    assert centroid.x == pytest.approx(55.0)
    offset = 50.0
    iyy = (2 * (height * width ** 3 / 12.0)
           + 2 * (width * height) * offset ** 2)
    assert inertia.A22 == pytest.approx(iyy)


def test_a_single_face_reports_its_own_properties():
    area, centroid, inertia = modelmass.surface_properties(
        Part.makePlane(10.0, 20.0))
    assert area == pytest.approx(200.0)
    assert centroid.x == pytest.approx(5.0)
    assert inertia.A11 == pytest.approx(10.0 * 20.0 ** 3 / 12.0)


def test_summary_and_report_carry_center_of_gravity_and_inertia():
    plate = Part.makePlane(10.0, 20.0)
    by_member, centroids, inertia = _shape_members({"Plate": plate}, 5e-7)
    props = modelmass.mass_properties(by_member, centroids, inertia)
    summary = modelmass.summarize(by_member, {}, properties=props)
    assert summary["center_of_mass"].x == pytest.approx(5.0)
    assert summary["inertia"].A11 > 0.0
    lines = []
    modelmass.log_report(summary, lines.append)
    text = "\n".join(lines)
    assert "centre of gravity" in text
    assert "inertia about the centre of gravity" in text


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
