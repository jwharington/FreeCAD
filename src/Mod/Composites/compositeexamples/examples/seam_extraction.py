# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Seam extraction example — overlap geometry between two composite panels.

Builds two coplanar composite shells sharing an edge (master + attachment)
and runs the ``SeamShellFP`` extraction so the seam surface and the
remainder geometry are produced as child objects of the seam feature.
"""

import FreeCAD
import Part

from ...features.CompositeShell import CompositeShellFP
from ...features.Laminate import LaminateFP
from ...features.SeamExtraction import SeamShellFP

DOCUMENT_NAME = "Composites_Seam_Extraction"


def _ensure_document(doc):
    """Return ``doc`` or a fresh document for this example."""
    if doc is not None:
        return doc
    if DOCUMENT_NAME in FreeCAD.listDocuments():
        FreeCAD.closeDocument(DOCUMENT_NAME)
    return FreeCAD.newDocument(DOCUMENT_NAME)


def _face(pts):
    """Create a planar face from a list of vertices."""
    wire = Part.makePolygon(pts + [pts[0]])
    return Part.Face(wire)


def build(doc=None, run_solver=False):
    """Build the seam extraction example.

    Parameters
    ----------
    doc
        Optional FreeCAD document receiving model entities.
    run_solver
        Accepted for runner parity; seam extraction runs inside the seam
        feature's recompute.

    Returns
    -------
    dict
        The resolved document, the seam feature, its seam surface and
        remainder children, and the master/attachment shells.
    """

    doc = _ensure_document(doc)

    # Master panel: x in [0, 50].
    master_sup = doc.addObject("Part::Feature", "MasterSup")
    master_sup.Shape = _face([
        FreeCAD.Vector(0, -25, 0),
        FreeCAD.Vector(50, -25, 0),
        FreeCAD.Vector(50, 25, 0),
        FreeCAD.Vector(0, 25, 0),
    ])

    # Attachment panel: x in [-50, 0] (shares the x=0 edge).
    att_sup = doc.addObject("Part::Feature", "AttSup")
    att_sup.Shape = _face([
        FreeCAD.Vector(-50, -25, 0),
        FreeCAD.Vector(0, -25, 0),
        FreeCAD.Vector(0, 25, 0),
        FreeCAD.Vector(-50, 25, 0),
    ])

    lam = doc.addObject("Part::FeaturePython", "Laminate")
    LaminateFP(lam)

    ms = doc.addObject("Part::FeaturePython", "MasterShell")
    CompositeShellFP(ms, support=master_sup, laminate=lam, rosette=None)

    as_ = doc.addObject("Part::FeaturePython", "AttShell")
    CompositeShellFP(as_, support=att_sup, laminate=lam, rosette=None)

    # Recompute so the shells carry their draped shapes before the seam
    # solver reads them (SeamShellFP extracts from the shell shapes).
    doc.recompute()

    seam = doc.addObject("Part::FeaturePython", "SeamExtraction")
    SeamShellFP(seam, ms, as_)

    doc.recompute()

    return {
        "doc": doc,
        "seam": seam,
        "seam_surface": getattr(seam, "Seam", None),
        "remainder": getattr(seam, "Remainder", None),
        "master": ms,
        "attachment": as_,
    }


def main():
    """Run the example in its own document."""
    result = build()
    seam = result["seam"]
    print(f"Created {len(result['doc'].Objects)} objects")
    print(f"Seam: {seam.Seam.Name if seam.Seam else 'None'}")
    print(f"Remainder: {seam.Remainder.Name if seam.Remainder else 'None'}")


if __name__ == "__main__":
    main()
