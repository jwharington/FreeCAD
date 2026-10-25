# ***************************************************************************
# *   Copyright (c) 2026 I. M. Wang <jmw@earendil-works.dev>                *
# *                                                                         *
# *   This file is part of the FreeCAD FEM workbench.                       *
# *                                                                         *
# ***************************************************************************
"""Regression tests for the ConstraintReaction wrench decomposition.

decompose_wrench (femsolver/calculix/write_constraint_pressure_reaction.py)
absorbs the moment component perpendicular to the force by shifting the
line of action.  The static-equivalence property it must satisfy:

    shift x F + reduced_moment == moment   (about the original origin)

The shipped code solved shift = (m_perp x F)/|F|^2 — the wrong cross
order — which moves the line of action the wrong way and, at
shift_scale 1, delivers the NEGATED moment.  Found on a stitched shell
model whose reaction wrench was scaled from N·mm to N·m: the +1602
nose-up case delivered −1602, and only the verification parse of the
written *CLOAD caught it.
"""

import FreeCAD
import pytest

from femsolver.calculix.write_constraint_pressure_reaction import (
    decompose_wrench,
    exclude_jig321_nodes,
    jig321_support_nodes,
)

Vector = FreeCAD.Vector


def _assert_equivalent(force, moment, scale=1.0, limit=50.0):
    """shift x F + reduced_moment must reproduce the original moment."""
    shift, reduced = decompose_wrench(force, moment, scale, limit)
    total = shift.cross(force) + reduced
    assert (total - moment).Length < 1e-9, (
        "F=%s M=%s scale=%s: got total %s (shift %s, reduced %s)"
        % (force, moment, scale, total, shift, reduced)
    )
    return shift, reduced


def test_nose_up_bending_case_shifts_toward_plus_x():
    """The failing production configuration: tail load DOWN
    (model -z) with nose-up moment +1602 N·mm about y.  The shift must
    point +x (the wrong-order code gave -0.47 mm and delivered
    -1602)."""
    force = Vector(0, 0, -3409.5)
    moment = Vector(0, 1602.0, 0)
    shift, reduced = _assert_equivalent(force, moment)
    assert shift.x > 0.0, "line of action must move +x for down-force/nose-up"
    assert shift.x == pytest.approx(1602.0 / 3409.5, rel=1e-9)
    assert reduced.Length == pytest.approx(0.0, abs=1e-9)  # fully absorbed


def test_example_configuration_is_sign_correct():
    """The shipped example (F=(0,0,-2000) reaction → writer F=(0,0,2000),
    M=(-10,0,0) about x): the delivered moment must keep the target
    sign, not flip it."""
    force = Vector(0, 0, 2000.0)
    moment = Vector(-10.0, 0, 0)
    shift, reduced = _assert_equivalent(force, moment)
    assert reduced.x == pytest.approx(-10.0, rel=1e-9) or (
        shift.Length > 0 and (shift.cross(force) + reduced).x
        == pytest.approx(-10.0, rel=1e-9)
    )


def test_zero_scale_keeps_full_moment_and_no_shift():
    force = Vector(0, 0, -1000.0)
    moment = Vector(0, 500.0, 0)
    shift, reduced = decompose_wrench(force, moment, 0.0, 50.0)
    assert shift.Length == pytest.approx(0.0, abs=1e-12)
    assert (reduced - moment).Length < 1e-9


def test_parallel_only_moment_is_not_shifted():
    """A moment parallel to the force is a free vector — no line-of-
    action shift can absorb it; the full moment passes through."""
    force = Vector(0, 0, -1000.0)
    moment = Vector(0, 0, -250.0)
    shift, reduced = _assert_equivalent(force, moment)
    assert shift.Length == pytest.approx(0.0, abs=1e-12)
    assert (reduced - moment).Length < 1e-9


def test_free_moment_above_limit_is_not_shifted():
    """Parallel moment beyond free_m_limit: caller realizes the whole
    moment as a couple; no shift."""
    force = Vector(0, 0, -1000.0)
    moment = Vector(0, 500.0, 60.0)  # parallel part 60 > limit 50
    shift, reduced = _assert_equivalent(force, moment, limit=50.0)
    assert shift.Length == pytest.approx(0.0, abs=1e-12)
    assert (reduced - moment).Length < 1e-9


