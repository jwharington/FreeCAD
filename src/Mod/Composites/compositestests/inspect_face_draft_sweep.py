# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Sweep face-draft sampling density on a benchmark shape.

For each face whose midpoint normal reads as draft-safe but whose sampled
normals reveal local negative draft, prints how ``min_direction_dot`` and the
negative-sample fraction converge as the per-axis sample count grows.

Persistent diagnostic for the midpoint-normal overconfidence investigation.
"""

from __future__ import annotations

import argparse

import FreeCAD as App
import Part

from Composites.tools.mould_analysis import (
    _dot,
    _face_midpoint_normal,
    _sample_face_draft_alignment,
    default_mould_analysis_draw_direction,
)
from Composites.tools.profile_mould_analysis import (
    _make_blade_shape,
    _make_loft_shape,
)


def _make_shape(shape_name):
    doc = App.newDocument(f"face_draft_sweep_{shape_name}")
    if shape_name == "box":
        shape = Part.makeBox(20.0, 15.0, 10.0)
    elif shape_name == "blade":
        shape = _make_blade_shape()
    elif shape_name == "loft":
        shape = _make_loft_shape()
    else:
        raise SystemExit(f"unsupported synthetic shape: {shape_name}")
    obj = doc.addObject("Part::Feature", "Source")
    obj.Shape = shape
    doc.recompute()
    return doc, shape


def _candidate_face(shape, direction):
    """First face whose midpoint reads safe but a 5x5 sample shows negative draft."""
    for index, face in enumerate(shape.Faces, start=1):
        midpoint_normal = _face_midpoint_normal(face)
        if midpoint_normal is None:
            continue
        midpoint_dot = _dot(midpoint_normal, direction)
        if midpoint_dot <= 0.0:
            continue
        coarse = _sample_face_draft_alignment(face, direction, samples_per_axis=5)
        if coarse["min_direction_dot"] is not None and coarse["min_direction_dot"] < 0.0:
            return index, face, midpoint_dot
    return None, None, None


def _print_sweep(shape_name, face_index, face, midpoint_dot, direction, max_samples):
    print(f"=== {shape_name}: candidate face Face{face_index}, midpoint_dot={midpoint_dot:.4f}")
    print(f"{'n':>3} {'samples':>7} {'min_dot':>10} {'max_dot':>10} "
          f"{'neg':>4} {'pos':>4} {'neg_frac':>9} {'delta_min':>10}")
    prev_min = None
    for n in range(2, max_samples + 1):
        result = _sample_face_draft_alignment(face, direction, samples_per_axis=n)
        total = result["sample_count"]
        min_dot = result["min_direction_dot"]
        max_dot = result["max_direction_dot"]
        neg = result["negative_sample_count"]
        pos = result["positive_sample_count"]
        frac = (neg / total) if total else 0.0
        delta = (min_dot - prev_min) if prev_min is not None else 0.0
        print(f"{n:>3} {total:>7} {min_dot:>10.5f} {max_dot:>10.5f} "
              f"{neg:>4} {pos:>4} {frac:>9.3f} {delta:>+10.5f}")
        prev_min = min_dot


def sweep_face_draft(shape_name, max_samples=15):
    direction = default_mould_analysis_draw_direction
    doc, shape = _make_shape(shape_name)
    try:
        face_index, face, midpoint_dot = _candidate_face(shape, direction)
        if face is None:
            print(f"=== {shape_name}: no candidate face (midpoint-safe, sampled-negative)")
            return
        _print_sweep(shape_name, face_index, face, midpoint_dot, direction, max_samples)
    finally:
        try:
            App.closeDocument(doc.Name)
        except Exception:
            pass


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shape",
        default="loft",
        choices=("box", "blade", "loft"),
        help="Named benchmark shape to sweep.",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=15,
        help="Maximum samples per axis (sweeps from 2 up to this value).",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    sweep_face_draft(args.shape, args.max_samples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
