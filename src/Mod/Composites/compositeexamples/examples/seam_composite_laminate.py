# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""SeamCompositeLaminate example — the combined layup at an overlap seam.

Two coplanar composite panels (master + attachment) share the x = 100
edge, each draped with the fabric laid at 30 degrees to the panel
edges. The ``SeamShellFP`` extraction cuts a seam strip out of the
attachment, solves both transfer rosettes (master → seam seeds the seam
shell's drape; attachment → seam is analysis-only), and builds the
``SeamCompositeLaminate``: the effective combined stack of the joint,
with per-ply angles evaluated at the seam rather than nominal.

The attachment is re-supported on the remainder, so each region of the
joint shows exactly one weave: the master plate, the seam strip (the
combined layup), and the attachment remainder.

See docs/seam_composite_laminate.md and
docs/adr/0001-seam-angle-analysis-symmetric-transfers.md.
"""

import FreeCAD
import Part

from ...features.SeamExtraction import SeamShellFP
from ._shell_example_common import (
    create_composite_feature_stack,
    create_support_feature,
    ensure_document,
)

PLATE_LENGTH = 100.0  # along X — the joint line direction... the shared
# edge runs along Y at x = PLATE_LENGTH
PLATE_WIDTH = 80.0  # along Y
FABRIC_OFFSET_ANGLE = 30.0  # fabric laid at 30 degrees to the panel edges
SEAM_WIDTH = "15.0 mm"
DRAPE_PITCH = 2.5

DOCUMENT_NAME = "Composites_Seam_Composite_Laminate"


def build(doc=None, run_solver=False):
    """Create two panels, extract the seam, and build the combined layup."""
    doc = ensure_document(doc, DOCUMENT_NAME)

    master_plate = create_support_feature(
        doc, "MasterPlate", Part.makePlane(PLATE_LENGTH, PLATE_WIDTH)
    )
    master = create_composite_feature_stack(doc, master_plate, name_prefix="Master")
    master["rosette"].Angle = FABRIC_OFFSET_ANGLE

    att_shape = Part.makePlane(PLATE_LENGTH, PLATE_WIDTH)
    att_shape.translate(FreeCAD.Vector(PLATE_LENGTH, 0.0, 0.0))
    attachment_plate = create_support_feature(doc, "AttachmentPlate", att_shape)
    attachment = create_composite_feature_stack(
        doc, attachment_plate, name_prefix="Attachment"
    )
    attachment["rosette"].Angle = FABRIC_OFFSET_ANGLE

    for shell in (master["shell"], attachment["shell"]):
        shell.DrapePitch = DRAPE_PITCH
    doc.recompute()

    # Extraction cuts the seam strip out of the attachment, solves both
    # transfer rosettes, and builds the SeamCompositeLaminate on the seam
    # shell. The attachment is re-supported on the remainder.
    seam = doc.addObject("Part::FeaturePython", "SeamCompositeLaminateExample")
    SeamShellFP(seam, master["shell"], attachment["shell"], seam_width=SEAM_WIDTH)
    doc.recompute()

    seam_shell = getattr(seam, "Seam", None)
    # Visibility must be set after the creating recompute settles (the
    # GUI leaves recompute-born shells invisible).
    if seam_shell is not None:
        SeamShellFP._ensure_seam_shell_visible(seam_shell)
    scl = seam_shell.Laminate if seam_shell is not None else None
    remainder = getattr(seam, "Remainder", None)

    return {
        "doc": doc,
        "seam_feature": seam,
        "seam_shell": seam_shell,
        "seam_composite_laminate": scl,
        "remainder": remainder,
        "master_shell": master["shell"],
        "attachment_shell": attachment["shell"],
    }
