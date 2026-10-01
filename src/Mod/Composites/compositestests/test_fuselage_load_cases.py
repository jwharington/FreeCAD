# SPDX-License-Identifier: LGPL-2.1-or-later
"""Unit tests for the fuselage critical CS-22 load cases.

CASES_ULTIMATE (FuselageFem.py) transcribes the non-dominated frontier of
ultimate resultants at the fin-base leading edge from
Design/Structure/critical-load-cases.md — 26 rule cases enveloped by 6:
three governing families (rudder, gust, combined), each in both signs
because the airframe is symmetric.  The model mirrors the design axes
(model point = (-x, y, -z)), so components transform
(-Fx, Fy, -Fz, -Mx, My, -Mz).  These tests pin the transcription and the
axis transform — a sign error here is the sideways-load bug again.
"""

import importlib.util
import os
import sys

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


def test_default_case_is_gust_up(ff):
    """LC-03 (gust HLW V_B up) is the default: vertical bending is what
    the engine-bay cutout and its reinforcement band are sized against."""
    assert ff.SELECTED_CASE == "lc03"
    for comp in ("Fx", "Fy", "Mx", "Mz"):
        assert ff.LOAD_CASE[comp] == 0.0


def test_case_frontier_transcribed_verbatim(ff):
    """The six ultimate rows, design coords, exactly as published."""
    expected = {
        "lc01": {"Fy": 3658.0, "Mx": 2588.0, "Mz": -988.0},
        "lc02": {"Fy": -3658.0, "Mx": -2588.0, "Mz": 988.0},
        "lc03": {"Fz": -2168.0, "My": -1019.0},
        "lc04": {"Fz": 2168.0, "My": 1019.0},
        "lc05": {"Fy": 2744.0, "Fz": -1613.0, "Mx": 2249.0,
                 "My": -758.0, "Mz": -741.0},
        "lc06": {"Fy": -2744.0, "Fz": -1613.0, "Mx": -2249.0,
                 "My": -758.0, "Mz": 741.0},
    }
    for name, row in expected.items():
        for comp, value in row.items():
            assert ff.CASES_ULTIMATE[name][comp] == pytest.approx(value), (
                "%s/%s" % (name, comp))
        for comp in ("Fx", "Fy", "Fz", "Mx", "My", "Mz"):
            assert ff.CASES_ULTIMATE[name].get(comp, 0.0) == pytest.approx(
                row.get(comp, 0.0)), "%s/%s absent-but-nonzero" % (name, comp)


def test_mirror_cases_are_y_antisymmetric(ff):
    """The airframe is symmetric: the ±side pairs (rudder, combined)
    negate exactly the y-odd components (Fy, Mx, Mz) and keep Fz and My."""
    for pos, neg in (("lc01", "lc02"), ("lc05", "lc06")):
        for comp in ("Fy", "Mx", "Mz"):
            assert ff.CASES_ULTIMATE[pos].get(comp, 0.0) == pytest.approx(
                -ff.CASES_ULTIMATE[neg].get(comp, 0.0)), "%s/%s" % (pos, comp)
        for comp in ("Fz", "My"):
            assert ff.CASES_ULTIMATE[pos].get(comp, 0.0) == pytest.approx(
                ff.CASES_ULTIMATE[neg].get(comp, 0.0)), "%s/%s" % (pos, comp)


def test_gust_pair_reverses_whole_load(ff):
    """The gust up/down pair is not a mirror — the whole load reverses,
    so every nonzero component changes sign."""
    for comp in ("Fz", "My"):
        assert ff.CASES_ULTIMATE["lc03"][comp] == pytest.approx(
            -ff.CASES_ULTIMATE["lc04"][comp]), comp


def test_rudder_case_transforms_side_terms(ff, monkeypatch):
    """LC-01 in model coords: design Fy+ right (unchanged), Mx+ roll
    right and Mz- flip sign."""
    monkeypatch.setattr(ff, "SELECTED_CASE", "lc01")
    lc = ff._build_load_case()
    assert lc["Fy"] == pytest.approx(3658.0)
    assert lc["Mx"] == pytest.approx(-2588.0)
    assert lc["Mz"] == pytest.approx(+988.0)
    assert lc["Fz"] == 0.0


def test_gust_up_is_upward_in_model_axes(ff, monkeypatch):
    """Design z+ points DOWN, so LC-03's Fz -2168 is an upward tail load
    and becomes +Fz in the model; My keeps its sign (My+ is nose-up in
    both frames)."""
    monkeypatch.setattr(ff, "SELECTED_CASE", "lc03")
    lc = ff._build_load_case()
    assert lc["Fz"] == pytest.approx(+2168.0)
    assert lc["My"] == pytest.approx(-1019.0)


def test_gust_down_is_the_reverse(ff, monkeypatch):
    monkeypatch.setattr(ff, "SELECTED_CASE", "lc04")
    lc = ff._build_load_case()
    assert lc["Fz"] == pytest.approx(-2168.0)
    assert lc["My"] == pytest.approx(+1019.0)


def test_combined_case_upward_force_and_flipped_torsion(ff, monkeypatch):
    """LC-05 in model coords: design Fz -1613 is upward → model +Fz;
    design Mx +2249 flips; design My -758 keeps its sign; Mz -741 flips."""
    monkeypatch.setattr(ff, "SELECTED_CASE", "lc05")
    lc = ff._build_load_case()
    assert lc["Fz"] == pytest.approx(+1613.0)
    assert lc["Fy"] == pytest.approx(+2744.0)
    assert lc["Mx"] == pytest.approx(-2249.0)
    assert lc["My"] == pytest.approx(-758.0)
    assert lc["Mz"] == pytest.approx(+741.0)


def test_unknown_case_name_fails_loudly(ff, monkeypatch):
    monkeypatch.setattr(ff, "SELECTED_CASE", "typo_case")
    with pytest.raises(RuntimeError, match="typo_case"):
        ff._build_load_case()


def test_env_override_wins_over_case(ff, monkeypatch):
    monkeypatch.setattr(ff, "SELECTED_CASE", "lc03")
    monkeypatch.setenv("FUSELAGE_FZ", "1000.0")
    monkeypatch.setenv("FUSELAGE_MX", "-500.0")
    lc = ff._build_load_case()
    assert lc["Fz"] == pytest.approx(1000.0)
    assert lc["Mx"] == pytest.approx(-500.0)
    assert lc["My"] == pytest.approx(-1019.0)  # untouched term survives


def test_fin_base_reference_is_the_boom_crown_at_frame_5(ff):
    """Design (-3070, 0, -4) — crown of the boom at frame_5 — maps to
    model (+3070, 0, +4) under (x, y, z) → (-x, y, -z)."""
    v = ff.FIN_BASE_MODEL
    assert (v.x, v.y, v.z) == pytest.approx((3070.0, 0.0, 4.0))
