# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Headless timing and profiling helper for mould-analysis hot paths."""

from __future__ import annotations

import argparse
import cProfile
import faulthandler
import io
import pstats
import sys
import time
from pathlib import Path

import FreeCAD as App
import Part

from Composites.tools.mould_analysis import (
    _classify_draft_faces,
    analyze_source_shape,
    default_mould_analysis_draw_direction,
    make_mould_halves,
    normalize_source_shape,
    propose_parting_surface,
)


def _repo_root():
    file_value = globals().get("__file__")
    if file_value:
        return Path(file_value).resolve().parents[4]
    return Path.cwd()


DEFAULT_FIXTURE = _repo_root() / "src/Mod/Composites/compositestests/fixtures/propblade.FCStd"
DEFAULT_PROFILE_LINES = 35
DEFAULT_SHAPE = "propblade"


def _load_fixture_shape(fixture_path: Path):
    doc = App.openDocument(str(fixture_path))
    try:
        obj = next(
            candidate
            for candidate in doc.Objects
            if hasattr(candidate, "Shape") and not candidate.Shape.isNull()
        )
    except StopIteration as exc:
        raise RuntimeError(f"no non-null shape found in {fixture_path}") from exc
    return doc, obj, obj.Shape


def _spline_wire(points, periodic=False):
    curve = Part.BSplineCurve()
    curve.buildFromPoles(
        [App.Vector(*point) for point in points],
        periodic,
        3,
        False,
    )
    return Part.Wire(curve.toShape())


_BLADE_PROFILE = [
    (-0.55, 0.00),
    (-0.34, -0.10),
    (0.00, -0.16),
    (0.36, -0.08),
    (0.54, 0.02),
    (0.41, 0.13),
    (0.00, 0.20),
    (-0.30, 0.11),
    (-0.55, 0.00),
]


def _make_blade_section(spec):
    points = []
    for px, py in _BLADE_PROFILE:
        x = spec["sweep"] + (spec["chord"] * px) + (spec["twist"] * py)
        y = spec["offset_y"] + (spec["thickness"] * py)
        points.append((x, y, spec["z"]))
    return _spline_wire(points, periodic=True)


def _make_blade_shape():
    # A simpler blade-like taper used as the fast-loop middle benchmark.
    sections = [
        {
            "z": 0.0,
            "chord": 24.0,
            "thickness": 11.0,
            "sweep": 0.0,
            "twist": 0.0,
            "offset_y": 0.0,
        },
        {
            "z": 14.0,
            "chord": 12.5,
            "thickness": 5.4,
            "sweep": 1.2,
            "twist": 0.9,
            "offset_y": 0.5,
        },
        {
            "z": 28.0,
            "chord": 4.2,
            "thickness": 1.5,
            "sweep": 2.5,
            "twist": 1.7,
            "offset_y": 0.1,
        },
    ]
    return Part.makeLoft([
        _make_blade_section(spec) for spec in sections
    ], solid=True)


def _make_loft_shape():
    # A cambered, slightly twisted blade-like loft that sits between the
    # simple primitives and the full propblade topology.
    sections = [
        {
            "z": 0.0,
            "chord": 24.0,
            "thickness": 11.0,
            "sweep": 0.0,
            "twist": 0.0,
            "offset_y": 0.0,
        },
        {
            "z": 8.0,
            "chord": 18.0,
            "thickness": 8.6,
            "sweep": 1.0,
            "twist": 1.0,
            "offset_y": 0.7,
        },
        {
            "z": 17.0,
            "chord": 12.0,
            "thickness": 5.6,
            "sweep": 2.0,
            "twist": 1.8,
            "offset_y": 1.0,
        },
        {
            "z": 25.0,
            "chord": 6.4,
            "thickness": 2.8,
            "sweep": 2.7,
            "twist": 2.3,
            "offset_y": 0.5,
        },
        {
            "z": 32.0,
            "chord": 2.7,
            "thickness": 1.0,
            "sweep": 3.1,
            "twist": 2.6,
            "offset_y": -0.1,
        },
    ]
    return Part.makeLoft([
        _make_blade_section(spec) for spec in sections
    ], solid=True)


def _make_synthetic_shape(shape_name: str):
    doc = App.newDocument(f"mould_profile_{shape_name}")
    if shape_name == "box":
        shape = Part.makeBox(20.0, 15.0, 10.0)
    elif shape_name == "cylinder":
        shape = Part.makeCylinder(10.0, 20.0)
    elif shape_name == "blade":
        shape = _make_blade_shape()
    elif shape_name == "loft":
        shape = _make_loft_shape()
    else:
        raise SystemExit(f"unsupported synthetic shape: {shape_name}")

    obj = doc.addObject("Part::Feature", "Source")
    obj.Shape = shape
    doc.recompute()
    return doc, obj, obj.Shape


def _bench(label, fn):
    print(f"{label}: start", flush=True)
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    print(f"{label}: {elapsed:.3f}s", flush=True)
    return result


