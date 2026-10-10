# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""The eigenvalue tables CalculiX writes per load step in its ``.dat``.

Both kinds of eigenvalue run — buckling factors and natural frequencies —
arrive the same way: one table per step, titled with spaced capitals, one row
per mode.  Nothing in the result files ties a table to the load case it
belongs to, so the scan is shared here and the two readers differ only in what
a row means.

A missing table is not skipped and a surplus is not truncated: either shifts
every later number onto the wrong case, which is worse than no answer, so both
abort.  Mode numbers inside a table must run 1..n without a gap, for the same
reason — reading past a truncated block would attribute mode 3's value to
mode 2.

CalculiX writes a spaced ``S T E P <n>`` head before each step's tables.  A
table with no such head in front of it — a single-step run trimmed down to the
tables, as FreeCAD's own test data is — belongs to step 1.
"""

import re

_STEP_HEAD = re.compile(r"^\s+S\s+T\s+E\s+P\s+(\d+)\s*$")

_BUCKLING_TABLE_HEAD = "B U C K L I N G   F A C T O R   O U T P U T"
_BUCKLING_ROW = re.compile(r"^\s*(\d+)\s+([-+0-9.eE]+)\s*$")

_FREQUENCY_TABLE_HEAD = "E I G E N V A L U E   O U T P U T"
_NUMBER = r"[-+0-9.eE]+"
_FREQUENCY_ROW = re.compile(r"^\s*(\d+)((?:\s+%s){4})\s*$" % _NUMBER)

_FIRST_STEP = 1


def step_tables(path, head, row_of):
    """``{step number: [value per mode]}`` from one CalculiX ``.dat``.

    ``head`` is the table's own spaced title and ``row_of`` turns a line into
    ``(mode, value)`` or ``None``.  A table is filed under the step of the
    nearest preceding ``S T E P`` head, or under step 1 when none precedes it.
    """
    by_step = {}
    step = None
    reading = False
    table_step = _FIRST_STEP
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            found = _STEP_HEAD.match(line)
            if found:
                step = int(found.group(1))
                continue
            if head in line:
                table_step = _FIRST_STEP if step is None else step
                by_step[table_step] = []
                reading = True
                continue
            if not reading:
                continue
            row = row_of(line)
            if row is None:
                # Between the table's own title and its first row sit the
                # column headings and a blank; text there is still the table.
                # Once rows have started, the next line with text is the next
                # section and the table is over.
                if by_step[table_step] and line.strip():
                    reading = False
                continue
            mode, value = row
            rows = by_step[table_step]
            if mode != len(rows) + 1:
                raise RuntimeError(
                    "step %d: mode %d follows %d rows in %s — the mode "
                    "numbering is not contiguous, so no row can be named"
                    % (table_step, mode, len(rows), path))
            rows.append(value)
    return {step: rows for step, rows in by_step.items() if rows}


def _buckling_row(line):
    """``(mode, factor)`` from a buckling table row, or ``None``."""
    match = _BUCKLING_ROW.match(line)
    if not match:
        return None
    return int(match.group(1)), float(match.group(2))


def buckling_factors_by_step(path):
    """``{step number: [λ in mode order]}`` from one CalculiX ``.dat``.

    Steps are keyed by the number ccx printed rather than by position, so a
    deck that died at step 3 yields three steps instead of three plausible
    ones.
    """
    return step_tables(path, _BUCKLING_TABLE_HEAD, _buckling_row)


def buckling_factors_for_cases(path, cases, modes=None):
    """``{case name: [λ …]}`` with the case-to-step pairing asserted.

    One step per case, in ``cases`` order — the same mapping the deck's step
    order was written in.  A missing table is not skipped and a surplus is not
    truncated: both shift every later λ onto the wrong case, which is worse
    than no answer, so they abort instead.
    """
    by_step = buckling_factors_by_step(path)
    if sorted(by_step) != list(range(1, len(cases) + 1)):
        raise RuntimeError(
            "%d load case%s but buckling tables for step%s %s in %s — λ "
            "cannot be assigned to cases"
            % (len(cases), "" if len(cases) == 1 else "s",
               "" if len(cases) == 1 else "s",
               sorted(by_step), path))
    if modes is not None:
        for step, values in by_step.items():
            if len(values) < modes:
                raise RuntimeError(
                    "step %d returned %d of %d requested modes in %s — fewer "
                    "than asked for means the eigen-solve did not converge, "
                    "not that the structure is stiff"
                    % (step, len(values), modes, path))
    return {case: by_step[step] for step, case in enumerate(cases, start=1)}


def _frequency_row(line):
    """``(mode, {eigenvalue, hz, imaginary})`` from a frequency table row.

    Five fields is this table; any other count is a different one, and a row
    of the wrong shape is not silently a mode.  The row carries eigenvalue,
    the circular frequency, that divided by 2π in cycles/time, and the
    imaginary part — the third field is the hertz.  FreeCAD's own reader
    slices out that column and ignores the fourth, which turns an unstable
    mode into 0.00 Hz.
    """
    match = _FREQUENCY_ROW.match(line)
    if not match:
        return None
    eigenvalue, _circular, hz, imag = (float(field)
                                       for field in match.group(2).split())
    return int(match.group(1)), {
        "eigenvalue": eigenvalue,
        "hz": hz,
        "imaginary": bool(hz == 0.0 and imag != 0.0),
    }


def mode_text(mode):
    """How to say one frequency mode out loud, real frequency or not."""
    return ("%.2f Hz" % mode["hz"] if not mode["imaginary"]
            else "imaginary")


def frequencies_by_step(path):
    """``{step number: [mode in order]}`` from one CalculiX ``.dat``."""
    return step_tables(path, _FREQUENCY_TABLE_HEAD, _frequency_row)


def modes_for_run(path, requested=None):
    """``[mode in order]`` from a frequency deck, which has one step.

    Natural frequencies are a property of the article — of its stiffness and
    its mass — so a frequency run is written as one step and no load.  More
    than one table means the deck was written as a batch, which would ask the
    same question once per load case and answer it the same way every time.
    Fewer modes than were asked for means the eigen-solve did not converge,
    not that the structure is stiff.
    """
    by_step = frequencies_by_step(path)
    if sorted(by_step) != [1]:
        raise RuntimeError(
            "a frequency deck has one step but tables were written for step%s "
            "%s in %s — natural frequencies belong to the article, not to a "
            "load case" % ("" if len(by_step) <= 1 else "s", sorted(by_step),
                           path))
    modes = by_step[1]
    if requested is not None and len(modes) < requested:
        raise RuntimeError(
            "the run returned %d of %d requested modes in %s — fewer than "
            "asked for means the eigen-solve did not converge, not that the "
            "structure is stiff" % (len(modes), requested, path))
    return modes


def lowest(modes, count):
    """The ``count`` lowest-frequency modes, imaginary ones first.

    An imaginary mode leads the list rather than dropping off the bottom of
    it: it means the structure cannot vibrate in that shape at all, which is
    not something to leave out because it has no hertz to sort by.
    """
    return sorted(modes, key=lambda mode: (not mode["imaginary"],
                                          mode["hz"]))[:count]
