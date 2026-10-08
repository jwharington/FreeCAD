# SPDX-License-Identifier: LGPL-2.1-or-later

"""A borrowed weave answers with the source's own material frame.

A shell that borrows a drape (``DrapeSource``) shows the weave of the skin
it stands on: it never solves, it serves the solved drape of its source.
The frame the FEM exporter puts on an element — the material X direction
the solver laid the fibre down, Z the surface normal — must therefore come
from the *source*, unchanged and everywhere, not just inside the member's
own footprint.  ``BorrowedDrapeBackend`` delegates ``get_lcs``,
``get_lcs_batch``, ``get_lcs_at_point`` and ``get_tex_coord_at_point``
straight to the source for exactly that reason; only the cell list (the
geometry of the drawn weave) is filtered to the member's region.

These tests pin that delegation against the source's own answers, on
elements inside the member's region and on elements off it, and they fail
loudly if the shell under test stops borrowing — a silently re-solved
member would otherwise pass an equality check against itself.

The panel + band pair and the LCS sampling helpers are the existing
suites' fixtures, reused rather than reimplemented: the band is already
asserted to borrow the panel, and the frame helpers come from
``test_drape_lcs_frame``.  The suites are imported as *modules* and their
classes referenced through them — binding a TestCase subclass into this
module's namespace would make unittest collect and re-run that suite's
tests here, which is how one run of this module used to cost 83 s.  The
pair is built once per class (one drape solve); the per-test document
churn of ``TestFreeCADFP`` is deliberately not used.
"""

import os
import sys
import unittest

import FreeCAD  # noqa: E402
import Part  # noqa: E402

# Ensure repo root is on sys.path so package imports work.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import Composites  # noqa: E402, F401  (canonical package init order first)
import Composites.objects  # noqa: E402, F401

from Composites.compositestests import (  # noqa: E402
    test_base,
    test_bulkhead,
    test_drape_lcs_frame,
)

# One code path serves both shells here, so the frames are the same object
# values, not merely close: a borrowed frame that drifts by any amount is a
# bug, and a loose tolerance would hide it.
FRAME_TOL = 1e-9


