# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Quasi-isotropic stiffener panel example (PRD quasi_isotropic_laminate.md §8.2).

The stiffener-panel scenario with QI laminates — the QI property
exercised through the full composition path:

1. the panel stays a draped composite shell (the realistic baseline);
2. the stiffener's own laminate is QI ``[0/45/-45/90]s`` declared
   ``IsotropicEquivalent`` — no web rosette is created, the web shell
   has no drape and renders plain;
3. the foot combined laminate (stiffener ⊕ panel) is draped, mixed:
   the panel-side foot transfer still solves; the QI side enters the
   record at nominal angles with rotation 0 (D8);
4. ``panel_qi=True`` makes the panel laminate also QI — foot and
   assembly become fully orientation-free (the FEM-export shortcut end
   to end).

See docs/quasi_isotropic_laminate.md and
docs/adr/0003-quasi-isotropic-presentation-contract.md.
"""

import FreeCAD
import Part

from ...features.Stiffener import (
    StiffenerFP,
    ViewProviderStiffener,
    add_stiffener_filters,
)
from ...features.StiffenerCompositeShell import (
    ensure_stiffener_shells_visible,
)
from ...objects import SymmetryType, WeaveType
from ._shell_example_common import (
    _carbon_material,
    _resin_material,
    _prepare_feature_import_environment,
    _to_length_mm,
    create_composite_feature_stack,
    ensure_document,
)
from .stiffener import (
    PLATE_LENGTH,
    PLATE_WIDTH,
    _make_shape_object,
    _make_sketch,
    plate_cut_surface,
    _z_profile,
)

FABRIC_OFFSET_ANGLE = 30.0  # fabric laid at 30 degrees on the draped panel
DRAPE_PITCH = 5.0
QI_ANGLES = (0.0, 45.0, -45.0, 90.0)

DOCUMENT_NAME = "Composites_QuasiIso_Stiffener_Panel"


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


def _make_qi_panel(doc, name="QIPanel"):
    """A QI-declared composite panel shell — no rosette, no drape."""
    _prepare_feature_import_environment()
    from ...features.CompositeShell import CompositeShellFP

    support = _make_shape_object(
        doc, f"{name}Plate", Part.makePlane(PLATE_LENGTH, PLATE_WIDTH)
    )
    laminate = _make_qi_laminate(doc, f"{name}Laminate")
    shell = doc.addObject("Part::FeaturePython", name)
    CompositeShellFP(shell, support, laminate=laminate)
    doc.recompute()
    return shell


def build(doc=None, run_solver=False, panel_qi=False):
    """Build the QI stiffener panel (``panel_qi=True``: QI panel too)."""
    doc = ensure_document(doc, DOCUMENT_NAME)

    if panel_qi:
        panel = {"shell": _make_qi_panel(doc)}
    else:
        # The panel: a draped composite shell at 30 degrees (baseline).
        panel_plate = _make_shape_object(
            doc, "PanelPlate", Part.makePlane(PLATE_LENGTH, PLATE_WIDTH)
        )
        panel = create_composite_feature_stack(doc, panel_plate, name_prefix="Panel")
        panel["rosette"].Angle = FABRIC_OFFSET_ANGLE
        panel["shell"].DrapePitch = DRAPE_PITCH
        doc.recompute()

    # The stiffener: Z-section along the panel, with its own QI laminate.
    # No web rosette is created and the web shell never drapes (D8).
    stiffener_laminate = _make_qi_laminate(doc, "StiffenerLaminate")
    stiffener = doc.addObject("Part::FeaturePython", "ZStiffener")
    StiffenerFP(
        stiffener,
        support=panel["shell"],
        cut_surface=_make_shape_object(
            doc, "ZStiffenerCutSurface", plate_cut_surface()
        ),
        profile=_make_sketch(doc, "ZStiffenerProfile", _z_profile()),
    )
    stiffener.Laminate = stiffener_laminate
    if FreeCAD.GuiUp:
        ViewProviderStiffener(stiffener.ViewObject)
    add_stiffener_filters(doc, stiffener)
    doc.recompute()

    # Visibility must be set after the creating recompute settles (the
    # GUI leaves recompute-born shells invisible).
    ensure_stiffener_shells_visible(stiffener)

    web_shell = doc.getObject(f"{stiffener.Name}_Web")
    foot_shell = doc.getObject(f"{stiffener.Name}_Foot")
    scl = foot_shell.Laminate if foot_shell is not None else None

    return {
        "doc": doc,
        "stiffener": stiffener,
        "panel_shell": panel["shell"],
        "web_shell": web_shell,
        "foot_shell": foot_shell,
        "combined_laminate": scl,
        "web_rosette": stiffener.Rosette,
        "panel_qi": panel_qi,
        "combined_isotropic": (
            scl.IsotropicEquivalent if scl is not None else None
        ),
        "web_draped": bool(web_shell.DrapeValid) if web_shell else None,
        "foot_draped": bool(foot_shell.DrapeValid) if foot_shell else None,
        "panel_draped": bool(panel["shell"].DrapeValid),
    }


def main():
    case = build()
    scl = case["combined_laminate"]
    print(
        f"quasi_iso_stiffener_panel: combined={scl.Name if scl is not None else None} "
        f"derived_isotropic={case['combined_isotropic']} "
        f"web_rosette={case['web_rosette']}"
    )


if __name__ == "__main__":
    main()
