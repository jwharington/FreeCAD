# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Creating a constraint twice must not make two, and a load must read back as
written.  Both are silent failures in the deck otherwise: a ``.001`` copy
changes which object the writer walks, and a sign flip solves to nonsense.
"""

import FreeCAD
import ObjectsFem
import pytest

from femtools import readback


@pytest.fixture
def document():
    doc = FreeCAD.newDocument("ReadbackTest")
    yield doc
    if doc.Name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(doc.Name)


def _support(document):
    box = document.addObject("Part::Box", "Support")
    box.recompute()
    return box


def test_a_fixed_constraint_is_created_once_and_repointed(document):
    analysis = ObjectsFem.makeAnalysis(document, "Analysis")
    support = _support(document)
    first = readback.add_fixed(document, analysis, "Fix",
                               [(support, ["Edge1"])])
    again = readback.add_fixed(document, analysis, "Fix",
                               [(support, ["Edge2"])])
    assert first is again
    assert document.getObject("Fix.001") is None
    assert list(again.References[0][1]) == ["Edge2"]


def test_a_reaction_stores_the_reaction_sign(document):
    analysis = ObjectsFem.makeAnalysis(document, "Analysis")
    support = _support(document)
    reaction = readback.add_reaction(
        document, analysis, "Load", [(support, ["Face1"])],
        force=(1.0, 2.0, 3.0), torque=(4.0, 5.0, 6.0),
        origin=FreeCAD.Vector(0.0, 0.0, 0.0))
    assert reaction.Force == FreeCAD.Vector(-1.0, -2.0, -3.0)
    assert reaction.Torque == FreeCAD.Vector(-4.0, -5.0, -6.0)
    assert document.getObject("Load.001") is None


def test_a_reaction_reads_back_as_written(document):
    analysis = ObjectsFem.makeAnalysis(document, "Analysis")
    support = _support(document)
    reaction = readback.add_reaction(
        document, analysis, "Load", [(support, ["Face1"])],
        force=(1.0, 2.0, 3.0), torque=(4.0, 5.0, 6.0),
        origin=FreeCAD.Vector(0.0, 0.0, 0.0))
    readback.verify_reaction(reaction, (1.0, 2.0, 3.0), (4.0, 5.0, 6.0))


def test_a_sign_flip_is_refused(document):
    analysis = ObjectsFem.makeAnalysis(document, "Analysis")
    support = _support(document)
    reaction = readback.add_reaction(
        document, analysis, "Load", [(support, ["Face1"])],
        force=(1.0, 2.0, 3.0), torque=(4.0, 5.0, 6.0),
        origin=FreeCAD.Vector(0.0, 0.0, 0.0))
    reaction.Force = FreeCAD.Vector(1.0, 2.0, 3.0)
    with pytest.raises(RuntimeError, match=r"Force is"):
        readback.verify_reaction(reaction, (1.0, 2.0, 3.0), (4.0, 5.0, 6.0))
