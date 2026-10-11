# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""B2.1: the Composites stiffener feature on a solid spar, coupled and solved.

The stiffener's own shells (web, foot) and the panel it sits on are all
``Composite::Shell`` objects the section provider accepts, and the panel is
tied to the solid spar, so this exercises the mixed path with the real feature
rather than with bare geometry.
"""

import FreeCAD

from Composites.compositeexamples.examples import mixed_shell_solid_stiffener as example


def test_the_mixed_stiffener_couples_and_solves():
    case = example.build(run_solver=True)
    doc = case["doc"]
    try:
        job = case["fem_job"]
        assert job is not None, "run_solver=True produced no FEM job"
        assert job["solve_result"], "ccx refused the mixed stiffener deck"
        tip = example.max_displacement(job["analysis"])
        assert tip is not None and tip > 0.0, "the deck solved to no displacement"
        with open(job["inp_file"], encoding="utf-8") as deck:
            text = deck.read()
        assert "*TIE" in text, "the panel was not tied to the solid"
        assert "*SHELL SECTION" in text and "*SOLID SECTION" in text, text[:500]
    finally:
        FreeCAD.closeDocument(doc.Name)
