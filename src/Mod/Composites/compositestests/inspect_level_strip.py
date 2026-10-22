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
or have no plan width, and exits non-zero unless the strip is level — one
plane normal to the draw, which means the draw coordinate is constant along
each chain, not merely equal between the two chains at each station.

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
from pathlib import Path

import FreeCAD as App
import Part

from Composites.tools.mould_analysis import (
    DEFAULT_TESSELLATION_BAND_TOL_DEG,
    analyze_source_shape,
    default_mould_analysis_draw_direction,
)
from Composites.tools.mould_fixture import level_strip_stations
from Composites.compositeexamples.examples import (
    mould_fixture_groove,
    mould_fixture_loft,
)
from Composites.tools.profile_mould_analysis import _make_loft_shape

# The benchmark shapes, sized as their examples build them: the 40 x 40 x 60 box
# of mould_fixture_groove.py, and the loft of mould_fixture_loft.py scaled by ten
# to the 262 x 52 x 320 mm its fixture defaults are chosen for.
# Read off the examples that build them, never restated: a control that is not
# the example's own shape is not a control. The first version of this file asserted
# a 40 x 40 x 60 box with 25 mm of stock, and no example builds that.
BOX_SIZE_MM = mould_fixture_groove.PART_SIZE
LOFT_SCALE = mould_fixture_loft.LOFT_SCALE

# In-plane stock around each shape. The box needs 25 mm to leave a 15 mm land;
# the loft needs the 60 mm its fixtures are sized for. The margin's z has no
# bearing on the strip, which is what the in-plane margin leaves.
BOX_STOCK_MM = mould_fixture_groove.STOCK_MARGIN
LOFT_STOCK_MM = mould_fixture_loft.STOCK_MARGIN

# The loft is drawn through its thickness (see mould_fixture_loft.py); the box is
# drawn along z, as its own example does.
# The box example sets no draw of its own, so the FP's default is the box's;
# the loft's is its own example's.
BOX_DRAW = default_mould_analysis_draw_direction
LOFT_DRAW = mould_fixture_loft.DRAW

# The knobs the mould examples set, and the FP's defaults, so this analyses the
# mould they build rather than the binding's defaults: both examples take their
# part line from HLR (the tessellation march does not close every shape), and the
# FP's part-line tolerance is 0.1 mm with its band at DEFAULT_TESSELLATION_BAND_TOL_DEG.
PART_LINE_SOURCE = "hlr"
PART_LINE_TOLERANCE = 0.1

# The levelling methods, so a run can be asked for each of them: A14's level
# strip exists for the `fixed` extent only, and which method actually leaves the
# rail in one plane is the question, not an assumption.
LEVELLING_METHODS = ("s-curve", "direct", "off")
LEVELLING_EXTENTS = ("fixed", "whole")
DEFAULT_LEVELLING = mould_fixture_loft.LEVELLING
DEFAULT_EXTENT = mould_fixture_loft.LEVELLING_EXTENT

# A `fixed` levelling takes its whole fall in the first 10 mm outboard of the
# cutline, so this is the strip's plan width before the wall's own run adds to it.
TRANSITION_MM = mould_fixture_loft.LEVELLING_TRANSITION_MM

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
    in_draw: tuple
    out_draw: tuple

    @classmethod
    def of(cls, stations, draw):
        """Read `stations` against `draw`, as ``(inboard, outboard)`` pairs.

        Every quantity is measured in the parting plane, so `draw` has to be a
        unit vector — the case constants are.
        """
        drops = []
        plan_widths = []
        in_draw = []
        out_draw = []
        for point_in, point_out in stations:
            reach = point_out - point_in
            along = reach.dot(draw)
            drops.append(along)
            plan_widths.append((reach - draw * along).Length)
            in_draw.append(point_in.dot(draw))
            out_draw.append(point_out.dot(draw))
        return cls(tuple(stations), tuple(drops), tuple(plan_widths),
                   tuple(in_draw), tuple(out_draw))

    def plane_spread(self):
        """``(inboard, outboard)`` spread of the draw coordinate, in mm.

        This is the whole-chain number. A level strip lies in one plane normal
        to the draw, so both are zero: every point of each chain at one draw
        coordinate. The station-by-station drop is a different property and does
        not imply it — two chains can agree with each other everywhere and still
        walk up and down together.
        """
        if not self.in_draw:
            return 0.0, 0.0
        return (max(self.in_draw) - min(self.in_draw),
                max(self.out_draw) - min(self.out_draw))

    def is_level_within(self, tolerance):
        """True when each chain lies in one plane and the two share it.

        An empty strip is not level: there is no land to be one.
        """
        if not self.stations:
            return False
        in_spread, out_spread = self.plane_spread()
        if max(in_spread, out_spread) > tolerance:
            return False
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
        return LOFT_DRAW, LOFT_STOCK_MM
    return BOX_DRAW, BOX_STOCK_MM


@dataclass(frozen=True)
class Levelling:
    """The levelling a run is asked for: method, extent and transition."""

    mode: str = DEFAULT_LEVELLING
    extent: str = DEFAULT_EXTENT
    transition_mm: float = TRANSITION_MM