def test_no_force_returns_moment_unchanged():
    moment = Vector(3, -4, 5)
    shift, reduced = decompose_wrench(Vector(0, 0, 0), moment, 1.0, 50.0)
    assert shift.Length == pytest.approx(0.0, abs=1e-12)
    assert (reduced - moment).Length < 1e-9


class _CountingMesh:
    """A mesh whose node access is counted, like the real one's cost."""

    def __init__(self, nodes):
        self._nodes = nodes
        self.scans = 0

    @property
    def Nodes(self):
        self.scans += 1
        return self._nodes


def _jig(supports):
    class _Jig:
        Supports = supports

    return {"Object": _Jig()}


def _writer(jigs):
    class _Member:
        cons_jig321 = jigs

    class _Writer:
        member = _Member()

    return _Writer()


def test_jig321_support_nodes_finds_the_nearest_node():
    mesh = _CountingMesh({1: (0.0, 0.0, 0.0), 2: (0.0, 0.0, 5.0),
                          3: (10.0, 0.0, 0.0)})
    found = jig321_support_nodes(_writer([_jig([Vector(0.1, 0.0, 4.9)])]),
                                 mesh)
    assert found == {2}, "nearest node to the support position, got %r" % found


def test_jig321_support_nodes_walks_the_mesh_once_not_per_step():
    """The node search is remembered, so a batch step does not repeat it.

    The search visits every node of the mesh for every support position and
    this runs once per load step: left uncached, a batch deck spent minutes
    per step on a 77k-node part (measured ~2 minutes per step).
    """
    mesh = _CountingMesh({1: (0.0, 0.0, 0.0), 2: (0.0, 0.0, 5.0)})
    jigs = [_jig([Vector(0.0, 0.0, 5.0)])]
    writer = _writer(jigs)

    jig321_support_nodes(writer, mesh)
    after_first = mesh.scans
    jig321_support_nodes(writer, mesh)

    assert after_first == 1, "one walk per support position, got %d" % after_first
    assert mesh.scans == after_first, (
        "the second step re-walked the mesh (%d walks) - the result was not "
        "remembered on the constraint" % mesh.scans)


def test_exclude_jig321_nodes_removes_only_the_held_nodes():
    weights = {1: 1.0, 2: 1.0, 3: 1.0}
    removed = exclude_jig321_nodes(weights, {2, 3})
    assert removed == 2
    assert weights == {1: 1.0}, "only the held nodes may be dropped"


def test_excluding_every_node_empties_the_coupling():
    """The case the caller must refuse: a coupling with no nodes left.

    An emptied coupling is not an error the solver reports - the reaction
    is simply not applied, so the part is analysed unloaded and the result
    looks plausible.  The caller guards on a zero total weight, and this
    pins what that guard is guarding against.
    """
    weights = {1: 1.0, 2: 1.0}
    exclude_jig321_nodes(weights, {1, 2})
    assert weights == {}
    assert sum(weights.values()) <= 0.0


def test_scale_clamping():
    """Raw scales below 0 and above 1 clamp; in-range scales pass
    through proportionally.  Equivalence holds for every raw value."""
    force = Vector(0, 0, -1000.0)
    moment = Vector(0, 500.0, 0)
    for raw in (-0.5, 0.0, 0.5, 1.0, 2.0):
        _assert_equivalent(force, moment, scale=raw)
    # full absorption (clamped to 1.0): shift = M/F = 0.5 mm
    one = decompose_wrench(force, moment, 2.0, 50.0)[0]
    assert one.x == pytest.approx(500.0 / 1000.0, rel=1e-9)
    # half absorption: shift and residual moment split the perpendicular
    half_shift, half_moment = decompose_wrench(force, moment, 0.5, 50.0)
    assert half_shift.x == pytest.approx(0.25, rel=1e-9)
    assert half_moment.y == pytest.approx(250.0, rel=1e-9)
