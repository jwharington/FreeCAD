# SPDX-License-Identifier: LGPL-2.1-or-later
"""Unit tests for the fuselage inp uncovered-element repair's pure logic.

The repair (propeller/cad/FuselageFem.py) must find boundary-straddling
elements that reach the solver in no material elset — the OCCT
triple-point behaviour at web/bay-wall junctions — and assign each to the
elset of its nearest covered neighbour, reusing that neighbour's exact
laminate data.  These tests exercise the pure parse/append text logic
with hand-built inp text; no FreeCAD state involved (the module is
imported by path without executing its FreeCAD-dependent main()).
"""

import importlib.util
import os
import sys
import tempfile

import pytest

_SCRIPT = os.path.join(
    os.path.expanduser("~"),
    "Desktop", "Projects", "RTOA", "LS8e", "Design", "ls8e-design-tools",
    "propeller", "cad", "FuselageFem.py",
)


@pytest.fixture(scope="module")
def ff():
    spec = importlib.util.spec_from_file_location("fuselage_fem", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fuselage_fem"] = module
    spec.loader.exec_module(module)
    return module


def _inp_file(text):
    handle = tempfile.NamedTemporaryFile("w", suffix=".inp", delete=False)
    handle.write(text + "\n")
    handle.close()
    return handle.name


def _sample_inp():
    return "\n".join([
        "** header",
        "*Node",
        "1, 0.0, 0.0, 0.0",
        "*Element, TYPE=S6, ELSET=Efaces",
        "100, 1, 2, 3, 4, 5, 6",
        "101, 1, 2, 3, 7, 8, 9",
        "*ELSET, ELSET=MaterialSkin_Section",
        "100,",
        "*SHELL SECTION, ELSET=MaterialSkin_Section, MATERIAL=M, OFFSET=0",
        "0.085,,PLY",
        "*BOUNDARY",
        "1,1,1,0.0",
    ])


def test_parse_inp_reads_elements_and_elsets(ff):
    element_nodes, elsets, section_elsets = ff._parse_inp(
        _inp_file(_sample_inp()))
    assert element_nodes == {100: [1, 2, 3, 4, 5, 6], 101: [1, 2, 3, 7, 8, 9]}
    assert elsets["Efaces"] == {100, 101}
    assert elsets["MaterialSkin_Section"] == {100}
    assert section_elsets == {"MaterialSkin_Section"}


def test_parse_inp_handles_wrapped_element_lines(ff):
    inp = "\n".join([
        "*Element, TYPE=C3D20, ELSET=Eall",
        "1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10,",
        "11, 12, 13, 14, 15, 16, 17, 18, 19, 20",
        "*Element, TYPE=S6, ELSET=Efaces",
        "2, 1, 2, 3, 4, 5, 6",
    ])
    element_nodes, _, _ = ff._parse_inp(_inp_file(inp))
    assert element_nodes == {
        1: list(range(1, 21)),
        2: [1, 2, 3, 4, 5, 6],
    }


def test_parse_inp_no_elements(ff):
    element_nodes, elsets, section_elsets = ff._parse_inp(
        _inp_file("*Node\n1, 0.0, 0.0, 0.0\n"))
    assert element_nodes == {}
    assert elsets == {}
    assert section_elsets == set()


def test_append_to_elsets_writes_after_last_id(ff):
    path = _inp_file(_sample_inp())
    ff._append_to_elsets(path, [(101, "Skin_Section", "MaterialSkin_Section")])
    element_nodes, elsets, _ = ff._parse_inp(path)
    assert elsets["MaterialSkin_Section"] == {100, 101}
    # the file stays parseable and unchanged elsewhere
    assert element_nodes == {100: [1, 2, 3, 4, 5, 6], 101: [1, 2, 3, 7, 8, 9]}
