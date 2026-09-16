# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Quasi-isotropic seam example (PRD quasi_isotropic_laminate.md §8.4).

Two QI panels lap-jointed: the seam extraction runs the actual
extraction flow with **no transfer rosettes on either side** (the
wiring-relaxation case, D8), producing a derived-QI combined laminate —
the seam-region shell is orientation-free, and the remainder carries the
attachment's own QI laminate, likewise orientation-free.

See docs/quasi_isotropic_laminate.md and
docs/adr/0003-quasi-isotropic-presentation-contract.md.
"""

import FreeCAD
import Part

from ...features.SeamExtraction import SeamShellFP
from ...objects import SymmetryType, WeaveType
from ._shell_example_common import (
    _carbon_material,
    _resin_material,
    _prepare_feature_import_environment,
    _to_length_mm,
    ensure_document,
)

QI_ANGLES = (0.0, 45.0, -45.0, 90.0)

DOCUMENT_NAME = "Composites_QuasiIso_Seam"


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


def _make_qi_laminate(doc, name):
    """A QI [0/45/-45/90]s UD laminate, declared IsotropicEquivalent."""
    _prepare_feature_import_environment()
    from ...features.CompositeLaminate import CompositeLaminateFP
    from ...features.FibreCompositeLamina import FibreCompositeLaminaFP

    plies = []
    for idx, angle in enumerate(QI_ANGLES, start=1):
        ply = doc.addObject("App::FeaturePython", f"{name}_Ply{idx:02d}")
        FibreCompositeLaminaFP(ply)
        ply.FibreMaterial = _carbon_material()
        ply.FibreVolumeFraction = 55
        ply.Thickness = _to_length_mm(FreeCAD, 0.2)
        ply.Angle = angle
        ply.WeaveType = WeaveType.UD.name
        plies.append(ply)

    laminate = doc.addObject("App::FeaturePython", name)
    CompositeLaminateFP(laminate, laminae=plies)
    laminate.ResinMaterial = _resin_material()
    laminate.FibreVolumeFraction = 55
    # A QI stack must be symmetric (B = 0) for isotropic presentation.
    laminate.Symmetry = SymmetryType.Even.name
    laminate.IsotropicEquivalent = True
    doc.recompute()
    return laminate


def _make_qi_panel(doc, name, pts):
    """A QI-declared composite panel shell — no rosette, no drape."""
    _prepare_feature_import_environment()
    from ...features.CompositeShell import CompositeShellFP

    support = doc.addObject("Part::Feature", f"{name}Sup")
    support.Shape = _face(pts)
    laminate = _make_qi_laminate(doc, f"{name}Laminate")
    shell = doc.addObject("Part::FeaturePython", name)
    CompositeShellFP(shell, support, laminate=laminate, rosette=None)
    return shell


def build(doc=None, run_solver=False):
    """Build the QI seam example.

    Parameters
    ----------
    doc
        Optional FreeCAD document receiving model entities.
    run_solver
        Accepted for runner parity; the extraction runs inside the seam
        feature's recompute (no drape solves on a QI assembly).

    Returns
    -------
    dict
        The resolved document, seam feature and children, the combined
        laminate with its derived flag, and wiring facts.
    """

    doc = _ensure_document(doc)

    # Master panel: x in [0, 50]; attachment: x in [-50, 0] — both QI.
    ms = _make_qi_panel(doc, "MasterShell", [
        FreeCAD.Vector(0, -25, 0),
        FreeCAD.Vector(50, -25, 0),
        FreeCAD.Vector(50, 25, 0),
        FreeCAD.Vector(0, 25, 0),
    ])
    as_ = _make_qi_panel(doc, "AttShell", [
        FreeCAD.Vector(-50, -25, 0),
        FreeCAD.Vector(0, -25, 0),
        FreeCAD.Vector(0, 25, 0),
        FreeCAD.Vector(-50, 25, 0),
    ])
    doc.recompute()

    seam = doc.addObject("Part::FeaturePython", "SeamExtraction")
    SeamShellFP(seam, ms, as_)

    doc.recompute()

    seam_shell = getattr(seam, "Seam", None)
    scl = seam_shell.Laminate if seam_shell is not None else None

    return {
        "doc": doc,
        "seam": seam,
        "seam_surface": seam_shell,
        "remainder": getattr(seam, "Remainder", None),
        "master": ms,
        "attachment": as_,
        "combined_laminate": scl,
        # Wiring facts (D8): no transfer rosettes on either side, and
        # the derived combined presentation is isotropic.
        "master_transfer": getattr(scl, "MasterTransfer", None)
        if scl is not None
        else None,
        "attachment_transfer": getattr(scl, "AttachmentTransfer", None)
        if scl is not None
        else None,
        "combined_isotropic": (
            scl.IsotropicEquivalent if scl is not None else None
        ),
        "seam_shell_draped": bool(seam_shell.DrapeValid)
        if seam_shell is not None
        else None,
        "remainder_isotropic": (
            is_isotropic(getattr(seam, "Remainder", None))
        ),
        # §8.4: the seam-region shell and the remainder export plain
        # isotropic material (no composite layer stack).
        "seam_export_materials": _export_materials(scl),
        "remainder_export_materials": _export_materials(
            getattr(getattr(seam, "Remainder", None), "Laminate", None)
        ),
    }


def is_isotropic(shell):
    from ...features.CompositeShell import is_isotropic_shell

    return bool(shell is not None and is_isotropic_shell(shell))


def _export_materials(laminate):
    """The CalcuiX material text a laminate exports (PRD §8.4 check)."""
    if laminate is None:
        return None
    from ...util.fem_util import write_lamina_materials_ccx

    return write_lamina_materials_ccx(
        laminate.Proxy.FEMLayers, prefix=laminate.Name
    )


def main():
    """Run the example in its own document."""
    result = build()
    print(
        f"quasi_iso_seam: derived_isotropic={result['combined_isotropic']} "
        f"transfers=({result['master_transfer']}, "
        f"{result['attachment_transfer']}) "
        f"remainder_isotropic={result['remainder_isotropic']}"
    )


if __name__ == "__main__":
    main()
