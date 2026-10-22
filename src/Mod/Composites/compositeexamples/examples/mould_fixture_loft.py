# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Mould fixtures on a lofted part — the same fittings, on a curved shape.

The box example shows what the fittings are; this one shows that nothing in
them assumed a box. The part is the cambered, slightly twisted loft the mould
profiler benchmarks with, and the block is built around it and parted by the
HLR part line.

Two things are worth watching.

The draw direction is Y, through the part's thickness, so the parting follows
its camber. Along its own axis (Z) this loft produces no halves at all — the
part line does not span the candidate network — and across the chord (X) it
parts, but that is not the direction the part is moulded in.

And the block the analysis builds is not aligned to the world axes, so every
position is worked out in the recovered block frame rather than in XYZ: the
walls a pin is inset from are the block's own, and the mating height is a
different plane at every station, read from the halves rather than assumed.

The wedge slot along each wall and the seating of each locating part are the
same cuts as in the box example, on the same default hardware.
"""

import FreeCAD

from ...features.MouldAnalysis import MouldAnalysisFP, ViewProviderMouldAnalysis
from ...features.MouldFixture import (
    CompositeMouldFixtureCommand,
    MouldFixtureFP,
    ViewProviderMouldFixture,
)
from ...tools.profile_mould_analysis import _make_loft_shape
from ._mould_example_common import (
    LEVELLING,
    LEVELLING_EXTENT,
    LEVELLING_TRANSITION_MM,
    _attach_view_provider,
    _hide,
    _paint,
)

# Through the part's thickness, so the parting follows its camber. Parted along
# its own axis (Z) this loft produces no halves: the part line does not span the
# candidate network.
DRAW = FreeCAD.Vector(0.0, 1.0, 0.0)

# The loft is authored around 26 x 5 x 32 mm - a blade section rather than a part
# in its own right. Scaling by ten makes it 262 x 52 x 320 mm, which is the size
# the fixture defaults are chosen for.
LOFT_SCALE = 10.0

# Stock around the part. Generous on purpose: the default 5 mm cannot hold the
# default fixtures, and the wedge slot needs each wall to run past 100 mm.
STOCK_MARGIN = 60.0

SOURCE_COLOUR = (0.85, 0.15, 0.15)
LOWER_COLOUR = (0.25, 0.45, 0.85)
UPPER_COLOUR = (0.30, 0.70, 0.35)


def build(doc=None, run_solver=False, **_ignored):
    """Source loft, its mould analysis, and the fixtures cut into the halves."""
    doc = doc or FreeCAD.newDocument("MouldFixtureLoftExample")

    source = doc.addObject("Part::Feature", "Source")
    source.Shape = _make_loft_shape().scaled(LOFT_SCALE)
    _paint(source, SOURCE_COLOUR, 0)

    mould = doc.addObject("Part::FeaturePython", "Mould")
    MouldAnalysisFP(mould, source)
    mould.PartLineSource = "hlr"
    mould.PreferredDrawDirection = DRAW
    mould.PartingStockMarginX = STOCK_MARGIN
    mould.PartingStockMarginY = STOCK_MARGIN
    mould.PartingStockMarginZ = STOCK_MARGIN
    # The land the mould closes on, so the seal groove has a strip to cut into:
    # this is the fixtured loft, and without it the mould has no land at all.
    mould.SkirtLevelling = LEVELLING
    mould.SkirtLevellingExtent = LEVELLING_EXTENT
    mould.SkirtLevellingTransition = LEVELLING_TRANSITION_MM
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

    # The analysis's own halves and the part line sit exactly where the fixtured
    # halves do; show the fixtured pair, which is the point of the example.
    _hide(mould.MouldHalfA)
    _hide(mould.MouldHalfB)
    _hide(mould.PartingSurface)
    _paint(fixture.FixtureLower, LOWER_COLOUR, 60)
    _paint(fixture.FixtureUpper, UPPER_COLOUR, 78)

    return {"doc": doc, "mould": mould, "fixture": fixture}


def main():
    """Run the example in its own document."""
    build()


if __name__ == "__main__":
    main()
