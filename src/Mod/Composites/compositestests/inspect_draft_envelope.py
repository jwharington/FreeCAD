# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Inspect whole-side draft-envelope evidence for a benchmark shape.

Persistent diagnostic for the whole-side draft-envelope investigation.
Prints per-side undercut counts/fractions and worst releasability for the
planar parting split, plus per-face breakdown so a local midpoint miss can be
told apart from a globally unreleasable side.
"""

from __future__ import annotations

import argparse

import FreeCAD as App
import Part

from Composites.tools.mould_analysis import (
    _whole_side_draft_envelope,
    default_mould_analysis_draw_direction,
)
from Composites.tools.profile_mould_analysis import (
    _make_blade_shape,
    _make_loft_shape,
)
from synthetic_mould_shapes import (
    make_angled_cone,
    make_sideways_cone,
    make_sphere,
    make_vertical_cone,
)


def _make_shape(shape_name):
    doc = App.newDocument(f"draft_envelope_{shape_name}")
    if shape_name == "box":
        shape = Part.makeBox(20.0, 15.0, 10.0)
    elif shape_name == "blade":
        shape = _make_blade_shape()
    elif shape_name == "loft":
        shape = _make_loft_shape()
    elif shape_name == "cone-vertical":
        shape = make_vertical_cone()
    elif shape_name == "cone-sideways":
        shape = make_sideways_cone()
    elif shape_name == "cone-45":
        shape = make_angled_cone(45.0)
    elif shape_name == "sphere":
        shape = make_sphere()
    else:
        raise SystemExit(f"unsupported synthetic shape: {shape_name}")
    obj = doc.addObject("Part::Feature", "Source")
    obj.Shape = shape
    doc.recompute()
    return doc, shape


def inspect_draft_envelope(shape_name, samples_per_axis=5, parting_offset=None):
    direction = _draw_direction_for(shape_name)
    doc, shape = _make_shape(shape_name)
    try:
        return _whole_side_draft_envelope(
            shape, direction, samples_per_axis, parting_offset=parting_offset,
        )
    finally:
        try:
            App.closeDocument(doc.Name)
        except Exception:
            pass


def _draw_direction_for(shape_name):
    # The sideways cone is the one case where the draw direction is not +Z:
    # its axis lies along +X, so the hook is along +X.
    if shape_name == "cone-sideways":
        return App.Vector(1, 0, 0)
    return default_mould_analysis_draw_direction


def _print_report(report):
    print(f"status: {report['status']}")
    print(f"summary: {report['summary']}")
    print(f"parting_offset: {report['parting_offset']:.4f}")
    print(f"upper: samples={report['upper_sample_count']} "
          f"undercut={report['upper_undercut_count']} "
          f"frac={report['upper_undercut_fraction']:.3f} "
          f"worst_releasability={report['upper_worst_releasability']}")
    print(f"lower: samples={report['lower_sample_count']} "
          f"undercut={report['lower_undercut_count']} "
          f"frac={report['lower_undercut_fraction']:.3f} "
          f"worst_releasability={report['lower_worst_releasability']}")
    print(f"skipped_samples: {report['skipped_sample_count']}")
    print(f"globally_negative_sides: {report['globally_negative_sides']}")
    print("per_face:")
    for item in report["per_face"]:
        print(f"  - {item}")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shape",
        default="loft",
        choices=(
            "box", "blade", "loft",
            "cone-vertical", "cone-sideways", "cone-45", "sphere",
        ),
        help="Named benchmark shape to inspect.",
    )
    parser.add_argument(
        "--samples-per-axis",
        type=int,
        default=5,
        help="Grid resolution per face parameter axis.",
    )
    parser.add_argument(
        "--parting-offset",
        type=float,
        default=None,
        help="Override the parting offset (default: bbox midpoint).",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    report = inspect_draft_envelope(
        args.shape, args.samples_per_axis, parting_offset=args.parting_offset,
    )
    print(f"shape: {args.shape}")
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
