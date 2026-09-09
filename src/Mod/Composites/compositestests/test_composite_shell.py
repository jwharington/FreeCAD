# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for CompositeShellFP."""

import os
import tempfile
import unittest

import FreeCAD
import Part

from .test_base import TestFreeCADFP


class TestCompositeShellFP(TestFreeCADFP):
    """Tests for CompositeShellFP."""

    def test_basic_creation(self):
        shell = self._create_shell()
        self.assertIsNotNone(shell)
        self.assertFalse(shell.Shape.isNull())

    def test_save_load_document(self):
        shell = self._create_shell()
        filepath = os.path.join(tempfile.gettempdir(), "test_shell.FCStd")
        self._save_document(filepath)
        loaded_doc = self._load_document(filepath)
        try:
            loaded_shell = loaded_doc.getObject(shell.Name)
            self.assertIsNotNone(loaded_shell)
            self.assertFalse(loaded_shell.Shape.isNull())
        finally:
            try:
                loaded_doc.close()
            except Exception:
                pass
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_laminate_property(self):
        shell = self._create_shell()
        laminate = self._create_laminate()
        shell.Laminate = laminate
        self.assertIs(shell.Laminate, laminate)
    def test_live_support_shape_tracks_moved_support(self):
        """Known-issue #6: geometry queries must read the live support, not
        the shell's cached Shape snapshot."""
        import FreeCAD
        import Part

        from Composites.features.CompositeShell import CompositeShellFP
        from Composites.util.geometry_util import live_support_shape

        support = self.doc.addObject("Part::Feature", "Support")
        support.Shape = Part.makePlane(100.0, 100.0)
        shell = self.doc.addObject("Part::FeaturePython", "Shell")
        CompositeShellFP(shell, support)
        self.doc.recompute()
        self.assertEqual(
            live_support_shape(shell).BoundBox.ZMax,
            support.Shape.BoundBox.ZMax,
        )

        # Move the support WITHOUT recomputing: the shell's own Shape is
        # still the pre-move snapshot, but the live query must track.
        support.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0.0, 0.0, 40.0), FreeCAD.Rotation()
        )
        self.assertLess(shell.Shape.BoundBox.ZMax, 39.0)
        self.assertGreater(live_support_shape(shell).BoundBox.ZMax, 39.0)

        # After a recompute the snapshot catches up.
        self.doc.recompute()
        self.assertGreater(shell.Shape.BoundBox.ZMax, 39.0)


class TestRosettelessFallbackSeed(TestFreeCADFP):
    """Known-issue #7: a rosette-less shell seeds its drape from the
    support's centre of mass projected onto the surface.  On a closed
    surface the COM lies on the axis and the old bounding-box clamp
    landed off-surface (solver_failure); the true nearest-point
    projection lands on the shell."""

    save_fcstd = False

    def test_closed_cylinder_com_seed_lands_on_surface(self):
        import Part

        from Composites.tools.drape_backend_nextdrape import NextDrapeBackend

        cylinder = next(
            f for f in Part.makeCylinder(10.0, 20.0).Faces
            if isinstance(f.Surface, Part.Cylinder)
        )
        backend = NextDrapeBackend(mesh=None, lcs=None, shape=cylinder)
        com = cylinder.CenterOfMass
        seed = backend._project_point_to_surface([com.x, com.y, com.z])

        # The projected seed must lie ON the shell (distance ~0), not on
        # a bbox face.
        dist = cylinder.distToShape(Part.Vertex(seed[0], seed[1], seed[2]))[0]
        self.assertLess(dist, 1e-6)
        # The axis COM was radius=10 away — the clamp never got this close.
        self.assertGreater(com.x ** 2 + com.y ** 2, 0.0)

    def test_rosetteless_open_cylinder_drapes(self):
        """The full lazy solve: a rosette-less shell on an open cylinder
        must produce a valid drape from the COM fallback seed.

        A *closed* cylinder still fails the march itself — that is the
        wrap-around lattice-closing problem (known-issue #3), not the
        seed: the projected seed is on-surface (previous test)."""
        import Part

        from Composites.tools.drape_backend_nextdrape import NextDrapeBackend

        solid = Part.makeCylinder(10.0, 20.0, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 270.0)
        panel = next(
            f for f in solid.Faces
            if isinstance(f.Surface, Part.Cylinder)
        )
        backend = NextDrapeBackend(mesh=None, lcs=None, shape=panel)
        result = backend._run_solve()
        self.assertTrue(result.get("success"), f"solve failed: {result.get('error')}")
        self.assertTrue(backend.is_valid())
