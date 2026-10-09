# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

from typing import List

from FreeCAD import Console
from pivy import coin


class CompositeBaseFP:
    # The ViewProvider class that restores this feature's serialised VP
    # proxy; each concrete feature sets it (see onDocumentRestored).
    view_provider_class = None

    def __init__(self, obj):
        obj.addExtension("App::SuppressibleExtensionPython")
        obj.Proxy = self

    def __getstate__(self):
        return {}

    def __setstate__(self, state):
        return None

    def onDocumentRestored(self, obj):
        # Restore must not re-solve: an up-to-date document opens inert
        # (the previous unconditional recompute re-draped every shell and
        # re-swept every stiffener on each load, ~15 s on the fuselage
        # model, and made the GUI grind).  FreeCAD settles any object
        # restore genuinely touched; the extension add below is the only
        # change we make ourselves.
        if not obj.hasExtension("App::SuppressibleExtensionPython"):
            obj.addExtension("App::SuppressibleExtensionPython")
            obj.recompute()
        # Repair the serialised ViewProvider proxy: FreeCAD serialises the
        # VP proxy as an int (a memory address) on save, so after restore
        # it is not a Python object — icons, claimChildren and task panels
        # all break, and interacting with those objects in the tree grinds
        # on the broken proxy.  Each concrete feature names its VP class;
        # re-attach here for all of them (previously only CompositeShellFP
        # repaired its own, leaving plies, laminates, rosettes and rings
        # broken).
        vobj = getattr(obj, "ViewObject", None)
        vp_class = getattr(self, "view_provider_class", None)
        if (
            vobj is not None
            and vp_class is not None
            and isinstance(getattr(vobj, "Proxy", None), int)
        ):
            proxy = vp_class(vobj)
            vobj.Proxy = proxy
            # The VP constructor only sets the proxy; attach() is what
            # binds Object/ViewObject and builds the display mode, and
            # FreeCAD does not call it for a proxy assigned after restore.
            # Without it the VP methods that use self.ViewObject break the
            # features that touch them (the foot shells went Invalid via
            # raise_render_order).  Same repair the shell's weave
            # injection has always done for itself.
            if getattr(proxy, "ViewObject", None) is not vobj and hasattr(proxy, "attach"):
                proxy.attach(vobj)


class VPCompositeBase:
    # based on view_base_femobject.py
    _taskPanel = None

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = (
            vobj.Object
        )  # used on various places, claim childreens, get icon, etc.
        self.ViewObject = vobj
        self.standard = coin.SoGroup()
        vobj.addDisplayMode(self.standard, "Standard")

    def setEdit(self, vobj, mode=0):
        import FreeCADGui

        if self._taskPanel is None:
            # avoid edit mode by return False
            # https://forum.freecad.org/viewtopic.php?t=12139&start=10#p161062
            return False
        # show task panel
        task = self._taskPanel(vobj.Object)
        FreeCADGui.Control.showDialog(task)
        return True

    def unsetEdit(self, vobj, mode=0):
        import FreeCADGui

        FreeCADGui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        import FreeCADGui

        guidoc = FreeCADGui.getDocument(vobj.Object.Document)
        # check if another VP is in edit mode
        # https://forum.freecad.org/viewtopic.php?t=13077#p104702
        if not guidoc.getInEdit():
            guidoc.setEdit(vobj.Object.Name)
        else:
            from PySide.QtGui import QMessageBox

            message = (
                "Active Task Dialog found! "
                "Please close this one before opening a new one!"
            )
            QMessageBox.critical(None, "Error in tree view", message)
            Console.PrintError(message + "\n")
        return True

    def getDisplayModes(self, obj) -> List[str]:
        return ["Standard"]

    def getDefaultDisplayMode(self) -> str:
        return "Standard"

    def setDisplayMode(self, mode):
        return mode

    def updateData(self, vobj, prop):
        # Update visual data based on feature properties
        pass

    def __getstate__(self):
        return {}

    def __setstate__(self, state):
        return None

    # they are needed, see:
    # https://forum.freecad.org/viewtopic.php?f=18&t=44021
    # https://forum.freecad.org/viewtopic.php?f=18&t=44009
    def dumps(self):
        return None

    def loads(self, state):
        return None

    def claimChildren(self):
        return []
