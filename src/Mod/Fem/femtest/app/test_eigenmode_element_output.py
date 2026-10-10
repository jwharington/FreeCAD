# SPDX-License-Identifier: LGPL-2.1-or-later

"""An eigenvalue step asks for element output only if the solver says so.

A buckling or frequency step answers with a factor or a frequency and a mode
shape; its element stresses are per mode and per ply, which is most of the
deck's size, and nothing reads them.  The solver property turns them off for
those steps and defaults to writing them, so an existing analysis is unchanged.
"""

import FreeCAD

from io import StringIO
from types import SimpleNamespace

from femsolver.calculix import write_step_output


def _writer(analysis_type, eigenmode_element_output):
    member = SimpleNamespace(
        geos_beamsection=[],
        geos_shellthickness=[],
        geos_fluidsection=[],
        cons_fixed=[],
        cons_displacement=[],
        cons_jig321=[],
        cons_rigidbody=[],
        cons_contact=[],
    )
    solver_obj = SimpleNamespace(
        Output3d=False,
        MaterialNonlinearity=False,
        OutputFrequency=1,
        EigenmodeElementOutput=eigenmode_element_output,
    )
    return SimpleNamespace(
        member=member,
        solver_obj=solver_obj,
        analysis_type=analysis_type,
        meshdatagetter=SimpleNamespace(is_mixed=False),
    )


def _step_output(analysis_type, eigenmode_element_output):
    buf = StringIO()
    write_step_output.write_step_output(buf, _writer(analysis_type, eigenmode_element_output))
    return buf.getvalue()


def test_a_buckling_step_omits_element_output_when_the_solver_says_so():
    assert "*EL FILE" not in _step_output("buckling", False)


def test_a_frequency_step_omits_element_output_when_the_solver_says_so():
    assert "*EL FILE" not in _step_output("frequency", False)


def test_an_eigenvalue_step_still_writes_it_when_asked_for():
    assert "*EL FILE" in _step_output("buckling", True)


def test_a_static_step_always_writes_element_output():
    assert "*EL FILE" in _step_output("static", False)
