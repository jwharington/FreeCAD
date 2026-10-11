# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for the laminate builders (Composites.tools.laminate_builder).

The builders lay a stack out; the material schedule — fibre card, resin,
volume fraction, angle set — travels in as arguments, so that is what these
tests pin, alongside the ply naming the deck and the sections rely on."""

import FreeCAD
import pytest

from Composites.objects import WeaveType
from Composites.tools.laminate_builder import (
    QI_ANGLES,
    build_frame_laminate,
    build_skin_laminate,
    make_lamina,
)


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

RESIN = {
    "Name": "Epoxy",
    "Density": "1100.0 kg/m^3",
    "YoungsModulus": "3.5 GPa",
    "PoissonRatio": "0.36",
}

STACK = (
    ("Glass220UD", 0.0, "UD", 0.17),
    ("Glass220UD", 45.0, "UD", 0.17),
)


@pytest.fixture
def doc():
    document = FreeCAD.newDocument("TestLaminateBuilder")
    yield document
    FreeCAD.closeDocument(document.Name)


def _skin(doc, **kwargs):
    return build_skin_laminate(
        doc, GLASS, STACK, uuid="glass-uuid", volume_fraction=50,
        resin=RESIN, resin_uuid="resin-uuid", **kwargs)


def test_skin_laminate_names_its_plies_and_itself(doc):
    laminate, plies = _skin(doc)
    assert laminate.Name == "SkinLaminate"
    assert [ply.Name for ply in plies] == ["SkinPly00", "SkinPly01"]
    assert [ply.Label for ply in plies] == ["Skin_Glass220UD_0",
                                            "Skin_Glass220UD_1"]


def test_skin_laminate_carries_the_material_schedule(doc):
    laminate, plies = _skin(doc)
    assert plies[0].FibreMaterial["Name"] == "Glass"
    assert plies[0].FibreMaterialUUID == "glass-uuid"
    assert plies[0].FibreVolumeFraction == 50
    assert laminate.ResinMaterial["Name"] == "Epoxy"
    assert laminate.ResinMaterialUUID == "resin-uuid"
    assert laminate.FibreVolumeFraction == 50
    assert laminate.Symmetry == "Assymmetric"


def test_skin_laminate_can_declare_a_fraction_of_its_own(doc):
    """A reinforced zone's plies may carry a different card's fraction from
    the laminate's declared design fraction."""
    laminate, plies = build_skin_laminate(
        doc, GLASS, STACK, uuid="u", volume_fraction=55,
        laminate_volume_fraction=50, resin=RESIN, resin_uuid="r")
    assert plies[0].FibreVolumeFraction == 55
    assert laminate.FibreVolumeFraction == 50


def test_skin_laminate_thickness_factor_scales_every_ply(doc):
    _, plies = _skin(doc, thickness_factor=2.0)
    assert plies[0].Thickness == pytest.approx(0.34)
    assert plies[1].Thickness == pytest.approx(0.34)


def test_skin_laminate_prefix_names_every_object(doc):
    laminate, plies = _skin(doc, prefix="SkinBand")
    assert laminate.Name == "SkinBandLaminate"
    assert [ply.Name for ply in plies] == ["SkinBandPly00", "SkinBandPly01"]


def test_skin_laminate_takes_the_stack_from_the_caller(doc):
    """The stack is an argument, never a module default: the schedule that
    chooses it belongs to the study."""
    laminate, plies = build_skin_laminate(
        doc, GLASS, (), uuid="u", volume_fraction=50, resin=RESIN,
        resin_uuid="r")
    assert plies == []
    assert laminate.Name == "SkinLaminate"


def test_frame_laminate_is_a_symmetric_qi_stack(doc):
    laminate, plies = build_frame_laminate(
        doc, GLASS, ply_thickness=0.15, uuid="u", volume_fraction=50,
        resin=RESIN, resin_uuid="r")
    assert laminate.Name == "FrameQILaminate"
    assert len(plies) == len(QI_ANGLES)
    assert laminate.Symmetry == "Even"
    assert laminate.IsotropicEquivalent is True
    assert [ply.Thickness for ply in plies] == [pytest.approx(0.15)] * len(plies)


def test_frame_laminate_blocks_repeat_the_angle_set(doc):
    _, plies = build_frame_laminate(
        doc, GLASS, stack_blocks=2, ply_thickness=0.15, uuid="u",
        volume_fraction=50, resin=RESIN, resin_uuid="r")
    assert len(plies) == 2 * len(QI_ANGLES)


def test_frame_laminate_extra_plies_are_declared_layered(doc):
    """A mixed-fibre stack is not quasi-isotropic however the plies are
    angled, so it is declared as what it is."""
    _, plies = build_frame_laminate(
        doc, GLASS, ply_thickness=0.15, uuid="u", volume_fraction=50,
        extra_plies=((45.0, GLASS, "c-uuid", 55, "CarbonQI"),),
        resin=RESIN, resin_uuid="r")
    assert len(plies) == len(QI_ANGLES) + 1


def test_frame_laminate_extra_plies_drop_the_isotropic_declaration(doc):
    laminate, _ = build_frame_laminate(
        doc, GLASS, ply_thickness=0.15, uuid="u", volume_fraction=50,
        extra_plies=((45.0, GLASS, "c-uuid", 55, "CarbonQI"),),
        resin=RESIN, resin_uuid="r")
    assert laminate.IsotropicEquivalent is False


def test_frame_laminate_angle_set_is_a_parameter(doc):
    _, plies = build_frame_laminate(
        doc, GLASS, angles=(0.0, 90.0), ply_thickness=0.2, uuid="u",
        volume_fraction=50, resin=RESIN, resin_uuid="r")
    assert [ply.Angle for ply in plies] == [0.0, 90.0]


def test_make_lamina_accepts_a_weave_name_or_a_member(doc):
    by_name = make_lamina(doc, "ByName", "ByName", 0.0, 0.1, "UD", GLASS,
                          "u", 50)
    by_member = make_lamina(doc, "ByMember", "ByMember", 0.0, 0.1,
                            WeaveType.UD, GLASS, "u", 50)
    assert by_name.WeaveType == by_member.WeaveType == "UD"
