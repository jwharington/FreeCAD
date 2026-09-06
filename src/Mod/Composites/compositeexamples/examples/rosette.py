# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Rosette example — the fibre orientation datum on a draped shell.

A flat plate is draped with a quasi-isotropic laminate. The Rosette on the
plate face is the datum the drape is seeded from: its origin is the point
where the flat ply starts, its X axis is the warp fibre direction, and its
Angle rotates the whole texture about the origin.

Look for the red/green fibre symbol at the plate centre — the drape grid on
the shell is aligned with it.
"""

import Part

from ._shell_example_common import (
    create_composite_feature_stack,
    create_support_feature,
    ensure_document,
)

PLATE_SIDE = 100.0


def build(doc=None, run_solver=False):
    """Create a draped plate with a plain Rosette datum."""
    doc = ensure_document(doc, "Composites_Rosette")

    support = create_support_feature(
        doc, "Plate", Part.makePlane(PLATE_SIDE, PLATE_SIDE)
    )
    stack = create_composite_feature_stack(doc, support, name_prefix="Rosette")
    return {
        "doc": doc,
        "rosette": stack["rosette"],
        "shell": stack["shell"],
    }
