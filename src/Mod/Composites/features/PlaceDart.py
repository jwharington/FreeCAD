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

from .. import DART_TOOL_ICON, is_comp_type
from .Command import BaseCommand


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

    def Activated(self):
        state = self._collect_selection()
        if state is None:
            return

        shell, wires = state
        shell.DrapeCuts = self._merge_drape_cuts(shell, wires)
        if getattr(shell, "Proxy", None) is not None:
            shell.Proxy._needs_recompute = True

        doc = getattr(shell, "Document", None) or FreeCAD.ActiveDocument
        if doc is not None and hasattr(doc, "recompute"):
            doc.recompute()

        FreeCADGui.Selection.clearSelection()

    def IsActive(self):
        return self._collect_selection() is not None


FreeCADGui.addCommand("Composites_PlaceDart", PlaceDartCommand())
