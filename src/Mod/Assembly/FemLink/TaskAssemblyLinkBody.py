# SPDX-License-Identifier: LGPL-2.1-or-later
# /**************************************************************************
#                                                                           *
#    Copyright (c) 2026 John Wharington <jwharington@gmail.com>             *
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

# from collections.abc import Sequence
import FreeCAD as App
import FreeCADGui as Gui

# import Part
from PySide import QtCore, QtGui, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

__title__ = "Assembly Joint object"
__author__ = "John Wharington"
__url__ = "https://www.freecad.org"

import Plot
import UtilsAssembly
from FreeCAD import Console

import FemLink.UtilsAnalysis as UtilsAnalysis
import FemLink.UtilsFemLink as UtilsFemLink

translate = App.Qt.translate


class TaskAssemblyLinkBody(QtCore.QObject):

    ui_panel = ":/panels/TaskAssemblyLinkBody.ui"

    def __init__(self, linkObj=None):
        super().__init__()

        global activeTask
        activeTask = self
        self.blockOffsetRotation = False

        self.assembly = UtilsAssembly.activeAssembly()
        # ?? self.assembly = self.linkObj.getParentGroup()
        self.doc = self.assembly.Document
        self.gui_doc = Gui.getDocument(self.doc)
        self.view = self.gui_doc.activeView()

        if not self.assembly or not self.view or not self.doc:
            Console.PrintError("----- no active assy\n")
            return
        if not linkObj:
            Console.PrintError("----- no linkObj\n")
            return

        self.linkObj = linkObj
        Console.PrintMessage(f"----- all ok: Assembly: {self.assembly.Label}\n")

        # Create a top-level container widget for subclasses of TaskAssemblyLinkBody
        self.form = QtWidgets.QWidget()

        # Load the joint creation UI and parent it to `self.form`
        self.jForm = Gui.PySideUic.loadUi(self.ui_panel, self.form)

        # Create a layout for `self.form` and add `self.jForm` to it
        layout = QtWidgets.QVBoxLayout(self.form)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.jForm)

        self.jForm.setWindowTitle("Link Body")
        self.jForm.pushButtonClear.clicked.connect(self.onClearClicked)
        self.jForm.pushButtonSingle.clicked.connect(self.onSingleClicked)
        self.jForm.pushButtonAll.clicked.connect(self.onAllClicked)
        self.jForm.pushButtonScale.clicked.connect(self.onScaleClicked)

        self.jForm.pushButtonPurge.clicked.connect(self.onPurgeClicked)
        self.jForm.pushButtonFull.clicked.connect(self.onFullClicked)
        self.jForm.pushButtonReduced.clicked.connect(self.onReducedClicked)

        if self.assembly:
            simulations = UtilsFemLink.get_simulations(self.assembly)
            simulation_labels = [obj.Label for obj in simulations]
            if simulation_labels:
                self.jForm.comboBoxSimulation.addItems(simulation_labels)
            self.simulation = simulation_labels[0]
        self.jForm.comboBoxSimulation.currentTextChanged.connect(self.updateSimulation)
        Console.PrintMessage("done\n")
        self.updateNumStates()
        self._sim_updated = False
        self.sim_index = 1

    def updateSimulation(self, label):
        for sim in UtilsFemLink.get_simulations(self.assembly):
            if label == sim.Label:
                self.simulation = sim
                Console.PrintMessage(f"update simulation\n")
                self.assembly.generateSimulation(self.simulation)
                self._sim_updated = True
                self.sim_index = 1
                # TODO: get frame count etc
                return
        self.simulation = None
        Console.PrintMessage(f"can't set simulation {label}\n")

    def onClearClicked(self):
        Console.PrintMessage("clear collected load cases\n")
        self.linkObj.Proxy.clear(self.linkObj)
        self.updateNumStates()

    def saveTransparency(self):
        self.transparency = self.linkObj.Body.ViewObject.Transparency
        self.linkObj.Body.ViewObject.Transparency = 80

    def restoreTransparency(self):
        self.linkObj.Body.ViewObject.Transparency = self.transparency

    def collect(self, index=None):
        if not self._sim_updated:
            Console.PrintMessage("run simulation\n")
            self.updateSimulation(self.simulation)
        else:
            Console.PrintMessage("xxx sim updated\n")

        self.saveTransparency()

        UtilsAnalysis.assembly_collect_states(
            self.assembly,
            self.linkObj,
            index=index,
        )
        self.updateNumStates()

        self.restoreTransparency()

    def updateNumStates(self):
        num_states = self.linkObj.Proxy.num_states()
        Console.PrintMessage(f"num states {num_states}\n")
        self.jForm.groupBoxLoadCase.setTitle(f"Load cases: {num_states}")

    def onSingleClicked(self):
        self.collect(index=self.sim_index)
        n_frames = self.assembly.numberOfFrames()
        self.sim_index = (self.sim_index + 1) % n_frames

    def onAllClicked(self):
        self.collect(index=None)

    def onPurgeClicked(self):
        Console.PrintMessage("purge FEA results\n")
        self.linkObj.Proxy.purge(self.linkObj)

    def onScaleClicked(self):
        Console.PrintMessage("scale FEA results\n")
        self.linkObj.Proxy.scale(self.linkObj)

    def run_analysis(self, reduced=False):
        Console.PrintMessage("run_analysis\n")
        dry_run = self.jForm.checkDryRun.isChecked()
        self.saveTransparency()
        hull, dim_reduced = UtilsAnalysis.run_stored_analysis(
            self.linkObj, reduced=reduced, dry_run=dry_run
        )
        self.restoreTransparency()
        if hull is None:
            Console.PrintMessage("no hull\n")
            return

        def blank_plot(name):
            if plot := getattr(self, name, None):
                pass
            else:
                main = Gui.getMainWindow()
                plot = Plot.Plot()
                plot.setWindowTitle(self.linkObj.Label)
                plot.setParent(main)
                plot.setWindowFlags(QtGui.Qt.Dialog)
                plot.resize(main.size().height() / 2, main.size().height() / 2)  # keep it square
                plot.axes.clear()
                # axes decoration
                # self._plot_loadcases.axes.set_title(self.ViewObject.Title)
                # self._plot_loadcases.axes.legend(loc=self.ViewObject.LegendLocation)
                plot.update()
                setattr(self, name, plot)
            plot.series = []
            plot.show()
            return plot

        _plot = blank_plot("_plot_loadcases")
        _plot.axes.set_box_aspect(1)
        _plot.axes.set_xlabel("A0")
        _plot.axes.set_ylabel("A1")

        def plot(data, name, scatter=False):
            x = [h[0] for h in data]
            y = [h[1] for h in data]
            if scatter:
                _plot.axes.plot(x, y, "k.", label=name)
            else:
                _plot.axes.plot(x, y, "go-", label=name)

        plot(dim_reduced, "all", True)
        plot(hull, "hull")

        if dry_run:
            return

        results = UtilsAnalysis.extract_results(self.linkObj)
        if not results:
            return

        _plot = blank_plot("_plot_responses")
        _plot.axes.set_xlabel("index")
        _plot.axes.set_ylabel("Stress MPa")
        _plot.axes.plot(results["index"], results["max vonMises"], "g-", label="max vonMises")

    def onFullClicked(self):
        self.run_analysis(reduced=False)

    def onReducedClicked(self):
        self.run_analysis(reduced=True)
