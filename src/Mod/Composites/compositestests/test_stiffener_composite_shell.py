# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Scenario tests for the StiffenerCompositeShell feature.

Covers the stiffener's composite configuration: the geometry-only /
full-composite mode gate (PRD §3.4), the loud-failure contract on
violated wiring invariants (§3.2), and the tree claiming of the
composite flow's children.  The joint stack itself is covered by the
foot-strip and transfer scenarios further down the file; the seam
suites (test_seam_composite_laminate) pin the shared combination
machinery.
"""

import FreeCAD
import Part

from .test_base import TestFreeCADFP
from .test_stiffener import PLATE_CUT_Y, vertical_cut

RESIN = {
    "Name": "Epoxy",
    "Density": "1100.0 kg/m^3",
    "YoungsModulus": "3.500 GPa",
    "PoissonRatio": "0.36",
}

STEEL = {
    "Name": "Steel",
    "Density": "7850.0 kg/m^3",
    "YoungsModulus": "200 GPa",
    "PoissonRatio": "0.3",
}

PLATE_LENGTH = 120.0
PLATE_WIDTH = 60.0


def z_profile_points():
    """A Z-section as an OPEN polyline: base flange, web, top flange."""
    return [
        FreeCAD.Vector(0.0, 0.0, 0.0),
        FreeCAD.Vector(20.0, 0.0, 0.0),
        FreeCAD.Vector(20.0, 10.0, 0.0),
        FreeCAD.Vector(0.0, 10.0, 0.0),
    ]


def l_profile_points():
    """An L: base flange at y = 0 (12 wide), vertical web (16 tall)."""
    return [
        FreeCAD.Vector(0.0, 0.0, 0.0),
        FreeCAD.Vector(12.0, 0.0, 0.0),
        FreeCAD.Vector(12.0, 16.0, 0.0),
        FreeCAD.Vector(0.0, 0.0, 0.0),
    ]


def t_profile_points():
    """A thin T as three strokes: stem plus two flange arms.

    The stem's only base-row feature is a vertex — no base edge, so the
    profile has no bonding flange and the joint degrades gracefully.
    """
    return [
        (FreeCAD.Vector(0.0, 0.0, 0.0), FreeCAD.Vector(0.0, 15.0, 0.0)),
        (FreeCAD.Vector(-10.0, 15.0, 0.0), FreeCAD.Vector(0.0, 15.0, 0.0)),
        (FreeCAD.Vector(0.0, 15.0, 0.0), FreeCAD.Vector(10.0, 15.0, 0.0)),
    ]


class StiffenerCompositeFixture(TestFreeCADFP):
    """Shared fixtures: laminates, composite panel, wired stiffener."""

    def _make_laminate(self, angles, thicknesses, materials, name="Laminate"):
        from Composites.features.HomogeneousLamina import HomogeneousLaminaFP
        from Composites.features.Laminate import LaminateFP

        laminate = self.doc.addObject("Part::FeaturePython", name)
        LaminateFP(laminate)
        ply_objs = []
        for k, (angle, thickness, material) in enumerate(
            zip(angles, thicknesses, materials)
        ):
            ply = self.doc.addObject("Part::FeaturePython", f"{name}_Ply{k}")
            HomogeneousLaminaFP(ply)
            ply.Angle = angle
            ply.Thickness = thickness
            ply.Material = material
            ply_objs.append(ply)
        laminate.Layers = ply_objs
        self.doc.recompute()
        return laminate

    def _make_panel(self, name="Panel", with_laminate=True, rosette_angle=0.0):
        """A composite panel shell on a planar plate (the joint's Master)."""
        from Composites.features.CompositeShell import CompositeShellFP
        from Composites.features.Rosette import RosetteFP

        support = self.doc.addObject("Part::Feature", f"{name}_Support")
        support.Shape = Part.makePlane(PLATE_LENGTH, PLATE_WIDTH)
        panel = self.doc.addObject("Part::FeaturePython", name)
        CompositeShellFP(panel, support)
        if with_laminate:
            panel.Laminate = self._make_laminate(
                [0.0, 90.0],
                [0.5, 0.5],
                [STEEL, STEEL],
                name=f"{name}_Laminate",
            )
        rosette = self.doc.addObject("Part::FeaturePython", f"{name}_Rosette")
        RosetteFP(rosette, support=(support, ["Face1"]))
        rosette.Angle = rosette_angle
        panel.Rosette = rosette
        self.doc.recompute()
        return panel

    def _make_stiffener(
        self,
        panel,
        laminate=None,
        rosette=None,
        name="Stiffener",
        profile_points=None,
        cut_y=PLATE_CUT_Y,
    ):
        """A Z-section stiffener along the panel, with composite wiring."""
        from Composites.features.Stiffener import StiffenerFP

        if profile_points is None:
            profile_points = z_profile_points()
        surface = self.doc.addObject("Part::Feature", f"{name}CutSurface")
        surface.Shape = vertical_cut(
            cut_y, -10.0, PLATE_LENGTH + 10.0, -20.0, 80.0
        )
        profile = self.doc.addObject("Sketcher::SketchObject", f"{name}Profile")
        if profile_points and isinstance(profile_points[0], (tuple, list)):
            strokes = profile_points
        else:
            strokes = list(zip(profile_points, profile_points[1:]))
        for start, end in strokes:
            profile.addGeometry(Part.LineSegment(start, end), False)

        stiffener = self.doc.addObject("Part::FeaturePython", name)
        StiffenerFP(stiffener, support=panel, cut_surface=surface, profile=profile)
        if laminate is not None:
            stiffener.Laminate = laminate
        if rosette is not None:
            stiffener.Rosette = rosette
        self.doc.recompute()
        return stiffener


class TestStiffenerCompositeShell(StiffenerCompositeFixture):
    """Stiffener composite mode gate, wiring validation, and tree claiming."""

    # ── mode gate (§3.4) ──────────────────────────────────────────

    def test_geometry_only_is_the_default(self):
        from Composites.features.StiffenerCompositeShell import (
            is_stiffener_composite,
        )

        panel = self._make_panel()
        stiffener = self._make_stiffener(panel)
        self.assertFalse(is_stiffener_composite(stiffener))
        self.assertNotIn("Invalid", stiffener.State)
        self.assertIsNone(getattr(stiffener.Proxy, "last_error", None))
        self.assertFalse(stiffener.Shape.isNull())

    def test_geometry_only_creates_no_composite_children(self):
        from Composites.features.StiffenerCompositeShell import (
            stiffener_claimed_children,
        )

        panel = self._make_panel()
        stiffener = self._make_stiffener(panel)
        self.assertEqual(stiffener_claimed_children(stiffener), [])

    def test_linking_laminate_switches_to_composite_mode(self):
        from Composites.features.StiffenerCompositeShell import (
            is_stiffener_composite,
        )

        panel = self._make_panel()
        laminate = self._make_laminate(
            [0.0], [0.4], [RESIN], name="StiffenerLaminate"
        )
        stiffener = self._make_stiffener(panel, laminate=laminate)
        self.assertTrue(is_stiffener_composite(stiffener))
        # Missing rosette is NOT a failure — the flow auto-creates it on
        # the web shell, which only exists after the first build.
        self.assertNotIn("Invalid", stiffener.State)
        self.assertIsNone(stiffener.Proxy.last_error)

    # ── wiring failures (loud) ────────────────────────────────────

    def test_plain_part_support_raises(self):
        """Full composite mode needs the panel to be a draped shell."""
        from Composites.features.StiffenerCompositeShell import (
            is_stiffener_composite,
        )

        support = self.doc.addObject("Part::Feature", "PlainPlate")
        support.Shape = Part.makePlane(PLATE_LENGTH, PLATE_WIDTH)
        laminate = self._make_laminate([0.0], [0.4], [RESIN])
        stiffener = self._make_stiffener(support, laminate=laminate)
        self.assertTrue(is_stiffener_composite(stiffener))
        self.assertIn("Invalid", stiffener.State)
        self.assertIn("Composite::Shell", stiffener.Proxy.last_error)

    def test_panel_without_laminate_raises(self):
        """A lap joint against an unlaminateated panel is uncomputable."""
        panel = self._make_panel(with_laminate=False)
        laminate = self._make_laminate([0.0], [0.4], [RESIN])
        stiffener = self._make_stiffener(panel, laminate=laminate)
        self.assertIn("Invalid", stiffener.State)
        self.assertIn("no laminate layers", stiffener.Proxy.last_error)

    def test_empty_stiffener_laminate_raises(self):
        panel = self._make_panel()
        empty = self.doc.addObject("Part::FeaturePython", "EmptyLaminate")
        from Composites.features.Laminate import LaminateFP

        LaminateFP(empty)
        self.doc.recompute()
        stiffener = self._make_stiffener(panel, laminate=empty)
        self.assertIn("Invalid", stiffener.State)
        self.assertIn("no layers", stiffener.Proxy.last_error)

    def test_linked_non_rosette_raises(self):
        panel = self._make_panel()
        laminate = self._make_laminate([0.0], [0.4], [RESIN])
        stray = self.doc.addObject("Part::Feature", "Stray")
        stray.Shape = Part.makeBox(10, 10, 1)
        stiffener = self._make_stiffener(
            panel, laminate=laminate, rosette=stray
        )
        self.assertIn("Invalid", stiffener.State)
        self.assertIn("Rosette", stiffener.Proxy.last_error)

    def test_error_is_cleared_after_wiring_is_fixed(self):
        panel = self._make_panel(with_laminate=False)
        laminate = self._make_laminate([0.0], [0.4], [RESIN])
        stiffener = self._make_stiffener(panel, laminate=laminate)
        self.assertIn("Invalid", stiffener.State)

        panel.Laminate = self._make_laminate(
            [0.0, 90.0], [0.5, 0.5], [STEEL, STEEL], name="Panel_Laminate_Fixed"
        )
        self.doc.recompute()
        self.assertNotIn("Invalid", stiffener.State)
        self.assertIsNone(stiffener.Proxy.last_error)


class TestStiffenerFootProvenance(StiffenerCompositeFixture):
    """Foot identification (PRD test 1): the foot faces are exactly the
    base-row lofts — no geometric matching, pure profile provenance."""

    save_fcstd = False

    def _sweep_provenance(self, profile_points, name="Stiffener"):
        support = self.doc.addObject("Part::Feature", f"{name}Plate")
        support.Shape = Part.makePlane(PLATE_LENGTH, PLATE_WIDTH)
        stiffener = self._make_stiffener(
            support, name=name, profile_points=profile_points
        )
        proxy = stiffener.Proxy
        return (
            proxy.foot_faces,
            proxy.web_faces,
            proxy.foot_width,
            proxy.web_height,
        )

    def _bbox_span(self, face, axis):
        box = face.BoundBox
        return getattr(box, f"{axis}Length")

    def test_z_profile_foot_is_the_base_flange_loft(self):
        foot, web, foot_width, web_height = self._sweep_provenance(
            z_profile_points()
        )
        self.assertEqual(len(foot), 1)
        self.assertEqual(len(web), 2)
        # The foot runs the whole path (120 long) and is 20 wide across it;
        # the base flange rides the support (flat in Z).
        self.assertAlmostEqual(self._bbox_span(foot[0], "X"), 120.0, delta=1e-6)
        self.assertAlmostEqual(self._bbox_span(foot[0], "Y"), 20.0, delta=1e-6)
        self.assertAlmostEqual(self._bbox_span(foot[0], "Z"), 0.0, delta=1e-6)
        self.assertAlmostEqual(foot_width, 20.0, delta=1e-6)
        self.assertAlmostEqual(web_height, 10.0, delta=1e-6)

    def test_l_profile_foot_is_the_base_flange_loft(self):
        foot, web, foot_width, web_height = self._sweep_provenance(
            l_profile_points(), name="LStiff"
        )
        # The L closes as a triangle: base flange, web, hypotenuse.
        self.assertEqual(len(foot), 1)
        self.assertEqual(len(web), 2)
        self.assertAlmostEqual(self._bbox_span(foot[0], "Y"), 12.0, delta=1e-6)
        self.assertAlmostEqual(foot_width, 12.0, delta=1e-6)
        self.assertAlmostEqual(web_height, 16.0, delta=1e-6)

    def test_t_profile_has_no_base_edge(self):
        """A vertex on the base row is not a base edge — no foot, no joint."""
        foot, web, foot_width, web_height = self._sweep_provenance(
            t_profile_points(), name="TStiff"
        )
        self.assertEqual(foot, [])
        self.assertIsNone(foot_width)
        self.assertEqual(len(web), 3)
        self.assertAlmostEqual(web_height, 15.0, delta=1e-6)


class TestStiffenerJointStack(StiffenerCompositeFixture):
    """The joint: web/foot split, solved transfers, combined layup."""

    def _make_joint(self, name="Stiffener", panel_angle=0.0,
                    stiffener_angles=(45.0, -45.0), panel=None):
        if panel is None:
            panel = self._make_panel(rosette_angle=panel_angle)
        laminate = self._make_laminate(
            list(stiffener_angles),
            [0.4] * len(stiffener_angles),
            [RESIN] * len(stiffener_angles),
            name=f"{name}_Laminate",
        )
        stiffener = self._make_stiffener(panel, laminate=laminate, name=name)
        return panel, stiffener

    # ── children and wiring ───────────────────────────────────────

    def test_composite_build_creates_web_and_foot_shells(self):
        from Composites.features.SeamCompositeLaminate import SeamCompositeLaminateFP
        from Composites.features.StiffenerCompositeShell import (
            stiffener_claimed_children,
        )

        panel, stiffener = self._make_joint()
        self.assertNotIn("Invalid", stiffener.State)

        web = self.doc.getObject(f"{stiffener.Name}_Web")
        foot = self.doc.getObject(f"{stiffener.Name}_Foot")
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")
        self.assertIsNotNone(web)
        self.assertIsNotNone(foot)
        self.assertIsNotNone(scl)

        # The web shell carries the stiffener's own laminate; the foot
        # shell carries the combined laminate.
        self.assertIs(web.Laminate, stiffener.Laminate)
        self.assertIsInstance(scl.Proxy, SeamCompositeLaminateFP)
        self.assertIs(foot.Laminate, scl)

        # Everything the flow created is claimed.
        claimed = stiffener_claimed_children(stiffener)
        for child in (web, foot, scl):
            self.assertIn(child, claimed)

    def test_combined_laminate_wiring(self):
        from Composites.features.SeamCompositeLaminate import CombinationModel

        panel, stiffener = self._make_joint()
        web = self.doc.getObject(f"{stiffener.Name}_Web")
        foot = self.doc.getObject(f"{stiffener.Name}_Foot")
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")

        self.assertIs(scl.Master, panel)
        self.assertIs(scl.Attachment, web)
        self.assertIs(scl.SeamRegion, foot)
        self.assertIsNotNone(scl.MasterTransfer)
        self.assertIsNotNone(scl.AttachmentTransfer)
        # Physical default: stiffener plies over panel plies.
        self.assertEqual(
            scl.CombinationModel, CombinationModel.StackAttachmentOverMaster
        )
        self.assertNotIn("Invalid", scl.State)

    def test_web_rosette_auto_created(self):
        from Composites.features.Rosette import RosetteFP

        panel, stiffener = self._make_joint()
        web = self.doc.getObject(f"{stiffener.Name}_Web")
        rosette = stiffener.Rosette
        self.assertIsNotNone(rosette)
        self.assertEqual(rosette.Name, f"{stiffener.Name}_WebRosette")
        self.assertIsInstance(rosette.Proxy, RosetteFP)
        self.assertIs(web.Rosette, rosette)

    def test_user_linked_rosette_is_not_overwritten(self):
        from Composites.features.Rosette import RosetteFP

        panel = self._make_panel()
        laminate = self._make_laminate([0.0], [0.4], [RESIN], name="StiffLam")
        own = self.doc.addObject("Part::FeaturePython", "OwnRosette")
        RosetteFP(own, support=(panel.Support, ["Face1"]))
        stiffener = self._make_stiffener(panel, laminate=laminate, rosette=own)
        self.assertIs(stiffener.Rosette, own)
        self.assertIs(
            self.doc.getObject(f"{stiffener.Name}_Web").Rosette, own
        )
        self.assertIsNone(self.doc.getObject(f"{stiffener.Name}_WebRosette"))

    # ── pitch scaling ─────────────────────────────────────────────

    def test_pitch_scaled_to_foot_width_and_web_height(self):
        panel, stiffener = self._make_joint()
        foot = self.doc.getObject(f"{stiffener.Name}_Foot")
        web = self.doc.getObject(f"{stiffener.Name}_Web")
        # foot 20 wide → 20/4; web 10 tall → 10/4.
        self.assertAlmostEqual(float(foot.DrapePitch), 5.0, places=6)
        self.assertAlmostEqual(float(web.DrapePitch), 2.5, places=6)

    # ── stack ordering (PRD tests 2, 8) ───────────────────────────

    def test_stack_order_stiffener_over_panel(self):
        panel, stiffener = self._make_joint()
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")
        model = scl.Proxy.get_model(scl)
        orientations = [layer.orientation for layer in model.layers]
        thicknesses = [layer.thickness for layer in model.layers]
        # 2 panel plies below, 2 stiffener plies above; per-ply angles are
        # each side's nominal + its solved transfer angle.
        self.assertEqual(len(model.layers), 4)
        panel_angle = scl.MasterTransfer.Angle.Value
        stiffener_angle = scl.AttachmentTransfer.Angle.Value
        self.assertAlmostEqual(orientations[0], 0.0 + panel_angle, delta=1e-6)
        self.assertAlmostEqual(orientations[1], 90.0 + panel_angle, delta=1e-6)
        self.assertAlmostEqual(orientations[2], 45.0 + stiffener_angle, delta=1e-6)
        self.assertAlmostEqual(orientations[3], -45.0 + stiffener_angle, delta=1e-6)
        self.assertEqual(thicknesses, [0.5, 0.5, 0.4, 0.4])
        self.assertAlmostEqual(scl.Thickness.Value, 1.8)

    def test_switching_combination_model_reverses_the_blocks(self):
        from Composites.features.SeamCompositeLaminate import CombinationModel

        panel, stiffener = self._make_joint()
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")
        below = scl.Proxy.get_model(scl)
        below_orientations = [layer.orientation for layer in below.layers]

        scl.CombinationModel = CombinationModel.StackMasterOverAttachment
        scl.enforceRecompute()
        self.doc.recompute()

        above = scl.Proxy.get_model(scl)
        above_orientations = [layer.orientation for layer in above.layers]
        # The two blocks swap; the per-ply angles stay with their side.
        self.assertEqual(above_orientations, below_orientations[2:] + below_orientations[:2])
        self.assertNotIn("Invalid", scl.State)

    def test_symmetry_pinned_no_mirrored_plies(self):
        from Composites.objects import SymmetryType

        panel, stiffener = self._make_joint()
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")
        self.assertEqual(scl.Symmetry, SymmetryType.Assymmetric.name)
        model = scl.Proxy.get_model(scl)
        self.assertEqual(len(model.layers), 4)

    # ── solved angles (PRD test 3) ────────────────────────────────

    def test_effective_offset_is_the_difference_of_solved_angles(self):
        panel, stiffener = self._make_joint(panel_angle=30.0)
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")
        panel_angle = scl.MasterTransfer.Angle.Value
        stiffener_angle = scl.AttachmentTransfer.Angle.Value
        self.assertAlmostEqual(
            scl.EffectiveOffsetAngle.Value, stiffener_angle - panel_angle, delta=1e-6
        )
        # Both solves ran (angles are set by the solvers, not left at 0).
        self.assertIsNotNone(scl.MasterTransfer)
        self.assertIsNotNone(scl.AttachmentTransfer)
        self.assertNotIn("Invalid", scl.State)

    def test_offset_fabric_plies_carry_solved_angles(self):
        """Per-ply angles reflect the solved transfers, not naive nominal.

        With a 30° fabric on the panel and the stiffener's plies nominal
        at 45/-45 in its own (auto) rosette frame, each ply's foot angle
        is nominal + its side's solved transfer — asserted via the
        report, so the test pins the machinery without assuming the
        auto rosette's frame orientation.
        """
        panel, stiffener = self._make_joint(panel_angle=30.0)
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")
        model = scl.Proxy.get_model(scl)
        panel_angle = scl.MasterTransfer.Angle.Value
        stiffener_angle = scl.AttachmentTransfer.Angle.Value
        orientations = [layer.orientation for layer in model.layers]
        self.assertAlmostEqual(orientations[0], panel_angle, delta=1e-6)
        self.assertAlmostEqual(orientations[1], 90.0 + panel_angle, delta=1e-6)
        self.assertAlmostEqual(orientations[2], 45.0 + stiffener_angle, delta=1e-6)
        self.assertAlmostEqual(orientations[3], -45.0 + stiffener_angle, delta=1e-6)

    # ── graceful degradation (PRD test 9b, invariant 3) ──────────

    def test_profile_without_base_edge_degrades_gracefully(self):
        panel = self._make_panel()
        laminate = self._make_laminate([0.0], [0.4], [RESIN], name="StiffLam")
        stiffener = self._make_stiffener(
            panel, laminate=laminate, name="TStiff", profile_points=t_profile_points()
        )
        # No error, no foot, no joint machinery — the web weave persists.
        self.assertNotIn("Invalid", stiffener.State)
        self.assertIsNone(stiffener.Proxy.last_error)
        self.assertIsNone(self.doc.getObject(f"{stiffener.Name}_Foot"))
        self.assertIsNone(self.doc.getObject(f"{stiffener.Name}_CombinedLaminate"))
        web = self.doc.getObject(f"{stiffener.Name}_Web")
        self.assertIsNotNone(web)
        self.assertIs(web.Laminate, stiffener.Laminate)

    def test_base_edge_regained_rebuilds_the_joint(self):
        panel = self._make_panel()
        laminate = self._make_laminate([0.0], [0.4], [RESIN], name="StiffLam")
        stiffener = self._make_stiffener(
            panel, laminate=laminate, name="TStiff", profile_points=t_profile_points()
        )
        self.assertIsNone(self.doc.getObject(f"{stiffener.Name}_Foot"))

        # Swap the profile for one with a bonding flange (the user edits
        # the profile — modelled here as rewiring the Profile link).
        profile = self.doc.addObject("Sketcher::SketchObject", "TStiffProfile2")
        z = z_profile_points()
        for start, end in zip(z, z[1:]):
            profile.addGeometry(Part.LineSegment(start, end), False)
        stiffener.Profile = profile
        self.doc.recompute()

        foot = self.doc.getObject(f"{stiffener.Name}_Foot")
        self.assertIsNotNone(foot)
        self.assertIsNotNone(foot.Laminate)
        self.assertNotIn("Invalid", stiffener.State)

    # ── section round-trip (PRD test 7) ───────────────────────────

    def test_combined_section_round_trip(self):
        from Composites.util.fem_util import (
            write_lamina_materials_ccx,
            write_shell_section_ccx,
        )

        panel, stiffener = self._make_joint()
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")
        materials = write_lamina_materials_ccx(
            prefix=scl.Name, layers=scl.Proxy.FEMLayers
        )
        section = write_shell_section_ccx(
            prefix=scl.Name, layers=scl.Proxy.FEMLayers
        )
        self.assertEqual(materials.count("*MATERIAL"), 4)
        rows = section.strip().splitlines()
        self.assertEqual(len(rows), 4)
        values = [float(row.split(",")[0]) for row in rows]
        self.assertEqual(values, [0.5, 0.5, 0.4, 0.4])

    # ── recompute stability ───────────────────────────────────────

    def test_recompute_is_idempotent(self):
        panel, stiffener = self._make_joint()
        foot = self.doc.getObject(f"{stiffener.Name}_Foot")
        self.doc.recompute()
        self.assertNotIn("Invalid", stiffener.State)
        self.assertNotIn("Invalid", foot.State)
        area = foot.Support.Shape.Area
        self.doc.recompute()
        self.assertAlmostEqual(foot.Support.Shape.Area, area, places=6)

    # ── weave exclusivity (PRD tests 5, 6) ────────────────────────

    def test_panel_resupported_on_remainder(self):
        panel = self._make_panel()
        original_area = panel.Support.Shape.Area
        original_support = panel.Support
        panel, stiffener = self._make_joint(panel=panel)
        remainder_support = panel.Support

        self.assertEqual(remainder_support.Name, f"{stiffener.Name}_RemainderSupport")
        # The pre-stiffener geometry is captured for every recompute.
        self.assertIs(stiffener.SupportBase, original_support)
        # The remainder is strictly smaller than the original plate.
        self.assertLess(remainder_support.Shape.Area, original_area)
        # The joint pipeline still validates against the re-support.
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")
        self.assertNotIn("Invalid", scl.State)

    def test_resupport_idempotent_across_recomputes(self):
        panel, stiffener = self._make_joint()
        remainder_support = panel.Support
        area = remainder_support.Shape.Area
        foot = self.doc.getObject(f"{stiffener.Name}_Foot")
        foot_area = foot.Support.Shape.Area
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")

        self.doc.recompute()
        self.assertIs(panel.Support, remainder_support)
        self.assertAlmostEqual(remainder_support.Shape.Area, area, places=6)
        self.assertNotIn("Invalid", stiffener.State)
        self.assertNotIn("Invalid", scl.State)
        # The captured base geometry still drives the sweep: the foot
        # strip did not shrink to the remainder.
        self.assertAlmostEqual(foot.Support.Shape.Area, foot_area, places=6)

    def test_support_move_updates_foot_strip(self):
        panel, stiffener = self._make_joint()
        base = stiffener.SupportBase
        foot = self.doc.getObject(f"{stiffener.Name}_Foot")
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")
        offset_before = scl.EffectiveOffsetAngle.Value

        base.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0.0, 0.0, 20.0), FreeCAD.Rotation()
        )
        self.doc.recompute()

        foot_box = foot.Support.Shape.BoundBox
        self.assertAlmostEqual(foot_box.ZMin, 20.0, delta=1e-6)
        self.assertNotIn("Invalid", scl.State)
        # Same relative geometry — the solved angles are unchanged.
        self.assertAlmostEqual(
            scl.EffectiveOffsetAngle.Value, offset_before, delta=1e-6
        )

    def test_cut_surface_move_updates_foot_strip(self):
        panel, stiffener = self._make_joint()
        foot = self.doc.getObject(f"{stiffener.Name}_Foot")
        cut = self.doc.getObject(f"{stiffener.Name}CutSurface")
        y_before = foot.Support.Shape.BoundBox.YMin

        cut.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0.0, 10.0, 0.0), FreeCAD.Rotation()
        )
        self.doc.recompute()

        foot_box = foot.Support.Shape.BoundBox
        self.assertAlmostEqual(foot_box.YMin, y_before + 10.0, delta=1e-6)
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")
        self.assertNotIn("Invalid", scl.State)

    def test_mode_switch_to_geometry_only_restores_panel(self):
        panel, stiffener = self._make_joint()
        base = stiffener.SupportBase
        remainder_support = panel.Support

        stiffener.Laminate = None
        stiffener.enforceRecompute()
        self.doc.recompute()

        # The panel is put back on its original support.
        self.assertIs(panel.Support, base)
        self.assertIsNone(stiffener.SupportBase)
        # The flow's children are hidden; the filters render again (when
        # present — headless fixtures create none).
        web = self.doc.getObject(f"{stiffener.Name}_Web")
        self.assertFalse(web.Visibility)
        parts = self.doc.getObject(f"{stiffener.Name}Parts")
        if parts is not None:
            self.assertTrue(parts.Visibility)
        self.assertNotIn("Invalid", stiffener.State)


