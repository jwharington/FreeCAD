# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""B7: the tie pass reads interfaces the model declares by object identity."""

import FreeCAD
import ObjectsFem
import pytest

from Composites.compositeexamples.examples import mixed_shell_solid_auto_tie as example
from Composites.compositeexamples.examples._shell_example_common import (
    _add_shell_section_and_material,
    _create_fem_base,
)
from Composites.features.CompositeShell import CompositeShellFP
from Composites.fem.auto_tie import TOLERANCE_MARGIN, auto_tie

from femtools.membertools import AnalysisMember
from femtools.mixedcoupling import face_reference_on_axis


@pytest.fixture(scope="module")
def solved():
    case = example.build(run_solver=True)
    try:
        yield case
    finally:
        FreeCAD.closeDocument(case["doc"].Name)


def test_the_pass_ties_the_declared_interface(solved):
    tie = solved["tie"]
    shell = solved["shell"]
    spar = solved["spar"]

    slave_obj, slave_subs = tie.References[0]
    master_obj, master_subs = tie.References[1]
    assert slave_obj is shell, "the shell is the slave: its face is the expanded one"
    assert list(slave_subs) == ["Face1"]
    assert master_obj is spar
    assert list(master_subs) == [
        face_reference_on_axis(spar, "z", example.SPAR_HEIGHT)[1]
    ]

    assert "*TIE" in solved["solver_input"]
    assert solved["max_displacement"] > 0.0

    # The tolerance is derived from the laminate the deck expands, not from
    # the FEM section object's placeholder thickness: offset 0 and a coincident
    # master put the tied expanded face half the *laminate* thickness from the
    # reference surface, which is the value the writer's own rule requires.
    thickness = sum(layer.thickness for layer in shell.Laminate.Proxy.FEMLayers)
    assert AnalysisMember(solved["analysis"]).geos_shellthickness[0]["Object"].Offset == 0.0
    assert tie.Tolerance.getValueAs("mm").Value == pytest.approx(
        thickness / 2.0 * (1.0 + TOLERANCE_MARGIN)
    )


def test_a_second_run_creates_nothing(solved):
    before = list(AnalysisMember(solved["analysis"]).cons_tie)
    assert auto_tie(solved["analysis"]) == []
    assert list(AnalysisMember(solved["analysis"]).cons_tie) == before


def test_a_shell_that_opts_out_is_not_an_interface():
    doc = FreeCAD.newDocument("TestDoc_auto_tie_opt_out")
    try:
        _shell_on_a_solid(doc, auto_couple=False)
        assert auto_tie(_analysis_of(doc)) == []
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_a_shell_on_a_separate_support_is_not_an_interface():
    # The wing and the plate declare their skins this way; they keep the ties
    # they wrote by hand, so the pass has nothing to add.
    doc = FreeCAD.newDocument("TestDoc_auto_tie_separate_support")
    try:
        _shell_on_a_separate_support(doc)
        assert auto_tie(_analysis_of(doc)) == []
    finally:
        FreeCAD.closeDocument(doc.Name)


def _shell_on_a_solid(doc, auto_couple=True):
    spar = doc.addObject("Part::Box", "Spar")
    spar.Length = spar.Width = spar.Height = 20.0
    shell = doc.addObject("Part::FeaturePython", "SkinShell")
    CompositeShellFP(shell, support=None)
    shell.SupportReference = (spar, ["Face6"])
    shell.AutoCouple = auto_couple
    doc.recompute()
    return spar, shell


def _shell_on_a_separate_support(doc):
    spar = doc.addObject("Part::Box", "Spar")
    spar.Length = spar.Width = spar.Height = 20.0
    support = doc.addObject("Part::Feature", "SkinSupport")
    support.Shape = spar.Shape.Faces[5]
    shell = doc.addObject("Part::FeaturePython", "SkinShell")
    CompositeShellFP(shell, support=support)
    doc.recompute()
    return spar, support, shell


def _analysis_of(doc):
    """A minimal analysis whose only coupling candidates are the shell's."""
    tag = "AutoTieFixture"
    spar = doc.getObject("Spar")
    shell = doc.getObject("SkinShell")
    analysis, _solver, _mesh = _create_fem_base(doc, tag)
    _add_shell_section_and_material(doc, analysis, None, tag, shell_obj=shell)
    material = ObjectsFem.makeMaterialSolid(doc, f"{tag}_SparMaterial")
    material.References = [(spar, "")]
    analysis.addObject(material)
    return analysis
