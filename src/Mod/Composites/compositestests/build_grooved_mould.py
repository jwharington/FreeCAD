# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Build a levelled mould with its O-ring groove, and save it as .FCStd.

The fixture example builds the whole fitting set. On the lofted part that runs
for minutes — nine, measured, with the levelling and the groove on — and the
fittings are not what the groove is: the groove is one channel cut along the
level strip. This builds the same levelled mould, cuts only that groove, and
saves the document, so the thing worth looking at can be looked at without
waiting for the clamps.

Every other fitting is switched off, so the status reported here is the groove's
own: a mould with no level strip fails for that reason and no other.

Run it through the headless wrapper:

    run-script.sh src/Mod/Composites/compositestests/build_grooved_mould.py \
        --case loft --out /tmp/mould_grooved.FCStd
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import FreeCAD as App
import Part

from Composites.compositestests.inspect_level_strip import (
    _case_setup,
    _source_shape,
    analyze,
)
from Composites.tools.mould_fixture import (
    AlignmentParams,
    ClampingParams,
    FixtureRequest,
    PortParams,
    SealGrooveParams,
    WedgeParams,
    build_fixtures,
)

DEFAULT_CORD_MM = 3.0


def _say(text):
    """Print one line, flushed: FreeCADCmd discards buffered stdout at exit."""
    print(text, flush=True)


def _groove_halves(result, draw, cord):
    """``(fixture result, seconds)`` for the seal groove alone."""
    request = FixtureRequest(
        lower=result["mould_half_a_shape"],
        upper=result["mould_half_b_shape"],
        draw=draw,
        alignment=AlignmentParams(enabled=False),
        clamping=ClampingParams(bolts_enabled=False, ears_enabled=False),
        ports=PortParams(enabled=False),
        wedges=WedgeParams(enabled=False),
        seal_groove=SealGrooveParams(enabled=True, cord_diameter=cord),
        level_strip_in=result["level_strip_in_shape"],
        level_strip_out=result["level_strip_out_shape"])
    started = time.perf_counter()
    return build_fixtures(request), time.perf_counter() - started


def _land(result):
    """The levelled land: the ruled band the two exported chains bound."""
    try:
        land = Part.makeLoft([result["level_strip_in_shape"],
                              result["level_strip_out_shape"]], False, True)
    except Exception as exc:
        _say(f"land    : could not be lofted ({exc})")
        return None
    return None if land.isNull() else land


def _save(case, result, cut, path):
    """Write the mould, its groove, the strip it sits on and the land itself."""
    document = App.newDocument("GroovedMould")
    shapes = [("Source", _source_shape(case)),
              ("MouldHalfA", result["mould_half_a_shape"]),
              ("MouldHalfB", result["mould_half_b_shape"]),
              ("LowerWithGroove", cut["lower_shape"]),
              ("UpperWithGroove", cut["upper_shape"]),
              ("LevelStripIn", result["level_strip_in_shape"]),
              ("LevelStripOut", result["level_strip_out_shape"])]
    land = _land(result)
    if land is not None:
        shapes.append(("Land", land))
        _say(f"land    : {len(land.Faces)} faces, area {land.Area:.1f} mm^2")
    for name, shape in shapes:
        obj = document.addObject("Part::Feature", name)
        obj.Shape = shape
    document.recompute()
    path.parent.mkdir(parents=True, exist_ok=True)
    document.saveAs(str(path))
    return document


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        default="loft",
        choices=("box", "loft"),
        help="Benchmark case to build. Defaults to %(default)s.",
    )
    parser.add_argument(
        "--cord",
        type=float,
        default=DEFAULT_CORD_MM,
        metavar="MM",
        help="O-ring cord diameter the groove is sized from. Defaults to "
             "%(default)s mm.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="OUT.FCStd",
        help="Where to write the document. Defaults to the temporary directory "
             "as mould_<case>_grooved.FCStd.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    out_path = args.out or Path("/tmp") / f"mould_{args.case}_grooved.FCStd"

    result, analysis_seconds = analyze(args.case)
    draw, _stock = _case_setup(args.case)
    _say(f"analysis: {analysis_seconds:.1f} s  ({args.case}, s-curve/fixed levelling)")

    cut, groove_seconds = _groove_halves(result, draw, args.cord)
    _say(f"groove  : {groove_seconds:.1f} s  status={cut['status']}  "
         f"grooves={cut['seal_grooves']}")
    for issue in cut["issues"]:
        _say(f"  issue : {issue}")
    _say(f"summary : {cut['summary'][:220]}")

    _save(args.case, result, cut, out_path)
    _say(f"saved   : {out_path}")
    return 0 if cut["status"] != "Fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
