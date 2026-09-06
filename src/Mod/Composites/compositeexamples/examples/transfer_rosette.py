# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""TransferRosette example — carry the master orientation to another shell.

A flat master plate is draped from its own rosette. A TransferRosette then
reads the master plate's orientation where the shells would join and writes
it onto the cylindrical attachment shell, whose drape is seeded from it.

Both shells render the fibre weave: the cylinder's grid is the plate's
orientation mapped around the curve.
"""

import Part

from ...features.TransferRosette import TransferRosetteFP
from ._shell_example_common import (
    create_composite_feature_stack,
    create_support_feature,
    ensure_document,
)

PLATE_SIDE = 100.0
CYLINDER_RADIUS = 50.0
CYLINDER_HEIGHT = 100.0


def build(doc=None, run_solver=False):
    """Create a master plate and a cylinder sharing one orientation."""
    doc = ensure_document(doc, "Composites_TransferRosette")

    plate = create_support_feature(
        doc, "Plate", Part.makePlane(PLATE_SIDE, PLATE_SIDE)
    )
    master = create_composite_feature_stack(doc, plate, name_prefix="Plate")

    cylinder_shape = next(
        face
        for face in Part.makeCylinder(CYLINDER_RADIUS, CYLINDER_HEIGHT).Faces
        if isinstance(face.Surface, Part.Cylinder)
    )
    cylinder = create_support_feature(doc, "Cylinder", cylinder_shape)
    attachment = create_composite_feature_stack(
        doc, cylinder, name_prefix="Cylinder"
    )

    transfer = doc.addObject("Part::FeaturePython", "TransferRosette")
    TransferRosetteFP(
        transfer,
        support=(cylinder, ["Face1"]),
        master_shell=master["shell"],
        attachment_shell=attachment["shell"],
    )
    doc.recompute()

    # The attachment shell drapes from the transferred orientation.
    doc.removeObject(attachment["rosette"].Name)
    attachment["shell"].Rosette = transfer
    doc.recompute()

    return {
        "doc": doc,
        "transfer": transfer,
        "master_shell": master["shell"],
        "attachment_shell": attachment["shell"],
    }
