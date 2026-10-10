# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Regression for the fuselage skin L/R split: a ring swept on a halved skin.

The fuselage skins drape as L/R halves cut at the model symmetry plane y = 0
(``HANDOVER-2026-09-30-skin-lr-split.md``).  When that halved skin is the
ring's support, the station section is two arcs meeting smoothly at the
crown — a *closed, two-edge* row.  ``tools/stiffener._sideways`` dispatches
on edge count alone, so it routes that smooth closed row to
``_creased_sideways``, whose exact-offset direction probe raises
``Part.OCCError: Offset on C0 curve`` on the row's C0-trimmed end.  The ring
build then dies: measured on the fuselage at ring 1 (``Spar_frame: no swept
geometry``), both the raw OCCError and the open 4-edge row it leaves behind.

The QI frame ring spans the full closed section — only the draped fabric
(skin weave and foot) is split — so the ring's sweep must succeed on the
full skin.  These tests pin the two halves of that contract at the scale and
geometry of the real fuselage:

* the section of a halved skin is the expected closed two-arc row (the
  geometry is sound — the failure is the sweep's handling of it), and
* a ring swept on that halved support builds without raising (the defect).

They reproduce the blocker as committed, failing tests, ahead of the fix.
"""

import unittest

import FreeCAD
import Part

from Composites.tools import stiffener as st
from Composites.util.geometry_util import split_at_symmetry_plane as _split_halves
from .test_base import TestFreeCADFP
from .test_stiffener import lofted_skin_face, standalone_station_plane

# Fuselage-scale sections (station_x, height, width), mirroring frame_0's
# neighbourhood — the same fixture test_drape_common_with_rings uses.
SECTIONS = (
    (-10.0, 565.0, 460.0),
    (200.0, 495.0, 400.0),
    (420.0, 415.0, 330.0),
    (630.0, 355.0, 280.0),
)
STATION_X = 200.0
FRAME_SECTION = 34.0


def split_at_symmetry_plane(shape):
    """Cut every face of ``shape`` at the model symmetry plane y = 0.

    The L/R halves the skins drape as, as one compound.  The split itself is
    the same ``geometry_util`` call the design side uses, so this fixture
    cannot drift from what the model actually does.
    """
    left, right = _split_halves(shape)
    return Part.makeCompound(list(left.Faces) + list(right.Faces))


def frame_profile():
    """The C frame section as plain edges (foot, web, inboard flange)."""
    s = FRAME_SECTION
    return [
        Part.LineSegment(FreeCAD.Vector(s, 0, 0), FreeCAD.Vector(0, 0, 0)).toShape(),
        Part.LineSegment(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, s, 0)).toShape(),
        Part.LineSegment(FreeCAD.Vector(0, s, 0), FreeCAD.Vector(s, s, 0)).toShape(),
    ]


class TestRingOnHalvedSkin(TestFreeCADFP, unittest.TestCase):
    """The ring sweep on the L/R-halved lofted skin."""

    def _halved_skin(self):
        face = lofted_skin_face(SECTIONS)
        return split_at_symmetry_plane(face)

    def test_halved_skin_sections_to_a_closed_two_arc_row(self):
        """The station plane cuts the halves into a closed two-edge path.

        This is the sound geometry the sweep mishandles: two arcs meeting
        smoothly at the crown, chaining into one closed ring path.  If this
        fails the split itself is wrong, not the sweep.
        """
        support = self._halved_skin()
        self.assertGreaterEqual(len(support.Faces), 2, "the skin did not split")
        plane = standalone_station_plane(2.0 * 400.0, STATION_X)
        paths = st.intersection_paths(support, plane)
        self.assertEqual(len(paths), 1, f"expected one ring path, got {len(paths)}")
        path = paths[0]
        self.assertTrue(path.isClosed(), "the ring path is not closed")
        self.assertEqual(
            len(path.Edges), 2, f"expected the two section arcs, got {len(path.Edges)}"
        )

    def test_ring_sweeps_on_the_halved_skin(self):
        """A full ring sweeps on the halved skin without raising.

        THE reproduction: ``_sideways`` mis-dispatches the smooth closed
        two-edge web row to ``_creased_sideways``, whose exact-offset probe
        raises ``Offset on C0 curve``.  The ring must build — the QI frame
        spans the full section and only the fabric is split.
        """
        support = self._halved_skin()
        plane = standalone_station_plane(2.0 * 400.0, STATION_X)
        # The profile has to be a shape: a bare list of edges has no .Edges,
        # so _profile_edges found nothing and the sweep built an empty shell,
        # which is why this test reported no web faces while its sibling, which
        # never passes a profile, passed.
        profile = Part.Wire(frame_profile())
        sweep = st.make_stiffener(
            support, plane, profile, st.ProfileMirror(flip_y=True)
        )
        self.assertFalse(
            sweep.shell.isNull(), "the ring produced no swept geometry"
        )
        self.assertGreater(
            len(sweep.web_faces), 0, "the ring produced no web faces"
        )

    def test_a_profile_with_no_edges_is_refused(self):
        """A profile the sweep cannot read must fail, not build an empty shell.

        This is what hid the fixture mistake above: an empty shell is not null,
        so the sweep looked like it had built something and only the face count
        disagreed.
        """
        with self.assertRaises(ValueError):
            st.get_xsect([])


if __name__ == "__main__":
    unittest.main()
