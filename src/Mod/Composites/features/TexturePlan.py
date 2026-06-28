# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

import FreeCADGui
import Part
from FreeCAD import Console

from .. import (
    TEXTURE_PLAN_TOOL_ICON,
)
from .Command import BaseCommand
from .CompositeShell import is_composite_shell
from .VPCompositePart import (
    CompositePartFP,
    VPCompositePart,
)


class TexturePlanFP(CompositePartFP):
    Type = "Composite::TexturePlan"

    def __init__(self, obj, shells=[]):
        obj.addProperty(
            type="App::PropertyLinkListGlobal",
            name="CompositeShell",
            group="References",
            doc="Composite Shells to unwrap",
        ).CompositeShell = shells

        super().__init__(obj)

    def execute(self, fp):
        import FreeCAD

        shapes = []
        for obj in fp.CompositeShell:
            if "Composite::Shell" != obj.Proxy.Type:
                Console.PrintError(f"Incorrect type {obj.Name}\n")
                continue
            # TODO: lay out separate named shapes for each layer in the shell
            stack_assembly = obj.Proxy.get_stack_assembly(obj)
            # Get the support shape for UV→3D projection
            support_shape = obj.Support.Shape if hasattr(obj, "Support") and obj.Support else None
            for key, orientation in stack_assembly.items():
                Console.PrintMessage(
                    f"name {obj.Name} key {key} orientation {orientation}"
                )
                boundaries = obj.Proxy.get_boundaries(
                    offset_angle_deg=int(orientation),
                )
                if not boundaries:
                    continue
                for w in boundaries:
                    if len(w) < 2:
                        continue
                    # Project 2D UV tuples to 3D FreeCAD.Vectors
                    pts = []
                    for uv in w:
                        try:
                            u, v = float(uv[0]), float(uv[1])
                            if support_shape is not None:
                                # Project UV to 3D using the support shape's surface.
                                # Use face.isInside() to correctly handle trimmed faces
                                # where a UV point may lie outside UVBounds but still
                                # map to a valid 3D point on the physical face.
                                uv_point = FreeCAD.Base.Vector(u, v)
                                projected = False
                                for face in support_shape.Faces:
                                    try:
                                        if face.isInside(uv_point, 1e-6, True):
                                            pt = face.value(u, v)
                                            if pt.isValid():
                                                pts.append(pt)
                                                projected = True
                                                break
                                    except Exception:
                                        continue
                                # If no face accepted the UV point (outside all UVBounds
                                # AND outside all physical face boundaries), fall back
                                # to the XY plane rather than silently dropping it.
                                if not projected:
                                    pts.append(
                                        FreeCAD.Vector(float(uv[0]), float(uv[1]), 0.0)
                                    )
                        except Exception:
                            pass
                    # Validate the loop has enough points to form a valid polygon.
                    # At least 3 distinct points are required for Part.makePolygon.
                    if len(pts) >= 3:
                        shapes.append(Part.Wire(Part.makePolygon(pts)))
        fp.Shape = Part.makeCompound(shapes)

        # fp.ViewObject.update()

    def onChanged(self, fp, prop):
        match prop:
            case "CompositeShell":
                fp.recompute()


class ViewProviderTexturePlan(VPCompositePart):
    def getDefaultDisplayMode(self):
        return "Wireframe"

    def getIcon(self):
        return TEXTURE_PLAN_TOOL_ICON


class TexturePlanCommand(BaseCommand):
    icon = TEXTURE_PLAN_TOOL_ICON
    menu_text = "Texture plan"
    tool_tip = """Create texture plan.
    Select composite shells."""
    sel_args = [
        {
            "key": "shells",
            "test": is_composite_shell,
            "array": True,
            "optional": True,
        },
    ]
    type_id = "Part::FeaturePython"
    instance_name = "TexturePlan"
    cls_fp = TexturePlanFP
    cls_vp = ViewProviderTexturePlan


FreeCADGui.addCommand(
    "Composites_TexturePlan",
    TexturePlanCommand(),
)
