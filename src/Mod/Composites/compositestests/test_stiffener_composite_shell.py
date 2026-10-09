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

import math

import FreeCAD
import Part

from Composites.features.StiffenerCompositeShell import chain_base_is_orphaned

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

# A solved transfer must land the attachment's fibre on the master's line;
# anything above this is a different layup, not a rounding difference.
WARP_AGREEMENT_DEG = 1.0


def warp_axis(shell):
    """The shell's fibre direction in GLOBAL coordinates, or None.

    The rosette LCS X-axis is the warp the drape seeds from
    (``NextDrapeBackend._frame_seed``), so it is the direction the shell
    actually carries — read in world axes, not in the support face's own
    frame, which is what lets two surfaces with opposite normals be
    compared at all.
    """
    rosette = getattr(shell, "Rosette", None)
    lcs = getattr(rosette, "LocalCoordinateSystem", None)
    if lcs is None:
        return None
    return lcs.Placement.Rotation.multVec(FreeCAD.Vector(1.0, 0.0, 0.0))


def line_offset_deg(a, b):
    """Undirected angle between two fibre lines, in degrees.

    A warp is an undirected line: identical and 180 deg apart are the same
    layup, perpendicular is not.
    """
    cos = abs(a.dot(b)) / (a.Length * b.Length)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def azimuth_deg(v):
    """Azimuth of a global vector about world Z, for failure messages."""
    return math.degrees(math.atan2(v.y, v.x))


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

    def _make_laminate(
        self, angles, thicknesses, materials, name="Laminate", isotropic=False
    ):
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
        if isotropic:
            laminate.Symmetry = "Even"
            laminate.IsotropicEquivalent = True
        self.doc.recompute()
        return laminate

    def _make_panel(
        self,
        name="Panel",
        with_laminate=True,
        rosette_angle=0.0,
        isotropic=False,
        with_rosette=True,
        plate=None,
        pitch=None,
    ):
        """A composite panel shell on a planar plate (the joint's Master).

        ``pitch`` must be set before the first recompute: under the
        common drape the panel solves once here, and a later DrapePitch
        write would not re-solve it.
        """
        from Composites.features.CompositeShell import CompositeShellFP
        from Composites.features.Rosette import RosetteFP

        support = self.doc.addObject("Part::Feature", f"{name}_Support")
        support.Shape = plate if plate is not None else Part.makePlane(
            PLATE_LENGTH, PLATE_WIDTH
        )
        panel = self.doc.addObject("Part::FeaturePython", name)
        CompositeShellFP(panel, support)
        if with_laminate:
            if isotropic:
                # A QI panel declaration needs evenly spaced carbon plies
                # (isotropic-material plies hit a pre-existing factor-2 in
                # the isotropic compliance branch and are not usable here).
                qi_angles = [0.0, 45.0, -45.0, 90.0]
                panel.Laminate = self._make_laminate(
                    qi_angles,
                    [0.5] * len(qi_angles),
                    [TestQuasiIsotropicStiffener.CARBON] * len(qi_angles),
                    name=f"{name}_Laminate",
                    isotropic=True,
                )
            else:
                panel.Laminate = self._make_laminate(
                    [0.0, 90.0],
                    [0.5, 0.5],
                    [STEEL, STEEL],
                    name=f"{name}_Laminate",
                )
        if with_rosette:
            rosette = self.doc.addObject("Part::FeaturePython", f"{name}_Rosette")
            RosetteFP(rosette, support=(support, ["Face1"]))
            rosette.Angle = rosette_angle
            panel.Rosette = rosette
        if pitch is not None:
            panel.DrapePitch = pitch
        # This fixture asserts on coverage_ratio. Coverage geometry is a
        # diagnostic and is off unless asked for, so ask for it here rather
        # than have every production drape pay for it.
        panel.DrapeAnalyzeCoverage = True
        self.doc.recompute()
        return panel

    def _panel_coverage(self, panel):
        """The panel drape's measured coverage ratio (None when unmeasured)."""
        import json

        raw = getattr(panel, "DrapeDiagnostics", None)
        if not raw:
            return None
        return json.loads(raw).get("coverage_ratio")

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

    def test_foot_inherits_the_panel_warp_not_its_mirror(self):
        """M2: the foot strip must carry the panel's fibre.

        The foot is the same physical surface as the panel, but its
        support face normal is opposite.  A transfer solve that measures
        each side about its own frame normal mirrors the attachment, so
        the foot lands at -30 deg against a +30 deg panel — and because
        the rosette frame seeds the drape, the foot strip then drapes the
        other way.
        """
        panel, stiffener = self._make_joint(panel_angle=30.0)
        foot = self.doc.getObject(f"{stiffener.Name}_Foot")
        self.assertIsNotNone(foot, "the Z-profile must produce a foot")
        panel_dir = warp_axis(panel)
        foot_dir = warp_axis(foot)
        offset = line_offset_deg(panel_dir, foot_dir)
        self.assertLess(
            offset,
            WARP_AGREEMENT_DEG,
            f"foot warp is {offset:.2f} deg off the panel warp",
        )

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

    # ── the common drape (lap joint; was: weave exclusivity) ──────

    def test_panel_keeps_support_and_drapes_once(self):
        """The panel drapes once, before the stiffeners, and never again.

        Lap joint (owner decision 2026-09-30): the skin weave runs
        continuously UNDER the stiffener's foot — one common drape per
        panel, solved on the full support.  Wiring a stiffener must not
        re-point the panel's support onto the seat remainder and must
        not re-drape it: the seat's coverage gap and the island seeding
        problem were both artefacts of the re-drape.
        """
        panel = self._make_panel()
        original_support = panel.Support
        common_coverage = self._panel_coverage(panel)
        panel, stiffener = self._make_joint(panel=panel)

        # The panel's support pointer never moved.
        self.assertIs(panel.Support, original_support)
        # The pre-stiffener geometry is still captured for the sweep.
        self.assertIs(stiffener.SupportBase, original_support)
        # The seat remainder is still recorded — the joint's master-side
        # surface (its cut edges are what the foot shares) — but it is
        # bookkeeping now, not the panel's support.
        remainder = self.doc.getObject(f"{stiffener.Name}_RemainderSupport")
        self.assertIsNotNone(remainder)
        self.assertLess(remainder.Shape.Area, original_support.Shape.Area)
        # The drape is the common one: not re-solved by the wiring.
        self.assertEqual(self._panel_coverage(panel), common_coverage)
        # The joint pipeline still validates.
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")
        self.assertNotIn("Invalid", scl.State)

    def test_panel_keeps_its_support_when_the_seat_leaves_no_remainder(self):
        """A seat that covers the whole panel leaves nothing to record.

        The remainder record may be empty; the panel's support is never
        re-pointed either way, and the sweep still ran on the captured
        base geometry.
        """
        plate = Part.makePlane(
            PLATE_LENGTH, 20.0, FreeCAD.Vector(0.0, PLATE_CUT_Y, 0.0)
        )
        panel = self._make_panel(plate=plate)
        original_support = panel.Support
        panel, stiffener = self._make_joint(panel=panel)

        # The remainder is empty: the flange (20 wide) spans the plate.
        remainder = self.doc.getObject(f"{stiffener.Name}_RemainderSupport")
        self.assertEqual(len(remainder.Shape.Faces), 0)
        # The panel kept its support, and the sweep still ran on the
        # captured base geometry.
        self.assertIs(panel.Support, original_support)
        self.assertIs(stiffener.SupportBase, original_support)
        self.assertGreater(panel.Support.Shape.Area, 0.0)
        # The joint wires against the living panel geometry.
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")
        self.assertIsNotNone(scl)
        self.assertNotIn("Invalid", stiffener.State)
        self.assertNotIn("Invalid", scl.State)

    def test_joint_record_idempotent_across_recomputes(self):
        panel, stiffener = self._make_joint()
        original_support = panel.Support
        remainder = self.doc.getObject(f"{stiffener.Name}_RemainderSupport")
        area = remainder.Shape.Area
        foot = self.doc.getObject(f"{stiffener.Name}_Foot")
        foot_area = foot.Support.Shape.Area
        scl = self.doc.getObject(f"{stiffener.Name}_CombinedLaminate")

        self.doc.recompute()
        # The panel stays on its own support — a recompute neither moves
        # the pointer nor re-drapes the common weave.
        self.assertIs(panel.Support, original_support)
        self.assertAlmostEqual(remainder.Shape.Area, area, places=6)
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

        stiffener.Laminate = None
        stiffener.enforceRecompute()
        self.doc.recompute()

        # The panel was never re-pointed (common drape); the teardown's
        # restore is a no-op that leaves it exactly where it was.
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
    """Several composite stiffeners on one panel under the common drape.

    Lap joint (owner decision 2026-09-30): the panel drapes once, before
    any stiffener, and its weave runs continuously under every foot.
    Wiring a stiffener records only that stiffener's own seat remainder
    — the joint's master-side surface, whose cut edges are what the foot
    shares — and never moves the panel's support pointer or re-drapes
    the panel.  Each remainder is a pure cut of the panel's support by
    its own stiffener's seat.
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

    def test_two_stiffeners_record_their_seats_one_drape(self):
        panel, stiffener_a, stiffener_b = self._make_two_stiffeners()
        original = stiffener_a.SupportBase
        remainder_a = self.doc.getObject("StiffenerA_RemainderSupport")
        remainder_b = self.doc.getObject("StiffenerB_RemainderSupport")

        # Each stiffener recorded its own seat remainder — a pure cut of
        # the panel's support by that stiffener's seat — and neither
        # moved the panel's pointer off the original support.
        self.assertIs(stiffener_a.SupportBase, original)
        self.assertIs(stiffener_b.SupportBase, original)
        self.assertIs(panel.Support, original)
        self.assertLess(remainder_a.Shape.Area, original.Shape.Area)
        self.assertLess(remainder_b.Shape.Area, original.Shape.Area)

        for stiffener in (stiffener_a, stiffener_b):
            self._assert_joint_valid(stiffener)
        self.assertNotIn("Invalid", panel.State)

    def test_earlier_stiffener_recompute_leaves_the_panel_alone(self):
        """A recompute of A (its sweep runs on its own SupportBase)
        neither re-drapes the panel nor moves its pointer."""
        panel, stiffener_a, stiffener_b = self._make_two_stiffeners()
        original = panel.Support
        coverage = self._panel_coverage(panel)

        # Force A's execute — a plain recompute is a no-op when nothing
        # is touched, and would never exercise the wiring.
        stiffener_a.touch()
        self.doc.recompute()

        self.assertIs(panel.Support, original)
        self.assertEqual(self._panel_coverage(panel), coverage)
        for stiffener in (stiffener_a, stiffener_b):
            self._assert_joint_valid(stiffener)

    def test_earlier_stiffener_edit_leaves_the_panel_alone(self):
        """Editing an EARLIER stiffener after a later one exists (only its
        fingerprint changes, so only it re-wires) re-records A's own seat
        and leaves the panel's pointer and drape untouched."""
        panel, stiffener_a, stiffener_b = self._make_two_stiffeners()
        original = panel.Support

        cut_a = self.doc.getObject("StiffenerACutSurface")
        cut_a.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0.0, 5.0, 0.0), FreeCAD.Rotation()
        )
        self.doc.recompute()
        # Settle: the remainder writes are imperative (invisible to the
        # DAG), so give the document a second pass.
        self.doc.recompute()

        self.assertIs(panel.Support, original)
        for stiffener in (stiffener_a, stiffener_b):
            self._assert_joint_valid(stiffener)

    def test_support_move_updates_both_joints(self):
        """Moving the plate touches both stiffeners; whichever order they
        re-execute in, both recorded seats are re-cut on the raised
        plate, and the panel stays on its (moved) support."""
        panel, stiffener_a, stiffener_b = self._make_two_stiffeners()
        original = panel.Support
        base = stiffener_a.SupportBase

        base.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0.0, 0.0, 20.0), FreeCAD.Rotation()
        )
        self.doc.recompute()
        # Settle: the remainder writes are imperative (invisible to the
        # DAG), so B may re-record only in this second pass.
        self.doc.recompute()

        self.assertIs(panel.Support, original)
        # Both recorded seats moved with the plate.
        for name in ("StiffenerA_RemainderSupport", "StiffenerB_RemainderSupport"):
            self.assertAlmostEqual(
                self.doc.getObject(name).Shape.BoundBox.ZMin, 20.0, delta=1e-6
            )

    def test_teardown_of_a_stiffener_leaves_the_panel_alone(self):
        panel, stiffener_a, stiffener_b = self._make_two_stiffeners()
        original = panel.Support

        stiffener_b.Laminate = None
        self.doc.recompute()

        # The teardown never moved the panel (common drape): it stays on
        # its own support, and A's joint survives the switch.
        self.assertIs(panel.Support, original)
        self._assert_joint_valid(stiffener_a)

    def test_deleting_a_stiffener_leaves_the_panel_alone(self):
        """Deleting A cannot orphan anything: B's SupportBase is the
        panel's own support (never a remainder under the common drape),
        so B's next execute re-records B's seat and nothing else moves."""
        panel, stiffener_a, stiffener_b = self._make_two_stiffeners()
        original = panel.Support
        remainder_b = self.doc.getObject("StiffenerB_RemainderSupport")
        seated_area = remainder_b.Shape.Area

        self.doc.removeObject("StiffenerA")
        stiffener_b.touch()
        self.doc.recompute()

        self.assertIs(stiffener_b.SupportBase, original)
        self.assertIs(panel.Support, original)
        self.assertFalse(chain_base_is_orphaned(stiffener_b))
        self._assert_joint_valid(stiffener_b)

    def test_deleting_stiffener_and_its_remainder_leaves_too(self):
        """Same scenario as the GUI delete (which removes claimed
        children): A and its remainder are both gone — B's SupportBase
        still resolves (the panel's own support) and B stays valid."""
        panel, stiffener_a, stiffener_b = self._make_two_stiffeners()
        original = panel.Support

        self.doc.removeObject("StiffenerA_RemainderSupport")
        self.doc.removeObject("StiffenerA")
        stiffener_b.touch()
        self.doc.recompute()

        self.assertIs(stiffener_b.SupportBase, original)
        self.assertIs(panel.Support, original)
        self._assert_joint_valid(stiffener_b)

    def test_deleting_the_last_stiffener_leaves_the_first_valid(self):
        """Deleting B leaves A's joint valid and the panel untouched."""
        panel, stiffener_a, stiffener_b = self._make_two_stiffeners()
        original = panel.Support

        self.doc.removeObject("StiffenerB")
        stiffener_a.touch()
        self.doc.recompute()

        self.assertIs(panel.Support, original)
        self._assert_joint_valid(stiffener_a)
        self.assertNotIn("Invalid", panel.State)


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

        # Common drape: the panel's support was never re-pointed — no
        # remainder owns the panel's weave.
        panel_shell = result["panel_shell"]
        self.assertFalse(
            getattr(panel_shell.Support, "Name", "").endswith("_RemainderSupport")
        )

        # 30-degree fabric on both sides: both solves present.
        self.assertIsNotNone(scl.MasterTransfer)
        self.assertIsNotNone(scl.AttachmentTransfer)
        self.assertAlmostEqual(
            result["web_rosette"].Angle, 30.0
        )


