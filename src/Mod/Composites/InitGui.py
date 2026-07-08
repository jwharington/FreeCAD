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
        # ── Load C++ draping solver immediately so failures are visible at
        #    workbench activation, not deep inside a draping operation. ────
        try:
            from Composites.ext._native import solve  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "Composites: failed to load C++ draping solver "
                f"({exc}). Was FreeCAD built with BUILD_COMPOSITES=ON? "
                "Or is there a shared-library loading conflict?"
            )

        # Import command classes and register them
        from Composites.features.Stiffener import CompositeStiffenerCommand
        from Composites.features.Laminate import LaminateCommand
        from Composites.features.CompositeShell import CompositeShellCommand
        from Composites.features.Mould import CompositeMouldCommand
        from Composites.features.PlaceDart import PlaceDartCommand
        from Composites.features.Seam import CompositeSeamCommand
        from Composites.features.Rosette import RosetteCommand
        from Composites.features.AlignFibreRosette import AlignFibreRosetteCommand
        from Composites.features.TransferRosette import TransferRosetteCommand
        from Composites.features.MouldAnalysis import CompositeMouldAnalysisCommand
        from Composites.features.PartPlane import CompositePartPlaneCommand
        from Composites.features.TexturePlan import TexturePlanCommand
        from Composites.features.FibreCompositeLamina import FibreCompositeLaminaCommand
        from Composites.features.HomogeneousLamina import HomogeneousLaminaCommand
        from Composites.features.CompositeLaminate import CompositeLaminateCommand
        from Composites.features.ToolbarGroup import get_command_groups

        # Register each command with its proper name
        commands = [
            ("Composites_Stiffener", CompositeStiffenerCommand()),
            ("Composites_Laminate", LaminateCommand()),
            ("Composites_CompositeShell", CompositeShellCommand()),
            ("Composites_Mould", CompositeMouldCommand()),
            ("Composites_PlaceDart", PlaceDartCommand()),
            ("Composites_Seam", CompositeSeamCommand()),
            ("Composites_Rosette", RosetteCommand()),
            ("Composites_AlignFibreRosette", AlignFibreRosetteCommand()),
            ("Composites_TransferRosette", TransferRosetteCommand()),
            ("Composites_MouldAnalysis", CompositeMouldAnalysisCommand()),
            ("Composites_PartPlane", CompositePartPlaneCommand()),
            ("Composites_TexturePlan", TexturePlanCommand()),
            ("Composites_FibreCompositeLamina", FibreCompositeLaminaCommand()),
            ("Composites_HomogeneousLamina", HomogeneousLaminaCommand()),
            ("Composites_CompositeLaminate", CompositeLaminateCommand()),
        ]
        for name, cmd in commands:
            FreeCADGui.addCommand(name, cmd)

        # Get command groups from ToolbarGroup
        for cmd_name, group in get_command_groups():
            FreeCADGui.addCommand(cmd_name, group)

        # Build menu/toolbar structure
        cmds_section = [
            "Composites_LaminaTools",
            "Composites_LaminateTools",
        ]
        cmds_structure = [
            "Composites_CompositeShell",
            "Composites_StructureTools",
            "Composites_LCSTools",
        ]
        cmds_manufacturing = [
            "Composites_TexturePlan",
            "Composites_MouldTools",
            "Composites_MouldAnalysis",
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
