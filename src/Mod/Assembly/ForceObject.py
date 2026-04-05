__title__ = "Assembly Force object"
__author__ = "John Wharington"
__url__ = "https://www.freecad.org"

import FreeCAD as App
from JointObject import (
    Joint,
    ViewProviderJoint,
)
from TaskAssemblyItemIJ import (
    TaskAssemblyCreateItemIJ,
    activeTask,
)

if App.GuiUp:
    import FreeCADGui as Gui
    from PySide import QtGui, QtWidgets

__title__ = "Assembly Joint object"
__author__ = "Ondsel"
__url__ = "https://www.freecad.org"

import UtilsAssembly
from FreeCAD import Console
from PySide import QtCore
from PySide.QtCore import QT_TRANSLATE_NOOP

translate = App.Qt.translate

TranslatedForceTypes = [
    translate("Assembly", "General"),
    translate("Assembly", "InLine"),
]

ForceTypes = [
    "General",
    "InLine",
]

MarkerKSigns = [
    "O",
    "I",
    "J",
]


class ForceTorque(Joint):

    def __init__(self, obj, type_index):
        obj.Proxy = self

        obj.addExtension("App::SuppressibleExtensionPython")

        obj.addProperty(
            "App::PropertyEnumeration",
            "ForceType",
            "Force",
            QT_TRANSLATE_NOOP("App::Property", "The type of the force"),
            locked=True,
        )
        obj.ForceType = ForceTypes  # sets the list
        obj.ForceType = ForceTypes[type_index]  # set the initial value
        obj.setEditorMode("ForceType", 1)
        # make this read-only

        self.createProperties(obj)
        self.setJointConnectors(obj, [])

    def createProperties(self, obj):
        # First Joint Connector
        if not hasattr(obj, "Reference1"):
            obj.addProperty(
                "App::PropertyXLinkSubHidden",
                "Reference1",
                "Joint Connector 1",
                QT_TRANSLATE_NOOP("App::Property", "The first reference of the joint"),
                locked=True,
            )

        if not hasattr(obj, "Placement1"):
            obj.addProperty(
                "App::PropertyPlacement",
                "Placement1",
                "Joint Connector 1",
                QT_TRANSLATE_NOOP(
                    "App::Property",
                    "This is the local coordinate system within Reference1's object that will be used for the joint",
                ),
                locked=True,
            )

        # Second Joint Connector
        if not hasattr(obj, "Reference2"):
            obj.addProperty(
                "App::PropertyXLinkSubHidden",
                "Reference2",
                "Joint Connector 2",
                QT_TRANSLATE_NOOP("App::Property", "The second reference of the joint"),
                locked=True,
            )

        if not hasattr(obj, "Placement2"):
            obj.addProperty(
                "App::PropertyPlacement",
                "Placement2",
                "Joint Connector 2",
                QT_TRANSLATE_NOOP(
                    "App::Property",
                    "This is the local coordinate system within Reference2's object that will be used for the joint",
                ),
                locked=True,
            )

    def onChanged(self, force, prop):
        """Do something when a property has changed"""
        # App.Console.PrintMessage("Change property: " + str(prop) + "\n")

        # during loading the onchanged may be triggered before full init.
        if App.isRestoring():
            return

        if prop == "Reference1" or prop == "Reference2":
            force.recompute()

        if (
            not hasattr(force, "Reference1")
            or not hasattr(force, "Reference2")
            or force.Reference1 is None
            or force.Reference2 is None
        ):
            return

    def setJointConnectors(self, force, refs):
        # current selection is a vector of strings like "Assembly.Assembly1.Assembly2.Body.Pad.Edge16" including both what selection return as obj_name and obj_sub

        if len(refs) >= 1:
            force.Reference1 = refs[0]
            force.Placement1 = self.findPlacement(force, force.Reference1, 0)
        else:
            force.Reference1 = None
            force.Placement1 = App.Placement()

        if len(refs) >= 2:
            force.Reference2 = refs[1]
            force.Placement2 = self.findPlacement(force, force.Reference2, 1)
            self.updateJCSPlacements(force)
        else:
            force.Reference2 = None
            force.Placement2 = App.Placement()

    def updateJCSPlacements(self, force):
        force.Placement1 = self.findPlacement(force, force.Reference1, 0)
        force.Placement2 = self.findPlacement(force, force.Reference2, 1)

    def findPlacement(self, force, ref, index=0):
        return UtilsAssembly.findPlacement(ref, False)