def analyze(case, levelling=Levelling()):
    """``(result, seconds)``: the analysis for `case`, as its example configures it.

    The arguments are the mould examples' own property values, translated the way
    MouldAnalysis.execute() translates them, so what this measures is what they
    build — same part-line source, same stock on all three axes, same tolerances,
    same levelling.
    """
    draw, stock = _case_setup(case)
    started = time.perf_counter()
    result = analyze_source_shape(
        _source_shape(case), draw,
        parting_stock_margin_x=stock, parting_stock_margin_y=stock,
        parting_stock_margin_z=stock,
        parting_line_tolerance=PART_LINE_TOLERANCE,
        parting_tessellation_band_tol_deg=DEFAULT_TESSELLATION_BAND_TOL_DEG,
        part_line_source=PART_LINE_SOURCE,
        skirt_levelling=levelling.mode,
        skirt_levelling_extent=levelling.extent,
        skirt_levelling_transition_mm=levelling.transition_mm)
    return result, time.perf_counter() - started


def _save_document(case, result, path):
    """Write the analysed mould to `path`, for looking at rather than reading.

    Source, both halves and both strip rings, every shape the analysis's own, so
    the saved document opens without recomputing anything. That is the point of
    it: the solve has already happened here, and a GUI that re-runs it cannot be
    used while it does.
    """
    document = App.newDocument("LevelStrip")
    shapes = [("Source", _source_shape(case)),
              ("MouldHalfA", result["mould_half_a_shape"]),
              ("MouldHalfB", result["mould_half_b_shape"]),
              ("LevelStripIn", result["level_strip_in_shape"]),
              ("LevelStripOut", result["level_strip_out_shape"])]
    for name, shape in shapes:
        obj = document.addObject("Part::Feature", name)
        obj.Shape = shape
    # The land itself: the ruled band the two exported chains bound. It is what
    # the levelling makes, and the one thing a picture of this mould has to show,
    # since the chains alone are thin rings inside the block's silhouette.
    try:
        land = Part.makeLoft([result["level_strip_in_shape"],
                              result["level_strip_out_shape"]], False, True)
    except Exception as exc:  # a band that will not loft is worth knowing about
        _say(f"land   : could not be lofted ({exc})")
        land = None
    if land is not None and not land.isNull():
        obj = document.addObject("Part::Feature", "Land")
        obj.Shape = land
        _say(f"land   : {len(land.Faces)} faces, area {land.Area:.1f} mm^2")
    document.recompute()
    path.parent.mkdir(parents=True, exist_ok=True)
    document.saveAs(str(path))
    return document


def _print_walls(walls, reading):
    """Print each wall run's station count, drop range and in-plane width."""
    first = 0
    for wall in walls:
        count = len(wall["level_in_points"])
        window = slice(first, first + count)
        in_spread = max(reading.in_draw[window]) - min(reading.in_draw[window])
        out_spread = max(reading.out_draw[window]) - min(reading.out_draw[window])
        _say(f"  wall {wall['wall']:>2}: {count:4d} stations  "
             f"plane spread in/out [{in_spread:8.3f} /{out_spread:8.3f}] mm  "
             f"drop [{min(reading.drops[window]):7.3f}, "
             f"{max(reading.drops[window]):7.3f}] mm  "
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
        "--levelling",
        default=DEFAULT_LEVELLING,
        choices=LEVELLING_METHODS,
        help="Levelling method to ask for. Defaults to %(default)s.",
    )
    parser.add_argument(
        "--extent",
        default=DEFAULT_EXTENT,
        choices=LEVELLING_EXTENTS,
        help="Levelling extent; `whole` produces no level strip at all. "
             "Defaults to %(default)s.",
    )
    parser.add_argument(
        "--save-document",
        type=Path,
        default=None,
        metavar="OUT.FCStd",
        help="Also write the analysed mould - source, both halves and both "
             "strip rings - to this .FCStd, so it can be opened and looked at "
             "without recomputing the solve. No fixtures: they are the "
             "expensive part and they are not what the strip is.",
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
    levelling = Levelling(args.levelling, args.extent)
    result, seconds = analyze(args.case, levelling)

    stations = level_strip_stations(result["level_strip_in_shape"],
                                    result["level_strip_out_shape"])
    walls = (result["parting_level_strips"] or {}).get("walls", ())
    draw, _stock = _case_setup(args.case)
    reading = StripReading.of(stations, draw)

    _say(f"case {args.case}: {levelling.mode}/{levelling.extent} "
         f"t={levelling.transition_mm:g} mm, {len(walls)} wall runs, "
         f"{len(stations)} stations, analysis {seconds:.1f} s")
    _say(f"summary: {result['level_strip_summary']}")
    # The halves' volumes say whether the levelling reached the mould itself or
    # only the export: a levelled land takes material off the block, so two
    # levelling methods that differ must not weigh the same.
    _say(f"halves  : A {result['mould_half_a_shape'].Volume:.0f} mm^3, "
         f"B {result['mould_half_b_shape'].Volume:.0f} mm^3")
    _print_walls(walls, reading)
    _print_offenders(reading, args.tolerance)

    if not stations:
        _say(f"\nVERDICT case {args.case}: NO STRIP — "
             f"{result['level_strip_summary']}")
        return 1

    in_spread, out_spread = reading.plane_spread()
    _say(f"\nplane   : draw coordinate spread over all {len(stations)} stations — "
         f"inboard {in_spread:.3f} mm, outboard {out_spread:.3f} mm")
    _say("          (a level strip is one plane: these must be 0, not merely "
         "equal to each other)")

    if args.save_document is not None:
        _save_document(args.case, result, args.save_document)
        _say(f"document: {args.save_document}")

    level = reading.is_level_within(args.tolerance)
    _say(f"\nVERDICT case {args.case}: {'LEVEL' if level else 'NOT LEVEL'}")
    return 0 if level else 1


if __name__ == "__main__":
    raise SystemExit(main())
