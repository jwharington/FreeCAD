# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for StiffenerFP."""

import os
import tempfile
import unittest

import FreeCAD
import Part

from .test_base import TestFreeCADFP


class TestStiffenerFP(TestFreeCADFP):
    """Tests for StiffenerFP."""

    def _make_support(self, name, shape):
        support = self.doc.addObject("Part::Feature", name)
        support.Shape = shape
        return support

    def _make_sketch(self, name, points):
        sketch = self.doc.addObject("Sketcher::SketchObject", name)
        for start, end in zip(points, points[1:]):
            sketch.addGeometry(Part.LineSegment(start, end), False)
        return sketch

    def _build_stiffener(
        self,
        support,
        plan_points,
        profile_points,
        *,
        mirror_x=False,
        mirror_y=False,
        direction=None,
        name="Stiffener",
    ):
        from Composites.features.Stiffener import StiffenerFP

        plan = self._make_sketch(f"{name}Plan", plan_points)
        profile = self._make_sketch(f"{name}Profile", profile_points)
        stiffener = self.doc.addObject("Part::FeaturePython", name)
        StiffenerFP(stiffener, support=support, plan=plan, profile=profile)
        stiffener.MirrorX = mirror_x
        stiffener.MirrorY = mirror_y
        if direction is not None:
            stiffener.Direction = direction
        self.doc.recompute()
        return stiffener, support, plan, profile

    def _build_stiffener_3d_plan(
        self,
        support,
        plan_wire,
        profile_points,
        *,
        direction=None,
        name="Stiffener",
    ):
        """Build a stiffener whose plan is a 3D wire (not a 2D sketch).

        A 2D sketch forces z=0, which is wrong for a circumferential plan on a
        curved surface at mid-height. A Part::Feature holding a 3D wire
        preserves the plan's z.
        """
        from Composites.features.Stiffener import StiffenerFP

        plan = self.doc.addObject("Part::Feature", f"{name}Plan")
        plan.Shape = plan_wire
        profile = self._make_sketch(f"{name}Profile", profile_points)
        stiffener = self.doc.addObject("Part::FeaturePython", name)
        StiffenerFP(stiffener, support=support, plan=plan, profile=profile)
        if direction is not None:
            stiffener.Direction = direction
        self.doc.recompute()
        return stiffener, support, plan, profile

    def _plan_points(self):
        return [
            FreeCAD.Vector(10.0, 10.0, 0.0),
            FreeCAD.Vector(80.0, 10.0, 0.0),
        ]

    def _bent_plan_points(self):
        return [
            FreeCAD.Vector(10.0, 10.0, 0.0),
            FreeCAD.Vector(50.0, 10.0, 0.0),
            FreeCAD.Vector(50.0, 30.0, 0.0),
        ]

    def _rect_profile_points(self):
        return [
            FreeCAD.Vector(0.0, 0.0, 0.0),
            FreeCAD.Vector(0.0, 10.0, 0.0),
            FreeCAD.Vector(20.0, 10.0, 0.0),
            FreeCAD.Vector(20.0, 0.0, 0.0),
            FreeCAD.Vector(0.0, 0.0, 0.0),
        ]

    def _asymmetric_profile_points(self):
        return [
            FreeCAD.Vector(0.0, 0.0, 0.0),
            FreeCAD.Vector(0.0, 16.0, 0.0),
            FreeCAD.Vector(4.0, 16.0, 0.0),
            FreeCAD.Vector(4.0, 4.0, 0.0),
            FreeCAD.Vector(12.0, 4.0, 0.0),
            FreeCAD.Vector(12.0, 0.0, 0.0),
            FreeCAD.Vector(0.0, 0.0, 0.0),
        ]

    def _z_profile_points(self):
        """A Z-section as an OPEN polyline: bottom flange, web, top flange.

        The bottom flange (y=0) is the surface edge; the web and top flange
        are the free edges swept along the plan. No closing edge — a closing
        edge would create a spurious wall and collapse the Z into a box.
        """
        return [
            FreeCAD.Vector(0.0, 0.0, 0.0),
            FreeCAD.Vector(20.0, 0.0, 0.0),
            FreeCAD.Vector(20.0, 10.0, 0.0),
            FreeCAD.Vector(0.0, 10.0, 0.0),
        ]

    def _circumferential_plan_points(self, radius=40.0, z=60.0, segments=8):
        """An arc ON the curved surface, tangential to the axis (annular frame).

        Points lie on the cylinder/cone surface at height ``z``, sweeping a
        quarter turn in theta in [45, 135] deg — mid-face, away from the
        slice seams. This is the plan a circumferential stiffener (annular
        frame) is swept along.
        """
        import math

        return [
            FreeCAD.Vector(
                radius * math.cos(math.radians(45.0 + 90.0 * i / segments)),
                radius * math.sin(math.radians(45.0 + 90.0 * i / segments)),
                z,
            )
            for i in range(segments + 1)
        ]

    def _tangential_plan_points(self, outboard=50.0, z=60.0):
        """A straight plan line, tangential to the axis, outboard and centered.

        The line runs along X at y=``outboard`` (outside the surface) and
        height ``z``, with its midpoint at (0, outboard, z) — directly
        outboard of the near-face point (0, radius, z). This is the plan a
        circumferential stiffener is swept along: the tool projects it
        radially onto the surface.
        """
        return [
            FreeCAD.Vector(-10.0, outboard, z),
            FreeCAD.Vector(10.0, outboard, z),
        ]

    def assert_valid_stiffener(self, stiffener):
        self.assertIsNotNone(stiffener.Shape)
        self.assertFalse(stiffener.Shape.isNull())
        self.assertEqual(stiffener.Shape.ShapeType, "Compound")

    def test_basic_creation_on_planar_support(self):
        support = self._make_support("PlanarSupport", Part.makePlane(120.0, 60.0))
        stiffener, support, plan, profile = self._build_stiffener(
            support,
            self._plan_points(),
            self._asymmetric_profile_points(),
        )

        self.assert_valid_stiffener(stiffener)
        self.assertFalse(support.Visibility)
        self.assertFalse(plan.Visibility)
        self.assertFalse(profile.Visibility)

    @unittest.skip("Known issue: MirrorX on planar support produces null edges due to projection failure")
    @unittest.skip("Known issue: MirrorX on planar support produces null edges due to projection failure")
    def test_mirror_x_on_planar_support(self):
        support = self._make_support("PlanarSupport", Part.makePlane(120.0, 60.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            self._plan_points(),
            self._rect_profile_points(),
            mirror_x=True,
        )

        self.assert_valid_stiffener(stiffener)
        self.assertTrue(stiffener.MirrorX)
        self.assertFalse(stiffener.MirrorY)

    def test_mirror_y_on_planar_support(self):
        support = self._make_support("PlanarSupport", Part.makePlane(120.0, 60.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            self._plan_points(),
            self._rect_profile_points(),
            mirror_y=True,
        )

        self.assert_valid_stiffener(stiffener)
        self.assertFalse(stiffener.MirrorX)
        self.assertTrue(stiffener.MirrorY)

    def test_cylindrical_support_with_rect_profile(self):
        support = self._make_support("CylinderSupport", Part.makeCylinder(40.0, 120.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            self._plan_points(),
            self._rect_profile_points(),
        )

        self.assert_valid_stiffener(stiffener)

    def test_conical_support_with_oblique_direction(self):
        support = self._make_support("ConeSupport", Part.makeCone(45.0, 20.0, 120.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            self._plan_points(),
            self._rect_profile_points(),
            direction=FreeCAD.Vector(0.0, 1.0, 1.0),
        )

        self.assert_valid_stiffener(stiffener)
        self.assertEqual(stiffener.Direction, FreeCAD.Vector(0.0, 1.0, 1.0))

    def test_stiffener_geometry_is_non_degenerate(self):
        # The compound must have non-zero extent in every direction.
        support = self._make_support("PlanarSupport", Part.makePlane(120.0, 60.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            self._plan_points(),
            self._rect_profile_points(),
        )

        bb = stiffener.Shape.BoundBox
        self.assertGreater(bb.XLength, 0.0)
        self.assertGreater(bb.YLength, 0.0)
        self.assertGreater(bb.ZLength, 0.0)

    def test_z_section_on_plate(self):
        """A Z-section profile swept along a straight plan on a planar plate.

        The Z is an open polyline (bottom flange, web, top flange — no closing
        edge), so the stiffener is the web + top flange (an L), distinct from
        the closed rect box.
        """
        support = self._make_support("PlanarSupport", Part.makePlane(120.0, 60.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            self._plan_points(),
            self._z_profile_points(),
        )

        self.assert_valid_stiffener(stiffener)
        bb = stiffener.Shape.BoundBox
        self.assertGreater(bb.XLength, 0.0)
        self.assertGreater(bb.YLength, 0.0)
        self.assertGreater(bb.ZLength, 0.0)

    def test_z_section_on_cylindrical_shell(self):
        """A Z-section swept circumferentially on a cylindrical shell panel.

        The plan is a 3D wire arc ON the shell surface at mid-height (z=60),
        tangential to the axis — the way an annular-frame stiffener is swept.
        KNOWN FAILURE: the tool's makeParallelProjection cannot offset the
        profile radially on a curved surface — the web-base edge degenerates
        and the loft fails. This test asserts the correct geometry and fails,
        documenting the limitation.
        """
        cyl = Part.makeCylinder(
            40.0, 120.0, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 270.0
        )
        curved = [f for f in cyl.Faces if "Cylinder" in str(f.Surface)]
        shell = Part.makeShell([curved[0]])
        support = self._make_support("CylShellSupport", shell)
        # Plan line: tangential to the axis (along X), outboard (y=50 > 40),
        # centered at (0,50,60) — directly outboard of the near-face point.
        plan_wire = Part.makePolygon(
            self._tangential_plan_points(outboard=50.0, z=60.0)
        )
        stiffener, _, _, _ = self._build_stiffener_3d_plan(
            support,
            plan_wire,
            self._z_profile_points(),
            direction=FreeCAD.Vector(0.0, -1.0, 0.0),
        )

        self.assert_valid_stiffener(stiffener)
        bb = stiffener.Shape.BoundBox
        # The plan is at z=60 and the profile is 10 tall; a correct annular
        # frame spans a small z-range around 60. The broken projection sweeps
        # the full cylinder height (120).
        self.assertLess(
            bb.ZLength,
            50.0,
            f"Z-section on cylindrical shell should span a small z-range, got {bb.ZLength:.1f} (projection swept the full height)",
        )

    def test_z_section_on_conical_panel(self):
        """A Z-section swept circumferentially on a conical panel.

        The plan is a 3D wire arc ON the cone surface at mid-height,
        tangential to the axis. KNOWN FAILURE: same curved-surface projection
        limitation as the cylindrical shell. Asserts correct geometry and
        fails.
        """
        cone = Part.makeCone(
            45.0, 20.0, 120.0, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 270.0
        )
        curved = [f for f in cone.Faces if "Cone" in str(f.Surface)]
        panel = Part.makeShell([curved[0]])
        support = self._make_support("ConePanelSupport", panel)
        # The cone radius at mid-height (z=60) is 32.5 (linear from 45 to 20).
        # Plan line: tangential to the axis, outboard (y=42.5 > 32.5), centered.
        plan_wire = Part.makePolygon(
            self._tangential_plan_points(outboard=42.5, z=60.0)
        )
        stiffener, _, _, _ = self._build_stiffener_3d_plan(
            support,
            plan_wire,
            self._z_profile_points(),
            direction=FreeCAD.Vector(0.0, -1.0, 0.0),
        )

        self.assert_valid_stiffener(stiffener)
        bb = stiffener.Shape.BoundBox
        self.assertLess(
            bb.ZLength,
            50.0,
            f"Z-section on conical panel should span a small z-range, got {bb.ZLength:.1f} (projection swept the full height)",
        )

    def test_example_build(self):
        """The registered stiffener example builds valid compounds.

        Each stiffener lives in its own document. The plate cases must be
        valid compounds; the curved cases are known failures (documented).
        """
        from Composites.compositeexamples import runner

        result = runner.run("stiffener", run_solver=False)
        # Working plate cases.
        for key in ("rect_plate", "z_plate"):
            shape = result[key]["shape"]
            self.assertFalse(shape.isNull(), f"{key} should be non-null")
            self.assertEqual(shape.ShapeType, "Compound", f"{key} should be a compound")
        # Curved cases are documented failures.
        self.assertFalse(result["z_cylinder_shell"]["ok"])
        self.assertFalse(result["z_cone_panel"]["ok"])
        self.assertTrue(result["z_cylinder_shell"]["error"])
        self.assertTrue(result["z_cone_panel"]["error"])

    @unittest.skip("Known issue: Shell support with bent plan produces null input shape during projection")
    def test_shell_support_with_bent_plan(self):
        support = self._create_shell("ShellSupport")
        stiffener, _, _, _ = self._build_stiffener(
            support,
            self._bent_plan_points(),
            self._rect_profile_points(),
        )

        self.assert_valid_stiffener(stiffener)

    def test_save_load_round_trip(self):
        support = self._make_support("SaveLoadSupport", Part.makePlane(120.0, 60.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            self._plan_points(),
            self._asymmetric_profile_points(),
        )

        filepath = os.path.join(tempfile.gettempdir(), "stiffener_round_trip.FCStd")
        try:
            self._save_document(filepath)
            loaded_doc = self._load_document(filepath)
            try:
                loaded_stiffener = loaded_doc.getObject(stiffener.Name)
                self.assertIsNotNone(loaded_stiffener)
                self.assertFalse(loaded_stiffener.Shape.isNull())
            finally:
                try:
                    loaded_doc.close()
                except Exception:
                    pass
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
