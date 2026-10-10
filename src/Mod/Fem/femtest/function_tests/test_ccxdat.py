# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Reading CalculiX's per-step eigenvalue tables out of a ``.dat``.

The solver writes a buckling-factor or frequency table per load step, and
nothing else ties a table to the case it belongs to, so a second table or a
missing one is the difference between the answer for lc03 and some other
case wearing lc03's name.

The single-step inputs are FreeCAD's own real CalculiX output; the multi-step
files are those same ccx-written rows with the spaced ``S T E P`` heads ccx
writes between them put back in.
"""

import os

import pytest

from feminout import ccxdat

_DATA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "calculix"
)
_BUCKLING_DAT = os.path.join(_DATA, "ccx_buckling_flexuralbuckling.dat")
_FREQUENCY_DAT = os.path.join(_DATA, "box_frequency.dat")

_BUCKLING_FACTORS = [
    53.53773,
    112.3524,
    442.9172,
    840.6785,
    1066.613,
    1760.44,
    1781.06,
    2428.616,
    2625.109,
    3032.522,
]

# Rows exactly as CalculiX wrote them for a real run (a two-element
# cantilever): modes 1-3 came out imaginary, mode 4 real.
_IMAGINARY_ROWS = [
    "      1  -0.1007441E-03   0.0000000E+00   0.0000000E+00   0.1003713E-01",
    "      2  -0.5621660E-04   0.0000000E+00   0.0000000E+00   0.7497773E-02",
    "      3  -0.1949123E-04   0.0000000E+00   0.0000000E+00   0.4414888E-02",
    "      4   0.9025146E-06   0.9500077E-03   0.1511984E-03   0.0000000E+00",
]


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _step(step, text):
    return " " * 24 + "S T E P       %d\n" % step + text


def _frequency_table(rows):
    return (" " * 5 + "E I G E N V A L U E   O U T P U T\n"
            + "\n".join(rows) + "\n")


@pytest.fixture
def write(tmp_path):
    def writer(text, name="case.dat"):
        path = tmp_path / name
        path.write_text(text)
        return str(path)
    return writer


# --- buckling ---------------------------------------------------------------


def test_real_buckling_dat_is_read_under_step_one():
    """A trimmed single-step ``.dat`` has no ``S T E P`` head; its table is
    still step 1's, and every factor is read in mode order."""
    assert ccxdat.buckling_factors_by_step(_BUCKLING_DAT) == {
        1: pytest.approx(_BUCKLING_FACTORS)
    }


def test_one_case_takes_the_only_table():
    got = ccxdat.buckling_factors_for_cases(_BUCKLING_DAT, ["flexural"])
    assert got["flexural"] == pytest.approx(_BUCKLING_FACTORS)


def test_each_step_keeps_its_own_table(write):
    """The same real rows under two ``S T E P`` heads must not merge: a deck
    with one step per load case gets one table per case."""
    text = _read(_BUCKLING_DAT)
    path = write(_step(1, text) + _step(2, text))
    got = ccxdat.buckling_factors_by_step(path)
    assert sorted(got) == [1, 2]
    assert got[1] == pytest.approx(_BUCKLING_FACTORS)
    assert got[2] == pytest.approx(_BUCKLING_FACTORS)


def test_cases_are_paired_with_steps_in_order(write):
    text = _read(_BUCKLING_DAT)
    path = write(_step(1, text) + _step(2, text))
    got = ccxdat.buckling_factors_for_cases(path, ["lc01", "lc03"], modes=10)
    assert list(got) == ["lc01", "lc03"]


def test_a_surplus_table_is_refused(write):
    """One table per case is the claim being made; a second means the deck had
    a step nobody named and pairing would be guesswork."""
    text = _read(_BUCKLING_DAT)
    path = write(_step(1, text) + _step(2, text))
    with pytest.raises(RuntimeError, match=r"tables for step \[1, 2\]"):
        ccxdat.buckling_factors_for_cases(path, ["lc01"], modes=10)


def test_a_missing_table_is_refused(write):
    path = write(_step(1, _read(_BUCKLING_DAT)))
    with pytest.raises(RuntimeError, match=r"tables for steps \[1\]"):
        ccxdat.buckling_factors_for_cases(path, ["lc01", "lc02"], modes=10)


def test_a_gap_in_the_mode_numbering_is_refused(write):
    """Mode 3 after mode 1 is a truncated block; reading it as mode 2's value
    would mis-name every mode after the gap."""
    text = _read(_BUCKLING_DAT).replace("      2   0.1123524E+03\n", "")
    path = write(text)
    with pytest.raises(RuntimeError, match=r"not contiguous"):
        ccxdat.buckling_factors_by_step(path)


# --- frequency --------------------------------------------------------------


def test_real_frequency_dat_gives_the_hertz_calculix_means():
    modes = ccxdat.frequencies_by_step(_FREQUENCY_DAT)[1]
    assert modes[0]["hz"] == pytest.approx(0.5428201e05)
    assert not modes[0]["imaginary"]
    assert ccxdat.mode_text(modes[0]) == "54282.01 Hz"


def test_one_imaginary_mode_is_not_called_zero_hertz(write):
    modes = ccxdat.frequencies_by_step(
        write(_frequency_table(_IMAGINARY_ROWS)))[1]
    assert [ccxdat.mode_text(mode) for mode in modes[:3]] == [
        "imaginary", "imaginary", "imaginary"]
    assert modes[3]["hz"] == pytest.approx(0.1511984e-03)
    assert not modes[3]["imaginary"]


def test_imaginary_modes_lead_the_lowest(write):
    modes = ccxdat.modes_for_run(
        write(_frequency_table(_IMAGINARY_ROWS)))
    assert [ccxdat.mode_text(mode)
            for mode in ccxdat.lowest(modes, 2)] == ["imaginary", "imaginary"]


def test_a_frequency_deck_with_a_step_per_case_is_refused(write):
    """A batch deck asks one question twice and expects two answers."""
    single = _frequency_table(_IMAGINARY_ROWS)
    path = write(_step(1, single) + _step(2, single))
    with pytest.raises(RuntimeError, match=r"one step but tables were written"):
        ccxdat.modes_for_run(path)


def test_fewer_modes_than_asked_is_refused(write):
    modes = ccxdat.modes_for_run(write(_frequency_table(_IMAGINARY_ROWS)),
                                 requested=4)
    assert len(modes) == 4
    with pytest.raises(RuntimeError, match=r"4 of 5 requested modes"):
        ccxdat.modes_for_run(write(_frequency_table(_IMAGINARY_ROWS)),
                             requested=5)
