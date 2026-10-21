# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Mould fixtures — a box mould's two halves, fitted out for the shop floor.

The mould analysis builds a stock block around the part and parts it into two
halves.  `MouldFixture` then cuts the fittings into those halves: alignment
dowel and bush sockets in the corners, clamp bolt holes through the upper into
a tapped hole in the lower, process bores in from the walls, and a triangular
parting slot along each wall whose apex sits on the mating plane.

The fixtures are cut *into* the halves rather than added beside them, so
`MouldFixture` has no shape of its own — the block you see is its two hidden
children, `MouldFixture_FixtureLower` and `_FixtureUpper`, each with its
fittings taken out of it.  Compare them with the analysis's own `MouldHalfA` /
`MouldHalfB`, which are hidden here to keep the two from overlapping.

The source is a plain box, so all the interesting geometry is the block the
analysis builds around it and what the fixture cuts into that: the part (red)
sits in the cavity, `FixtureLower` (blue) carries the dowels, the tapped bolt
holes and the lower half of every parting slot, and `FixtureUpper` (green, more
transparent so the lower shows through) carries the bushes and the bolt
clearance holes.  Each slot runs its wall's full length less a 50 mm standoff
at either corner (`WedgeCornerStandoff`), so a wedge can be driven in wherever
the halves stick while the corners that hold the alignment stay whole, and it
is interrupted over each process port so the bore does not break into it.

The part-line solver is set to 'hlr'.  The tessellation march is the drafted
path and the default, but on a box in this tree it never closes its loop
("no closed loop", chains=1 loops=0) and no halves come out of it; HLR projects
the outline instead and does close.  Set `Mould.PartLineSource` back to
'tessellation' to watch the halves disappear.
"""

import FreeCAD
import Part

from ...features.MouldAnalysis import MouldAnalysisFP, ViewProviderMouldAnalysis
from ...features.MouldFixture import (
    CompositeMouldFixtureCommand,
    MouldFixtureFP,
    ViewProviderMouldFixture,
)

PART_SIZE = (40.0, 30.0, 20.0)

# Stock around the part.  Generous on purpose: the default 5 mm cannot hold the
# default fixtures, whose corner pin alone needs about 41 mm for the skirt
# clearance rule, and the wedge slots leave a 50 mm standoff at every corner.
STOCK_MARGIN = 60.0

SOURCE_COLOUR = (0.85, 0.15, 0.15)
LOWER_COLOUR = (0.25, 0.45, 0.85)
UPPER_COLOUR = (0.30, 0.70, 0.35)


def _attach_view_provider(obj, provider):
    """Attach a feature's own ViewProvider when a GUI is up.

    The command path does this (`cls_vp(obj.ViewObject)`); a bare `addObject`
    example must do the same, or the GUI object carries no VP proxy — the tree
    shows a default part feature, the icon is missing, and the object cannot be
    enabled for display.
    """
    view = getattr(obj, "ViewObject", None)
    if view is not None and getattr(view, "Proxy", None) is None:
        provider(view)


def _paint(obj, colour, transparency):
    """Tint `obj` if there is a view provider to tint; headless just skips it."""
    view = getattr(obj, "ViewObject", None)
    if view is None:
        return
    try:
        view.ShapeColor = colour
        view.Transparency = transparency
        view.DisplayMode = "Flat Lines"
    except (AttributeError, TypeError, ValueError):
        pass


def _hide(obj):
    view = getattr(obj, "ViewObject", None)
    if view is not None:
        view.Visibility = False


def build(doc=None, run_solver=False, **_ignored):
    """Source part, its mould analysis, and the fixtures cut into the halves."""
    doc = doc or FreeCAD.newDocument("MouldFixtureExample")

    source = doc.addObject("Part::Feature", "Source")
    source.Shape = Part.makeBox(*PART_SIZE)
    _paint(source, SOURCE_COLOUR, 0)

    mould = doc.addObject("Part::FeaturePython", "Mould")
    MouldAnalysisFP(mould, source)
    mould.PartLineSource = "hlr"
    mould.PartingStockMarginX = STOCK_MARGIN
    mould.PartingStockMarginY = STOCK_MARGIN
    mould.PartingStockMarginZ = STOCK_MARGIN
    _attach_view_provider(mould, ViewProviderMouldAnalysis)
    doc.recompute()

    fixture = doc.addObject("Part::FeaturePython", "MouldFixture")
    MouldFixtureFP(fixture, mould)
    _attach_view_provider(fixture, ViewProviderMouldFixture)
    # The command gives the mould the stock the fixtures need as it creates
    # them; an example creating the object by hand asks for the same thing
    # rather than duplicating the arithmetic.
    CompositeMouldFixtureCommand().post_create(fixture)
    doc.recompute()

    print("mould halves : %s — %s" % (mould.MouldHalvesStatus, mould.MouldHalvesSummary))
    print("fixture      : %s" % fixture.FixtureStatus)
    print("summary      : %s" % fixture.FixtureSummary)
    print("issues       : %s" % fixture.FixtureIssues)

    # The analysis's own halves and the part line would sit exactly where the
    # fixtured halves do; show the fixtured pair, which is the point of the
    # example, and the part inside the cavity.
    _hide(mould.MouldHalfA)
    _hide(mould.MouldHalfB)
    _hide(mould.PartingSurface)
    _paint(fixture.FixtureLower, LOWER_COLOUR, 60)
    _paint(fixture.FixtureUpper, UPPER_COLOUR, 78)

    return {"doc": doc, "mould": mould, "fixture": fixture}
