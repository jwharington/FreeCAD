# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

from .. import (
    COMPOSITE_LAMINATE_TOOL_ICON,
)
from ..objects import (
    CompositeLaminate,
    SymmetryType,
)
from ..taskpanels import task_composite_laminate
from .Composite import add_composite_props
from .Laminate import (
    LaminateCommand,
    LaminateFP,
    ViewProviderLaminate,
)


class CompositeLaminateFP(LaminateFP):
    def __init__(self, obj, laminae=[]):
        super().__init__super().__init__(obj, laminae=laminae)

        # Attach ViewProvider when running in GUI mode (FreeCADGui is available)
        # This ensures the correct ViewProvider is saved with the document
        if hasattr(FreeCADGui, "getDocument"):
            try:
                vobj = obj.ViewObject
                if vobj is not None:
                    vobj.Proxy = ViewProviderCompositeLaminate(self)
            except Exception:
                pass


        add_composite_props(obj)

    def make_model(self, obj, model_layers):
        if volume_fraction := obj.FibreVolumeFraction:
            volume_fraction *= 0.01
        else:
            volume_fraction = 0

        return CompositeLaminate(
            symmetry=SymmetryType[obj.Symmetry],
            layers=model_layers,
            volume_fraction_fibre=volume_fraction,  # noqa
            material_matrix=obj.ResinMaterial,
        )

    def execute(self, obj):
        if not obj.ResinMaterial:
            raise ValueError("invalid resin material")
        super().execute(obj)


class ViewProviderCompositeLaminate(ViewProviderLaminate):
    _taskPanel = task_composite_laminate._TaskPanel

    def getIcon(self):
        return COMPOSITE_LAMINATE_TOOL_ICON


class CompositeLaminateCommand(LaminateCommand):
    icon = COMPOSITE_LAMINATE_TOOL_ICON
    menu_text = "Composite laminate"
    tool_tip = """Create composite laminate.
        Select laminae."""
    instance_name = "CompositeLaminate"
    cls_fp = CompositeLaminateFP
    cls_vp = ViewProviderCompositeLaminate


# Command registration moved to InitGui.py to avoid FreeCADGui dependency
