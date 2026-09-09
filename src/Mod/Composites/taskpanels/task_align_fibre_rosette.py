# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Creation task panel for the AlignFibreRosette command.

Guides the reference picking the command needs — the composite shell,
the rosette anchor, and the second point the warp fibre must pass
through.  Each row arms on its *Pick…* button; the next 3D-view
selection that matches the row's filter fills it and disarms the row.
The anchor resolver maps a pick on the draped shell onto the shell's
own support (the rosette anchors on the support face — the shell's
shape mirrors it, so subelement names carry over).

GUI-only: imported lazily from the command's ``Activated``, never at
module load (headless must not touch FreeCADGui/Qt).
"""

from os import path

import FreeCAD
import FreeCADGui

from .. import UIPATH
from ..features.AlignFibreRosette import create_align_fibre_rosette
from ..features.CompositeShell import is_composite_shell

# Row key → (line edit, pick button) widget names live in the .ui file;
# the filter callables below decide which selections each row accepts.


def _resolve_shell(obj, subnames):
    """The composite shell itself — subelements ignored."""
    if obj is not None and is_composite_shell(obj):
        return obj
    return None


def _resolve_anchor(obj, subnames):
    """Anchor link: a face/edge/vertex of the shell's support, or of the
    shell itself (the shape mirrors the support, so the subelement name
    carries over), or of any other pickable shape."""
    if obj is None or not subnames:
        return None
    if is_composite_shell(obj):
        if obj.Support is not None:
            return (obj.Support, list(subnames))
        return None
    if subnames[0].startswith(("Face", "Edge", "Vertex")):
        return (obj, list(subnames))
    return None


def _resolve_second_point(obj, subnames):
    """Second point: a vertex of any pickable object."""
    if obj is None or not subnames or not subnames[0].startswith("Vertex"):
        return None
    return (obj, list(subnames))


_ROWS = {
    "composite_shell": (
        "edt_shell",
        "btn_pick_shell",
        _resolve_shell,
        "pick the composite shell",
    ),
    "support": (
        "edt_anchor",
        "btn_pick_anchor",
        _resolve_anchor,
        "pick the rosette anchor (face, edge or vertex)",
    ),
    "second_point": (
        "edt_second",
        "btn_pick_second",
        _resolve_second_point,
        "pick the second point (a vertex)",
    ),
}


_active_panel = None  # live handle for GUI automation / tests


class _TaskPanel:
    """Task dialog protocol object for FreeCADGui.Control.showDialog."""

    UI_FILENAME = "AlignFibreRosette.ui"

    def __init__(self, prefill=None):
        self.form = FreeCADGui.PySideUic.loadUi(
            path.join(UIPATH, self.UI_FILENAME)
        )
        self.obj = None
        self.refs = {"composite_shell": None, "support": None, "second_point": None}
        self._armed = None
        global _active_panel
        _active_panel = self

        for key, (_, btn_name, _, _) in _ROWS.items():
            getattr(self.form, btn_name).clicked.connect(
                self._make_arm(key)
            )
        self._apply_prefill(prefill or {})
        FreeCADGui.Selection.addObserver(self)
        self._armed = self._next_missing()
        self._update()

    # ── task dialog protocol ─────────────────────────────────────

    def getForm(self):
        return self.form

    def accept(self):
        if self.refs["composite_shell"] is None:
            return False
        doc = FreeCAD.ActiveDocument
        try:
            self.obj = create_align_fibre_rosette(
                doc,
                composite_shell=self.refs["composite_shell"],
                support=self.refs["support"],
                second_point=self.refs["second_point"],
            )
        except Exception as exc:  # noqa: BLE001 - surfaced in the dialog
            FreeCAD.Console.PrintError(f"AlignFibreRosette: {exc}\n")
            return False
        FreeCADGui.Selection.removeObserver(self)
        global _active_panel
        _active_panel = None
        return True

    def reject(self):
        FreeCADGui.Selection.removeObserver(self)
        global _active_panel
        _active_panel = None
        return True

    # ── selection observer ───────────────────────────────────────

    def addSelection(self, doc_name, obj_name, sub, point):
        if self._armed is None:
            return
        doc = FreeCAD.getDocument(doc_name)
        obj = doc.getObject(obj_name)
        subnames = [sub] if sub else []
        row = self._armed
        resolved = _ROWS[row][2](obj, subnames)
        if resolved is None:
            return  # keep the row armed for the next pick
        self.refs[row] = resolved
        self._armed = self._next_missing()
        self._update()

    # ── internals ────────────────────────────────────────────────

    def _make_arm(self, key):
        def _arm():
            self._armed = None if self._armed == key else key
            self._update()

        return _arm

    def _next_missing(self):
        """The first unfilled row, in pick order — armed automatically so
        the guided flow is pick-by-click; manual Pick… overrides."""
        for key in _ROWS:
            if self.refs[key] is None:
                return key
        return None

    def _apply_prefill(self, prefill):
        """Pre-fill rows from the command's pre-selection, when present."""
        for key, value in prefill.items():
            if key not in self.refs or value is None:
                continue
            if isinstance(value, tuple):
                value = (value[0], list(value[1:]))
            self.refs[key] = value

    def _update(self):
        """Refresh the row readouts, button states, and status line."""
        for key, (edt_name, btn_name, _, prompt) in _ROWS.items():
            getattr(self.form, btn_name).setChecked(self._armed == key)
            edit = getattr(self.form, edt_name)
            ref = self.refs[key]
            if ref is None:
                edit.setText("")
            elif isinstance(ref, tuple):
                edit.setText(f"{ref[0].Label} · {ref[1][0]}")
            else:
                edit.setText(ref.Label)
        if self._armed is not None:
            self.form.lbl_status.setText(_ROWS[self._armed][3])
        elif self.refs["composite_shell"] is None:
            self.form.lbl_status.setText(
                "pick the composite shell to begin"
            )
        else:
            self.form.lbl_status.setText("")
