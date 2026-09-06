# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""TransferRosette example — ply orientation continued across a bend.

A realistic transition between surfaces: a flat leg and a cylindrical
radius laid up as one sheet, sharing the bend line. The flat leg is
draped from its own rosette. The TransferRosette on the radius solves
its angle so the warp makes the same signed angle with the bend line on
both sides — the ply continues across the bend exactly the way a real
layup does.

The surfaces bound the drape naturally: the radius is a quarter
cylinder, so the weft marches 90 degrees and stops. Nothing wraps
around.
"""

import math

import FreeCAD
import Part

from ...features.TransferRosette import TransferRosetteFP
from ._shell_example_common import (
    create_composite_feature_stack,
    create_support_feature,
    ensure_document,
)

LEG_LENGTH = 100.0  # along X — the bend line direction
LEG_WIDTH = 80.0  # along Y, ending at the bend line
BEND_RADIUS = 30.0
# Fine pitch so the arc is many cells wide. This works around a nextdrape
# boundary-snapping weakness: at some grid alignments the snapped boundary
# rows duplicate and their degenerate quads are dropped, leaving gaps
# (coverage < 1.0 with gap_fraction failures). Solver-side fix is a
# follow-up; the right answer is not "tune the pitch".
DRAPE_PITCH = 2.5


def _bend_face():
    """Quarter-cylinder radius extending the leg's far edge upward.

    Starts at the leg edge (y = LEG_WIDTH, z = 0) tangent to the leg —
    continuing in the leg's own +y direction — and curves up through 90
    degrees to a vertical tangent at (y = LEG_WIDTH + BEND_RADIUS).
    """
    mid = math.radians(45.0)
    arc = Part.Arc(
        FreeCAD.Vector(0.0, LEG_WIDTH, 0.0),
        FreeCAD.Vector(
            0.0,
            LEG_WIDTH + BEND_RADIUS * math.sin(mid),
            BEND_RADIUS * (1.0 - math.cos(mid)),
        ),
        FreeCAD.Vector(0.0, LEG_WIDTH + BEND_RADIUS, BEND_RADIUS),
    ).toShape()
    return arc.extrude(FreeCAD.Vector(LEG_LENGTH, 0.0, 0.0))


def build(doc=None, run_solver=False):
    """Create a flat leg and a bend sharing one continuous ply orientation."""
    doc = ensure_document(doc, "Composites_TransferRosette")

    leg = create_support_feature(
        doc, "FlatLeg", Part.makePlane(LEG_LENGTH, LEG_WIDTH)
    )
    master = create_composite_feature_stack(doc, leg, name_prefix="Leg")

    bend = create_support_feature(doc, "Bend", _bend_face())
    attachment = create_composite_feature_stack(doc, bend, name_prefix="Bend")

    for shell in (master["shell"], attachment["shell"]):
        shell.DrapePitch = DRAPE_PITCH
    doc.recompute()

    # Creating the transfer rosette rewires the attachment shell and solves
    # its angle for warp continuity across the shared bend line.
    transfer = doc.addObject("Part::FeaturePython", "TransferRosette")
    TransferRosetteFP(
        transfer,
        support=(bend, ["Face1"]),
        master_shell=master["shell"],
        attachment_shell=attachment["shell"],
    )
    doc.recompute()

    # The stack's placeholder rosette is superseded by the transfer rosette.
    doc.removeObject(attachment["rosette"].Name)
    doc.recompute()

    return {
        "doc": doc,
        "transfer": transfer,
        "master_shell": master["shell"],
        "attachment_shell": attachment["shell"],
    }
