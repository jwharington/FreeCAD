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

import math
from collections.abc import Sequence

import FreeCAD as App
import Part
from PySide import QtCore
from PySide.QtCore import QT_TRANSLATE_NOOP

if App.GuiUp:
    import FreeCADGui as Gui
    from PySide import QtGui, QtWidgets

__title__ = "Assembly Joint object"
__author__ = "Ondsel"
__url__ = "https://www.freecad.org"

import UtilsAssembly

translate = App.Qt.translate

activeTask = None


class MakeJointSelGate:
    def __init__(self, taskbox, assembly):
        self.taskbox = taskbox
        self.assembly = assembly

    def allow(self, doc, obj, sub):
        if not sub:
            return False

        objs_names, element_name = UtilsAssembly.getObjsNamesAndElement(obj.Name, sub)

        if self.assembly.Name not in objs_names:
            # Only objects within the assembly.
            return False

        ref = [obj, [sub]]
        sel_obj = UtilsAssembly.getObject(ref)

        if UtilsAssembly.isLink(sel_obj):
            linked = sel_obj.getLinkedObject()
            if linked == sel_obj:
                return True  # We accept empty links
            sel_obj = linked

        if sel_obj.isDerivedFrom("Part::Feature") or sel_obj.isDerivedFrom("App::Part"):
            return True

        if sel_obj.isDerivedFrom("App::LocalCoordinateSystem") or sel_obj.isDerivedFrom(
            "App::DatumElement"
        ):
            datum = sel_obj
            if datum.isDerivedFrom("App::DatumElement"):
                parent = datum.getParent()
                if parent.isDerivedFrom("App::LocalCoordinateSystem"):
                    datum = parent

            if self.assembly.hasObject(datum) and hasattr(datum, "MapMode"):
                # accept only datum that are not attached
                return datum.MapMode == "Deactivated"

            return True

        return False


