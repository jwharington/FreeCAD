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
"""

import os

import FreeCAD
import pytest

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
