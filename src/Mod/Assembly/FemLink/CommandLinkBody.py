import FreeCAD as App
import FreeCADGui as Gui
from PySide.QtCore import QT_TRANSLATE_NOOP
from UtilsAssembly import activeAssembly, isAssemblyCommandActive

from .LinkBody import LinkBody
from .ViewLinkBody import VPLinkBody

if App.GuiUp:
    import FreeCADGui as Gui


class CommandLinkBody:
    def __init__(self):
        pass

    def GetResources(self):
        return {
            "Pixmap": "FemLink_LinkBody",
            "MenuText": QT_TRANSLATE_NOOP("FemLink_LinkBody", "Link body"),
            "ToolTip": QT_TRANSLATE_NOOP("FemLink_LinkBody", "Link body"),
        }

    def IsActive(self):
        return isAssemblyCommandActive()

    def Activated(self):
        doc = App.ActiveDocument
        body = None
        if App.GuiUp:
            sel = Gui.Selection.getSelection()
            if sel and sel[0].isDerivedFrom("App::Link"):
                body = sel[0]
            Gui.Selection.clearSelection()

        obj = doc.addObject(
            "App::FeaturePython",
            "LinkBody",
        )
        LinkBody(obj, body)
        if App.GuiUp:
            VPLinkBody(obj.ViewObject)
        assembly = activeAssembly()
        assembly.addObject(obj)
        doc.recompute()


if App.GuiUp:
    Gui.addCommand("FemLink_LinkBody", CommandLinkBody())