class TestBorrowedDrapeFrame(
    test_bulkhead.TestBulkheadFeature, test_base.TestFreeCADFP
):
    """The band's frame is the panel's frame, on the band and off it."""

    # The bulkhead suite's fixture helpers, bound here rather than
    # inherited: subclassing TestBulkheadWiring would drag its whole test
    # suite into this module's run.
    _make_laminate = test_bulkhead.TestBulkheadWiring._make_laminate
    _make_panel = test_bulkhead.TestBulkheadWiring._make_panel
    _make_wired_bulkhead = test_bulkhead.TestBulkheadWiring._make_wired_bulkhead

    @classmethod
    def setUpClass(cls):
        """One panel + band pair for the whole class, solved once."""
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)
        cls.doc = FreeCAD.newDocument("TestDoc_BorrowedDrapeLcs")
        # A bare instance carries the fixture calls: the helpers are bound
        # methods, and calling them through the *class* would leave self
        # unbound (the first argument would be the name string).
        fixture = cls.__new__(cls)
        fixture.doc = cls.doc
        cls.panel = fixture._make_panel()
        fixture._make_wired_bulkhead("Bulkhead", cls.panel)
        cls.band = cls.doc.getObject("Bulkhead_Band")
        if cls.band is None:
            raise AssertionError("the fixture built no band shell")
        if cls.band.DrapeSource is not cls.panel:
            raise AssertionError(
                "the fixture's band must borrow the panel's solved drape"
            )
        backend = cls.band.Proxy._backend
        if type(backend).__name__ != "BorrowedDrapeBackend":
            raise AssertionError(
                "the band is not borrowing - the equality below would be vacuous"
            )
        if backend._source is not cls.panel.Proxy._backend:
            raise AssertionError(
                "the borrowed backend must serve the panel's own backend"
            )

    @classmethod
    def tearDownClass(cls):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)
        cls.doc = None
        cls.panel = None
        cls.band = None

    def setUp(self):
        """Nothing per test: the pair is class-level, one solve total."""
        pass

    def tearDown(self):
        """No document churn, no per-test save: the class owns the doc."""
        pass

    @staticmethod
    def _triangles_at(shell, fractions):
        """Triangles at parameter fractions of *shell*'s support face."""
        triangles = []
        for u_frac, v_frac in fractions:
            point, u_axis, normal = test_drape_lcs_frame._FrameFixture._face_frame(
                shell, u_frac, v_frac
            )
            triangles.append(
                test_drape_lcs_frame._FrameFixture._triangle(
                    None, point, u_axis, normal
                )
            )
        return triangles

    def assertSameFrame(self, got, want, msg):
        """Frame equality at the tolerance the shared code path implies."""
        self.assertIsNotNone(got, f"{msg}: the borrower answered nothing")
        self.assertIsNotNone(want, f"{msg}: the source answered nothing")
        for axis in ("x", "y", "z"):
            self.assertAlmostEqual(
                getattr(got.Base, axis), getattr(want.Base, axis),
                delta=FRAME_TOL, msg=f"{msg}: frame origin differs on {axis}",
            )
        got_warp = test_drape_lcs_frame._FrameFixture._warp(got)
        want_warp = test_drape_lcs_frame._FrameFixture._warp(want)
        for axis, (a, b) in enumerate(zip(got_warp, want_warp)):
            self.assertAlmostEqual(
                a, b, delta=FRAME_TOL,
                msg=f"{msg}: warp direction differs on {axis}",
            )

    def test_frame_matches_the_source_on_the_member(self):
        """On its own footprint the member reports the skin's frame."""
        for triangle in self._triangles_at(self.band, [(0.5, 0.5)]):
            self.assertSameFrame(
                self.band.Proxy.get_drape_lcs(triangle),
                self.panel.Proxy.get_drape_lcs(triangle),
                "frame on the member",
            )

    def test_frame_matches_the_source_off_the_member(self):
        """Off the member's region the skin still answers for it.

        The frame query is not a region query: the member borrows the whole
        continuous field, so an element of the member that lands outside
        its own footprint — a flange edge, a joint element — gets the
        skin's frame there, not a nearest-quad guess.
        """
        off_band = [(0.05, 0.05), (0.5, 0.5), (0.95, 0.95)]
        for triangle in self._triangles_at(self.panel, off_band):
            self.assertSameFrame(
                self.band.Proxy.get_drape_lcs(triangle),
                self.panel.Proxy.get_drape_lcs(triangle),
                "frame off the member",
            )

    def test_batch_form_matches_the_source_element_for_element(self):
        """The deck's bulk call is the same query, in the same order."""
        triangles = self._triangles_at(
            self.panel, [(0.05, 0.05), (0.5, 0.5), (0.95, 0.95)]
        )
        borrowed = self.band.Proxy.get_drape_lcs_batch(triangles)
        source = self.panel.Proxy.get_drape_lcs_batch(triangles)
        self.assertEqual(
            len(borrowed), len(source),
            "the batch and the source answered different numbers of elements",
        )
        for index, (got, want) in enumerate(zip(borrowed, source)):
            self.assertSameFrame(got, want, f"batch element {index}")

    def test_texture_coordinate_query_defers_to_the_source(self):
        """The flat-pattern lookup is the source's, point for point.

        The drawn cells are filtered to the member's region, but the
        coordinate a point maps to is not: it comes from the solved
        locator, so a point inside the member and a point off it both
        agree with the skin's answer.
        """
        source_backend = self.panel.Proxy._backend
        borrowed_backend = self.band.Proxy._backend
        for u_frac, v_frac in ((0.5, 0.5), (0.05, 0.05), (0.95, 0.95)):
            point, _, _ = test_drape_lcs_frame._FrameFixture._face_frame(
                self.panel, u_frac, v_frac
            )
            got = borrowed_backend.get_tex_coord_at_point(point, 0)
            want = source_backend.get_tex_coord_at_point(point, 0)
            self.assertIsNotNone(want, "the source did not locate the point")
            self.assertIsNotNone(
                got, "the borrower did not locate a point the source located"
            )
            for a, b in zip(got, want):
                self.assertAlmostEqual(
                    a, b, delta=FRAME_TOL,
                    msg="borrowed texture coordinate differs from the source",
                )


if __name__ == "__main__":
    unittest.main()
