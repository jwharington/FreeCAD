# SPDX-License-Identifier: LGPL-2.1-or-later
# /**************************************************************************
#                                                                           *
#    Copyright (c) 2023 Ondsel <development@ondsel.com>                     *
#                                                                           *
#    This file is part of FreeCAD.                                          *
#                                                                           *
#    FreeCAD is free software: you can redistribute it and/or modify it     *
#    under the terms of the GNU Lesser General Public License as            *
#    published by the Free Software Foundation, either version 2.1 of the   *
#    License, or (at your option) any later version.                        *
#                                                                           *
#    FreeCAD is distributed in the hope that it will be useful, but         *
#    WITHOUT ANY WARRANTY; without even the implied warranty of             *
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
#    Lesser General Public License for more details.                        *
#                                                                           *
#    You should have received a copy of the GNU Lesser General Public       *
#    License along with FreeCAD. If not, see                                *
#    <https://www.gnu.org/licenses/>.                                       *
#                                                                           *
# **************************************************************************/

import os

import FreeCAD as App
from PySide.QtCore import QT_TRANSLATE_NOOP

if App.GuiUp:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets

import Assembly_rc
import ForceObject
import UtilsAssembly

# translate = App.Qt.translate

__title__ = "Assembly Commands to Create Forces"
__author__ = "John Wharington"
__url__ = "https://www.freecad.org"


def noOtherTaskActive():
    return UtilsAssembly.isAssemblyCommandActive() or ForceObject.activeTask is not None


def isCreateForceTorqueActive():
    return UtilsAssembly.assembly_has_at_least_n_parts(1) and noOtherTaskActive()


def activateForceTorque(index):
    if ForceObject.activeTask:
        ForceObject.activeTask.reject()

    if App.GuiUp:
        Gui.addModule("ForceObject")  # NOLINT
        Gui.doCommand(f"panel = ForceObject.TaskAssemblyCreateForceTorque({index})")
        Gui.doCommandGui("dialog = Gui.Control.showDialog(panel)")
        dialog = Gui.doCommandEval("dialog")
        if dialog is not None:
            dialog.setAutoCloseOnTransactionChange(True)
            dialog.setAutoCloseOnDeletedDocument(True)
            dialog.setDocumentName(App.ActiveDocument.Name)
    else:
        assembly = UtilsAssembly.activeAssembly()
        force_group = UtilsAssembly.getForceGroup(assembly)
        obj = force_group.newObject("App::FeaturePython", "ForceTorque")
        if index == 0:
            obj.Label = "ForceTorque_General"
            ForceObject.ForceTorqueGeneral(obj)
            ForceObject.ViewProviderForceTorqueGeneral(obj.ViewObject)
        elif index == 1:
            obj.Label = "ForceTorque_InLine"
            ForceObject.ForceTorqueInLine(obj)
            ForceObject.ViewProviderForceTorqueInLine(obj.ViewObject)
        return


class CommandCreateForceTorqueGeneral:
    def __init__(self):
        pass

    def GetResources(self):
        return {
            "Pixmap": "Assembly_CreateForceTorqueGeneral",
            "MenuText": QT_TRANSLATE_NOOP(
                "Assembly_CreateForceTorqueGeneral",
                "Fixed Force",
            ),
            "Accel": "F",
            "ToolTip": QT_TRANSLATE_NOOP(
                "Assembly_CreateForceTorqueGeneral", "<p>Creates a force between selected parts</p>"
            ),
            "CmdType": "ForEdit",
        }

    def IsActive(self):
        if UtilsAssembly.activePart() is not None:
            return UtilsAssembly.assembly_has_at_least_n_parts(2)

        return isCreateForceTorqueActive()

    def Activated(self):
        activateForceTorque(0)


class CommandCreateForceTorqueInLine:
    def __init__(self):
        pass

    def GetResources(self):
        return {
            "Pixmap": "Assembly_CreateForceTorqueInLine",
            "MenuText": QT_TRANSLATE_NOOP("Assembly_CreateForceTorqueInLine", "InLine Force"),
            "Accel": "R",
            "ToolTip": QT_TRANSLATE_NOOP(
                "Assembly_CreateForceTorqueInLine",
                "Creates an in-line force between selected parts",
            ),
            "CmdType": "ForEdit",
        }

    def IsActive(self):
        if UtilsAssembly.activePart() is not None:
            return UtilsAssembly.assembly_has_at_least_n_parts(2)

        return isCreateForceTorqueActive()

    def Activated(self):
        activateForceTorque(1)


if App.GuiUp:
    Gui.addCommand("Assembly_CreateForceTorqueGeneral", CommandCreateForceTorqueGeneral())
    Gui.addCommand("Assembly_CreateForceTorqueInLine", CommandCreateForceTorqueInLine())
