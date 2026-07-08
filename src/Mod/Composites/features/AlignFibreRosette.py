# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""AlignFibreRosette — a Rosette whose Angle is solved so a warp fibre
passes through a second picked point on the draped surface.

It EXTENDS :class:`RosetteFP` (it *is* a Rosette: anchored on a Face via the
inherited ``Support``, with an ``Angle`` that folds into the LCS X-axis). The
``Angle`` is not given by the user but solved iteratively by
:func:`tools.rosette_solver.solve_rosette_angle` so that the warp fibre
(``v = 0`` in texture coords) passes through the ``SecondPoint`` vertex on the
draped shell. The solved Angle is written back into the inherited ``Angle``
property.

Architecture: the iterative solve mutates ``Angle`` and calls
``Document.recompute()``. To prevent infinite recursion, the solve is driven
from ``onChanged`` for the defining properties (``Support`` /
``CompositeShell`` / ``SecondPoint``), guarded by a ``_solving`` proxy flag so
that the ``onChanged("Angle")`` events fired by the solver itself are
swallowed. ``execute`` only places the LCS from the current ``Angle`` (no
solve) — exactly the base Rosette behaviour.
"""

import Part

from .. import (
    ALIGN_FIBRE_ROSETTE_TOOL_ICON,
    is_comp_type,
)
from ..tools.rosette_solver import (
    RosetteSolveError,
    solve_rosette_angle,
)
from .Command import BaseCommand
from .CompositeShell import is_composite_shell
from .Rosette import RosetteFP, ViewProviderRosette, is_rosette


def is_align_fibre_rosette(obj):
    """Return True if *obj* is an AlignFibreRosette feature."""
    return is_comp_type(obj, "App::FeaturePython", "Composite::AlignFibreRosette")


def _vertex_from_link_sub(link_sub):
    """Resolve a ``PropertyLinkSubGlobal`` value to a ``Part.Vertex``.

    ``link_sub`` is ``(obj, [subname])``; returns the first resolved shape
    element, which must be a ``Part.Vertex``.
    """
    (sup, sub) = link_sub
    geom_list = sup.getSubObject(sub)
    if geom_list is None or len(geom_list) == 0:
        raise ValueError("SecondPoint sub-object could not be resolved")
    geom = geom_list[0]
    if not isinstance(geom, Part.Vertex):
        raise ValueError(f"SecondPoint must be a Vertex, got {type(geom)}")
    return geom


class AlignFibreRosetteFP(RosetteFP):
    """FeaturePython for an AlignFibreRosette.

    Adds ``CompositeShell`` (the shell whose rosette this is) and ``SecondPoint``
    (a picked vertex the warp fibre ``v = 0`` must pass through). The inherited
    ``Support`` anchors the rosette on the face and the inherited ``Angle`` is
    the solved fibre orientation.
    """

    Type = "Composite::AlignFibreRosette"

    def __init__(self, obj, support=None, composite_shell=None, second_point=None):
        # Suppress any solve while the defining references are being set up.
        # Set before super().__init__ (which may trigger onChanged).
        self._solving = False
        super().__init__(obj, support)  # adds Support, Angle, LocalCoordinateSystem
        obj.addProperty(
            "App::PropertyLinkGlobal",
            "CompositeShell",
            "References",
            "Composite shell whose rosette this is",
        )
        obj.addProperty(
            "App::PropertyLinkSubGlobal",
            "SecondPoint",
            "References",
            "Picked vertex the warp fibre (v=0) must pass through",
        )
        obj.CompositeShell = composite_shell
        obj.SecondPoint = second_point
        self._solving = False

    def execute(self, fp):
        # Place the LCS from the current Angle. NO solve here — solving inside
        # execute() would recurse (the solver calls doc.recompute()).
        super().execute(fp)

    def onChanged(self, fp, prop):
        if getattr(self, "_solving", False):
            return
        # Don't run the iterative solve during document restore: the solve
        # calls doc.recompute() re-entrantly, which corrupts the restore
        # graph (and the draper/links may not be fully restored yet). The
        # solved Angle is persisted, so it survives restore; a later user
        # edit re-triggers the solve if needed.
        if fp.Document.Restoring:
            return
        match prop:
            case "Support" | "CompositeShell" | "SecondPoint":
                if fp.CompositeShell and fp.SecondPoint:
                    self._solving = True
                    try:
                        self._solve(fp)
                    finally:
                        self._solving = False
                    fp.recompute()  # place LCS for the final solved Angle
                else:
                    fp.recompute()
            case "Angle":
                fp.recompute()

    def _solve(self, fp):
        """Iteratively solve ``fp.Angle`` so the warp fibre (v=0) passes
        through ``fp.SecondPoint`` on the draped ``fp.CompositeShell``.

        The ``_solving`` guard is held by the caller; the ``onChanged("Angle")``
        events fired by the solver (which sets ``fp.Angle``) are swallowed.
        """
        shell = fp.CompositeShell
        if shell is None or not is_composite_shell(shell):
            raise ValueError("CompositeShell must be a CompositeShell feature")
        if fp.SecondPoint is None:
            raise ValueError("SecondPoint must be set")

        def error_fn(angle: float) -> float:
            vert = _vertex_from_link_sub(fp.SecondPoint)
            draper = shell.Proxy.get_draper()
            tc = draper.get_tex_coord_at_point(vert.Point, 0)
            return float(tc[1])  # v-coordinate; drive to 0

        angle = solve_rosette_angle(shell, fp, error_fn)
        fp.Angle = angle  # written while _solving=True (swallowed by guard)


class ViewProviderAlignFibreRosette(ViewProviderRosette):
    def getIcon(self):
        return ALIGN_FIBRE_ROSETTE_TOOL_ICON


def _is_vertex(o):
    """Return True if *o* is a Part vertex shape."""
    return isinstance(o, Part.Vertex)


class AlignFibreRosetteCommand(BaseCommand):
    icon = ALIGN_FIBRE_ROSETTE_TOOL_ICON
    menu_text = "Align Fibre Rosette"
    tool_tip = (
        "Create an AlignFibreRosette: a Rosette whose Angle is solved so the\n"
        "warp fibre (v=0) passes through a second picked vertex on the shell.\n"
        "Select a composite shell, a support face/vertex/edge (rosette anchor),\n"
        "and a second vertex the warp fibre must pass through."
    )
    sel_args = [
        {
            "key": "composite_shell",
            "test": is_composite_shell,
        },
        {
            "key": "support",
            "test": lambda o: isinstance(o, (Part.Vertex, Part.Edge, Part.Face)),
            "optional": True,
        },
        {
            "key": "second_point",
            "test": _is_vertex,
            "optional": True,
        },
    ]
    type_id = "App::FeaturePython"
    instance_name = "AlignFibreRosette"
    cls_fp = AlignFibreRosetteFP
    cls_vp = ViewProviderAlignFibreRosette


# Command registration moved to InitGui.py to avoid FreeCADGui dependency
