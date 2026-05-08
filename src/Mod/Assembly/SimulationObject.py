# SPDX-License-Identifier: LGPL-2.1-or-later
# /**************************************************************************
#                                                                           *
#    Copyright (c) 2024 Ondsel <development@ondsel.com>                     *
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

"""Data-model proxy for the Simulation object.

Free of Qt/GUI imports at module level so this module can be imported in
headless (FreeCADCmd) contexts.
"""

import FreeCAD as App
from PySide.QtCore import QT_TRANSLATE_NOOP


######### Simulation Object ###########
class Simulation:
    def __init__(self, feaPy):
        feaPy.Proxy = self
        feaPy.addExtension("App::GroupExtensionPython")

        if not hasattr(feaPy, "aTimeStart"):
            feaPy.addProperty(
                "App::PropertyTime",
                "aTimeStart",
                "Simulation",
                QT_TRANSLATE_NOOP(
                    "App::Property",
                    "Simulation start time.",
                ),
                locked=True,
            )

        if not hasattr(feaPy, "bTimeEnd"):
            feaPy.addProperty(
                "App::PropertyTime",
                "bTimeEnd",
                "Simulation",
                QT_TRANSLATE_NOOP(
                    "App::Property",
                    "Simulation end time.",
                ),
                locked=True,
            )

        if not hasattr(feaPy, "cTimeStepOutput"):
            feaPy.addProperty(
                "App::PropertyTime",
                "cTimeStepOutput",
                "Simulation",
                QT_TRANSLATE_NOOP(
                    "App::Property",
                    "Simulation time step for output.",
                ),
                locked=True,
            )

        if not hasattr(feaPy, "fGlobalErrorTolerance"):
            feaPy.addProperty(
                "App::PropertyFloat",
                "fGlobalErrorTolerance",
                "Simulation",
                QT_TRANSLATE_NOOP(
                    "App::Property",
                    "Integration global error tolerance.",
                ),
                locked=True,
            )

        if not hasattr(feaPy, "jFramesPerSecond"):
            feaPy.addProperty(
                "App::PropertyInteger",
                "jFramesPerSecond",
                "Simulation",
                QT_TRANSLATE_NOOP(
                    "App::Property",
                    "Frames Per Second.",
                ),
                locked=True,
            )

        if not hasattr(feaPy, "Dynamic"):
            feaPy.addProperty(
                "App::PropertyBool",
                "Dynamic",
                "Simulation",
                QT_TRANSLATE_NOOP(
                    "App::Property",
                    "Simulation dynamic.",
                ),
                locked=True,
            )

        feaPy.aTimeStart = 0.0
        feaPy.bTimeEnd = 1.0
        feaPy.cTimeStepOutput = 1.0e-2
        feaPy.fGlobalErrorTolerance = 1.0e-6
        feaPy.jFramesPerSecond = 30
        feaPy.Dynamic = False

        self.motionsChangedCallback = None

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def onChanged(self, feaPy, prop):
        if prop == "Group" and hasattr(self, "motionsChangedCallback"):
            if self.motionsChangedCallback is not None:
                self.motionsChangedCallback()

    def setMotionsChangedCallback(self, callback):
        self.motionsChangedCallback = callback

    def execute(self, feaPy):
        """Do something when doing a recomputation, this method is mandatory"""
        pass

    def getAssembly(self, feaPy):
        assert feaPy.isDerivedFrom("App::FeaturePython"), "Type error"
        for obj in feaPy.InList:
            if obj.isDerivedFrom("Assembly::AssemblyObject"):
                return obj
        return None