class TestQuasiIsotropicStiffener(StiffenerCompositeFixture):
    """QI composition through the stiffener flow (D8, §7.4)."""

    QI_ANGLES = [0.0, 45.0, -45.0, 90.0]
    CARBON = {
        "Name": "Carbon",
        "Density": "1750.0 kg/m^3",
        "PoissonRatioXY": "0.27",
        "PoissonRatioXZ": "0.27",
        "PoissonRatioYZ": "0.45",
        "ShearModulusXY": "5000 MPa",
        "ShearModulusXZ": "5000 MPa",
        "ShearModulusYZ": "3500 MPa",
        "YoungsModulusX": "135 GPa",
        "YoungsModulusY": "9.5 GPa",
        "YoungsModulusZ": "9.5 GPa",
    }

    def _make_qi_laminate(self, name="QILaminate"):
        return self._make_laminate(
            self.QI_ANGLES,
            [0.5] * len(self.QI_ANGLES),
            [self.CARBON] * len(self.QI_ANGLES),
            name=name,
            isotropic=True,
        )

    def _qi_children(self, stiffener_name="Stiffener"):
        doc = self.doc
        get = doc.getObject
        return (
            get(f"{stiffener_name}"),
            get(f"{stiffener_name}_Web"),
            get(f"{stiffener_name}_Foot"),
            get(f"{stiffener_name}_CombinedLaminate"),
        )

    def _assert_all_valid(self, *features):
        for obj in features:
            if obj is not None:
                self.assertNotIn("Invalid", obj.State)

    def test_qi_web_needs_no_rosette_and_no_drape(self):
        panel = self._make_panel()
        stiffener = self._make_stiffener(
            panel, laminate=self._make_qi_laminate(name="WebLam")
        )
        self._assert_all_valid(panel, *self._qi_children())
        # No web rosette is auto-created for a QI web laminate (D8).
        self.assertIsNone(self.doc.getObject("Stiffener_WebRosette"))
        self.assertIsNone(stiffener.Rosette)
        web = self.doc.getObject("Stiffener_Web")
        self.assertIsNone(web.Proxy._backend)
        self.assertFalse(web.DrapeValid)

    def test_qi_stiffener_qi_panel_foot_orientation_free(self):
        panel = self._make_panel(
            name="QIPanel", isotropic=True, with_rosette=False
        )
        stiffener = self._make_stiffener(
            panel, laminate=self._make_qi_laminate(name="WebLam")
        )
        self._assert_all_valid(panel, *self._qi_children())
        scl = self.doc.getObject("Stiffener_CombinedLaminate")
        # Derived read-only flag: both sides declared → combined QI.
        self.assertTrue(scl.IsotropicEquivalent)
        layers = scl.Proxy.FEMLayers
        self.assertEqual(len(layers), 1)
        self.assertNotIn("YoungsModulusX", layers[0].material)
        # Neither transfer exists — both sides are orientation-free.
        self.assertIsNone(self.doc.getObject("Stiffener_PanelFootTransfer"))
        self.assertIsNone(
            self.doc.getObject("Stiffener_StiffenerFootTransfer")
        )
        foot = self.doc.getObject("Stiffener_Foot")
        self.assertIsNone(foot.Proxy._backend)
        self.assertFalse(foot.DrapeValid)

    def test_qi_stiffener_draped_panel_keeps_panel_machinery(self):
        panel = self._make_panel()
        stiffener = self._make_stiffener(
            panel, laminate=self._make_qi_laminate(name="WebLam")
        )
        self._assert_all_valid(panel, *self._qi_children())
        scl = self.doc.getObject("Stiffener_CombinedLaminate")
        # Mixed combination stays draped (derived flag false).
        self.assertFalse(scl.IsotropicEquivalent)
        # The panel-side foot transfer is kept; the analysis transfer for
        # the QI web is meaningless and skipped.
        self.assertIsNotNone(
            self.doc.getObject("Stiffener_PanelFootTransfer")
        )
        self.assertIsNone(
            self.doc.getObject("Stiffener_StiffenerFootTransfer")
        )
        report = dict(scl.SideAngleReport)
        self.assertNotEqual(report["master_angle_at_seam"], "n/a")
        self.assertEqual(report["attachment_angle_at_seam"], "n/a")

    def test_joint_surfaces_carry_one_global_fibre_orientation(self):
        """One uniform panel + a QI stiffener: the shapes must agree globally.

        Narrow case: a single flat panel draped at a uniform 30 deg, then a
        quasi-isotropic stiffener set into it.  That makes three shapes —
        master (the panel remainder), foot (the base strip) and attachment
        (the web).  The foot strip is the SAME physical plane as the panel,
        so the only logical orientation is one fibre direction in global
        coordinates across all three: identical, or 180 deg apart.  The web
        is QI and carries no frame at all, which is asserted below so its
        exemption is a measured fact rather than an untested hole.

        It fails today because the foot's support face normal is opposite
        the panel's and ``TransferRosette._axis_angle`` measures each side
        about its OWN normal: the mirrored warp then reads the same signed
        angle, the mod-pi fold makes the residual exactly zero, and the
        solve settles 60 deg off the panel it is supposed to inherit.
        """
        panel = self._make_panel(rosette_angle=30.0)
        stiffener = self._make_stiffener(
            panel, laminate=self._make_qi_laminate(name="WebLam")
        )
        self._assert_all_valid(panel, *self._qi_children())
        foot = self.doc.getObject(f"{stiffener.Name}_Foot")
        web = self.doc.getObject(f"{stiffener.Name}_Web")
        self.assertIsNotNone(foot, "the Z-profile must produce a foot")
        self.assertIsNotNone(web, "the Z-profile must produce a web")

        # The attachment side is orientation-free (QI): no rosette, no
        # drape, so it cannot disagree with the panel's fibre.
        self.assertIsNone(warp_axis(web))

        panel_dir = warp_axis(panel)
        foot_dir = warp_axis(foot)
        self.assertIsNotNone(panel_dir)
        self.assertIsNotNone(foot_dir, "the foot must inherit a frame")
        offset = line_offset_deg(panel_dir, foot_dir)
        self.assertLess(
            offset,
            WARP_AGREEMENT_DEG,
            f"master and foot disagree by {offset:.2f} deg in global "
            f"coordinates (master {azimuth_deg(panel_dir):+.2f} deg, "
            f"foot {azimuth_deg(foot_dir):+.2f} deg)",
        )
