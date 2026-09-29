# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Ring-frame scenario: closed stiffener rings on lofted sleeve panels.

An airframe-style frame ring is a closed stiffener on a sleeve panel,
sharing one quasi-isotropic laminate, with the seam wiring that follows
(web/foot shells, the combined joint laminate).  This module exercises
that path end to end at a small test scale, on the geometry the real case
uses:

1. a **lofted elliptical sleeve** per station, passed through a boolean
   ``common`` so the ring's section planes behave as they do on the real
   part (see ``sleeve_shape``);
2. a **station plane** as the inboard-facing face of a thin box (the
   cut surface a ring sweeps from);
3. a **QI ring stiffener** on that sleeve, sharing one isotropic-
   equivalent laminate;
4. the **seam wiring** that follows, and the panel's support contract:
   the ring's seat consumes the sleeve, so there is no remainder to weave
   on and the panel must keep its own support rather than be re-supported
   onto an empty one.

The lofted ellipse is deliberate — the B-spline sections are the
expensive part of this scenario, and they are what the real frames use.
The related ``test_stiffener_composite_shell`` case
``test_panel_keeps_its_support_when_the_seat_leaves_no_remainder`` pins
the same support contract on a cheap planar panel.
"""

import FreeCAD
import Part

from Composites.features.Stiffener import StiffenerFP

from .test_stiffener_composite_shell import (
    StiffenerCompositeFixture,
    TestQuasiIsotropicStiffener,
)

# Test-scale frame section (mm).  A real frame section is larger; the
# shape of the problem is the same and the run stays fast.
FRAME_SECTION = 8.0
# Sleeve margin beyond the frame on either side.
SLEEVE_MARGIN = 6.0
# Ring stations in model X, with the station's ellipse (height, width).
STATIONS = (
    (0.0, 48.0, 36.0),
    (-60.0, 40.0, 30.0),
)
# Cut-surface / sleeve box extent in Y and Z (mm): comfortably past the
# largest station ellipse, and no larger — these boxes feed the boolean
# sections, which are the expensive part of the set-up.
BOX_SPAN = 80.0


def ellipse_wire(station_x, height, width):
    """An ellipse in the station plane, major axis vertical: height along
    model Z, width along model Y."""
    point = FreeCAD.Vector(station_x, 0.0, 0.0)
    ellipse = Part.Ellipse(point, height / 2.0, width / 2.0)
    rotation = FreeCAD.Rotation(
        FreeCAD.Vector(1.0, 0.0, 0.0), FreeCAD.Vector(0.0, 0.0, 1.0)
    )
    ellipse.rotate(FreeCAD.Placement(point, rotation))
    return ellipse.toShape()


def sleeve_shape(station_x, height, width):
    """The ring's helper sleeve: a plain ruled loft spanning exactly the
    frame section.

    No boolean ``common`` treatment.  That was a workaround so the seat's
    rows — interior sections of a wider sleeve — would be offsettable, and it
    left the support face in a state the Boolean engine cannot split at all
    (measured: cutting it by the stiffener's faces returns nothing; the same
    cut on this plain loft returns the expected pieces).  Spanning exactly
    the frame section puts both rows on the face's own boundary sections,
    which a plain loft sections and offsets correctly.
    """
    outboard = ellipse_wire(station_x, height, width)
    inboard = ellipse_wire(station_x + FRAME_SECTION, height, width)
    return Part.makeLoft([outboard, inboard], False, True).Faces[0]


class TestRingFrames(StiffenerCompositeFixture):
    """Closed QI ring frames on lofted sleeve panels."""

    def _make_qi_laminate(self, name="FrameQILaminate"):
        """One isotropic-equivalent laminate shared by every ring."""
        return self._make_laminate(
            TestQuasiIsotropicStiffener.QI_ANGLES,
            [0.5] * 4,
            [TestQuasiIsotropicStiffener.CARBON] * 4,
            name=name,
            isotropic=True,
        )

    def _make_sleeve_panel(self, name, station_x, height, width):
        """A QI composite panel draped over the ring's helper sleeve.

        No rosette: an isotropic-equivalent (QI) shell has no fibre frame
        to seed one from, and the feature rejects a linked rosette.
        """
        sleeve = sleeve_shape(station_x, height, width)
        return self._make_panel(
            name=f"{name}Panel",
            plate=sleeve,
            isotropic=True,
            with_rosette=False,
        )

    def _make_ring(self, name, panel, laminate, station_x):
        """A full-composite ring stiffener on `panel`, sweeping inboard
        from the station plane."""
        cut_surface = self.doc.addObject("Part::Feature", f"{name}Plane")
        # The station plane is the inboard-facing face of a 1 mm box on
        # the outboard side, so the profile rows are re-cut inboard.
        box = Part.makeBox(
            1.0,
            BOX_SPAN,
            BOX_SPAN,
            FreeCAD.Vector(station_x - 1.0, -BOX_SPAN / 2.0, -BOX_SPAN / 2.0),
        )
        cut_surface.Shape = [
            face
            for face in box.Faces
            if abs(face.BoundBox.XLength) < 1e-9
            and abs(face.BoundBox.XMin - station_x) < 1e-9
        ][0]

        profile = self.doc.addObject("Sketcher::SketchObject", f"{name}Profile")
        points = [
            FreeCAD.Vector(0.0, 0.0, 0.0),
            FreeCAD.Vector(FRAME_SECTION, 0.0, 0.0),
            FreeCAD.Vector(FRAME_SECTION, FRAME_SECTION, 0.0),
            FreeCAD.Vector(0.0, FRAME_SECTION, 0.0),
            FreeCAD.Vector(0.0, 0.0, 0.0),
        ]
        for start, end in zip(points, points[1:]):
            profile.addGeometry(Part.LineSegment(start, end), False)

        stiffener = self.doc.addObject("Part::FeaturePython", name)
        StiffenerFP(
            stiffener, support=panel, cut_surface=cut_surface, profile=profile
        )
        stiffener.Laminate = laminate
        self.doc.recompute()
        return stiffener

    def _build_all_rings(self):
        """Build a sleeve panel plus its ring at every station.

        Returns ``(laminate, [(name, panel, stiffener), ...])``.
        """
        laminate = self._make_qi_laminate()
        built = []
        for index, (station_x, height, width) in enumerate(STATIONS):
            name = f"Ring{index}"
            panel = self._make_sleeve_panel(name, station_x, height, width)
            stiffener = self._make_ring(name, panel, laminate, station_x)
            built.append((name, panel, stiffener))
        return laminate, built

    def test_rings_wire_without_error(self):
        """Each ring sweeps, wires its joint, and leaves the panel whole."""
        laminate, built = self._build_all_rings()
        for name, panel, stiffener in built:
            # The sweep produced a ring spanning the frame section.
            # The stiffener's Shape compound also carries the support
            # remainder (the regions the seat was cut away from), so the
            # ring's own axial extent is measured on the swept shell itself.
            swept = stiffener.Shape.childShapes()[0]
            self.assertAlmostEqual(
                swept.BoundBox.XLength, FRAME_SECTION, delta=0.5
            )
            self.assertNotIn("Invalid", stiffener.State)

            # The composite children exist and the joint validated.
            last_error = getattr(stiffener.Proxy, "last_error", None)
            self.assertIs(stiffener.Laminate, laminate)
            self.assertIsNone(
                last_error, f"{name}: composite wiring failed: {last_error}"
            )
            for suffix in ("_Web", "_Foot", "_CombinedLaminate"):
                self.assertIsNotNone(
                    self.doc.getObject(f"{name}{suffix}"),
                    f"{name}{suffix} missing (state={stiffener.State!r}, "
                    f"last_error={last_error!r})",
                )
            combined = self.doc.getObject(f"{name}_CombinedLaminate")
            self.assertNotIn("Invalid", combined.State)

            # The seat consumes the sleeve, so there is no remainder to
            # re-support onto: the panel keeps its support (an empty
            # remainder would orphan the joint's master side).
            remainder = self.doc.getObject(f"{name}_RemainderSupport")
            self.assertEqual(len(remainder.Shape.Faces), 0)
            self.assertGreater(panel.Support.Shape.Area, 0.0)

    def test_seat_cut_is_justified_by_the_geometry(self):
        """The ring's remainder is empty because the seat covers the sleeve.

        A ring's sleeve spans exactly the frame section — a plain loft whose
        boundaries are the seat's rows, which is what makes those rows
        sectionable and offsettable — so there is no region beside the seat
        to leave behind.  The remainder must be empty *for that reason*, not
        because a Boolean silently failed: the sleeve's area equals the
        seat's footprint, which is the check.  The complementary case — a
        support wider than the seat, where the margins must survive — is
        pinned by the plate fixture
        (test_stiffener_composite_shell.TestStiffenerJointStack.\\
        test_support_is_left_with_the_stiffener_cut_away) and measured by the
        boolean-cost diagnostic's wide-loft case.
        """
        _, built = self._build_all_rings()
        name, panel, _ = built[0]
        remainder = self.doc.getObject(f"{name}_RemainderSupport")
        self.assertEqual(len(remainder.Shape.Faces), 0)
        foot = self.doc.getObject(f"{name}_Foot")
        # Tolerance: an area identity across the fuse, on faces of ~1000 mm2.
        self.assertAlmostEqual(
            panel.Support.Shape.Area,
            foot.Support.Shape.Area,
            delta=1.0,
            msg="the support should be exactly the seat's footprint, so an "
            "empty remainder is the geometry's own answer",
        )

    def test_ring_recompute_is_stable(self):
        """A second recompute keeps the rings wired and the panels whole."""
        _, built = self._build_all_rings()
        supports = {name: panel.Support for name, panel, _ in built}
        foot_areas = {
            name: self.doc.getObject(f"{name}_Foot").Support.Shape.Area
            for name, _, _ in built
        }

        self.doc.recompute()

        for name, panel, stiffener in built:
            self.assertIs(panel.Support, supports[name])
            self.assertNotIn("Invalid", stiffener.State)
            combined = self.doc.getObject(f"{name}_CombinedLaminate")
            self.assertNotIn("Invalid", combined.State)
            # The captured base geometry still drives each sweep.
            self.assertAlmostEqual(
                self.doc.getObject(f"{name}_Foot").Support.Shape.Area,
                foot_areas[name],
                places=6,
            )
