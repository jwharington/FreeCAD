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
shift_scale 1, delivers the NEGATED moment.  Found on the LS8e aft
fuselage: ultimate nose-up moment My = +1602 N·mm... N·mm→N·m scaled
case delivered −1602; the verification parse of the written *CLOAD
caught it.
"""

import FreeCAD
import pytest

from femsolver.calculix.write_constraint_pressure_reaction import (
    decompose_wrench,
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


def test_fuselage_bending_case_shifts_toward_plus_x():
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
