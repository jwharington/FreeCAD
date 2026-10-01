# SPDX-License-Identifier: LGPL-2.1-or-later
"""Unit tests for the fuselage four-term load verification logic.

The load case (Fy, Fz, My, Mz at the aft frame) is applied through a
Fem::ConstraintReaction; the ground truth is the written solver input,
so FuselageFem parses its *CLOAD lines and reconstructs the resultant
force and moment about the reaction Origin.  These tests exercise the
pure parse/verify logic with hand-built inp text and a small synthetic
FemMesh; no FreeCAD document involved (the module is imported by path
without executing its FreeCAD-dependent main()).
"""

import importlib.util
import os
import sys
import tempfile

import FreeCAD
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


@pytest.fixture(name="mesh")
def fixture_mesh():
    """Three nodes in the x=3070 plane (the aft frame), 10 mm apart."""
    import Fem

    mesh = Fem.FemMesh()
    mesh.addNode(3070.0, -10.0, 0.0)
    mesh.addNode(3070.0, 0.0, 0.0)
    mesh.addNode(3070.0, 10.0, 0.0)
    return mesh


def _inp_file(text):
    handle = tempfile.NamedTemporaryFile("w", suffix=".inp", delete=False)
    handle.write(text + "\n")
    handle.close()
    return handle.name


def _origin():
    return FreeCAD.Vector(3070.0, 0.0, 0.0)


def _set_load_case(ff, fy, fz, my, mz):
    old = dict(ff.LOAD_CASE)
    ff.LOAD_CASE.update({"Fy": fy, "Fz": fz, "My": my, "Mz": mz})
    return old


def test_parse_inp_cload_reads_entries_and_synthetic_nodes(ff):
    text = "\n".join([
        "** header",
        "*Node",
        "1, 3070.0, -10.0, 0.0",
        "*Element, TYPE=S6, ELSET=Efaces",
        "100, 1, 1, 1, 1, 1, 1",
        "** ConstraintReaction FuselageLoad: using *DISTRIBUTING COUPLING delivery",
        "*Node",
        "11000, 3070.0, 0.0, 5.0",
        "*CLOAD",
        "1,2,123.5",
        "1,3,-7.25",
        "11000,3,500.0",
    ])
    synthetic, cloads = ff._parse_inp_cload(_inp_file(text))
    assert cloads == [(1, 2, 123.5), (1, 3, -7.25), (11000, 3, 500.0)]
    assert synthetic[11000] == FreeCAD.Vector(3070.0, 0.0, 0.0 + 5.0)


def test_verify_inp_loads_passes_on_matching_resultant(ff, mesh):
    """Fy=0, Fz=1000 spread over the three nodes; moment about the
    origin must reconstruct to zero because the forces are symmetric."""
    old = _set_load_case(ff, 0.0, 1000.0, 0.0, 0.0)
    try:
        text = "\n".join([
            "*Node",
            "1, 3070.0, -10.0, 0.0",
            "*CLOAD",
            "1,3,333.333333",
            "2,3,333.333334",
            "3,3,333.333333",
        ])
        ff._verify_inp_loads(_inp_file(text), mesh, _origin(), "FuselageLoad")
    finally:
        _set_load_case(ff, old["Fy"], old["Fz"], old["My"], old["Mz"])


def test_verify_inp_loads_catches_force_mismatch(ff, mesh):
    old = _set_load_case(ff, 0.0, 1000.0, 0.0, 0.0)
    try:
        text = "\n".join([
            "*Node",
            "1, 3070.0, -10.0, 0.0",
            "*CLOAD",
            "1,2,1000.0",  # sideways: the load-direction bug, again
        ])
        with pytest.raises(RuntimeError, match="resultant mismatch"):
            ff._verify_inp_loads(_inp_file(text), mesh, _origin(), "FuselageLoad")
    finally:
        _set_load_case(ff, old["Fy"], old["Fz"], old["My"], old["Mz"])


