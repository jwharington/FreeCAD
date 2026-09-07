# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Cylindrical panel to spherical cap — orientation transfer across a seam.

A pressure-vessel style transition: a cylindrical panel section and a
spherical cap section of the SAME radius, meeting along the seam arc
where the cap closes the shell. The cylindrical panel is draped from
its own rosette. The TransferRosette on the cap solves its angle so the
warp makes the same signed angle with the seam on both sides — the ply
continues across the seam the way a real layup does.
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

RADIUS = 50.0  # shared by shell and cap
SHELL_HEIGHT = 80.0
SWEEP_DEG = 60.0  # azimuthal width of both panels
CAP_LATITUDE_DEG = 75.0  # cap stops short of the pole (polar opening)
DRAPE_PITCH = 2.5  # stable pitch; the cap keeps a small seam-edge gap —
# nextdrape boundary snapping drops quads at some grid alignments
# (solver follow-up). Finer pitches pass quality but hit a flaky
# solver_failure at this size.


def _cylinder_panel():
    """Cylindrical panel face: RADIUS over SHELL_HEIGHT, SWEEP_DEG wide."""
    solid = Part.makeCylinder(
        RADIUS,
        SHELL_HEIGHT,
        FreeCAD.Vector(0.0, 0.0, 0.0),
        FreeCAD.Vector(0.0, 0.0, 1.0),
        SWEEP_DEG,
    )
    return next(
        face for face in solid.Faces if isinstance(face.Surface, Part.Cylinder)
    )


def _spherical_cap():
    """Spherical cap face of the same RADIUS, seated on the shell top.

    Upper spherical zone (equator to CAP_LATITUDE_DEG) centred at the
    shell top circle, so the cap's equator edge IS the shell's top arc —
    the seam. The cap stops short of the pole: a polar opening, as on a
    real vessel head, and it avoids the sphere's parametric singularity.
    """
    solid = Part.makeSphere(
        RADIUS,
        FreeCAD.Vector(0.0, 0.0, SHELL_HEIGHT),
        FreeCAD.Vector(0.0, 0.0, 1.0),
        0.0,
        CAP_LATITUDE_DEG,
        SWEEP_DEG,
    )
    return next(
        face for face in solid.Faces if isinstance(face.Surface, Part.Sphere)
    )


def build(doc=None, run_solver=False):
    """Create a shell panel and cap of one radius sharing a seam."""
    doc = ensure_document(doc, "Composites_CylSphereSeam")

    shell_panel = create_support_feature(doc, "ShellPanel", _cylinder_panel())
    shell = create_composite_feature_stack(doc, shell_panel, name_prefix="Shell")

    # The ply runs meridionally over the head (warp across the seam, not
    # around it): a circumferential warp strains absurdly against the
    # cap's converging latitudes.
    shell["rosette"].Angle = 90.0
    doc.recompute()

    cap_panel = create_support_feature(doc, "CapPanel", _spherical_cap())
    cap = create_composite_feature_stack(doc, cap_panel, name_prefix="Cap")

    for stack_shell in (shell["shell"], cap["shell"]):
        stack_shell.DrapePitch = DRAPE_PITCH
    doc.recompute()

    # Creating the transfer rosette wires the cap shell to it and solves
    # the angle for warp continuity across the shared seam arc.
    transfer = doc.addObject("Part::FeaturePython", "TransferRosette")
    TransferRosetteFP(
        transfer,
        support=(cap_panel, ["Face1"]),
        master_shell=shell["shell"],
        attachment_shell=cap["shell"],
    )
    doc.recompute()

    # The stack's placeholder rosette is superseded by the transfer rosette.
    doc.removeObject(cap["rosette"].Name)
    doc.recompute()

    return {
        "doc": doc,
        "transfer": transfer,
        "shell_shell": shell["shell"],
        "cap_shell": cap["shell"],
    }
