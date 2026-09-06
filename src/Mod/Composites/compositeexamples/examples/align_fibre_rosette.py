# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""AlignFibreRosette example — solve the fibre angle through a picked point.

The drape is seeded from an AlignFibreRosette instead of a plain Rosette.
Its Angle is not set by hand: the solver rotates it until the warp fibre
(v = 0) passes through a picked vertex.

The vertex sits at 45 degrees from the rosette origin at the plate centre,
so the solve must land on 45 — the drape grid on the plate visibly turns
with it. A solve that cannot converge leaves the feature Invalid in the
tree; a failed alignment is never silent.
"""

import FreeCAD
import Part

from ...features.AlignFibreRosette import AlignFibreRosetteFP
from ._shell_example_common import (
    create_composite_feature_stack,
    create_support_feature,
    ensure_document,
)

PLATE_SIDE = 100.0
SECOND_POINT = FreeCAD.Vector(60.0, 60.0, 0.0)


def build(doc=None, run_solver=False):
    """Create a draped plate whose rosette angle is solved, not typed."""
    doc = ensure_document(doc, "Composites_AlignFibreRosette")

    support = create_support_feature(
        doc, "Plate", Part.makePlane(PLATE_SIDE, PLATE_SIDE)
    )
    stack = create_composite_feature_stack(doc, support, name_prefix="AlignFibre")
    shell = stack["shell"]

    # The align rosette replaces the stack's plain rosette: the solver steers
    # the drape by mutating its Angle, so the shell must seed from it.
    doc.removeObject(stack["rosette"].Name)
    align = doc.addObject("Part::FeaturePython", "AlignFibreRosette")
    AlignFibreRosetteFP(align, support=(support, ["Face1"]), composite_shell=None)
    doc.recompute()
    shell.Rosette = align
    align.CompositeShell = shell
    doc.recompute()

    point = doc.addObject("Part::Feature", "SecondPoint")
    point.Shape = Part.makeSphere(1.0, SECOND_POINT)
    doc.recompute()
    align.SecondPoint = (point, ["Vertex1"])
    doc.recompute()

    return {
        "doc": doc,
        "align_fibre": align,
        "shell": shell,
    }
