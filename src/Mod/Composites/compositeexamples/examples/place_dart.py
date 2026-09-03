# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Place dart example — project a wire cut onto a composite shell.

Builds a composite shell on a cylinder support and a closed wire source,
then runs the ``PlaceDartCommand`` (with the selection injected) so the
wire is projected onto the shell and added to its ``DrapeCuts`` list.
"""

import sys
import types

import FreeCAD
import Part

from ...features.CompositeShell import CompositeShellFP
from ...features.PlaceDart import PlaceDartCommand

DOCUMENT_NAME = "Composites_Place_Dart"


def _ensure_gui_stub():
    """Make FreeCADGui.Selection usable headless (mirrors compositestests.test_base).

    Handles both cases: FreeCADGui absent (install a stub) and FreeCADGui
    present but without a Selection attribute (FreeCADCmd headless).
    """
    import sys
    import types

    gui = sys.modules.get("FreeCADGui")
    if gui is None:
        gui = types.SimpleNamespace()
        gui.addCommand = lambda *a, **k: None
        gui.addWorkbench = lambda *a, **k: None
        sys.modules["FreeCADGui"] = gui
    if not hasattr(gui, "Selection"):
        sel = types.SimpleNamespace()
        sel.getSelectionEx = lambda *a, **k: []
        sel.clearSelection = lambda *a, **k: None
        gui.Selection = sel


def _ensure_document(doc):
    """Return ``doc`` or a fresh document for this example."""
    if doc is not None:
        return doc
    if DOCUMENT_NAME in FreeCAD.listDocuments():
        FreeCAD.closeDocument(DOCUMENT_NAME)
    return FreeCAD.newDocument(DOCUMENT_NAME)


def _closed_wire():
    """A closed square wire to project onto the shell."""
    return Part.makePolygon([
        FreeCAD.Vector(-5.0, -5.0, 0.0),
        FreeCAD.Vector(5.0, -5.0, 0.0),
        FreeCAD.Vector(5.0, 5.0, 0.0),
        FreeCAD.Vector(-5.0, 5.0, 0.0),
        FreeCAD.Vector(-5.0, -5.0, 0.0),
    ])


def build(doc=None, run_solver=False):
    """Build the place-dart example.

    Parameters
    ----------
    doc
        Optional FreeCAD document receiving model entities.
    run_solver
        Accepted for runner parity; the dart projection is immediate.

    Returns
    -------
    dict
        The resolved document, the shell, the wire source, and the projected
        ``DrapeCuts`` list.
    """

    doc = _ensure_document(doc)

    support = doc.addObject("Part::Feature", "Support")
    support.Shape = Part.makeCylinder(10.0, 20.0)

    shell = doc.addObject("Part::FeaturePython", "CompositeShell")
    CompositeShellFP(shell, support)

    wire = doc.addObject("Part::Feature", "DartWire")
    wire.Shape = _closed_wire()

    doc.recompute()

    # Inject the selection (shell + wire) and run the real command path.
    _ensure_gui_stub()
    from unittest.mock import patch

    class _Entry:
        def __init__(self, obj):
            self.Object = obj

    selection_ex = [_Entry(shell), _Entry(wire)]
    with patch("FreeCADGui.Selection.getSelectionEx", return_value=selection_ex):
        PlaceDartCommand().Activated()

    return {
        "doc": doc,
        "shell": shell,
        "wire": wire,
        "drape_cuts": list(getattr(shell, "DrapeCuts", None) or []),
    }


def main():
    """Run the example in its own document."""
    result = build()
    print(f"Created {len(result['doc'].Objects)} objects")
    print(f"DrapeCuts: {len(result['drape_cuts'])} projected wire(s)")


if __name__ == "__main__":
    main()
