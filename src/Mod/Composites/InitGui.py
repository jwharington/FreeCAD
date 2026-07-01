# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

import os

import FreeCAD as App
import FreeCADGui as Gui


class CompositesWorkbench(Gui.Workbench):
    # Resolve from FreeCAD's install root because this workbench is installed
    # under <prefix>/Mod/Composites, not under the shared resource tree.
    Icon = os.path.join(
        App.getHomePath(),
        "Mod",
        "Composites",
        "resources",
        "icons",
        "CompositesWB.svg",
    )
    MenuText = "Composites"
    ToolTip = "Tools for composite structures"

    def Initialize(self):
        """This function is executed when the workbench is first activated.
        It is executed once in a FreeCAD session followed by the Activated
        function.
        """

        import Composites.features.CompositeShell  # noqa
        import Composites.features.TexturePlan  # noqa
        import Composites.features.ToolbarGroup  # noqa
        import Composites.features.Dart  # noqa
        import Composites.features.RunCompositeExample  # noqa

        cmds_section = [
            "Composites_LaminaTools",
            "Composites_LaminateTools",
            "Composites_RunCompositeExample",
        ]
        cmds_structure = [
            "Composites_CompositeShell",
            "Composites_StructureTools",
            "Composites_LCSTools",
        ]
        cmds_manufacturing = [
            "Composites_TexturePlan",
            "Composites_Dart",
            "Composites_MouldTools",
        ]
        self.list = (
            cmds_section
            + ["Separator"]
            + cmds_structure
            + ["Separator"]
            + cmds_manufacturing
        )
        self.appendToolbar("Composites", self.list)
        self.appendMenu("Composites", self.list)

    def Activated(self):
        """This function is executed whenever the workbench is activated"""
        return

    def Deactivated(self):
        """This function is executed whenever the workbench is deactivated"""
        return

    def ContextMenu(self, recipient):
        """This function is executed whenever the user right-clicks on
        screen"""
        # "recipient" will be either "view" or "tree"
        self.appendContextMenu("Composites", self.list)

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(CompositesWorkbench())
FreeCAD.__unit_test__ += ["TestCompositesGui"]
