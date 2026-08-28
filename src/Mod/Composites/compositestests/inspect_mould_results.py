# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Inspect mould-analysis results for a chosen benchmark shape.

This helper is intended for persistent diagnostics during the withdrawal-
clearance work. It prints the key analysis fields for a synthetic shape or a
fixture-backed real shape and includes the explicit withdrawal-clearance check.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import FreeCAD as App
import Part

from Composites.tools.mould_analysis import (
    analyze_source_shape,
    default_mould_analysis_draw_direction,
    make_mould_halves,
    propose_parting_surface,
)
from Composites.tools.profile_mould_analysis import (
    _make_blade_shape,
    _make_loft_shape,
)
from Composites.compositestests.synthetic_mould_shapes import (
    make_sideways_cone,
    make_sphere,
    make_vertical_cone,
)


_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_FIXTURE = _REPO_ROOT / "src/Mod/Composites/compositestests/fixtures/propblade.FCStd"

_DIRECTION_PRESETS = {
    "x": App.Vector(1, 0, 0),
    "y": App.Vector(0, 1, 0),
    "z": App.Vector(0, 0, 1),
}


def _load_fixture_shape(fixture_path: Path):
    doc = App.openDocument(str(fixture_path))
    try:
        obj = next(
            candidate
            for candidate in doc.Objects
            if hasattr(candidate, "Shape") and not candidate.Shape.isNull()
        )
    except StopIteration as exc:
        App.closeDocument(doc.Name)
        raise RuntimeError(f"no non-null shape found in {fixture_path}") from exc
    return doc, obj, obj.Shape


def _make_shape(shape_name: str):
    doc = App.newDocument(f"inspect_mould_{shape_name}")
    if shape_name == "box":
        shape = Part.makeBox(20.0, 15.0, 10.0)
    elif shape_name == "cylinder":
        shape = Part.makeCylinder(10.0, 20.0)
    elif shape_name == "sphere":
        shape = make_sphere()
    elif shape_name == "cone":
        shape = make_vertical_cone()
    elif shape_name == "cone_side":
        shape = make_sideways_cone()
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


def _build_inspection_report(shape_name: str, shape, direction, source_obj=None):
    result = analyze_source_shape(
        shape,
        direction,
        source_obj=source_obj,
        parting_model="NonPlanar",
    )
    parting = propose_parting_surface(shape, direction)
    halves = make_mould_halves(
        shape,
        parting["surface_normal"],
        parting["surface_offset"],
    )
    # Native C++ withdrawal-clearance verdict, re-surfaced from the flattened
    # top-level analysis fields (there is no pure-Python fallback any more).
    clearance = {
        "status": result.get("withdrawal_clearance_status"),
        "summary": result.get("withdrawal_clearance_summary"),
        "sample_count": 0,
        "failure_count": result.get("withdrawal_clearance_failure_count", 0),
        "failure_regions": [],
        "half_checks": [],
        "step_mm": 0.0,
    }

    source_document = getattr(source_obj, "Document", None) if source_obj is not None else None
    document_name = source_document.Name if source_document is not None else ""
    object_name = getattr(source_obj, "Name", "") if source_obj is not None else ""

    return {
        "shape_name": shape_name,
        "shape": shape,
        "document_name": document_name,
        "object_name": object_name,
        "analysis": result,
        "parting": parting,
        "halves": halves,
        "withdrawal_clearance": clearance,
    }


def _print_report(report: dict):
    result = report["analysis"]
    clearance = report["withdrawal_clearance"]
    parting = report["parting"]
    halves = report["halves"]

    print(f"shape: {report['shape_name']}")
    print(f"status: {result.get('status')}")
    print(f"validation_status: {result.get('validation_status')}")
    print(f"analysis_gate_status: {result.get('analysis_gate_status')}")
    print(f"summary: {result.get('summary')}")
    print(f"draft_face_summary: {result.get('draft_face_summary')}")
    print(f"validation_summary: {result.get('validation_summary')}")
    print(f"withdrawal_clearance_status: {clearance.get('status')}")
    print(f"withdrawal_clearance_summary: {clearance.get('summary')}")
    print("withdrawal_clearance_half_checks:")
    for item in clearance.get("half_checks", []):
        print(f"  - {item}")
    print("parting_surface_summary:", parting["summary"])
    print("mould_halves_summary:", halves["summary"])


def inspect_benchmark_shape(shape_name: str, direction=None, fixture_path: Path = _DEFAULT_FIXTURE):
    draw_direction = direction or default_mould_analysis_draw_direction
    doc = None
    try:
        if shape_name == "propblade":
            if not fixture_path.is_file():
                raise SystemExit(f"fixture not found: {fixture_path}")
            doc, obj, shape = _load_fixture_shape(fixture_path)
        else:
            doc, obj, shape = _make_shape(shape_name)
        return _build_inspection_report(shape_name, shape, draw_direction, source_obj=obj)
    finally:
        if doc is not None:
            try:
                App.closeDocument(doc.Name)
            except Exception:
                pass


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shape",
        default="box",
        choices=("box", "cylinder", "sphere", "cone", "cone_side", "blade", "loft", "propblade"),
        help="Named benchmark shape to inspect.",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=_DEFAULT_FIXTURE,
        help="Path to the .FCStd fixture used when --shape propblade is selected.",
    )
    parser.add_argument(
        "--direction",
        default="z",
        choices=sorted(_DIRECTION_PRESETS),
        help="Draw direction to probe (x/y/z). Defaults to z.",
    )
    parser.add_argument(
        "--dump-shape",
        default=None,
        metavar="OUT.brep",
        help="Instead of inspecting, write the exact benchmark shape to OUT.brep "
             "for the nextdrape mould_cli --load-shapefile harness.",
    )
    return parser


def _dump_shape_brep(shape_name, out_path, fixture_path):
    """Write the exact benchmark shape (same builder the tests feed the binding)
    to a BREP file that mould_cli --load-shapefile can read."""
    doc = None
    try:
        if shape_name == "propblade":
            if not fixture_path.is_file():
                raise SystemExit(f"fixture not found: {fixture_path}")
            doc, obj, shape = _load_fixture_shape(fixture_path)
        else:
            doc, obj, shape = _make_shape(shape_name)
    finally:
        if doc is not None:
            try:
                App.closeDocument(doc.Name)
            except Exception:
                pass
    shape.exportBrep(str(out_path))
    print(f"dumped {shape_name} -> {out_path}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.dump_shape:
        _dump_shape_brep(args.shape, Path(args.dump_shape), fixture_path=args.fixture)
        return 0
    direction = _DIRECTION_PRESETS[args.direction]
    report = inspect_benchmark_shape(args.shape, direction=direction, fixture_path=args.fixture)

    if args.shape == "propblade":
        print(f"fixture: {args.fixture}")
    else:
        print(f"shape preset: {args.shape}")

    print(f"document: {report['document_name']}")
    print(f"object: {report['object_name']}")
    _print_report(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
