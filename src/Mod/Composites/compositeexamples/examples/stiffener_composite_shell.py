# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""StiffenerCompositeShell example — the combined layup at a stiffener joint.

A composite panel (30° fabric) carries a Z-section stiffener with its
own laminate (also laid at 30° in its rosette frame). The stiffener's
composite flow partitions the swept shell into a web shell (the
stiffener's own plies) and a foot shell (the base-row faces that run
along the panel), solves the two transfers onto the foot (panel → foot
seeds the foot drape; stiffener → foot is analysis-only), and builds
the ``SeamCompositeLaminate``: the effective stiffener⊕panel stack of
the lap joint, per-ply angles solved at the joint rather than nominal.

Weave exclusivity: the panel is re-supported on the stiffener's support
remainder, so each region renders exactly one weave — panel remainder,
foot strip (combined layup), web. In composite mode the stiffener's
CompoundFilters are hidden: every visible surface is a weave
(ADR-0002).

See docs/stiffener_composite_shell.md and
docs/adr/0002-stiffener-region-split-and-render-ownership.md.
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

FABRIC_OFFSET_ANGLE = 30.0  # fabric laid at 30 degrees on both sides
DRAPE_PITCH = 5.0

DOCUMENT_NAME = "Composites_Stiffener_Composite_Shell"


def _make_stiffener_laminate(doc, name):
    """A compact UD laminate for the stiffener's own structure."""
    from Composites.features.CompositeLaminate import CompositeLaminateFP
    from Composites.features.FibreCompositeLamina import FibreCompositeLaminaFP

    plies = []
    for idx, angle in enumerate((0.0, 90.0), start=1):
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
    laminate.Symmetry = SymmetryType.Assymmetric.name
    return laminate


def build(doc=None, run_solver=False):
    """Build a Z-stiffener composite shell on a draped panel."""
    doc = ensure_document(doc, DOCUMENT_NAME)

    # The panel: a draped composite shell at 30 degrees.
    panel_plate = _make_shape_object(
        doc, "PanelPlate", Part.makePlane(PLATE_LENGTH, PLATE_WIDTH)
    )
    panel = create_composite_feature_stack(doc, panel_plate, name_prefix="Panel")
    panel["rosette"].Angle = FABRIC_OFFSET_ANGLE
    panel["shell"].DrapePitch = DRAPE_PITCH
    doc.recompute()

    # The stiffener: Z-section along the panel, with its own laminate.
    # Linking the laminate switches the feature into full composite mode.
    stiffener_laminate = _make_stiffener_laminate(doc, "StiffenerLaminate")
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

    # 30-degree fabric on the stiffener side too: the flow auto-created
    # the web rosette at 0; rotate it and let the solves follow.
    web_rosette = stiffener.Rosette
    web_rosette.Angle = FABRIC_OFFSET_ANGLE
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
        "web_rosette": web_rosette,
    }


def main():
    case = build()
    scl = case["combined_laminate"]
    print(
        f"stiffener_composite_shell: foot={case['foot_shell'].Name} "
        f"combined={scl.Name if scl is not None else None} "
        f"thickness={scl.Thickness if scl is not None else None}"
    )


if __name__ == "__main__":
    main()
