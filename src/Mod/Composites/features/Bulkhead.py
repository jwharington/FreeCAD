# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

import Part

from .. import BULKHEAD_TOOL_ICON
from ..tools.bulkhead_section import drape_cuts_of, make_bulkhead
from .Command import BaseCommand
from .VPCompositePart import (
    CompositePartFP,
    VPCompositePart,
)

# The flange dimensions the handover suggests (34 mm) and a band depth that
# straddles a real skin.  Both are parameters of the feature, not constants of
# the tool — the suggestion is a starting point, never a hidden default.
DEFAULT_FLANGE_WIDTH = 34.0


class BulkheadFP(CompositePartFP):
    """A bulkhead: the filled section of its cut, plus a flange band on the support.

    Geometry-first: the member's faces are the filled intersection (R1) and the
    band taken out of the support around it, and linking a Laminate later will
    switch it into composite mode the way StiffenerFP's does.  That wiring is
    not built yet — the feature carries pure geometry until it is, and the
    property names below are the standard Composite::Shell ones so the switch
    does not have to migrate anything.
    """

    def __init__(self, obj, support=None, cut_surface=None):
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
            "Surface whose intersection with the support carries the section",
            locked=True,
        ).IntersectSurface = cut_surface

        obj.addProperty(
            "App::PropertyLength",
            "FlangeWidth",
            "Dimensions",
            "Width of the flange band taken out of the support",
        ).FlangeWidth = DEFAULT_FLANGE_WIDTH

        super().__init__(obj)

    def execute(self, fp):
        plates, bands = make_bulkhead(
            support=fp.Support.Shape,
            cut_surface=fp.IntersectSurface.Shape,
            flange_width=float(fp.FlangeWidth),
        )
        if not plates:
            # Loud, not silent: a cut that never closed on the support would
            # otherwise leave the last good shape in place and read as a
            # successful recompute (the loud-failure contract).
            raise ValueError(
                "the cutting surface does not close on the support — "
                "no bulkhead section to build")
        fp.Shape = Part.makeCompound(
            [*plates, *bands,
             *drape_cuts_of(fp.Support.Shape, fp.IntersectSurface.Shape,
                            float(fp.FlangeWidth))])
        fp.IntersectSurface.Visibility = False
        self.last_error = None


class ViewProviderBulkhead(VPCompositePart):
    def claimChildren(self):
        obj = getattr(self, "Object", None)
        if obj is None:
            return []
        return [obj.Support, obj.IntersectSurface]

    def getIcon(self):
        return BULKHEAD_TOOL_ICON


class CompositeBulkheadCommand(BaseCommand):
    icon = BULKHEAD_TOOL_ICON
    menu_text = "Bulkhead"
    tool_tip = """Generate bulkhead.
        Select the support feature, then the surface that cuts the
        bulkhead's section from it."""
    sel_args = [
        {
            "key": "support",
            "type": "Part::Feature",
        },
        {
            "key": "cut_surface",
            "type": "Part::Feature",
        },
    ]
    type_id = "Part::FeaturePython"
    instance_name = "Bulkhead"
    cls_fp = BulkheadFP
    cls_vp = ViewProviderBulkhead


# The ViewProvider class that repairs this feature's serialised VP
# proxy on document restore (see CompositeBaseFP.onDocumentRestored).
BulkheadFP.view_provider_class = ViewProviderBulkhead
