# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

# FreeCADGui removed for decoupling
from FreeCAD import Vector

from .. import (
    PART_PLANE_TOOL_ICON,
)
from ..tools.part_plane import make_parting_surface3
from .Command import BaseCommand
from .VPCompositePart import (
    CompositePartFP,
    VPCompositePart,
)


class PartPlaneFP(CompositePartFP):
    def __init__(self, obj, source):
        obj.addProperty(
            "App::PropertyLink",
            "Source",
            "PartPlane",
            "Link to the source shape whose parting surface is being built",
            locked=True,
        ).Source = source

        obj.addProperty(
            "App::PropertyLength",
            "Inset",
            "PartPlane",
            "Inset from the sampled parting line",
            locked=True,
        ).Inset = "0.01 mm"

        obj.addProperty(
            "App::PropertyBool",
            "Ruled",
            "PartPlane",
            "Use a ruled parting surface",
            locked=True,
        ).Ruled = True

        obj.addProperty(
            "App::PropertyVector",
            "ViewDir",
            "ReflectLines",
            "View direction used to infer the parting line",
        ).ViewDir = Vector(0, 0, 1)

        super().__init__super().__init__(obj)

        # Attach ViewProvider when running in GUI mode (FreeCADGui is available)
        # This ensures the correct ViewProvider is saved with the document
        if hasattr(FreeCADGui, "getDocument"):
            try:
                vobj = obj.ViewObject
                if vobj is not None:
                    vobj.Proxy = ViewProviderPartPlane(self)
            except Exception:
                pass


    def execute(self, fp):
        shape = make_parting_surface3(
            fp.Source.Shape,
        )
        fp.Shape = shape


class ViewProviderPartPlane(VPCompositePart):
    def getIcon(self):
        return PART_PLANE_TOOL_ICON


class CompositePartPlaneCommand(BaseCommand):
    icon = PART_PLANE_TOOL_ICON
    menu_text = "Parting surface"
    tool_tip = """Generate a parting surface from the sampled parting line.
        Select source feature.
        WORK-IN-PROGRESS"""
    sel_args = [
        {
            "key": "source",
            "type": "Part::Feature",
        },
    ]
    type_id = "Part::FeaturePython"
    instance_name = "PartPlane"
    cls_fp = PartPlaneFP
    cls_vp = ViewProviderPartPlane


# Command registration moved to InitGui.py to avoid FreeCADGui dependency
