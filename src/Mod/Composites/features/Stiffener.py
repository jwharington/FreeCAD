# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

import FreeCAD
import Part

from .. import (
    STIFFENER_TOOL_ICON,
)
from ..tools.stiffener import (
    ProfileMirror,
    make_stiffener,
)
from .Command import BaseCommand
from .VPCompositePart import (
    CompositePartFP,
    VPCompositePart,
)


class StiffenerFP(CompositePartFP):
    def __init__(self, obj, support=None, cut_surface=None, profile=None):
        obj.addProperty(
            "App::PropertyLink",
            "Support",
            "References",
            "Link to the shape",
            locked=True,
        ).Support = support

        obj.addProperty(
            "App::PropertyLink",
            "IntersectSurface",
            "Layout",
            "Surface whose intersection with the support sweeps the path",
            locked=True,
        ).IntersectSurface = cut_surface

        obj.addProperty(
            "App::PropertyBool",
            "MirrorX",
            "Layout",
            "Mirror profile along the cut-surface normal",
        ).MirrorX = False

        obj.addProperty(
            "App::PropertyBool",
            "MirrorY",
            "Layout",
            "Mirror profile across the support surface",
        ).MirrorY = False

        obj.addProperty(
            "App::PropertyLink",
            "Profile",
            "Dimensions",
            "Profile section of the stiffener",
        ).Profile = profile

        super().__init__(obj)

    def execute(self, fp):
        shape, remainders, tools = make_stiffener(
            support=fp.Support.Shape,
            cut_surface=fp.IntersectSurface.Shape,
            profile=fp.Profile,
            mirror=ProfileMirror(flip_x=fp.MirrorX, flip_y=fp.MirrorY),
        )
        # The shape carries the stiffener and the remainder of the cut support
        # as its two children, for CompoundFilters to pick apart.
        fp.Shape = Part.makeCompound([shape, Part.makeCompound(remainders)])
        self.remainders = remainders
        self.tools = tools

        fp.IntersectSurface.Visibility = False
        fp.Profile.Visibility = False


def add_stiffener_filters(doc, stiffener):
    """The stiffener and the support remainder, as CompoundFilters on `stiffener`.

    The stiffener's shape holds both as its children; each filter picks one out
    and recomputes whenever the stiffener does. The stiffener feature itself is
    left hidden — it draws everything the two filters draw between them.
    """
    from CompoundTools import CompoundFilter

    filters = {}
    for name, items in (("Parts", "0"), ("Remainder", "1")):
        compound_filter = CompoundFilter.makeCompoundFilter(
            f"{stiffener.Name}{name}", into_group=doc
        )
        compound_filter.Base = stiffener
        compound_filter.FilterType = "specific items"
        compound_filter.items = items
        filters[name.lower()] = compound_filter
    stiffener.Visibility = False
    return filters


class ViewProviderStiffener(VPCompositePart):
    def claimChildren(self):
        obj = getattr(self, "Object", None)
        if obj is None:
            return []
        return [obj.Support, obj.IntersectSurface, obj.Profile]

    def getIcon(self):
        return STIFFENER_TOOL_ICON


class CompositeStiffenerCommand(BaseCommand):
    icon = STIFFENER_TOOL_ICON
    menu_text = "Stiffener"
    tool_tip = """Generate stiffener.
        Select the support feature, the surface that cuts the sweep path
        from it, and the profile sketch.
        WORK-IN-PROGRESS"""
    sel_args = [
        {
            "key": "support",
            "type": "Part::Feature",
        },
        {
            "key": "cut_surface",
            "type": "Part::Feature",
        },
        {
            "key": "profile",
            "type": "Sketcher::SketchObject",
        },
    ]
    type_id = "Part::FeaturePython"
    instance_name = "Stiffener"
    cls_fp = StiffenerFP
    cls_vp = ViewProviderStiffener

    def post_create(self, obj):
        add_stiffener_filters(obj.Document, obj)


# Command registration moved to InitGui.py to avoid FreeCADGui dependency
