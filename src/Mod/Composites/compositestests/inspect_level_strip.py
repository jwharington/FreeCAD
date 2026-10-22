# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Inspect whether the A14 level strip is level, station by station.

The level strip is the flat land a `fixed` skirt levelling leaves on the mould.
A14 exports it as two rings - P_level_in, the transition's far end on each ray,
and P_out, the wall base - and a land has both rings at one z at every station.
That is exactly what a groove sunk into the strip needs, so a strip whose rings
diverge in z is one no groove can be cut into.

This reads the rings through the same level_strip_stations() the fixture uses,
so it cannot disagree with what the groove sees. It prints each wall run's drop
(outboard z - inboard z) and plan width, names the stations that are not level
or have no plan width, and exits non-zero unless every station is level.

The box is the control: its land is flat, drop zero everywhere. The loft is the
case under diagnosis: it is drawn along its thickness, so its level plane is the
one normal to that draw.

A level strip is one flat land normal to the **draw direction**, so both of the
quantities this reads are taken in that plane:

- the **drop** is `(outboard - inboard)` projected onto the draw, which is zero
  on a land however that land happens to lie in world z;
- the **plan width** is the same vector with its draw component removed.

Measuring either on world x-y or world z is only right for a draw of world z —
which is what the box is, and the loft is not.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

import FreeCAD as App
import Part

from Composites.tools.mould_analysis import analyze_source_shape
from Composites.tools.mould_fixture import level_strip_stations
from Composites.tools.profile_mould_analysis import _make_loft_shape

# The benchmark shapes, sized as their examples build them: the 40 x 40 x 60 box
# of mould_fixture_groove.py, and the loft of mould_fixture_loft.py scaled by ten
# to the 262 x 52 x 320 mm its fixture defaults are chosen for.
BOX_SIZE_MM = (40.0, 40.0, 60.0)
LOFT_SCALE = 10.0

# In-plane stock around each shape. The box needs 25 mm to leave a 15 mm land;
# the loft needs the 60 mm its fixtures are sized for. The margin's z has no
# bearing on the strip, which is what the in-plane margin leaves.
BOX_STOCK_MM = 25.0
LOFT_STOCK_MM = 60.0

# The loft is drawn through its thickness (see mould_fixture_loft.py); the box is
# drawn along z, as its own example does.
BOX_DRAW = (0.0, 0.0, 1.0)
LOFT_DRAW = (0.0, 1.0, 0.0)

# The levelling the fixture asks for, and the one A14's level strip belongs to.
# `s-curve` is the mode under diagnosis: it is the one whose rays are Bezier
# transitions, and the one the fixture examples build with.
LEVELLING_MODE = "s-curve"
LEVELLING_EXTENT = "fixed"

# A `fixed` levelling takes its whole fall in the first 10 mm outboard of the
# cutline, so this is the strip's plan width before the wall's own run adds to it.
TRANSITION_MM = 10.0

# At or below this a drop counts as zero, and a plan width as no land at all.
DEFAULT_TOLERANCE_MM = 0.01


@dataclass(frozen=True)
class StripReading:
    """A strip's stations, with the drop and the plan width read off each.

    A drop is the outboard point less the inboard one, projected on the draw:
    zero wherever the strip is a landing, whatever its two rings do in world z.
    A plan width of zero means the two rings share a point in the parting plane,
    so the strip has no width across for a groove to sit in.
    """

    stations: tuple
    drops: tuple
    plan_widths: tuple

    @classmethod
    def of(cls, stations, draw):
        """Read `stations` against `draw`, as ``(inboard, outboard)`` pairs.

        Both quantities are measured in the parting plane, so `draw` has to be a
        unit vector — the case constants are.
        """
        drops = []
        plan_widths = []
        for point_in, point_out in stations:
            reach = point_out - point_in
            along = reach.dot(draw)
            drops.append(along)
            plan_widths.append((reach - draw * along).Length)
        return cls(tuple(stations), tuple(drops), tuple(plan_widths))

    def is_level_within(self, tolerance):
        """True when every station's two rings share their draw coordinate."""
        return all(abs(drop) <= tolerance for drop in self.drops)

    def not_level(self, tolerance):
        """The indices whose two rings are further apart in z than `tolerance`."""
        return tuple(index for index, drop in enumerate(self.drops)
                     if abs(drop) > tolerance)

    def with_no_land(self, tolerance):
        """The indices with no plan width across, so nothing to groove."""
        return tuple(index for index, width in enumerate(self.plan_widths)
                     if width <= tolerance)