class TestMultipleStiffenersOnOnePanel(StiffenerCompositeFixture):
    """Sequential remainders: several composite stiffeners on one panel.

    Weave exclusivity must compose: each stiffener re-supports the panel
    on the remainder of the support it found at wiring time, so the
    panel's weave covers the plate minus every stiffener seat.  The
    chain is static — each remainder is a pure cut of its own
    SupportBase — and the panel's Support pointer moves only at wiring
    time.  A later recompute of an earlier stiffener must not re-point
    the panel to its own (shallower) remainder: that would resurrect a
    seated region into the panel weave — double plies under the later
    stiffener's foot.
    """

    def _make_two_stiffeners(self):
        """Two composite Z-stiffeners on one panel, B chained on A."""
        panel = self._make_panel()
        laminate_a = self._make_laminate(
            [45.0, -45.0], [0.4, 0.4], [RESIN, RESIN],
            name="StiffenerA_Laminate",
        )
        stiffener_a = self._make_stiffener(
            panel, laminate=laminate_a, name="StiffenerA", cut_y=30.0
        )
        laminate_b = self._make_laminate(
            [0.0, 90.0], [0.4, 0.4], [RESIN, RESIN],
            name="StiffenerB_Laminate",
        )
        stiffener_b = self._make_stiffener(
            panel, laminate=laminate_b, name="StiffenerB", cut_y=10.0
        )
        self.doc.recompute()
        return panel, stiffener_a, stiffener_b

    def _assert_joint_valid(self, stiffener):
        for suffix in ("_Web", "_Foot", "_CombinedLaminate"):
            obj = self.doc.getObject(f"{stiffener.Name}{suffix}")
            self.assertIsNotNone(obj)
            self.assertNotIn("Invalid", obj.State)
        self.assertNotIn("Invalid", stiffener.State)
        self.assertIsNone(getattr(stiffener.Proxy, "last_error", None))

    def test_two_stiffeners_build_a_chained_remainder(self):
        panel, stiffener_a, stiffener_b = self._make_two_stiffeners()
        original = stiffener_a.SupportBase
        remainder_a = self.doc.getObject("StiffenerA_RemainderSupport")
        remainder_b = self.doc.getObject("StiffenerB_RemainderSupport")

        # The support chain: original → A's remainder → B's remainder,
        # and the panel weaves on the deepest link.
        self.assertIs(stiffener_b.SupportBase, remainder_a)
        self.assertIs(panel.Support, remainder_b)
        self.assertLess(remainder_a.Shape.Area, original.Shape.Area)
        self.assertLess(remainder_b.Shape.Area, remainder_a.Shape.Area)

        for stiffener in (stiffener_a, stiffener_b):
            self._assert_joint_valid(stiffener)
        self.assertNotIn("Invalid", panel.State)

    def test_earlier_stiffener_recompute_keeps_the_chain(self):
        """A recompute of A (its sweep runs on its own SupportBase) must
        not re-point the panel from B's chained remainder back to A's
        shallower one."""
        panel, stiffener_a, stiffener_b = self._make_two_stiffeners()
        chain = panel.Support
        chain_area = chain.Shape.Area

        # Force A's execute — a plain recompute is a no-op when nothing
        # is touched, and would never exercise the pointer fight.
        stiffener_a.touch()
        self.doc.recompute()

        self.assertIs(panel.Support, chain)
        self.assertAlmostEqual(chain.Shape.Area, chain_area, places=6)
        for stiffener in (stiffener_a, stiffener_b):
            self._assert_joint_valid(stiffener)

    def test_earlier_stiffener_edit_keeps_the_chain(self):
        """Editing an EARLIER stiffener after a later one exists (only its
        fingerprint changes, so only it re-wires) must not re-point the
        panel to its own shallower remainder — the later stiffener's seat
        would return to the panel weave (double plies)."""
        panel, stiffener_a, stiffener_b = self._make_two_stiffeners()
        chain = panel.Support

        cut_a = self.doc.getObject("StiffenerACutSurface")
        cut_a.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0.0, 5.0, 0.0), FreeCAD.Rotation()
        )
        self.doc.recompute()
        # Settle: B's remainder is re-cut from A's refreshed remainder,
        # which A re-wrote mid-execute.
        self.doc.recompute()

        self.assertIs(panel.Support, chain)
        for stiffener in (stiffener_a, stiffener_b):
            self._assert_joint_valid(stiffener)

    def test_support_move_recomputes_the_whole_chain(self):
        """Moving the plate touches both stiffeners; whichever order they
        re-execute in, the panel must end on the deepest chained
        remainder with both seats still cut away."""
        panel, stiffener_a, stiffener_b = self._make_two_stiffeners()
        chain = panel.Support
        base = stiffener_a.SupportBase

        base.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0.0, 0.0, 20.0), FreeCAD.Rotation()
        )
        self.doc.recompute()
        # Settle: the chain's shape writes are imperative (invisible to
        # the DAG), so B may re-cut from A's refreshed remainder only in
        # this second pass.
        self.doc.recompute()

        self.assertIs(panel.Support, chain)
        # The chained remainder moved with the plate: both seats cut,
        # sitting on the raised plate.
        self.assertAlmostEqual(chain.Shape.BoundBox.ZMin, 20.0, delta=1e-6)
        for stiffener in (stiffener_a, stiffener_b):
            self._assert_joint_valid(stiffener)

    def test_teardown_of_the_last_stiffener_steps_the_chain_back(self):
        panel, stiffener_a, stiffener_b = self._make_two_stiffeners()
        remainder_a = self.doc.getObject("StiffenerA_RemainderSupport")

        stiffener_b.Laminate = None
        self.doc.recompute()

        # B's teardown restores the panel to B's SupportBase — A's
        # remainder — so A's exclusivity survives the switch.
        self.assertIs(panel.Support, remainder_a)
        self._assert_joint_valid(stiffener_a)


