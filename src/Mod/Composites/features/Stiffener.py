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
from .StiffenerCompositeShell import (
    ensure_stiffener_shells_visible,
    is_stiffener_composite,
    stiffener_claimed_children,
    teardown_composite_stiffener,
    validate_composite_wiring,
    wire_composite_stiffener,
)
from .TransferRosette import TransferRosetteFP
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

        # Composite configuration (standard Composite::Shell property
        # names).  Linking a Laminate switches the feature into full
        # composite mode — web/foot split, combined joint layup; without
        # one the stiffener stays pure geometry.
        obj.addProperty(
            "App::PropertyLinkGlobal",
            "Laminate",
            "Materials",
            "Laminate material (links the stiffener's own structure)",
        )
        obj.addProperty(
            "App::PropertyLinkGlobal",
            "Rosette",
            "Materials",
            "Rosette defining the stiffener fibre orientation",
        )

        # Original panel support geometry, captured before the panel is
        # re-supported on the stiffener remainder (weave exclusivity).
        # Drives every recompute: extraction must never run on the
        # re-pointed (remainder) support.
        obj.addProperty(
            "App::PropertyLinkGlobal",
            "SupportBase",
            "References",
            "Original support geometry (captured pre-re-support)",
        )

        super().__init__(obj)

    def execute(self, fp):
        # Geometry queries read the captured base support, never the
        # re-pointed (remainder) one: after weave exclusivity the
        # panel's Support.Shape is the panel minus the stiffener seat,
        # which would re-sweep garbage.
        base = getattr(fp, "SupportBase", None)
        support_shape = (
            base.Shape
            if base is not None
            else TransferRosetteFP._shape_of(fp.Support)
        )
        sweep = make_stiffener(
            support=support_shape,
            cut_surface=fp.IntersectSurface.Shape,
            profile=fp.Profile,
            mirror=ProfileMirror(flip_x=fp.MirrorX, flip_y=fp.MirrorY),
        )
        # The shape carries the stiffener and the remainder of the cut support
        # as its two children, for CompoundFilters to pick apart.
        fp.Shape = Part.makeCompound([sweep.shell, Part.makeCompound(sweep.remainders)])
        self.remainders = sweep.remainders
        self.foot_faces = sweep.foot_faces
        self.web_faces = sweep.web_faces
        self.foot_width = sweep.foot_width
        self.web_height = sweep.web_height

        fp.IntersectSurface.Visibility = False
        fp.Profile.Visibility = False

        if not is_stiffener_composite(fp):
            # Geometry-only mode: pure geometry, no weave, no children.
            # A mode switch down from composite must undo the wiring —
            # a panel left re-supported on the remainder would be
            # silently wrong.
            if getattr(fp, "SupportBase", None) is not None:
                teardown_composite_stiffener(self, fp)
            return
        # Full composite mode: the loud-failure contract — record the
        # reason and surface the error so the feature shows as in error,
        # never a silently wrong stack.
        try:
            validate_composite_wiring(fp)
            wire_composite_stiffener(self, fp, sweep)
        except Exception as exc:
            self.last_error = str(exc)
            raise
        self.last_error = None


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
        return [obj.Support, obj.IntersectSurface, obj.Profile] + (
            stiffener_claimed_children(obj)
        )

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