def _say(text):
    """Print one line, flushed.

    FreeCADCmd leaves Python's stdout block-buffered and exits without
    flushing it, so a short run's whole report is discarded. Every line here
    is flushed so the report survives the process.
    """
    print(text, flush=True)


def _source_shape(case):
    """The benchmark shape for `case`, scaled as its example scales it."""
    if case == "loft":
        return _make_loft_shape().scaled(LOFT_SCALE)
    return Part.makeBox(*BOX_SIZE_MM)


def _case_setup(case):
    """``(draw, stock)`` for `case`, as its example sets them."""
    if case == "loft":
        return App.Vector(*LOFT_DRAW), LOFT_STOCK_MM
    return App.Vector(*BOX_DRAW), BOX_STOCK_MM


def analyze(case):
    """``(result, seconds)``: the analysis for `case`, in the fixture's own mode."""
    draw, stock = _case_setup(case)
    started = time.perf_counter()
    result = analyze_source_shape(
        _source_shape(case), draw,
        parting_stock_margin_x=stock, parting_stock_margin_y=stock,
        skirt_levelling=LEVELLING_MODE,
        skirt_levelling_extent=LEVELLING_EXTENT,
        skirt_levelling_transition_mm=TRANSITION_MM)
    return result, time.perf_counter() - started


def _print_walls(walls, reading):
    """Print each wall run's station count, drop range and in-plane width."""
    first = 0
    for wall in walls:
        count = len(wall["level_in_points"])
        window = slice(first, first + count)
        _say(f"  wall {wall['wall']:>2}: {count:4d} stations  "
             f"drop [{min(reading.drops[window]):8.3f}, "
             f"{max(reading.drops[window]):8.3f}] mm  "
             f"in-plane width [{min(reading.plan_widths[window]):8.3f}, "
             f"{max(reading.plan_widths[window]):8.3f}] mm")
        first += count


def _print_offenders(reading, tolerance):
    """Print the stations that are not level, and those with no land at all."""
    not_level = reading.not_level(tolerance)
    no_land = reading.with_no_land(tolerance)
    _say(f"\nstations not level (|drop along the draw| > {tolerance} mm): "
         f"{len(not_level)} {list(not_level)}")
    for index in not_level:
        point_in, point_out = reading.stations[index]
        _say(f"  {index:5d}  in=({point_in.x:9.3f}, {point_in.y:9.3f}, "
             f"{point_in.z:9.3f}) out=({point_out.x:9.3f}, "
             f"{point_out.y:9.3f}, {point_out.z:9.3f})  "
             f"drop={reading.drops[index]:8.3f}  "
             f"in-plane width={reading.plan_widths[index]:8.3f}")
    _say(f"stations with no in-plane width (nothing to groove): "
         f"{len(no_land)} {list(no_land)}")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        default="loft",
        choices=("box", "loft"),
        help="Benchmark case to inspect. The box is the control, whose land is "
             "flat; the loft is the case under diagnosis.",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TOLERANCE_MM,
        metavar="MM",
        help="Drop at or below which a station counts as level, and plan width "
             "at or below which it counts as having no land. Defaults to "
             "%(default)s mm.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    result, seconds = analyze(args.case)

    stations = level_strip_stations(result["level_strip_in_shape"],
                                    result["level_strip_out_shape"])
    walls = (result["parting_level_strips"] or {}).get("walls", ())
    draw, _stock = _case_setup(args.case)
    reading = StripReading.of(stations, draw)

    _say(f"case {args.case}: {LEVELLING_MODE}/{LEVELLING_EXTENT} "
         f"t={TRANSITION_MM:g} mm, {len(walls)} wall runs, {len(stations)} "
         f"stations, analysis {seconds:.1f} s")
    _say(f"summary: {result['level_strip_summary']}")
    _print_walls(walls, reading)
    _print_offenders(reading, args.tolerance)

    level = reading.is_level_within(args.tolerance)
    _say(f"\nVERDICT case {args.case}: {'LEVEL' if level else 'NOT LEVEL'}")
    return 0 if level else 1


if __name__ == "__main__":
    raise SystemExit(main())
