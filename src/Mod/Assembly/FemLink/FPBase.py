from abc import ABC, abstractmethod
from typing import List

import FreeCAD
from FreeCAD import Console
from pivy import coin


class FPBase(ABC):

    def __init__(self, obj):
        obj.addExtension("App::SuppressibleExtensionPython")
        obj.Proxy = self

    def __getstate__(self):
        return {}

    def __setstate__(self, state):
        return None

    def onDocumentRestored(self, obj):
        if not obj.hasExtension("App::SuppressibleExtensionPython"):
            obj.addExtension("App::SuppressibleExtensionPython")
        obj.recompute()

    def onChanged(self, fp, prop):
        # Console.PrintMessage(f"onChanged {prop}\n")
        pass

    def getAssembly(self, joint):
        # adapted from JointObject.py
        for obj in joint.InList:
            if obj.isDerivedFrom("Assembly::AssemblyObject"):
                return obj
            elif obj.isDerivedFrom("Assembly::AssemblyLink"):
                return self.getAssembly(obj)

        return None


class VPBase:

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object  # used on various places, claim childreens, get icon, etc.
        self.ViewObject = vobj
        self.standard = coin.SoGroup()
        vobj.addDisplayMode(self.standard, "Standard")

    def getDisplayModes(self, obj) -> List[str]:
        return ["Standard"]

    def getDefaultDisplayMode(self) -> str:
        return "FlatLines"

    def setEdit(self, vobj, mode=0):
        return False

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
