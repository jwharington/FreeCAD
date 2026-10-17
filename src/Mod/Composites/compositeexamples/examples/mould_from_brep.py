# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Mould analysis of a B-rep file, saved to an FCStd document.

The other mould examples build their source shape in memory. This one takes a
B-rep file, runs the same ``Composite::MouldAnalysis`` feature on it and saves
the computed document, so a long analysis can run headlessly and its result be
opened in the GUI afterwards — loading a saved document does not re-run the
analysis, which the GUI cannot afford on a large source (the blade fixture
below takes minutes to recompute and blocks the GUI for the whole of it).

Run it with the freecad-dev helper, which owns the FreeCADCmd invocation:

    run-script.sh examples/mould_from_brep.py --brep <shape.brep> --out <doc.FCStd>

The fixture shapes live outside this repository, so the path is an argument.
"""

import argparse
import os

import FreeCAD
import Part

from Composites.features.MouldAnalysis import MouldAnalysisFP, ViewProviderMouldAnalysis


def parse_args(argv=None):
    """Command line: the shape to analyse, where to save, and the draw."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--brep", required=True, help="B-rep file to analyse")
    parser.add_argument("--out", required=True, help="FCStd file to save")
    parser.add_argument(
        "--doc-name", default="MouldFromBrep", help="document name (default: %(default)s)"
    )
    parser.add_argument(
        "--draw",
        default="0,1,0",
        help="draw direction x,y,z in world coordinates (default: %(default)s)",
    )
    parser.add_argument(
        "--band-tol-deg",
        type=float,
        default=2.0,
        help="equator band half-width in degrees (default: %(default)s)",
    )
    return parser.parse_args(argv)


def parse_draw(text):
    """The draw direction as a vector; fails loudly on a malformed value."""
    parts = text.split(",")
    if len(parts) != 3:
        raise ValueError("--draw takes three comma-separated components, got %r" % text)
    return FreeCAD.Vector(*(float(part) for part in parts))


def build(brep_path, doc_name, draw_direction, band_tol_deg):
    """Analyse ``brep_path`` in a fresh document and return it."""
    if doc_name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(doc_name)
    doc = FreeCAD.newDocument(doc_name)

    shape = Part.Shape()
    shape.read(brep_path)
    source = doc.addObject("Part::Feature", "Source")
    source.Shape = shape

    mould = doc.addObject("Part::FeaturePython", "MouldAnalysis")
    MouldAnalysisFP(mould, source)
    if FreeCAD.GuiUp:
        ViewProviderMouldAnalysis(mould.ViewObject)
    mould.PreferredDrawDirection = draw_direction
    mould.TessellationBandTolDeg = band_tol_deg
    doc.recompute()
    return doc, source, mould


def report(mould):
    """Print the analysis outcome: what the saved document holds."""
    print("AnalysisStatus: %s" % getattr(mould, "AnalysisStatus", "n/a"))
    for half in ("MouldHalfA", "MouldHalfB"):
        obj = getattr(mould, half, None)
        shape = getattr(obj, "Shape", None)
        volume = 0.0 if shape is None or shape.isNull() else shape.Volume
        print("%s: volume=%.1f mm^3" % (half, volume))
    print("PartingSurface: %s" % getattr(mould, "PartingSurfaceStatus", "n/a"))


def main(argv=None):
    args = parse_args(argv)
    doc, _source, mould = build(
        os.path.abspath(args.brep), args.doc_name, parse_draw(args.draw), args.band_tol_deg
    )
    report(mould)
    doc.saveAs(os.path.abspath(args.out))
    print("saved: %s" % os.path.abspath(args.out))


if __name__ == "__main__":
    main()
