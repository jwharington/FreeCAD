# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Bulkhead on the fixture skin — the section layer, shown rather than asserted.

Builds the same support the bulkhead suites measure (`fixture_bulkhead`), cuts
it with the same station plane, and lays the member's two kinds of face into
the document as separate features:

* **CutSurface** — the 900 mm station plane, shown only to be visible in
  Section I: §5's `!IsInsideFace` fix means a closed loop inside an outer wire
  does lose coverage *over* the hole, so whether the plate needs cutting out of
  the skin is no longer answerable on paper.  The plane is where that would
  begin to show, and a plane that merely misses the skin is already caught by
  the x = 700 probe in the section suite.
* **Plate** — the filled section, `Part.Face` of the closed chain.
* **Flange** — the band taken *out of* the skin by `band_of`, and by
  `drape_cuts_of` subtracted from it, so panel and member cannot both claim one
  patch of material (F4's exclusivity).

Section II adds the `BulkheadFP` feature over the same shape: with no Laminate
linked the feature is pure geometry, and a linked Laminate is answered
`"Nope, for now."` — the same "geometry first, composites later" route the
stiffener examples take, kept here because the drape pitch and the stack model
are decided by what the *member* occupies, not by the plate's stand-off (R3).

Colours are set only when a ViewObject exists, so the module stays importable
under FreeCADCmd as well as in the GUI.
"""

import FreeCAD
import Part

from ...features.Bulkhead import BulkheadFP
from .. import fixture_bulkhead as fixture
from ...tools import bulkhead_section as section

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
        view.DisplayMode = "Flat Lines"
        view.ShapeColor = colour
        view.Transparency = 60
    except (AttributeError, TypeError):
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


def build(doc=None, sewn=False):
    """The bulkhead section over the fixture skin, in one document.

    Returns the document; `doc` may be an open document (the example runner
    hands one in) and a fresh one is made otherwise.  Each `Part::Feature`
    carries `Shape` — never `Shape.Faces`, which would make every object share
    one compound and colour and visibility would land on all of them at once.
    """
    doc = doc or FreeCAD.newDocument("Composites_BulkheadSection")
    cutter = fixture.station_plane(CUT_STATION)
    plates, bands = section.make_bulkhead(
        fixture.bulkhead_fixture(sewn=sewn), cutter, FLANGE_WIDTH)

    # The plate lies in the cutting plane; the flange lies on the skin, so the
    # fold between them is a fold and not an outline.
    plate = doc.addObject("Part::Feature", "Plate")
    plate.Shape = Part.makeCompound(list(plates))
    _paint(plate, (0.20, 0.45, 0.85))

    flange = doc.addObject("Part::Feature", "Flange")
    flange.Shape = Part.makeCompound(list(bands))
    _paint(flange, (0.85, 0.35, 0.20))

    return doc


def build_with_feature(doc=None, sewn=False):
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