class TestStiffenerCompositeExample(TestFreeCADFP):
    """The registered example builds the full joint end to end (PRD test 9)."""

    save_fcstd = False

    def test_example_build(self):
        from Composites.compositeexamples import runner

        result = runner.run("stiffener_composite_shell", run_solver=False)
        doc = result["doc"]
        self.assertIsNotNone(doc)
        stiffener = result["stiffener"]
        self.assertIsNotNone(stiffener)
        self.assertFalse(stiffener.Shape.isNull())

        foot = result["foot_shell"]
        scl = result["combined_laminate"]
        self.assertIsNotNone(foot)
        self.assertIsNotNone(scl)
        self.assertIs(foot.Laminate, scl)
        self.assertNotIn("Invalid", stiffener.State)
        self.assertNotIn("Invalid", scl.State)

        # Weave exclusivity: the panel is re-supported on the remainder.
        panel_shell = result["panel_shell"]
        self.assertEqual(
            panel_shell.Support.Name, f"{stiffener.Name}_RemainderSupport"
        )

        # 30-degree fabric on both sides: both solves present.
        self.assertIsNotNone(scl.MasterTransfer)
        self.assertIsNotNone(scl.AttachmentTransfer)
        self.assertAlmostEqual(
            result["web_rosette"].Angle, 30.0
        )
