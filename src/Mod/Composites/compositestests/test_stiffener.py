# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for the Stiffener feature: the intersection path and the swept shell."""

import math
import os
import tempfile
import unittest

import FreeCAD
import Part

from .test_base import TestFreeCADFP


def horizontal_cut(side, y_min, z):
    """A square cut surface lying in a z-plane, covering y from y_min upward."""
    return Part.makePlane(side, side, FreeCAD.Vector(-side / 2.0, y_min, z), FreeCAD.Vector(0, 0, 1))


def centred_rectangle(center, normal, side):
    """A square face of `side`, centred on `center`, with the given normal.

    Built from a placed plane rather than a polygon face: the section boolean
    rejects faces built from a polygon wire.
    """
    rotation = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), normal)
    face = Part.makePlane(side, side)
    corner = rotation.multVec(FreeCAD.Vector(side / 2.0, side / 2.0, 0))
    face.Placement = FreeCAD.Placement(center - corner, rotation)
    return face


def vertical_cut(y, x_min, x_max, z_min, z_max):
    """A planar cut surface with normal +y, spanning x and z, normal pointing +y."""
    corners = [
        FreeCAD.Vector(x_min, y, z_max),
        FreeCAD.Vector(x_max, y, z_max),
        FreeCAD.Vector(x_max, y, z_min),
        FreeCAD.Vector(x_min, y, z_min),
    ]
    return Part.Face(Part.makePolygon(corners + corners[:1]))


def open_cylinder(radius, height, angle=360.0):
    """The cylinder's lateral face alone — an open panel, not a capped solid."""
    solid = Part.makeCylinder(
        radius, height, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), angle
    )
    return next(face for face in solid.Faces if isinstance(face.Surface, Part.Cylinder))


def open_cone(base_radius, top_radius, height):
    """The cone's lateral face alone — an open panel, not a capped solid."""
    solid = Part.makeCone(base_radius, top_radius, height)
    return next(face for face in solid.Faces if isinstance(face.Surface, Part.Cone))


def stiffener_part(stiffener):
    """The stiffener's own faces — the first child of its combined shape."""
    return stiffener.Shape.childShapes()[0]


PLATE_CUT_Y = 30.0


def side_of(shape, axis, plane):
    """Which side of the coordinate `plane` the shape's centre lies on."""
    box = getattr(shape, "Shape", shape).BoundBox
    centre = (getattr(box, f"{axis}Min") + getattr(box, f"{axis}Max")) / 2.0
    return centre > plane


def folded_shell():
    """A shell folded along one edge, and a cut surface crossing both faces.

    The cut plane is tilted about all three axes so it meets each face in a
    line and the two lines meet on the fold, which bends the path there.
    """
    floor = Part.makePlane(100.0, 60.0)
    wall = Part.makePlane(100.0, 60.0)
    wall.Placement = FreeCAD.Placement(FreeCAD.Vector(0.0, 60.0, 0.0), FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 90))
    return Part.makeShell([floor, wall]), (FreeCAD.Vector(50.0, 45.0, 15.0), FreeCAD.Vector(1, 1, 1), 220.0)