class TaskAssemblyCreateItemIJ(QtCore.QObject):

    ui_panel = ":/panels/TaskAssemblyCreateJoint.ui"
    TranslatedJointTypes = []

    def __init__(self, typeIndex, itemObj=None, subclass=False):
        super().__init__()

        global activeTask
        activeTask = self
        self.blockOffsetRotation = False

        self.assembly = UtilsAssembly.activeAssembly()
        if not self.assembly:
            self.assembly = UtilsAssembly.activePart()
            self.activeType = "Part"
        else:
            self.activeType = "Assembly"
            self.assembly.ensureIdentityPlacements()

        self.doc = self.assembly.Document
        self.gui_doc = Gui.getDocument(self.doc)

        self.view = self.gui_doc.activeView()

        if not self.assembly or not self.view or not self.doc:
            return

        if self.activeType == "Assembly":
            self.assembly.ViewObject.MoveOnlyPreselected = True
            self.assembly.ViewObject.MoveInCommand = False

        # Create a top-level container widget for subclasses of TaskAssemblyCreateJoint
        self.form = QtWidgets.QWidget()

        # Load the joint creation UI and parent it to `self.form`
        self.jForm = Gui.PySideUic.loadUi(self.ui_panel, self.form)

        # Create a layout for `self.form` and add `self.jForm` to it
        layout = QtWidgets.QVBoxLayout(self.form)
        if not subclass:
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        layout.addWidget(self.jForm)

        self.isolate_modes = ["Transparent", "Wireframe", "Hidden", "Disabled"]
        self.jForm.isolateType.addItems(
            [translate("Assembly", mode) for mode in self.isolate_modes]
        )
        self.jForm.isolateType.currentIndexChanged.connect(self.updateIsolation)

        if self.activeType == "Part":
            self.jForm.setWindowTitle("Match parts")
            self.jForm.jointType.hide()
            self.jForm.isolateType.hide()

        self.jForm.jointType.addItems(self.TranslatedJointTypes)

        self.jForm.jointType.setCurrentIndex(typeIndex)
        self.jType = self.JointTypes[self.jForm.jointType.currentIndex()]
        self.jForm.jointType.currentIndexChanged.connect(self.onJointTypeChanged)

        if itemObj:
            Gui.Selection.clearSelection()
            self.creating = False
            self.joint = itemObj
            self.jointName = itemObj.Label
            App.setActiveTransaction("Edit " + self.jointName + " Joint")

            self.updateTaskboxFromJoint()
            self.visibilityBackup = self.joint.Visibility
            self.joint.Visibility = True

        else:
            self.creating = True
            self.jointName = self.jForm.jointType.currentText().replace(" ", "")
            if self.activeType == "Part":
                App.setActiveTransaction("Transform")
            else:
                App.setActiveTransaction("Create " + self.jointName + " Joint")

            self.refs = []
            self.presel_ref = None

            self.createItemObject()
            self.visibilityBackup = False

        self.connectUi()

        if self.creating:
            # This has to be after adaptUi so that properties default values are adapted
            # if needed. For instance for gears adaptUi will prevent radii from being 0
            # before handleInitialSelection tries to solve.
            self.handleInitialSelection()

        UtilsAssembly.setJointsPickableState(self.doc, False)

        Gui.Selection.addSelectionGate(
            MakeJointSelGate(self, self.assembly), Gui.Selection.ResolveMode.NoResolve
        )
        Gui.Selection.addObserver(self, Gui.Selection.ResolveMode.NoResolve)
        Gui.Selection.setSelectionStyle(Gui.Selection.SelectionStyle.GreedySelection)

        self.callbackMove = self.view.addEventCallback("SoLocation2Event", self.moveMouse)
        self.callbackKey = self.view.addEventCallback("SoKeyboardEvent", self.KeyboardEvent)

        self.jForm.featureList.installEventFilter(self)

        self.createDeleteAction()

        self.addition_rejected = False

    def connectUi(self):
        pass

    def solveIfAllowed(self):
        pass

    def accept(self):
        if len(self.refs) != 2:
            App.Console.PrintWarning(
                translate("Assembly", "Select 2 elements from 2 separate parts")
            )
            return False

        self.deactivate()

        self.solveIfAllowed()
        if self.activeType == "Assembly":
            self.joint.Visibility = self.visibilityBackup
        else:
            self.joint.Document.removeObject(self.joint.Name)

        cmds = UtilsAssembly.generatePropertySettings(self.joint)
        Gui.doCommand(cmds)

        App.closeActiveTransaction()
        return True

    def reject(self):
        self.deactivate()
        App.closeActiveTransaction(True)
        if not self.creating:  # update visibility only if we are editing the joint
            self.joint.Visibility = self.visibilityBackup
        return True

    def autoClosedOnTransactionChange(self):
        self.reject()

    def autoClosedOnDeletedDocument(self):
        global activeTask
        activeTask = None
        Gui.Selection.removeSelectionGate()
        Gui.Selection.removeObserver(self)
        Gui.Selection.setSelectionStyle(Gui.Selection.SelectionStyle.NormalSelection)
        App.closeActiveTransaction(True)

    def deactivate(self):
        global activeTask
        activeTask = None

        if self.activeType == "Assembly":
            self.assembly.clearUndo()
            self.assembly.ViewObject.MoveOnlyPreselected = False
            self.assembly.ViewObject.MoveInCommand = True

        Gui.Selection.removeSelectionGate()
        Gui.Selection.removeObserver(self)
        Gui.Selection.setSelectionStyle(Gui.Selection.SelectionStyle.NormalSelection)
        Gui.Selection.clearSelection()
        self.view.removeEventCallback("SoLocation2Event", self.callbackMove)
        self.view.removeEventCallback("SoKeyboardEvent", self.callbackKey)
        UtilsAssembly.setJointsPickableState(self.doc, True)
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()

    def handleInitialSelection(self):
        selection = Gui.Selection.getSelectionEx("*", 0)
        if not selection:
            return
        for sel in selection:
            # If you select 2 solids (bodies for example) within an assembly.
            # There'll be a single sel but 2 SubElementNames.

            if not sel.SubElementNames:
                # no subnames, so its a root assembly itself that is selected.
                Gui.Selection.removeSelection(sel.Object)
                continue

            for sub_name in sel.SubElementNames:
                # We add sub_name twice because the joints references have element name + vertex name
                # and in the case of initial selection, both are the same.
                ref = [sel.Object, [sub_name, sub_name]]
                moving_part = self.getMovingPart(ref)

                # Only objects within the assembly.
                if moving_part is None:
                    Gui.Selection.removeSelection(sel.Object, sub_name)
                    continue

                if len(self.refs) == 1 and moving_part == self.getMovingPart(self.refs[0]):
                    # do not select several feature of the same object.
                    self.refs.clear()
                    Gui.Selection.clearSelection()
                    return

                self.refs.append(ref)

        # do not accept initial selection if we don't have 2 selected features
        if len(self.refs) != 2:
            self.refs.clear()
            Gui.Selection.clearSelection()
        else:
            self.updateJoint()

    def onJointTypeChanged(self, index):
        self.jType = self.JointTypes[self.jForm.jointType.currentIndex()]
        self.joint.Proxy.setJointType(self.joint, self.jType)
        self.adaptUi()

    def onReverseClicked(self):
        self.joint.Proxy.flipOnePart(self.joint)

    def updateIsolation(self):
        """Isolates the two selected components or clears isolation."""

        if self.activeType != "Assembly":
            return

        isolate_mode = self.jForm.isolateType.currentIndex()

        assembly_vobj = self.assembly.ViewObject

        # If "Disabled" is selected, clear any active isolation and stop.
        if isolate_mode == 3:
            assembly_vobj.clearIsolate()
            return

        if len(self.refs) == 2:
            try:
                # Use a set to handle cases where both refs point to the same object
                parts_to_isolate = {
                    self.getMovingPart(self.refs[0]),
                    self.getMovingPart(self.refs[1]),
                }
                assembly_vobj.isolateComponents(list(parts_to_isolate), isolate_mode)
            except Exception as e:
                App.Console.PrintWarning(f"Could not update isolation: {e}\n")
                assembly_vobj.clearIsolate()
        else:
            assembly_vobj.clearIsolate()

    def updateTaskboxFromJoint(self):
        self.refs = []
        self.presel_ref = None

        ref1 = self.joint.Reference1
        ref2 = self.joint.Reference2

        self.refs.append(ref1)
        self.refs.append(ref2)

        sub1 = UtilsAssembly.addTipNameToSub(ref1)
        sub2 = UtilsAssembly.addTipNameToSub(ref2)

        Gui.Selection.addSelection(ref1[0].Document.Name, ref1[0].Name, sub1)
        Gui.Selection.addSelection(ref2[0].Document.Name, ref2[0].Name, sub2)

        self.updateJointList()
        self.updateIsolation()

    def updateJoint(self):
        # First we build the listwidget
        self.updateJointList()

        # Then we pass the new list to the joint object
        self.joint.Proxy.setJointConnectors(self.joint, self.refs)

        self.updateIsolation()

    def updateJointList(self):
        self.jForm.featureList.clear()
        simplified_names = []
        for ref in self.refs:

            sname = UtilsAssembly.getObject(ref).Label

            element_name = UtilsAssembly.getElementName(ref[1][0])
            if element_name != "":
                sname = sname + "." + element_name
            simplified_names.append(sname)
        self.jForm.featureList.addItems(simplified_names)

    def updateLimits(self):
        pass

    def moveMouse(self, info):
        if len(self.refs) >= 2 or (
            len(self.refs) == 1
            and (
                not self.presel_ref
                or self.getMovingPart(self.refs[0]) == self.getMovingPart(self.presel_ref)
            )
        ):
            self.joint.ViewObject.Proxy.showPreviewJCS(False)
            if len(self.refs) >= 2:
                self.updateLimits()
            return

        cursor_pos = self.view.getCursorPos()
        cursor_info = self.view.getObjectInfo(cursor_pos)
        # cursor_info example  {'x': 41.515, 'y': 7.449, 'z': 16.861, 'ParentObject': <Part object>, 'SubName': 'Body002.Pad.Face5', 'Document': 'part3', 'Object': 'Pad', 'Component': 'Face5'}

        if (
            not cursor_info
            or not self.presel_ref
            # or cursor_info["SubName"] != self.presel_ref["sub_name"]
            # Removed because they are not equal when hovering a line endpoints.
            # But we don't actually need to test because if there's no preselection then not cursor is None
        ):
            self.joint.ViewObject.Proxy.showPreviewJCS(False)
            return

        ref = self.presel_ref

        # newPos = self.view.getPoint(*info["Position"]) is not OK: it's not pos on the object but on the focal plane
        newPos = App.Vector(cursor_info["x"], cursor_info["y"], cursor_info["z"])
        vertex_name = UtilsAssembly.findElementClosestVertex(ref, newPos)

        ref = UtilsAssembly.addVertexToReference(ref, vertex_name)

        placement = self.joint.Proxy.findPlacement(self.joint, ref, 0)
        self.joint.ViewObject.Proxy.showPreviewJCS(True, placement, ref)
        self.previewJCSVisible = True

    # 3D view keyboard handler
    def KeyboardEvent(self, info):
        if info["State"] == "UP" and info["Key"] == "ESCAPE":
            self.reject()

        if info["State"] == "UP" and info["Key"] == "RETURN":
            self.accept()

    def _removeSelectedItems(self, selected_indexes):
        for index in selected_indexes:
            row = index.row()
            if row < len(self.refs):
                ref = self.refs[row]

                ref_id = id(ref)
                if hasattr(self, "_original_tnp_map") and ref_id in self._original_tnp_map:
                    # use original TNP string for newly added references
                    removal_string = self._original_tnp_map[ref_id]
                else:
                    # use processed element name for reloaded references
                    removal_string = ref[1][0]

                Gui.Selection.removeSelection(ref[0], removal_string)
            else:
                print(f"Row {row} is out of bounds for refs (length: {len(self.refs)})")

    def eventFilter(self, watched, event):
        if self.jForm is not None and watched == self.jForm.featureList:
            if event.type() == QtCore.QEvent.ShortcutOverride:
                if (
                    hasattr(self, "deleteAction")
                    and self.deleteAction.shortcut().matches(event.key())
                    != QtGui.QKeySequence.NoMatch
                ):
                    event.accept()
                    return True
                return False

            elif event.type() == QtCore.QEvent.KeyPress:
                if (
                    hasattr(self, "deleteAction")
                    and self.deleteAction.shortcut().matches(event.key())
                    != QtGui.QKeySequence.NoMatch
                ):
                    self.deleteAction.trigger()
                    return True  # Consume the event

        return super().eventFilter(watched, event)

    def createDeleteAction(self):
        """Create delete action with shortcut"""
        try:
            delete_sequence = Gui.QtTools.deleteKeySequence()
        except AttributeError:
            # fallback to standard key if there is no sequence defined
            delete_sequence = QtGui.QKeySequence(QtCore.Qt.Key_Delete)

        self.deleteAction = QtGui.QAction("Remove", self.jForm)
        self.deleteAction.setShortcut(delete_sequence)

        self.deleteAction.setIcon(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_DialogCancelButton)
        )

        self.deleteAction.setShortcutVisibleInContextMenu(True)

        self.jForm.featureList.addAction(self.deleteAction)
        self.jForm.featureList.setContextMenuPolicy(QtCore.Qt.ActionsContextMenu)

        self.deleteAction.triggered.connect(self.deleteSelectedItems)

    def deleteSelectedItems(self):
        """Delete selected items from the feature list - same logic as Delete key in ev filter"""
        selected_indexes = self.jForm.featureList.selectedIndexes()
        self._removeSelectedItems(selected_indexes)

    def getMovingPart(self, ref):
        return UtilsAssembly.getMovingPart(self.assembly, ref)

    # selectionObserver stuff
    def addSelection(self, doc_name, obj_name, sub_name, mousePos):
        original_sub_name = sub_name
        rootObj = App.getDocument(doc_name).getObject(obj_name)

        # We do not need the full TNP string like :"Part.Body.Pad.;#a:1;:G0;XTR;:Hc94:8,F.Face6"
        # instead we need : "Part.Body.Pad.Face6"
        resolved = rootObj.resolveSubElement(sub_name, True)
        sub_name = resolved[2]

        sub_name = UtilsAssembly.fixBodyExtraFeatureInSub(doc_name, sub_name)

        ref = [rootObj, [sub_name]]
        moving_part = self.getMovingPart(ref)

        # Check if the addition is acceptable (we are not doing this in selection gate to let user move objects)
        acceptable = True
        if len(self.refs) >= 2:
            # No more than 2 elements can be selected for basic joints.
            acceptable = False

        for reference in self.refs:
            sel_moving_part = self.getMovingPart(reference)
            if sel_moving_part == moving_part:
                # Can't join a solid to itself. So the user need to select 2 different parts.
                acceptable = False

        if not acceptable:
            self.addition_rejected = True
            Gui.Selection.removeSelection(doc_name, obj_name, sub_name)
            return

        # Selection is acceptable so add it

        mousePos = App.Vector(mousePos[0], mousePos[1], mousePos[2])
        vertex_name = UtilsAssembly.findElementClosestVertex(ref, mousePos)

        # add the vertex name to the reference
        ref = UtilsAssembly.addVertexToReference(ref, vertex_name)

        # store the original TNP string for deletion purposes
        if hasattr(self, "_original_tnp_map"):
            self._original_tnp_map[id(ref)] = original_sub_name
        else:
            self._original_tnp_map = {id(ref): original_sub_name}

        self.refs.append(ref)
        self.updateJoint()

        # We hide the preview JCS if we just added to the selection
        self.joint.ViewObject.Proxy.showPreviewJCS(False)

    def removeSelection(self, doc_name, obj_name, sub_name, mousePos=None):
        if self.addition_rejected:
            self.addition_rejected = False
            return

        rootObj = App.getDocument(doc_name).getObject(obj_name)

        # Apply the same processing as in addSelection to ensure consistent comparison
        resolved = rootObj.resolveSubElement(sub_name, True)
        sub_name = resolved[2]

        sub_name = UtilsAssembly.fixBodyExtraFeatureInSub(doc_name, sub_name)

        for reference in self.refs[:]:
            ref_obj = reference[0]
            ref_element_name = reference[1][0] if len(reference[1]) > 0 else ""

            # match both object and processed element name for precise identification
            if ref_obj == rootObj and ref_element_name == sub_name:
                self.refs.remove(reference)
                break
        else:
            print("No matching ref found for removal!")

        self.updateJoint()

    def setPreselection(self, doc_name, obj_name, sub_name):
        if not sub_name:
            self.presel_ref = None
            return

        self.presel_ref = [App.getDocument(doc_name).getObject(obj_name), [sub_name]]

    def clearSelection(self, doc_name):
        self.refs.clear()
        self.updateJoint()
