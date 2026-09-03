# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Stiffener example — sweep a profile along a plan on a support.

Builds a planar support, a plan sketch (a single line) and a profile sketch
(a rectangular section), then creates the ``StiffenerFP`` feature so the
profile is swept along the plan to produce the stiffener compound.
"""

import FreeCAD
import Part

from ...features.Stiffener import StiffenerFP, ViewProviderStiffener

DOCUMENT_NAME = "Composites_Stiffener"


def _ensure_document(doc):
    """Return ``doc`` or a fresh document for this example."""
    if doc is not None:
        return doc
    if DOCUMENT_NAME in FreeCAD.listDocuments():
        FreeCAD.closeDocument(DOCUMENT_NAME)
    return FreeCAD.newDocument(DOCUMENT_NAME)


def _make_sketch(doc, name, points):
    """Create a sketch from a list of points (line segments)."""
    sketch = doc.addObject("Sketcher::SketchObject", name)
    for start, end in zip(points, points[1:]):
        sketch.addGeometry(Part.LineSegment(start, end), False)
    return sketch


def build(doc=None, run_solver=False):
    """Build the stiffener example.

    Parameters
    ----------
    doc
        Optional FreeCAD document receiving model entities.
    run_solver
        Accepted for runner parity; the stiffener is generated during the
        feature's recompute.

    Returns
    -------
    dict
        The resolved document, the stiffener feature, its generated shape,
        and the support/plan/profile inputs.
    """

    doc = _ensure_document(doc)

    support = doc.addObject("Part::Feature", "Support")
    support.Shape = Part.makePlane(120.0, 60.0)

    plan = _make_sketch(doc, "Plan", [
        FreeCAD.Vector(10.0, 10.0, 0.0),
        FreeCAD.Vector(80.0, 10.0, 0.0),
    ])

    profile = _make_sketch(doc, "Profile", [
        FreeCAD.Vector(0.0, 0.0, 0.0),
        FreeCAD.Vector(0.0, 10.0, 0.0),
        FreeCAD.Vector(20.0, 10.0, 0.0),
        FreeCAD.Vector(20.0, 0.0, 0.0),
        FreeCAD.Vector(0.0, 0.0, 0.0),
    ])

    stiffener = doc.addObject("Part::FeaturePython", "Stiffener")
    StiffenerFP(stiffener, support=support, plan=plan, profile=profile)
    # Attach the real ViewProvider (as the workbench command does); deriving
    # the FP alone leaves the generic dimmed ViewProvider.
    if FreeCAD.GuiUp:
        ViewProviderStiffener(stiffener.ViewObject)

    doc.recompute()

    return {
        "doc": doc,
        "stiffener": stiffener,
        "shape": stiffener.Shape,
        "support": support,
        "plan": plan,
        "profile": profile,
    }


def main():
    """Run the example in its own document."""
    result = build()
    shape = result["shape"]
    print(f"Created {len(result['doc'].Objects)} objects")
    print(f"Stiffener shape: {shape.ShapeType} | null={shape.isNull()}")


if __name__ == "__main__":
    main()
