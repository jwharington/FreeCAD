# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

import Part

from .. import BULKHEAD_TOOL_ICON
from ..tools.bulkhead_section import drape_cuts_of, make_bulkhead
from ..tools.stiffener import StiffenerSweep
from .Command import BaseCommand
from .StiffenerCompositeShell import (
    BULKHEAD_ROLES,
    is_member_composite,
    member_claimed_children,
    teardown_composite_member,
    validate_composite_wiring,
    wire_composite_member,
)
from .VPCompositePart import (
    CompositePartFP,
    VPCompositePart,
)

# The flange width the handover suggests (34 mm) is a parameter of the
# feature, not a constant of the tool — the suggestion is a starting point.
DEFAULT_FLANGE_WIDTH = 34.0


class BulkheadFP(CompositePartFP):
    """A bulkhead: the filled section of its cut, plus a flange band on the support.

    Geometry-first: the member's faces are the filled intersection (R1) and
    the band taken out of the support around it.  Linking a Laminate
    switches it into full composite mode the way StiffenerFP's does: the
    plate and band become draped shells and the joint between the band and
    the remaining skin gets the combined stack, through the shared member
    flow with :data:`BULKHEAD_ROLES` (no stand-off knob — ``FlangeWidth``
    is the band's drape width and the member's plate height at once).
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

        obj.addProperty(
            "App::PropertyBool",
            "MirrorX",
            "Layout",
            "Put the flange band on the far side of the section",
        ).MirrorX = False

        # Composite configuration (standard Composite::Shell property
        # names).  Linking a Laminate switches the bulkhead into full
        # composite mode — plate/band split, combined joint layup.
        obj.addProperty(
            "App::PropertyLinkGlobal",
            "Laminate",
            "Materials",
            "Laminate material (links the bulkhead's own structure)",
        )
        obj.addProperty(
            "App::PropertyLinkGlobal",
            "Rosette",
            "Materials",
            "Rosette defining the bulkhead fibre orientation",
        )

        # Geometry-first trim, the stiffener's polarity: the plate/band
        # support faces are cut by this solid before their shells are
        # built, so the finished member stops at the opening. The drape
        # itself is untouched — it rides the uncut geometry, and the
        # trimmed shells borrow it. Unset (the default), the plate spans
        # the opening as before.
        obj.addProperty(
            "App::PropertyLink",
            "TrimTool",
            "Layout",
            "Solid cutting the plate/band supports before their shells are built",
        )

        super().__init__(obj)

    def execute(self, fp):
        plates, bands = make_bulkhead(
            support=fp.Support.Shape,
            cut_surface=fp.IntersectSurface.Shape,
            flange_width=float(fp.FlangeWidth),
            mirror_x=bool(fp.MirrorX),
        )
        if not plates:
            # Loud, not silent: a cut that never closed on the support would
            # otherwise leave the last good shape in place and read as a
            # successful recompute (the loud-failure contract).
            raise ValueError(
                "the cutting surface does not close on the support — "
                "no bulkhead section to build")
        cuts = drape_cuts_of(fp.Support.Shape, fp.IntersectSurface.Shape,
                              float(fp.FlangeWidth), bool(fp.MirrorX))
        fp.Shape = Part.makeCompound([*plates, *bands, *cuts])
        fp.IntersectSurface.Visibility = False
        if not is_member_composite(fp):
            if getattr(self, "_wired", False):
                teardown_composite_member(self, fp, BULKHEAD_ROLES)
                self._wired = False
            self.last_error = None
            return
        try:
            validate_composite_wiring(fp, BULKHEAD_ROLES)
            # One knob, both roles: the one-sided prism's width is the
            # band's drape width and the plate's height at once.
            width = float(fp.FlangeWidth)
            member = StiffenerSweep(
                shell=Part.makeCompound([*plates, *bands]),
                remainders=list(cuts),
                foot_faces=list(bands),
                web_faces=list(plates),
                foot_width=width,
                web_height=width,
            )
            wire_composite_member(self, fp, member, BULKHEAD_ROLES)
            self._wired = True
        except Exception as exc:
            # A silently wrong stack is the one unacceptable outcome.
            self.last_error = str(exc)
            raise
        self.last_error = None


class ViewProviderBulkhead(VPCompositePart):
    def claimChildren(self):
        obj = getattr(self, "Object", None)
        if obj is None:
            return []
        return [obj.Support, obj.IntersectSurface] + member_claimed_children(
            obj, BULKHEAD_ROLES)

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
