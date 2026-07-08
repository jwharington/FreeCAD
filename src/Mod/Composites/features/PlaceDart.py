# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""PlaceDart command.

The command records selected wire-like objects on a composite shell's
existing DrapeCuts property so the drape pipeline can treat them as cut
lines.
"""

from __future__ import annotations

import FreeCAD
import FreeCADGui
import Part

from .. import DART_TOOL_ICON, is_comp_type
from .Command import BaseCommand


PROJECT_TOLERANCE = 1e-6
PROJECTION_SAMPLES = 8


def is_composite_shell(obj) -> bool:
    return is_comp_type(obj, "Part::FeaturePython", "Composite::Shell")


def _is_dart_source(obj) -> bool:
    if is_composite_shell(obj):
        return False
    shape = getattr(obj, "Shape", None)
    if shape is None:
        return False
    edges = getattr(shape, "Edges", None)
    return bool(edges)


class PlaceDartCommand(BaseCommand):
    icon = DART_TOOL_ICON
    menu_text = "Place dart"
    tool_tip = (
        "Add wire-like objects to a composite shell's dart cut list. "
        "Select one composite shell and one or more wire sources."
    )
    sel_args = []
    type_id = "Part::FeaturePython"
    instance_name = "PlaceDart"
    cls_fp = None
    cls_vp = None

    def _collect_selection(self, selection_ex=None):
        if selection_ex is None:
            selection_ex = FreeCADGui.Selection.getSelectionEx()

        shell = None
        wires = []
        for entry in selection_ex:
            obj = getattr(entry, "Object", None)
            if obj is None:
                continue
            if is_composite_shell(obj):
                shell = obj
                continue
            if _is_dart_source(obj):
                wires.append(obj)

        if shell is None or not wires:
            return None

        unique_wires = []
        for wire in wires:
            if wire not in unique_wires:
                unique_wires.append(wire)
        return shell, unique_wires

    def _merge_drape_cuts(self, shell, wires):
        existing = list(getattr(shell, "DrapeCuts", None) or [])
        merged = []
        for item in existing + list(wires):
            if item not in merged:
                merged.append(item)
        return merged

    def _projection_name(self, shell, source):
        return f"{shell.Name}_{source.Name}_PlaceDartCut"

    def _project_point_to_support(self, support_shape, point):
        distance, pairs, _ = support_shape.distToShape(Part.Vertex(point))
        if not pairs or distance is None:
            return None
        projected, _ = pairs[0]
        return projected

    def _project_wire_to_support(self, support_shape, wire_shape):
        projected_points = []
        for edge in getattr(wire_shape, "Edges", []):
            points = edge.discretize(PROJECTION_SAMPLES)
            for point in points:
                projected = self._project_point_to_support(support_shape, point)
                if projected is None:
                    continue
                if projected_points:
                    last = projected_points[-1]
                    if projected.isEqual(last, PROJECT_TOLERANCE):
                        continue
                projected_points.append(projected)
        if len(projected_points) < 2:
            return None
        if hasattr(wire_shape, "isClosed") and wire_shape.isClosed():
            if not projected_points[0].isEqual(projected_points[-1], PROJECT_TOLERANCE):
                projected_points.append(projected_points[0])
        return Part.makePolygon(projected_points)

    def _ensure_projection_object(self, shell, source):
        doc = getattr(shell, "Document", None) or FreeCAD.ActiveDocument
        if doc is None:
            return None
        support = getattr(shell, "Support", None)
        support_shape = getattr(support, "Shape", None)
        if support_shape is None:
            return None
        projected_shape = self._project_wire_to_support(support_shape, source.Shape)
        if projected_shape is None:
            return None

        name = self._projection_name(shell, source)
        projected_obj = doc.getObject(name)
        if projected_obj is None:
            projected_obj = doc.addObject("Part::Feature", name)
            try:
                projected_obj.Visibility = False
            except Exception:
                pass
        projected_obj.Shape = projected_shape
        view_object = getattr(projected_obj, "ViewObject", None)
        if view_object is not None:
            view_object.Visibility = False
        return projected_obj

    def Activated(self):
        state = self._collect_selection()
        if state is None:
            return

        shell, wires = state
        projected_wires = []
        for wire in wires:
            projected = self._ensure_projection_object(shell, wire)
            if projected is not None:
                projected_wires.append(projected)

        if not projected_wires:
            return

        shell.DrapeCuts = self._merge_drape_cuts(shell, projected_wires)
        if getattr(shell, "Proxy", None) is not None:
            shell.Proxy._needs_recompute = True

        doc = getattr(shell, "Document", None) or FreeCAD.ActiveDocument
        if doc is not None and hasattr(doc, "recompute"):
            doc.recompute()

        FreeCADGui.Selection.clearSelection()

    def IsActive(self):
        return self._collect_selection() is not None


FreeCADGui.addCommand("Composites_PlaceDart", PlaceDartCommand())
