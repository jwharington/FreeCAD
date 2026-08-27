# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Synthetic primitive shapes for mould draft-envelope tests.

Cones and spheres with known geometry so draft-envelope behaviour can be
pinned without depending on the blade/loft lofts. Each factory returns a
solid ``Part.Shape``.
"""

from __future__ import annotations

import FreeCAD as App
import Part


_CONE_BASE_RADIUS = 10.0
_CONE_HEIGHT = 20.0


def make_vertical_cone():
    """Cone apex-up, base on z=0. Draw direction +Z hooks the upper half."""
    return Part.makeCone(_CONE_BASE_RADIUS, 0.0, _CONE_HEIGHT)


def make_sideways_cone():
    """Cone lying along +X (apex at +X). Draw direction +X hooks the upper half."""
    cone = Part.makeCone(_CONE_BASE_RADIUS, 0.0, _CONE_HEIGHT)
    cone.rotate(App.Vector(0, 0, 0), App.Vector(0, 1, 0), -90.0)
    return cone


def make_angled_cone(angle_deg):
    """Cone whose axis is tilted ``angle_deg`` from +Z toward +X."""
    cone = Part.makeCone(_CONE_BASE_RADIUS, 0.0, _CONE_HEIGHT)
    cone.rotate(App.Vector(0, 0, 0), App.Vector(0, 1, 0), angle_deg)
    return cone


def make_sphere(radius=5.0):
    """Sphere centred at the origin. Convex: releasable on both sides only at
    the centre parting plane, on exactly one side elsewhere."""
    return Part.makeSphere(radius)
