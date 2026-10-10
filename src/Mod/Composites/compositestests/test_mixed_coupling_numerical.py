# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Solve the mixed models with CalculiX and assert what deck text cannot show.

A deck-text test proves a deck was *written*. It cannot prove the two parts are
*coupled*, and both ways a mixed model goes wrong are silent. A shell that
shares the solid's nodes makes a hinge. A ``*TIE`` written on the wrong side of
the shell is a whole thickness out of position, so CalculiX generates no MPC at
all and prints its warning to stdout only. Either way the job converges, writes
a ``.dat``, and returns a wrong number.

So the only detector is a number, and this module runs real solves to get one.
The models come from ``inspect_mixed_cantilever``, which is also what the
mixed shell-and-solid plan quotes its figures from; defining them a second time
here would let the two drift apart.

The tolerances are stated before the run and are never relaxed to make a run
pass. Measured when this was written: mixed 6.4223e-02 mm against all-solid
6.4163e-02 mm, i.e. 0.09 %, with the bare spar at 1.2195e-01 mm.

The other in-scope face families (f1-f4 of the plan's section 8) are solved too,
from Fem's own fixtures, and asserted on what CalculiX says about the tie rather
than on a second reference model: a run that reports a slave node with no
opposite master face is not coupled, and that is the detector no deck-text test
has. That check is what exposed f1 and f2, whose tie tolerance was below the
half-thickness CalculiX expands a shell by, so 30 and 5 of their slave nodes were
never tied. The e1-e3 edge family is refused by the writer by design (section 5)
and so has no solve here.
"""

import os

import FreeCAD
import pytest

from femtools import ccxtools
from femtools.ccxtools import tied_mpc_warning_counts
from femexamples import constraint_mixed_face_coupling as face_coupling

from . import inspect_mixed_cantilever as probe

# Stated before the run. Measured 0.09 %; this is not a tuning knob.
SKIN_CARRIES_SECTION_TOLERANCE = 0.05
# The tied skin must carry load at all. The skin gives 1.90x a bare spar, so
# this asks only that it is attached - which is exactly what a silent
# uncoupling takes away, and the test that catches it.
MIN_STIFFENING_RATIO = 1.2

FLAG_PATH = "User parameter:BaseApp/Preferences/Mod/Fem/General"
FLAG_NAME = "AllowMixedShellSolid"


@pytest.fixture(scope="module")
def tip_deflections(tmp_path_factory):
    """Tip deflection of each model, solved once and shared by both assertions.

    Solving is the slow part, so it happens here rather than once per test.
    """
    if not os.path.exists(probe.DEFAULT_CCX):
        pytest.skip(f"no CalculiX binary at {probe.DEFAULT_CCX}; nothing can be solved")

    workdir = str(tmp_path_factory.mktemp("mixed_coupling"))
    group = FreeCAD.ParamGet(FLAG_PATH)
    previous = group.GetBool(FLAG_NAME, False)
    # These are mixed models, so the path has to be on; the old value goes back
    # afterwards so this module cannot decide anything for another one.
    group.SetBool(FLAG_NAME, True)
    try:
        return {
            name: probe.measure(probe.BUILDERS[name], name, workdir)
            for name in ("mixed", "solid", "bare")
        }
    finally:
        group.SetBool(FLAG_NAME, previous)


def test_mixed_skin_carries_the_section(tip_deflections):
    # If the *TIE is on the wrong side of the shell the skin floats: the model
    # returns the bare spar, which this catches by being far too soft.
    mixed = tip_deflections["mixed"]
    solid = tip_deflections["solid"]
    relative = abs(mixed - solid) / solid
    assert relative < SKIN_CARRIES_SECTION_TOLERANCE, (
        "a tied skin must give the stiffness of the all-solid rebuild: "
        f"mixed {mixed:.6e} mm against all-solid {solid:.6e} mm, {relative:.2%} apart"
    )


def test_a_tied_skin_is_stiffer_than_a_bare_spar(tip_deflections):
    # The silent-uncoupling detector. A hinge, or a tie that generated no MPC,
    # leaves the skin carrying nothing, and the model is then exactly as soft
    # as the spar alone - a difference no deck-text check can see.
    mixed = tip_deflections["mixed"]
    bare = tip_deflections["bare"]
    assert mixed * MIN_STIFFENING_RATIO < bare, (
        "the tied skin must carry load, not just be written: "
        f"mixed {mixed:.6e} mm against bare {bare:.6e} mm"
    )


FACE_FAMILIES = ("f1", "f2", "f3", "f4")


@pytest.fixture(scope="module")
def face_family_runs(tmp_path_factory):
    """Solve one fixture per face family, reporting what ccx said about its ties.

    A run that reports a slave node with no opposite master face is an uncoupled
    model, and one with an untouched shell does not converge at all, because the
    load sits on the shell and the fixed end on the solid. Neither needs a second
    reference model, which is what the F1 comparison above needs and what the
    offset and bag families have no natural equivalent of.
    """
    if not os.path.exists(probe.DEFAULT_CCX):
        pytest.skip(f"no CalculiX binary at {probe.DEFAULT_CCX}; nothing can be solved")

    root = tmp_path_factory.mktemp("mixed_face_families")
    group = FreeCAD.ParamGet(FLAG_PATH)
    previous = group.GetBool(FLAG_NAME, False)
    group.SetBool(FLAG_NAME, True)
    runs = {}
    try:
        for variant in FACE_FAMILIES:
            doc = face_coupling.setup(variant=variant)
            try:
                workdir = root / variant
                workdir.mkdir(parents=True, exist_ok=True)
                fea = ccxtools.FemToolsCcx(
                    analysis=doc.Analysis, solver=doc.CalculiXCcxTools
                )
                fea.update_objects()
                fea.setup_working_dir(str(workdir))
                ran = fea.run()
                not_coupled, already_constrained = tied_mpc_warning_counts(fea.ccx_stdout)
                runs[variant] = {
                    "ran": ran,
                    "not_coupled": not_coupled,
                    "already_constrained": already_constrained,
                    # Bounded, and only for the failure message: a family that
                    # does not solve has to say how, and ccx's own last words
                    # are the only place that is visible.
                    "ccx_tail": "\n".join(fea.ccx_stdout.splitlines()[-12:]),
                }
            finally:
                FreeCAD.closeDocument(doc.Name)
    finally:
        group.SetBool(FLAG_NAME, previous)
    return runs


@pytest.mark.parametrize("variant", FACE_FAMILIES)
def test_each_face_family_couples_its_shell(face_family_runs, variant):
    run = face_family_runs[variant]
    assert run["ran"], f"{variant} did not solve; ccx ended with:\n{run['ccx_tail']}"
    assert run["not_coupled"] == 0, (
        f"{variant}: {run['not_coupled']} slave node(s) found no opposite master "
        f"face, so the *TIE does not couple the shell; ccx ended with:\n{run['ccx_tail']}"
    )