def _profile_analyze(shape, source_obj, profile_lines):
    profiler = cProfile.Profile()
    start = time.perf_counter()
    profiler.enable()
    result = analyze_source_shape(
        shape,
        default_mould_analysis_draw_direction,
        source_obj=source_obj,
    )
    profiler.disable()
    elapsed = time.perf_counter() - start

    print(f"status: {result['status']}")
    print(f"validation: {result['validation_status']}")
    print(f"elapsed_sec: {elapsed:.3f}")

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream).sort_stats("cumulative")
    stats.print_stats(profile_lines)
    print(stream.getvalue())

    return result


def _benchmark_helpers(shape, checks):
    selected_checks = [check.strip() for check in checks if check.strip()]
    if not selected_checks:
        selected_checks = ["normalize", "parting", "halves"]

    print(f"shape_type: {shape.ShapeType}", flush=True)
    print(f"volume: {getattr(shape, 'Volume', 0.0):.6f}", flush=True)
    print(f"checks: {', '.join(selected_checks)}", flush=True)

    normalize_result = None
    parting = None

    if "normalize" in selected_checks:
        normalize_result = _bench("normalize_source_shape", lambda: normalize_source_shape(shape))
    if "parting" in selected_checks:
        parting = _bench(
            "propose_parting_surface",
            lambda: propose_parting_surface(shape, default_mould_analysis_draw_direction),
        )
    if "halves" in selected_checks:
        if parting is None:
            parting = propose_parting_surface(
                shape,
                default_mould_analysis_draw_direction,
            )
        _bench(
            "make_mould_halves",
            lambda: make_mould_halves(
                shape,
                parting["surface_normal"],
                parting["surface_offset"],
            ),
        )
    if "draft" in selected_checks:
        _bench(
            "_classify_draft_faces",
            lambda: _classify_draft_faces(
                shape,
                default_mould_analysis_draw_direction,
            ),
        )

    if normalize_result is not None:
        print(f"normalize_confidence: {normalize_result['confidence']}", flush=True)
        print(f"normalize_source_type: {normalize_result['source_type']}", flush=True)


def _profile_fast_loop():
    print("fast_loop: shapes=box, blade, loft", flush=True)
    for shape_name in ("box", "blade", "loft"):
        doc = None
        try:
            doc, obj, shape = _make_synthetic_shape(shape_name)
            print(f"fast_loop[{shape_name}]: document={doc.Name}", flush=True)
            print(f"fast_loop[{shape_name}]: object={obj.Name}", flush=True)
            result = _bench(
                f"analyze_source_shape[{shape_name}]",
                lambda: analyze_source_shape(
                    shape,
                    default_mould_analysis_draw_direction,
                    source_obj=obj,
                ),
            )
            print(
                "fast_loop[{name}]: status={status} validation={validation} "
                "gate={gate} withdrawal_clearance={wc}".format(
                    name=shape_name,
                    status=result["status"],
                    validation=result["validation_status"],
                    gate=result["analysis_gate_status"],
                    wc=result["withdrawal_clearance_status"],
                ),
                flush=True,
            )
        finally:
            if doc is not None:
                try:
                    App.closeDocument(doc.Name)
                except Exception:
                    pass


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="Path to the .FCStd fixture to profile.",
    )
    parser.add_argument(
        "--shape",
        default=DEFAULT_SHAPE,
        choices=("propblade", "box", "cylinder", "blade", "loft"),
        help="Named shape preset to profile.",
    )
    parser.add_argument(
        "--mode",
        choices=("helpers", "analyze", "fast-loop"),
        default="helpers",
        help="Which mould-analysis path to measure.",
    )
    parser.add_argument(
        "--checks",
        default="normalize,parting,halves",
        help="Comma-separated helper checks to run in helpers mode.",
    )
    parser.add_argument(
        "--profile-lines",
        type=int,
        default=DEFAULT_PROFILE_LINES,
        help="How many cProfile lines to print in analyze mode.",
    )
    parser.add_argument(
        "--dump-stack-after",
        type=int,
        default=50,
        help="Dump the Python stack after N seconds to reveal a hang point.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    fixture = args.fixture

    doc = None
    try:
        if args.dump_stack_after > 0:
            faulthandler.dump_traceback_later(args.dump_stack_after, repeat=False, file=sys.stderr)
        if args.mode == "fast-loop":
            _profile_fast_loop()
            return 0
        if args.shape == "propblade":
            if not fixture.is_file():
                raise SystemExit(f"fixture not found: {fixture}")
            doc, obj, shape = _load_fixture_shape(fixture)
            print(f"fixture: {fixture}", flush=True)
        else:
            doc, obj, shape = _make_synthetic_shape(args.shape)
            print(f"shape: {args.shape}", flush=True)
        print(f"document: {doc.Name}", flush=True)
        print(f"object: {obj.Name}", flush=True)

        if args.mode == "helpers":
            _benchmark_helpers(shape, args.checks.split(","))
        else:
            _profile_analyze(shape, obj, args.profile_lines)
    finally:
        faulthandler.cancel_dump_traceback_later()
        if doc is not None:
            try:
                App.closeDocument(doc.Name)
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
