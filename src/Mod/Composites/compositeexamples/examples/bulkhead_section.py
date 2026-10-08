# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Bulkhead on the fixture skin — the section layer, shown rather than asserted.

Section I lays the member's faces into the document as separate features:
the full skins (hidden, so the cutout can be seen), the holed skin — the
flange band cut *out of* the skin by `drape_cuts_of`, so panel and member
cannot both claim one patch of material — the filled section (`Plate`), the
band itself (`Flange`, its foot lying *behind* the plate), and a mirrored
copy of the whole member (`PlateM`/`FlangeM`, one-sided like every bulkhead
but hugging the *far* side of the plate: what the `MirrorX` property is
for).  Skin area = Remainder + Flange, exactly.

Section II reaches the same shape through the `BulkheadFP` feature, un-
mirrored and mirrored, with no Laminate linked — pure geometry.  Section
III declares the feature over the bay: a void solid (`BayBox`) and the
same feature with `TrimTool = BayBox`, so the plate and band stop at
the opening's edges while the footprint stays cut from the uncut skin
(the drape surface never moves).
"""

import FreeCAD
import Part

from ...features.Bulkhead import BulkheadFP, ViewProviderBulkhead
from .. import fixture_bulkhead as fixture
from ...tools import bulkhead_section as section


def _attach_view_provider(member):
    """Attach the bulkhead's own ViewProvider when a GUI is up.

    The command path does this (`cls_vp(obj.ViewObject)`); a bare
    `addObject` example must do the same, or the GUI object carries no
    VP proxy — the tree shows a default part feature, the icon is
    missing, and the object cannot be enabled for display.
    """
    view = getattr(member, "ViewObject", None)
    if view is not None and getattr(view, "Proxy", None) is None:
        ViewProviderBulkhead(view)

CUT_STATION = 210.0
FLANGE_WIDTH = 34.0


def _paint(obj, colour):
    """Tint `obj`, if there is a view provider to tint.

    A headless run still has to build the shape.  `obj` is a FeaturePython or a
    Part::Feature created by `build` and `colour` is an (r, g, b) triple; the
    headless ViewObject does take `ShapeColor`, so the assignment is made
    through the `SwatchColour` path the shell examples use.
    """
    view = getattr(obj, "ViewObject", None)
    if view is None:
        return
    try:
        view.ShapeColor = colour
        view.Transparency = 60
        # Display mode is per-view-provider: some members' VPs do not
        # carry "Flat Lines", and the enum raise must not eat the tint.
        view.DisplayMode = "Flat Lines"
    except (AttributeError, TypeError, ValueError):
        pass


def _support_features(doc, shape):
    """The skin, one feature per face, so each can be picked and inspected."""
    features = []
    for number, face in enumerate(shape.Faces, start=1):
        obj = doc.addObject("Part::Feature", f"Skin{number}")
        obj.Shape = face
        _paint(obj, (0.62, 0.50, 0.36))
        skin_view = getattr(obj, "ViewObject", None)
        if skin_view is not None:
            skin_view.Transparency = 70
        features.append(obj)
    return features


def build(doc=None, sewn=False, **_ignored):
    """The bulkhead section over the fixture skin, in one document.

    Returns the document; `doc` may be an open document (the example runner
    hands one in) and a fresh one is made otherwise.  Each `Part::Feature`
    carries `Shape` — never `Shape.Faces`, which would make every object share
    one compound and colour and visibility would land on all of them at once.
    """
    doc = doc or FreeCAD.newDocument("Composites_BulkheadSection")
    support = fixture.bulkhead_fixture(sewn=sewn)
    _support_features(doc, support)
    cutter = fixture.station_plane(CUT_STATION)
    plates, bands = section.make_bulkhead(support, cutter, FLANGE_WIDTH)

    # The plate lies in the cutting plane; the flange lies on the skin, so the
    # fold between them is a fold and not an outline.
    for skin in doc.Objects:
        if skin.Name.startswith("Skin"):
            skin_view = getattr(skin, "ViewObject", None)
            if skin_view is not None:
                skin_view.Visibility = False

    plate = doc.addObject("Part::Feature", "Plate")
    plate.Shape = Part.makeCompound(list(plates))
    _paint(plate, (0.20, 0.45, 0.85))

    flange = doc.addObject("Part::Feature", "Flange")
    flange.Shape = Part.makeCompound(list(bands))
    _paint(flange, (0.85, 0.35, 0.20))

    # The same skin, with the band's footprint cut out of it: what the
    # panel keeps where the flange lies is exactly what it gives up.
    holed = doc.addObject("Part::Feature", "Remainder")
    holed.Shape = Part.makeCompound(
        list(section.drape_cuts_of(support, cutter, FLANGE_WIDTH)))
    _paint(holed, (0.15, 0.60, 0.30))

    # A mirrored copy: one-sided like every bulkhead, but hugging the far
    # side of the plate — the shape `MirrorX = True` produces.  Its own
    # footprint is cut from its own copy of the skins, so the pair can be
    # compared without either one's hole being hidden behind the other.
    plates_m, bands_m = section.make_bulkhead(
        support, cutter, FLANGE_WIDTH, mirror_x=True)
    plate_m = doc.addObject("Part::Feature", "PlateM")
    plate_m.Shape = Part.makeCompound(list(plates_m))
    _paint(plate_m, (0.45, 0.20, 0.65))
    flange_m = doc.addObject("Part::Feature", "FlangeM")
    flange_m.Shape = Part.makeCompound(list(bands_m))
    _paint(flange_m, (0.85, 0.35, 0.20))
    holed_m = doc.addObject("Part::Feature", "SkinM")
    holed_m.Shape = Part.makeCompound(
        list(section.drape_cuts_of(support, cutter, FLANGE_WIDTH,
                                   mirror_x=True)))
    _paint(holed_m, (0.15, 0.60, 0.30))

    return doc


def build_with_feature(doc=None, sewn=False, **_ignored):
    """Section II — the same shape reached through the `BulkheadFP` feature.

    The feature computes its own Shape from Support + IntersectSurface, so the
    geometry is derived, not pasted: what the example shows and what the
    feature recomputes on reload are the same faces by construction.  A
    headless run resolves the feature through the same package path the
    other examples in this directory use.
    """
    doc = doc or FreeCAD.newDocument("Composites_BulkheadFeature")
    support = doc.addObject("Part::Feature", "Skin")
    support.Shape = fixture.bulkhead_fixture(sewn=sewn)
    cutter = doc.addObject("Part::Feature", "StationPlane")
    cutter.Shape = fixture.station_plane(CUT_STATION)

    member = doc.addObject("Part::FeaturePython", "Bulkhead")
    BulkheadFP(member, support=support, cut_surface=cutter)
    _attach_view_provider(member)
    doc.recompute()
    # The plate lies inside the skin and the band lies flat on it, so both are
    # invisible against an opaque grey tube: tint the member, fade the skin.
    _paint(member, (0.85, 0.10, 0.10))
    skin_view = getattr(support, "ViewObject", None)
    if skin_view is not None:
        skin_view.Transparency = 70
    cutter_view = getattr(cutter, "ViewObject", None)
    if cutter_view is not None:
        cutter_view.Visibility = False
    return doc


def build_trimmed(doc=None, sewn=False, **_ignored):
    """Section III — the bulkhead declared over an opening, trimmed by it.

    The bay box stands in for an engine-bay solid: with `TrimTool` set,
    the plate and band stop at the opening's edges (the trim applies to
    the member's faces before the feature's shape is built); the drape
    cut surface stays on the uncut skin.  The untrimmed feature from
    Section II is the before picture; this is the after.
    """
    doc = doc or FreeCAD.newDocument("Composites_BulkheadTrimmed")
    support = doc.addObject("Part::Feature", "Skin")
    support.Shape = fixture.bulkhead_fixture(sewn=sewn)
    cutter = doc.addObject("Part::Feature", "StationPlane")
    cutter.Shape = fixture.station_plane(CUT_STATION)

    bay = doc.addObject("Part::Feature", "BayBox")
    box = support.Shape.BoundBox
    bay.Shape = Part.makeBox(120.0, 2.0 * FLANGE_WIDTH, box.ZLength,
                             FreeCAD.Vector(CUT_STATION - 60.0,
                                            -FLANGE_WIDTH, box.ZMin))
    _paint(bay, (0.30, 0.30, 0.30))

    member = doc.addObject("Part::FeaturePython", "Bulkhead")
    BulkheadFP(member, support=support, cut_surface=cutter)
    _attach_view_provider(member)
    member.TrimTool = bay
    doc.recompute()
    _paint(member, (0.85, 0.10, 0.10))
    skin_view = getattr(support, "ViewObject", None)
    if skin_view is not None:
        skin_view.Transparency = 70
    cutter_view = getattr(cutter, "ViewObject", None)
    if cutter_view is not None:
        cutter_view.Visibility = False
    bay_view = getattr(bay, "ViewObject", None)
    if bay_view is not None:
        bay_view.Transparency = 80
    return doc
