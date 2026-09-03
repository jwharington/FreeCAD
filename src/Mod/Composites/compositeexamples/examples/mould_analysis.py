# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Parametric mould analysis example (the MouldAnalysis workbench feature).

Builds a ``Composite::MouldAnalysis`` FeaturePython object (from
:mod:`Composites.features.MouldAnalysis`) on a source solid and demonstrates
that the analysis is *parametric*: changing the linked source geometry and
recomputing regenerates the parting surface and both mould halves.

This contrasts with the one-shot ``non_planar_mould_demo``, which calls
``analyze_source_shape`` once and freezes the results into plain
``Part::Feature`` objects. Here the mould is a feature object whose
``execute()`` re-runs the analysis on every recompute.
"""

import FreeCAD
import Part

from ...features.MouldAnalysis import MouldAnalysisFP, ViewProviderMouldAnalysis

DOCUMENT_NAME = "Composites_Mould_Analysis"


def _ensure_document(doc):
    """Return ``doc`` or a fresh document for this example."""
    if doc is not None:
        return doc
    if DOCUMENT_NAME in FreeCAD.listDocuments():
        FreeCAD.closeDocument(DOCUMENT_NAME)
    return FreeCAD.newDocument(DOCUMENT_NAME)


def _add_source(doc, name, shape):
    source = doc.addObject("Part::Feature", name)
    source.Shape = shape
    return source


def _mould_half_volume(half):
    """Volume of a mould-half feature, or zero when absent/null."""
    shape = getattr(half, "Shape", None)
    if shape is None or shape.isNull():
        return 0.0
    return shape.Volume


def _report(mould, label):
    status = getattr(mould, "AnalysisStatus", "n/a")
    volume = _mould_half_volume(getattr(mould, "MouldHalfA", None))
    print(f"[{label}] AnalysisStatus={status} halfA_volume={volume:.1f} mm^3")
    return status, volume


def build(doc=None, run_solver=False):
    """Build the parametric mould analysis example.

    Parameters
    ----------
    doc
        Optional FreeCAD document receiving model entities.
    run_solver
        Accepted for runner parity; the mould analysis always runs inside
        the feature's ``execute()`` during recompute.

    Returns
    -------
    dict
        The resolved document, the source and mould feature objects, and the
        half-A volumes before/after the source-geometry change.
    """

    doc = _ensure_document(doc)

    # 1. Source in its initial shape (box).
    source = _add_source(doc, "MouldSource", Part.makeBox(20.0, 20.0, 20.0))
    # 2. MouldAnalysis feature linked to the source. The feature's
    #    ViewProvider must be attached explicitly (as the workbench command
    #    does); deriving the FP alone leaves the generic dimmed ViewProvider.
    mould = doc.addObject("Part::FeaturePython", "MouldAnalysis")
    MouldAnalysisFP(mould, source)
    if FreeCAD.GuiUp:
        ViewProviderMouldAnalysis(mould.ViewObject)
    doc.recompute()

    status_before, volume_before = _report(mould, "box")

    # 3. Change the source geometry and recompute: the mould must follow.
    source.Shape = Part.makeCylinder(8.0, 30.0)
    doc.recompute()

    status_after, volume_after = _report(mould, "cylinder")

    return {
        "doc": doc,
        "source": source,
        "mould": mould,
        "status_before": status_before,
        "volume_before": volume_before,
        "status_after": status_after,
        "volume_after": volume_after,
    }


def main():
    """Run the example in its own document."""
    result = build()
    if result["volume_before"] != result["volume_after"]:
        print("mould half A volume changed with the source — parametric recompute OK")
    else:
        print("mould half A volume did not change (check the source link/touch)")


if __name__ == "__main__":
    main()