def test_verify_inp_loads_catches_moment_mismatch(ff, mesh):
    """Fz=0 with My=1000: a couple must appear in the CLOAD lines; a
    bare force with no couple reconstructs a spurious moment."""
    old = _set_load_case(ff, 0.0, 0.0, 1000.0, 0.0)
    try:
        bad = "\n".join([
            "*Node",
            "1, 3070.0, -10.0, 0.0",
            "*CLOAD",
            "1,3,500.0",  # force only, no couple: moment = -5000 about y
        ])
        with pytest.raises(RuntimeError, match="My"):
            ff._verify_inp_loads(_inp_file(bad), mesh, _origin(), "FuselageLoad")

        good = "\n".join([
            "*Node",
            "1, 3070.0, -10.0, 0.0",
            "*CLOAD",
            "1,3,500.0",
            "2,3,-1000.0",
            "3,3,500.0",
        ])
        # The ±z forces on the y-offset nodes give x-moments that
        # cancel; node 2 sits at the origin so its force has no arm.
        # Resultant M=(0,0,0) but target My=1000 → mismatch caught:
        with pytest.raises(RuntimeError, match="My"):
            ff._verify_inp_loads(_inp_file(good), mesh, _origin(), "FuselageLoad")
    finally:
        _set_load_case(ff, old["Fy"], old["Fz"], old["My"], old["Mz"])


def test_verify_inp_loads_passes_on_true_couple(ff, mesh):
    """My=2000 realized by the writer's zero-net-force couple: opposite
    z forces on two x-offset nodes, whose r×f arms point along y."""
    old = _set_load_case(ff, 0.0, 0.0, 2000.0, 0.0)
    try:
        import Fem

        mesh_x = Fem.FemMesh()
        mesh_x.addNode(3060.0, 0.0, 0.0)
        mesh_x.addNode(3080.0, 0.0, 0.0)
        # A couple with the wrong sense reconstructs to M=(0,-2000,0):
        text = "\n".join([
            "*Node",
            "1, 3060.0, 0.0, 0.0",
            "*CLOAD",
            "1,3,-100.0",
            "2,3,100.0",
        ])
        with pytest.raises(RuntimeError, match="My"):
            ff._verify_inp_loads(_inp_file(text), mesh_x, _origin(), "FuselageLoad")
        # flip the couple: r×f for node1 f=(0,0,100): (0, -(−10·100),0)=(0,1000,0)
        text_ok = "\n".join([
            "*Node",
            "1, 3060.0, 0.0, 0.0",
            "*CLOAD",
            "1,3,100.0",
            "2,3,-100.0",
        ])
        ff._verify_inp_loads(_inp_file(text_ok), mesh_x, _origin(), "FuselageLoad")
    finally:
        _set_load_case(ff, old["Fy"], old["Fz"], old["My"], old["Mz"])


def test_verify_inp_loads_fails_on_unknown_node(ff, mesh):
    old = _set_load_case(ff, 0.0, 1000.0, 0.0, 0.0)
    try:
        text = "\n".join([
            "*Node",
            "1, 3070.0, -10.0, 0.0",
            "*CLOAD",
            "999,3,1000.0",
        ])
        with pytest.raises(RuntimeError, match="not found"):
            ff._verify_inp_loads(_inp_file(text), mesh, _origin(), "FuselageLoad")
    finally:
        _set_load_case(ff, old["Fy"], old["Fz"], old["My"], old["Mz"])


def test_verify_inp_loads_fails_on_no_cload(ff, mesh):
    text = "\n".join([
        "*Node",
        "1, 3070.0, -10.0, 0.0",
        "*BOUNDARY",
        "1,1,0,0.0",
    ])
    with pytest.raises(RuntimeError, match="no \\*CLOAD"):
        ff._verify_inp_loads(_inp_file(text), mesh, _origin(), "FuselageLoad")


def test_verify_reaction_sign_convention(ff):
    """The object stores the NEGATIVE of the structural load (writer
    applies -Force/-Torque); _verify_reaction must accept that and
    reject an un-negated object."""
    old = _set_load_case(ff, 0.0, 1000.0, 0.0, 500.0)

    class _FakeReaction:
        Name = "FuselageLoad"
        Force = FreeCAD.Vector(0.0, 0.0, -1000.0)
        Torque = FreeCAD.Vector(0.0, 0.0, -500.0)

    try:
        ff._verify_reaction(_FakeReaction())  # must not raise
        _FakeReaction.Force = FreeCAD.Vector(0.0, 0.0, 1000.0)
        with pytest.raises(RuntimeError, match="Force is"):
            ff._verify_reaction(_FakeReaction())
    finally:
        _set_load_case(ff, old["Fy"], old["Fz"], old["My"], old["Mz"])