class ForceTorqueGeneral(ForceTorque):
    def __init__(self, obj):
        super().__init__(obj, 0)

    def createProperties(self, obj):
        if not hasattr(obj, "MarkerKSign"):
            obj.addProperty(
                "App::PropertyEnumeration",
                "MarkerKSign",
                "Reaction",
                QT_TRANSLATE_NOOP("App::Property", "The marker K sign"),
                locked=True,
            )
            obj.MarkerKSign = MarkerKSigns  # sets the list
            obj.MarkerKSign = MarkerKSigns[0]  # set the initial value

        etypes = ["Force", "Torque"]
        dims = ["X", "Y", "Z"]
        for etype in etypes:
            for dim in dims:
                prop_name = f"{etype}{dim}"
                if not hasattr(obj, prop_name):
                    obj.addProperty(
                        "App::PropertyString",
                        prop_name,
                        "Reaction",
                        QT_TRANSLATE_NOOP(
                            "App::Property",
                            f"The {dim} component of the {etype} function",
                        ),
                    )
                    setattr(obj, prop_name, "0.0d")  # default value

        # e.g. TzOnI = (0.0d + 572.95779513082d*(angleIJz(self) + (-0.0d)) + 0.0d*omeIJKi(self,I,3))

        return super().createProperties(obj)


class ForceTorqueInLine(ForceTorque):
    def __init__(self, obj):
        super().__init__(obj, 1)

    def createProperties(self, obj):

        if not hasattr(obj, "TensionFunc"):
            obj.addProperty(
                "App::PropertyString",
                "TensionFunc",
                "Reaction",
                QT_TRANSLATE_NOOP("App::Property", "The tension function"),
            ).TensionFunc = "0.0d"

        if not hasattr(obj, "TwistFunc"):
            obj.addProperty(
                "App::PropertyString",
                "TwistFunc",
                "Reaction",
                QT_TRANSLATE_NOOP("App::Property", "The twist function"),
            ).TwistFunc = "0.0d"
        # e.g. (0.0d + 100.0d*(rIJ(self) + (-1.0d)) + 10.0d*vrIJ(self))

        return super().createProperties(obj)


class ViewProviderForceTorque(ViewProviderJoint):

    def doubleClicked(self, vobj):
        App.closeActiveTransaction(True)  # Close the auto-transaction

        task = Gui.Control.activeTaskDialog()
        if task:
            task.reject()

        assembly = vobj.Object.Proxy.getAssembly(vobj.Object)

        if assembly is None:
            return False

        if UtilsAssembly.activeAssembly() != assembly:
            vobj.Document.setEdit(assembly)

        panel = TaskAssemblyCreateForceTorque(0, vobj.Object)
        dialog = Gui.Control.showDialog(panel)
        if dialog is not None:
            dialog.setAutoCloseOnTransactionChange(True)
            dialog.setAutoCloseOnDeletedDocument(True)
            dialog.setDocumentName(App.ActiveDocument.Name)

        return True


class ViewProviderForceTorqueGeneral(ViewProviderForceTorque):

    def getIcon(self):
        return ":/icons/Assembly_CreateForceTorqueGeneral.svg"


class ViewProviderForceTorqueInLine(ViewProviderForceTorque):

    def getIcon(self):
        return ":/icons/Assembly_CreateForceTorqueInLine.svg"


class TaskAssemblyCreateForceTorque(TaskAssemblyCreateItemIJ):
    ui_panel = ":/panels/TaskAssemblyCreateForce.ui"
    TranslatedJointTypes = TranslatedForceTypes
    JointTypes = ForceTypes

    def createItemObject(self):
        type_index = self.jForm.jointType.currentIndex()
        force_group = UtilsAssembly.getForceGroup(self.assembly)
        self.joint = force_group.newObject("App::FeaturePython", "ForceTorque")
        if type_index == 0:
            self.joint.Label = "ForceTorque_General"
            ForceTorqueGeneral(self.joint)
            ViewProviderForceTorqueGeneral(self.joint.ViewObject)
        elif type_index == 1:
            self.joint.Label = "ForceTorque_InLine"
            ForceTorqueInLine(self.joint)
            ViewProviderForceTorqueInLine(self.joint.ViewObject)
