# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

import FreeCAD

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
            # Solve reference, not a geometry dependency: the real
            # dependency is the shell's Rosette link pointing back at this
            # rosette — visible back-references made shell→rosette→shell a
            # dependency cycle that tripped DAGView (known-issue #9).
            # Freshness is edit-driven: the solve re-runs when the defining
            # properties are set, and the shell re-draps through its own
            # links.
            "App::PropertyLinkHidden",
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

    def execute(self, fp):
        if getattr(self, "solve_error", None):
            raise RuntimeError(f"rosette alignment failed: {self.solve_error}")
        super().execute(fp)

    def _ensure_wired(self, fp) -> None:
        """Make the shell use this rosette as its orientation datum.

        The GUI command path (and any constructor-only script) never
        assigns ``shell.Rosette`` — the solved angle would steer a drape
        the shell never sees.  Same wiring rule as
        ``TransferRosetteFP._ensure_wired``; the example's manual wiring
        was the only thing masking this.
        """
        shell = fp.CompositeShell
        if shell is not None and getattr(shell, "Rosette", None) is not fp:
            shell.Rosette = fp

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

        self.solve_error = None  # a retry starts clean; _eval re-runs execute
        self._ensure_wired(fp)

        def error_fn(angle: float) -> float:
            vert = _vertex_from_link_sub(fp.SecondPoint)
            draper = shell.Proxy.get_draper()
            tc = draper.get_tex_coord_at_point(vert.Point, 0)
            return float(tc[1])  # v-coordinate; drive to 0

        previous_angle = fp.Angle
        try:
            angle = solve_rosette_angle(shell, fp, error_fn)
        except Exception as exc:  # noqa: BLE001 - any solve failure must be loud
            # A failed solve must not silently keep the last bracket probe's
            # angle: restore the previous orientation and remember the error,
            # so execute() raises and the feature shows as Invalid.
            fp.Angle = previous_angle
            self.solve_error = str(exc)
            raise
        fp.Angle = angle  # written while _solving=True (swallowed by guard)
        self.solve_error = None


class ViewProviderAlignFibreRosette(ViewProviderRosette):
    def getIcon(self):
        return ALIGN_FIBRE_ROSETTE_TOOL_ICON


def create_align_fibre_rosette(
    doc,
    composite_shell=None,
    support=None,
    second_point=None,
):
    """Create and wire an AlignFibreRosette (command / task-panel path).

    Mirrors the proven example sequence: the feature is created with the
    shell wired, and the second point is set after the creating recompute
    so the solve runs once, against a live drape.  The rosette wires
    itself as the shell's Rosette (``_ensure_wired``) — the solved angle
    steers the drape.
    """
    obj = doc.addObject("Part::FeaturePython", "AlignFibreRosette")
    AlignFibreRosetteFP(obj, support=support, composite_shell=composite_shell)
    if obj.ViewObject is not None:
        ViewProviderAlignFibreRosette(obj.ViewObject)
    from .Container import getCompositesContainer

    getCompositesContainer().addObject(obj)
    doc.recompute()
    if second_point is not None:
        obj.SecondPoint = second_point
        doc.recompute()
    return obj


def _is_vertex(o):
    """Return True if *o* is a Part vertex shape."""
    return isinstance(o, Part.Vertex)


class AlignFibreRosetteCommand(BaseCommand):
    icon = ALIGN_FIBRE_ROSETTE_TOOL_ICON
    menu_text = "Align Fibre Rosette"
    tool_tip = (
        "Create an AlignFibreRosette: a Rosette whose Angle is solved so the\n"
        "warp fibre (v=0) passes through a second picked vertex on the shell.\n"
        "Opens a task panel: pick the composite shell, a rosette anchor, and\n"
        "the second vertex the warp fibre must pass through."
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

    def Activated(self):
        """Open the creation task panel.

        The panel guides the reference picking (shell, anchor, second
        point) — the legacy pre-selection-only flow can't know the anchor
        and second point before the command starts.  Pre-selected
        references prefill the panel.  Headless callers (scripts) keep
        the direct pre-selection path.
        """
        if FreeCAD.GuiUp:
            import FreeCADGui

            # Lazy import: the taskpanel module pulls in FreeCADGui/Qt.
            from ..taskpanels.task_align_fibre_rosette import _TaskPanel

            FreeCADGui.Control.showDialog(
                _TaskPanel(prefill=self.check_sel(True) or {})
            )
            return
        super().Activated()

    def IsActive(self):
        # The task panel collects the references itself, so the command
        # is active with any open document — not only with a full
        # pre-selection.
        return FreeCAD.ActiveDocument is not None


# Command registration moved to InitGui.py to avoid FreeCADGui dependency
