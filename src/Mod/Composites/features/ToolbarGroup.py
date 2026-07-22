from . import (
    AlignFibreRosette,  # noqa
    CompositeLaminate,  # noqa
    FibreCompositeLamina,  # noqa
    HomogeneousLamina,  # noqa
    Laminate,  # noqa
    Mould,  # noqa
    MouldAnalysis,  # noqa
    PartPlane,  # noqa
    PlaceDart,  # noqa
    Rosette,  # noqa
    SeamExtraction,  # noqa
    Stiffener,  # noqa
    TransferRosette,  # noqa
)


class CommandGroup:
    # https://forum.freecad.org/viewtopic.php?t=44684

    def __init__(self, cmdlist, menu, TypeId=None, tooltip=None):
        self.cmdlist = cmdlist
        self.menu = menu
        self.TypeId = TypeId
        if tooltip is None:
            self.tooltip = menu
        else:
            self.tooltip = tooltip

    def GetCommands(self):
        return tuple(self.cmdlist)

    def GetResources(self):
        return {"MenuText": self.menu, "ToolTip": self.tooltip}


def get_command_groups():
    """Return a list of (command_name, group_object) tuples for command registration."""
    return [
        ("Composites_LaminaTools", CommandGroup(
            [
                "Composites_FibreCompositeLamina",
                "Composites_HomogeneousLamina",
            ],
            menu="Lamina",
            tooltip="Lamina construction tools",
        )),
        ("Composites_LaminateTools", CommandGroup(
            [
                "Composites_Laminate",
                "Composites_CompositeLaminate",
            ],
            menu="Laminate",
            tooltip="Laminate construction tools",
        )),
        ("Composites_StructureTools", CommandGroup(
            [
                "Composites_Seam",
                "Composites_PlaceDart",
                "Composites_Stiffener",
            ],
            menu="Structure",
            tooltip="Shell structure construction tools",
        )),
        ("Composites_MouldTools", CommandGroup(
            [
                "Composites_MouldAnalysis",
                "Composites_PartPlane",
            ],
            menu="Mould",
            tooltip="Mould construction tools",
        )),
        ("Composites_LCSTools", CommandGroup(
            [
                "Composites_TransferRosette",
                "Composites_AlignFibreRosette",
                "Composites_Rosette",
            ],
            menu="Material LCS",
            tooltip="Material local coordinate system tools",
        )),
    ]


# Command registration moved to InitGui.py to avoid FreeCADGui dependency
