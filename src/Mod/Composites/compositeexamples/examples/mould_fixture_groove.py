# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""An O-ring groove, cut into the level strip of a levelled mould.

A skirt that meets the block wall at a slope cannot be machined, so the skirt's
outer wall is levelled: each ray takes its whole fall in the first 10 mm
outboard of the cutline and then holds the outer z flat. What that leaves is a
flat strip along the wall - the only land outside the cavity a seal can be cut
into - and the analysis hands it over as the two rings that bound it, the
inboard edge of the flat and the wall base.

This example cuts the groove into that strip: centred on it, in the lower half
alone, so the ring seats in the groove and the upper half's flat face closes
over it. The size comes from the cord, because that is the number the shop has.

Three things are worth watching.

The levelling is inert unless it is asked for. `off` is the default and leaves
the mould exactly as it was, and `whole` shapes the ray but leaves no flat
strip - so a groove needs `s-curve` or `direct` with a `fixed` extent, and says
so instead of cutting a groove that is not there to cut.

The transition is measured from the cutline outward, so the strip is as wide as
the stock margin exceeds the transition. At the 60 mm stock below and a 10 mm
transition that is 50 mm of flat, far more than the groove needs; at the
default 5 mm margin the strip is 1 mm and the build refuses.

And the two rings come from the solve, not from a re-derivation: they are the
same stations the band is lofted through, in the same order, which is what lets
the groove be centred on the strip station for station.

The source is a plain box. The cambered loft the fixture example uses would be
the better showcase, but its skirt cannot be levelled on this tree: nextdrape
refuses it with "A8: outer relief rose from 1.761523 to 2.894227 mm" at ray
486, the ray that closes the part line, so no halves come out of it and there
is no strip to groove. The box levels, and the strip it leaves is what the
groove is cut into.

Only the groove and the process bores are cut here. The other fittings are the
neighbouring examples' subject, and on this part the default clamp bolts and a
groove centred on the strip cannot both keep their clearances: the bolt
counterbore reaches 17.5 mm in from the wall, while a strip wide enough to hold
the pins' own web puts the groove's centre further out than that.
"""

import FreeCAD
import Part

from ...features.MouldAnalysis import MouldAnalysisFP, ViewProviderMouldAnalysis
from ...features.MouldFixture import (
    CompositeMouldFixtureCommand,
    MouldFixtureFP,
    ViewProviderMouldFixture,
)
from ._mould_example_common import (
    LEVELLING,
    LEVELLING_EXTENT,
    LEVELLING_TRANSITION_MM,
    _attach_view_provider,
    _hide,
    _paint,
    _show,
)

PART_SIZE = (40.0, 30.0, 20.0)

# Stock around the part. The strip is as wide as the margin exceeds the
# transition, and the groove is centred on that strip - so generous stock pushes
# the groove out to where the pins and bolts sit, and the build reports the
# overlap. This is the mould's own need, not more: the wedge slot wants each
# block wall past 100 mm, and the command raises the margin to fit the fittings
# if this is too small.
STOCK_MARGIN = 40.0

# The ring the groove is cut for. A 3 mm cord gives a 3.75 mm wide, 2.25 mm deep
# groove; set SealGrooveWidth and SealGrooveDepth to use a table that disagrees.
CORD_DIAMETER = 3.0

SOURCE_COLOUR = (0.85, 0.15, 0.15)
LOWER_COLOUR = (0.25, 0.45, 0.85)
UPPER_COLOUR = (0.30, 0.70, 0.35)
STRIP_COLOUR = (0.95, 0.75, 0.10)


def build(doc=None, run_solver=False, **_ignored):
    """Source box, its levelled mould, and the groove cut into the lower half."""
    doc = doc or FreeCAD.newDocument("MouldGrooveExample")

    source = doc.addObject("Part::Feature", "Source")
    source.Shape = Part.makeBox(*PART_SIZE)
    _paint(source, SOURCE_COLOUR, 0)

    mould = doc.addObject("Part::FeaturePython", "Mould")
    MouldAnalysisFP(mould, source)
    # The tessellation march never closes its loop on a box in this tree, so the
    # projected outline is what produces the part line and the halves.
    mould.PartLineSource = "hlr"
    mould.PartingStockMarginX = STOCK_MARGIN
    mould.PartingStockMarginY = STOCK_MARGIN
    mould.PartingStockMarginZ = STOCK_MARGIN
    # The levelling has to be in place before the first analysis: the level
    # strip is an output of that analysis, and the groove is cut into the strip.
    mould.SkirtLevelling = LEVELLING
    mould.SkirtLevellingExtent = LEVELLING_EXTENT
    mould.SkirtLevellingTransition = LEVELLING_TRANSITION_MM
    _attach_view_provider(mould, ViewProviderMouldAnalysis)
    doc.recompute()

    fixture = doc.addObject("Part::FeaturePython", "MouldFixture")
    MouldFixtureFP(fixture, mould)
    # The groove, and the process bores every mould needs. The other fittings
    # are the neighbouring examples' subject, and on this part they cannot
    # coexist with a strip-centred groove - see the note in the module docstring
    # - so this example leaves them off rather than ship an example whose build
    # reports interferences.
    fixture.AlignmentPins = False
    fixture.ClampBolts = False
    fixture.PartingWedges = False
    fixture.SealGroove = True
    fixture.SealGrooveCordDiameter = CORD_DIAMETER
    _attach_view_provider(fixture, ViewProviderMouldFixture)
    # The command gives the mould the stock the fixtures need as it creates
    # them; an example creating the object by hand asks for the same thing
    # rather than duplicating the arithmetic.
    CompositeMouldFixtureCommand().post_create(fixture)
    doc.recompute()

    print("level strip  : %s" % mould.LevelStripSummary)
    print("mould halves : %s — %s" % (mould.MouldHalvesStatus, mould.MouldHalvesSummary))
    print("fixture      : %s" % fixture.FixtureStatus)
    print("summary      : %s" % fixture.FixtureSummary)
    print("issues       : %s" % fixture.FixtureIssues)

    # The analysis's own halves and the part line sit exactly where the fixtured
    # halves do; show the fixtured pair, which is the point of the example, and
    # the two rings the groove was centred between.
    _hide(mould.MouldHalfA)
    _hide(mould.MouldHalfB)
    _hide(mould.PartingSurface)
    _paint(mould.LevelStripIn, STRIP_COLOUR, 0)
    _paint(mould.LevelStripOut, STRIP_COLOUR, 0)
    _show(mould.LevelStripIn)
    _show(mould.LevelStripOut)
    _paint(fixture.FixtureLower, LOWER_COLOUR, 60)
    _paint(fixture.FixtureUpper, UPPER_COLOUR, 78)

    return {"doc": doc, "mould": mould, "fixture": fixture}


def main():
    """Run the example in its own document."""
    build()


if __name__ == "__main__":
    main()