def radius_span(shape, samples=9):
    """Nearest and farthest distance of `shape` from the z axis."""
    radii = [
        math.hypot(point.x, point.y) for edge in shape.Edges for point in edge.discretize(samples)
    ]
    return min(radii), max(radii)


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
        cut_surface,
        profile_points,
        *,
        mirror_x=False,
        mirror_y=False,
        name="Stiffener",
    ):
        from Composites.features.Stiffener import StiffenerFP

        surface = self._make_support(f"{name}CutSurface", cut_surface)
        profile = self._make_sketch(f"{name}Profile", profile_points)
        stiffener = self.doc.addObject("Part::FeaturePython", name)
        StiffenerFP(stiffener, support=support, cut_surface=surface, profile=profile)
        stiffener.MirrorX = mirror_x
        stiffener.MirrorY = mirror_y
        self.doc.recompute()
        return stiffener, support, surface, profile

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
        """A Z-section as an OPEN polyline: base flange, web, top flange.

        The base flange (y=0) rides the support surface; the web and top flange
        are free edges. No closing edge — one would collapse the Z into a box.
        """
        return [
            FreeCAD.Vector(0.0, 0.0, 0.0),
            FreeCAD.Vector(20.0, 0.0, 0.0),
            FreeCAD.Vector(20.0, 10.0, 0.0),
            FreeCAD.Vector(0.0, 10.0, 0.0),
        ]

    def assert_valid_stiffener(self, stiffener):
        self.assertIsNotNone(stiffener.Shape)
        self.assertFalse(stiffener.Shape.isNull())
        self.assertEqual(stiffener.Shape.ShapeType, "Compound")

    def test_basic_creation_on_planar_support(self):
        support = self._make_support("PlanarSupport", Part.makePlane(120.0, 60.0))
        stiffener, support, surface, profile = self._build_stiffener(
            support,
            vertical_cut(PLATE_CUT_Y, -10.0, 130.0, -20.0, 80.0),
            self._asymmetric_profile_points(),
        )

        self.assert_valid_stiffener(stiffener)
        self.assertTrue(support.Visibility)
        self.assertFalse(surface.Visibility)
        self.assertFalse(profile.Visibility)

    def _plate_stiffener(self, name, **mirror):
        support = self._make_support(f"{name}Support", Part.makePlane(120.0, 60.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            vertical_cut(PLATE_CUT_Y, -10.0, 130.0, -20.0, 80.0),
            self._rect_profile_points(),
            name=name,
            **mirror,
        )
        return stiffener

    def test_mirror_x_flips_the_flange_across_the_cut_surface(self):
        """The flange runs along the support on the other side of the cut."""
        as_built = self._plate_stiffener("AsBuilt")
        mirrored = self._plate_stiffener("Mirrored", mirror_x=True)

        self.assert_valid_stiffener(mirrored)
        self.assertTrue(mirrored.MirrorX)
        self.assertFalse(mirrored.MirrorY)
        self.assertNotEqual(
            side_of(stiffener_part(as_built), "Y", PLATE_CUT_Y),
            side_of(stiffener_part(mirrored), "Y", PLATE_CUT_Y),
        )

    def test_mirror_y_flips_the_shell_across_the_support(self):
        """The height direction reverses, so the shell stands the other way up."""
        as_built = self._plate_stiffener("AsBuilt")
        mirrored = self._plate_stiffener("Mirrored", mirror_y=True)

        self.assert_valid_stiffener(mirrored)
        self.assertFalse(mirrored.MirrorX)
        self.assertTrue(mirrored.MirrorY)
        self.assertNotEqual(side_of(as_built, "Z", 0.0), side_of(mirrored, "Z", 0.0))

    def test_ring_stiffener_on_a_cylinder(self):
        """A cut surface across a cylinder sweeps a closed ring frame."""
        radius, height, cut_z = 40.0, 120.0, 60.0
        support = self._make_support("CylinderSupport", open_cylinder(radius, height))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            horizontal_cut(120.0, -60.0, cut_z),
            self._rect_profile_points(),
        )

        self.assert_valid_stiffener(stiffener)
        nearest, farthest = radius_span(stiffener_part(stiffener))
        self.assertAlmostEqual(nearest, radius, delta=1e-6)
        self.assertAlmostEqual(farthest, radius + 10.0, delta=1e-6)
        self.assertAlmostEqual(stiffener_part(stiffener).BoundBox.ZLength, 20.0, delta=1e-6)

    def test_support_is_left_with_the_stiffener_cut_away(self):
        """The remainders are the support split around the stiffener's seat."""
        radius, height, cut_z = 40.0, 120.0, 60.0
        support = self._make_support("CylinderSupport", open_cylinder(radius, height))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            horizontal_cut(120.0, -60.0, cut_z),
            self._rect_profile_points(),
        )

        remainders = stiffener.Proxy.remainders
        self.assertEqual(len(remainders), 2)
        low, high = sorted(remainders, key=lambda remainder: remainder.BoundBox.ZMin)
        self.assertAlmostEqual(low.BoundBox.ZMin, 0.0, delta=1e-6)
        self.assertAlmostEqual(low.BoundBox.ZMax, cut_z, delta=1e-6)
        self.assertAlmostEqual(high.BoundBox.ZMin, cut_z + 20.0, delta=1e-6)
        self.assertAlmostEqual(high.BoundBox.ZMax, height, delta=1e-6)
        for remainder in remainders:
            self.assertTrue(remainder.isValid())

    def test_remainder_filter_tracks_the_stiffener(self):
        """Moving the cut surface moves the remainder the filter shows."""
        from Composites.features.Stiffener import add_stiffener_filters

        support = self._make_support("CylinderSupport", open_cylinder(40.0, 120.0))
        stiffener, _, surface, _ = self._build_stiffener(
            support,
            horizontal_cut(120.0, -60.0, 60.0),
            self._rect_profile_points(),
        )
        remainder_filter = add_stiffener_filters(self.doc, stiffener)["remainder"]

        self.doc.recompute()
        bands = sorted(face.BoundBox.ZMin for face in remainder_filter.Shape.Faces)
        self.assertAlmostEqual(bands[1], 80.0, delta=1e-6)

        surface.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 10), FreeCAD.Rotation())
        self.doc.recompute()
        bands = sorted(face.BoundBox.ZMin for face in remainder_filter.Shape.Faces)
        self.assertAlmostEqual(bands[1], 90.0, delta=1e-6)

    def test_oblique_cut_surface_on_a_cone(self):
        """An oblique cut surface still sweeps the whole section it cuts."""
        support = self._make_support("ConeSupport", open_cone(45.0, 20.0, 120.0))
        slanted = centred_rectangle(
            FreeCAD.Vector(0.0, 0.0, 60.0), FreeCAD.Vector(0.0, 0.6, 0.8), 160.0
        )

        stiffener, _, _, _ = self._build_stiffener(support, slanted, self._rect_profile_points())

        self.assert_valid_stiffener(stiffener)
        nearest, farthest = radius_span(stiffener.Shape)
        self.assertGreater(farthest, nearest)

    def test_stiffener_geometry_is_non_degenerate(self):
        support = self._make_support("PlanarSupport", Part.makePlane(120.0, 60.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            vertical_cut(PLATE_CUT_Y, -10.0, 130.0, -20.0, 80.0),
            self._rect_profile_points(),
        )

        bounding_box = stiffener.Shape.BoundBox
        self.assertGreater(bounding_box.XLength, 0.0)
        self.assertGreater(bounding_box.YLength, 0.0)
        self.assertGreater(bounding_box.ZLength, 0.0)

    def test_z_section_on_plate(self):
        """A Z-section profile swept along a straight path on a planar plate.

        The Z is an open polyline (base flange, web, top flange), so the
        stiffener is the web + top flange (an L), distinct from the closed box.
        """
        support = self._make_support("PlanarSupport", Part.makePlane(120.0, 60.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            vertical_cut(PLATE_CUT_Y, -10.0, 130.0, -20.0, 80.0),
            self._z_profile_points(),
        )

        self.assert_valid_stiffener(stiffener)
        self.assertAlmostEqual(stiffener.Shape.BoundBox.ZLength, 10.0, delta=1e-6)

    def test_z_section_ring_on_a_cylinder(self):
        """A Z-section swept as an annular frame on a cylindrical shell."""
        radius, height, cut_z = 40.0, 120.0, 60.0
        support = self._make_support("CylinderSupport", open_cylinder(radius, height))

        stiffener, _, _, _ = self._build_stiffener(
            support,
            horizontal_cut(120.0, -60.0, cut_z),
            self._z_profile_points(),
        )

        self.assert_valid_stiffener(stiffener)
        nearest, farthest = radius_span(stiffener.Shape)
        self.assertAlmostEqual(nearest, radius, delta=1e-6)
        self.assertAlmostEqual(farthest, radius + 10.0, delta=1e-6)

    def test_z_section_on_a_cylindrical_panel(self):
        """A Z-section swept around part of a cylindrical shell panel."""
        radius, height = 40.0, 120.0
        panel = Part.makeShell([open_cylinder(radius, height, angle=270.0)])
        support = self._make_support("CylPanelSupport", panel)

        stiffener, _, _, _ = self._build_stiffener(
            support,
            horizontal_cut(120.0, -60.0, 60.0),
            self._z_profile_points(),
        )

        self.assert_valid_stiffener(stiffener)
        nearest, farthest = radius_span(stiffener.Shape)
        self.assertAlmostEqual(nearest, radius, delta=1e-6)
        self.assertAlmostEqual(farthest, radius + 10.0, delta=1e-6)

    def test_path_bends_over_a_folded_shell(self):
        """A cut surface crossing two faces of a shell gives a bent path."""
        folded, bent_cut = folded_shell()
        support = self._make_support("FoldedShell", folded)

        stiffener, _, _, _ = self._build_stiffener(
            support, centred_rectangle(*bent_cut), self._rect_profile_points()
        )

        self.assert_valid_stiffener(stiffener)

    def test_stiffener_runs_on_every_path_of_a_split_support(self):
        """A support in two separate pieces gets a stiffener run on each piece."""
        support = self._make_support(
            "TwoPlateSupport",
            Part.makeCompound(
                [
                    Part.makePlane(40.0, 40.0),
                    Part.makePlane(40.0, 40.0, FreeCAD.Vector(0.0, 0.0, 60.0)),
                ]
            ),
        )

        stiffener, _, _, _ = self._build_stiffener(
            support,
            vertical_cut(20.0, -10.0, 50.0, -20.0, 80.0),
            self._rect_profile_points(),
        )

        self.assert_valid_stiffener(stiffener)
        self.assertEqual(len(stiffener_part(stiffener).Faces), 8)

    def test_cut_surface_clear_of_the_support_raises(self):
        """An intersecting surface that misses the support is reported, not crashed."""
        support = self._make_support("CylinderSupport", open_cylinder(40.0, 120.0))
        profile = self._make_sketch("MissProfile", self._rect_profile_points())
        surface = self._make_support("MissCutSurface", horizontal_cut(120.0, -60.0, 200.0))
        stiffener = self.doc.addObject("Part::FeaturePython", "MissStiffener")

        from Composites.features.Stiffener import StiffenerFP

        StiffenerFP(stiffener, support=support, cut_surface=surface, profile=profile)
        self.doc.recompute()

        self.assertIn("Invalid", stiffener.State)
        self.assertTrue(stiffener.Shape.isNull())

    def test_a_solid_support_is_rejected(self):
        """The stiffener is laid on a shell; a solid support is refused."""
        support = self._make_support("SolidSupport", Part.makeCylinder(40.0, 120.0))
        profile = self._make_sketch("SolidProfile", self._rect_profile_points())
        surface = self._make_support("SolidCutSurface", horizontal_cut(120.0, -60.0, 60.0))
        stiffener = self.doc.addObject("Part::FeaturePython", "SolidStiffener")

        from Composites.features.Stiffener import StiffenerFP

        StiffenerFP(stiffener, support=support, cut_surface=surface, profile=profile)
        self.doc.recompute()

        self.assertIn("Invalid", stiffener.State)
        self.assertTrue(stiffener.Shape.isNull())

    def test_example_build(self):
        """The registered stiffener example builds one document per example."""
        from Composites.compositeexamples import runner

        result = runner.run("stiffener", run_solver=False)
        self.assertIsNotNone(result["doc"])
        for key, case in result["cases"].items():
            self.assertFalse(case["shape"].isNull(), f"{key} should be non-null")
            self.assertEqual(case["shape"].ShapeType, "Compound", f"{key} should be a compound")
        documents = [case["doc"].Name for case in result["cases"].values()]
        self.assertEqual(len(set(documents)), len(documents))

    def test_save_load_round_trip(self):
        support = self._make_support("SaveLoadSupport", Part.makePlane(120.0, 60.0))
        stiffener, _, _, _ = self._build_stiffener(
            support,
            vertical_cut(PLATE_CUT_Y, -10.0, 130.0, -20.0, 80.0),
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


class TestStiffenerPath(TestFreeCADFP):
    """The sweep path is where the cut surface intersects the support.

    These check the path on its own, with no profile swept along it.
    """

    save_fcstd = False

    RADIUS = 40.0
    HEIGHT = 120.0
    CUT_Z = 60.0
    CUT_SIDE = 120.0
    GEOMETRY_TOLERANCE = 1e-7
    ON_SURFACE_TOLERANCE = 1e-9
    SAMPLES = 72

    def path_of(self, support, cut_surface):
        from Composites.tools.stiffener import generate_intersection_path

        return generate_intersection_path(support, cut_surface)

    def paths_of(self, support, cut_surface):
        from Composites.tools.stiffener import intersection_paths

        return intersection_paths(support, cut_surface)

    def assert_on_support_surface(self, path, support):
        for point in path.discretize(self.SAMPLES):
            distance = support.distToShape(Part.Vertex(point))[0]
            self.assertLess(
                distance,
                self.ON_SURFACE_TOLERANCE,
                f"path point {point} is {distance:g} off the support surface",
            )

    def test_cut_wide_enough_gives_a_closed_ring(self):
        """A cut surface spanning the full diameter cuts a complete ring."""
        support = open_cylinder(self.RADIUS, self.HEIGHT)

        path = self.path_of(support, horizontal_cut(self.CUT_SIDE, -self.CUT_SIDE / 2.0, self.CUT_Z))

        self.assertTrue(path.isClosed())
        self.assertEqual(len(path.Edges), 1)
        curve = path.Edges[0].Curve
        self.assertIsInstance(curve, Part.Circle)
        self.assertAlmostEqual(curve.Radius, self.RADIUS, delta=self.GEOMETRY_TOLERANCE)
        self.assertAlmostEqual(curve.Center.z, self.CUT_Z, delta=self.GEOMETRY_TOLERANCE)

    def test_narrower_cut_gives_a_partial_ring(self):
        """A cut surface reaching only part way across cuts an open arc."""
        support = open_cylinder(self.RADIUS, self.HEIGHT)

        path = self.path_of(support, horizontal_cut(self.CUT_SIDE, self.RADIUS / 2.0, self.CUT_Z))

        self.assertFalse(path.isClosed())
        expected_length = self.RADIUS * math.radians(120.0)
        self.assertAlmostEqual(path.Length, expected_length, delta=self.GEOMETRY_TOLERANCE)

    def test_ring_path_lies_on_the_cylinder_surface(self):
        """Every path point sits on the surface at the cylinder radius, not on a chord."""
        support = open_cylinder(self.RADIUS, self.HEIGHT)

        path = self.path_of(support, horizontal_cut(self.CUT_SIDE, -self.CUT_SIDE / 2.0, self.CUT_Z))

        self.assert_on_support_surface(path, support)
        for point in path.discretize(self.SAMPLES):
            self.assertAlmostEqual(
                math.hypot(point.x, point.y), self.RADIUS, delta=self.GEOMETRY_TOLERANCE
            )

    def test_ring_path_around_a_cone(self):
        """The ring radius is the cone's own radius at the cut height."""
        base_radius, top_radius = 45.0, 20.0
        support = open_cone(base_radius, top_radius, self.HEIGHT)
        radius_at_cut = base_radius + (top_radius - base_radius) * self.CUT_Z / self.HEIGHT

        path = self.path_of(support, horizontal_cut(self.CUT_SIDE, -self.CUT_SIDE / 2.0, self.CUT_Z))

        self.assertTrue(path.isClosed())
        self.assertAlmostEqual(
            path.Edges[0].Curve.Radius, radius_at_cut, delta=self.GEOMETRY_TOLERANCE
        )

    def test_ring_rises_on_the_outward_side_by_default(self):
        """Travel follows the right-hand rule about the cut normal, so b = t x N is outward."""
        from Composites.tools.stiffener import cut_surface_normal, frames_along

        support = open_cylinder(self.RADIUS, self.HEIGHT)
        cut_surface = horizontal_cut(self.CUT_SIDE, -self.CUT_SIDE / 2.0, self.CUT_Z)

        path = self.path_of(support, cut_surface)
        first_station = frames_along(path, cut_surface)[0]

        radial_at_start = FreeCAD.Vector(first_station.point.x, first_station.point.y, 0.0)
        self.assertGreater(first_station.height.dot(radial_at_start.normalize()), 0.999)

    def test_path_on_a_plate_follows_the_cut_surface_line(self):
        """A vertical cut surface across a plate gives a straight path on the plate."""
        support = Part.makePlane(120.0, 60.0)

        path = self.path_of(support, vertical_cut(PLATE_CUT_Y, -10.0, 130.0, -20.0, 80.0))

        self.assertIsInstance(path.Edges[0].Curve, Part.Line)
        self.assertAlmostEqual(path.Length, 120.0, delta=self.GEOMETRY_TOLERANCE)
        self.assertGreater(path.discretize(2)[1].x, path.discretize(2)[0].x)

    def test_path_crosses_a_fold_between_two_faces(self):
        """A cut surface over a folded shell bends where it crosses the fold."""
        folded, bent_cut = folded_shell()

        path = self.path_of(folded, centred_rectangle(*bent_cut))

        self.assertEqual(len(path.Edges), 2)
        self.assertFalse(path.isClosed())

    def test_split_faces_give_a_path_each(self):
        """One cut surface across two separate faces cuts a curve from both."""
        support = Part.makeCompound(
            [
                Part.makePlane(40.0, 40.0),
                Part.makePlane(40.0, 40.0, FreeCAD.Vector(0.0, 0.0, 60.0)),
            ]
        )

        paths = self.paths_of(support, vertical_cut(20.0, -10.0, 50.0, -20.0, 80.0))

        self.assertEqual(len(paths), 2)
        for path in paths:
            self.assertAlmostEqual(path.Length, 40.0, delta=self.GEOMETRY_TOLERANCE)

    def test_cut_surface_clear_of_the_support_gives_no_path(self):
        """An intersecting surface that misses the support yields an empty path, not a crash."""
        support = open_cylinder(self.RADIUS, self.HEIGHT)

        path = self.path_of(support, horizontal_cut(self.CUT_SIDE, -self.CUT_SIDE / 2.0, 200.0))

        self.assertEqual(len(path.Edges), 0)
