# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for SeamFP and SeamShellFP."""

import unittest

import FreeCAD

from .test_base import TestFreeCADFP


def _extractor_available():
    """Check if C++ seam extractor is importable."""
    try:
        from Composites.tools.seam_extraction import _import_extractor

        _import_extractor()
        return True
    except ImportError:
        return False


def _make_composite_shells(test_case):
    """Create two composite shells from adjacent planar faces sharing an edge.

    Produces two faces that share a common boundary edge so the seam
    extractor can find a seam between them.
    """
    import Part

    from Composites.features.CompositeShell import CompositeShellFP

    def _face_from_pts(pts):
        """Build a planar face from a closed polyline."""
        wire = Part.makePolygon(pts + [pts[0]])
        return Part.Face(wire)

    # Two rectangular faces sharing the edge at x=0, lying in XY plane
    master_face = _face_from_pts([
        FreeCAD.Vector(0, -25, 0),
        FreeCAD.Vector(50, -25, 0),
        FreeCAD.Vector(50, 25, 0),
        FreeCAD.Vector(0, 25, 0),
    ])
    att_face = _face_from_pts([
        FreeCAD.Vector(-50, -25, 0),
        FreeCAD.Vector(0, -25, 0),
        FreeCAD.Vector(0, 25, 0),
        FreeCAD.Vector(-50, 25, 0),
    ])

    master_sup = test_case.doc.addObject("Part::Feature", "MasterSup")
    master_sup.Shape = master_face

    att_sup = test_case.doc.addObject("Part::Feature", "AttSup")
    att_sup.Shape = att_face

    lam = test_case._create_laminate()

    ms = test_case.doc.addObject("Part::FeaturePython", "MasterShell")
    CompositeShellFP(ms, support=master_sup, laminate=lam, rosette=None)

    as_ = test_case.doc.addObject("Part::FeaturePython", "AttShell")
    CompositeShellFP(as_, support=att_sup, laminate=lam, rosette=None)

    # Recompute so shell shapes are computed before extraction
    test_case.doc.recompute()

    return ms, as_


class TestSeamGeometryFP(TestFreeCADFP):
    """Tests for SeamGeometryFP — the composite shell that holds seam geometry."""

    def test_creation(self):
        """SeamGeometryFP can be created with a doc reference."""
        from Composites.features.SeamExtraction import SeamGeometryFP

        seam_shell = self.doc.addObject("Part::FeaturePython", "SeamShell")
        SeamGeometryFP(seam_shell, FreeCAD.ActiveDocument)

        self.assertIsNotNone(seam_shell)
        self.assertIsNotNone(seam_shell.Support)
        self.assertEqual(seam_shell.TypeId, "Part::FeaturePython")

    def test_update_sets_shape(self):
        """update() sets the shape on the seam shell."""
        from Composites.features.SeamExtraction import SeamGeometryFP

        box = self.doc.addObject("Part::Box", "Box")
        box.Length = 100
        box.Width = 50
        box.Height = 2

        seam_shell = self.doc.addObject("Part::FeaturePython", "SeamShell")
        SeamGeometryFP(seam_shell, FreeCAD.ActiveDocument)
        seam_shell.Proxy.update(seam_shell, box.Shape, None, None)

        self.assertFalse(seam_shell.Shape.isNull())
        self.assertTrue(
            seam_shell.Shape.isSame(box.Shape),
            "Seam shell shape should match input box shape",
        )

    def test_update_sets_laminate(self):
        """update() sets the laminate on the seam shell."""
        from Composites.features.SeamExtraction import SeamGeometryFP

        box = self.doc.addObject("Part::Box", "Box")
        box.Length = 100
        box.Width = 50
        box.Height = 2

        lam = self._create_laminate()

        seam_shell = self.doc.addObject("Part::FeaturePython", "SeamShell")
        SeamGeometryFP(seam_shell, FreeCAD.ActiveDocument)
        seam_shell.Proxy.update(seam_shell, box.Shape, lam, None)

        self.assertIs(seam_shell.Laminate, lam)

    def test_update_sets_rosette(self):
        """update() sets the rosette on the seam shell."""
        from Composites.features.SeamExtraction import SeamGeometryFP

        box = self.doc.addObject("Part::Box", "Box")
        box.Length = 100
        box.Width = 50
        box.Height = 2

        rosette = self.doc.addObject("App::FeaturePython", "Rosette")

        seam_shell = self.doc.addObject("Part::FeaturePython", "SeamShell")
        SeamGeometryFP(seam_shell, FreeCAD.ActiveDocument)
        seam_shell.Proxy.update(seam_shell, box.Shape, None, rosette)

        self.assertIs(seam_shell.Rosette, rosette)

    def test_execute_is_noop(self):
        """execute() does nothing — seam shells never drape."""
        from Composites.features.SeamExtraction import SeamGeometryFP

        box = self.doc.addObject("Part::Box", "Box")
        box.Length = 100
        box.Width = 50
        box.Height = 2

        seam_shell = self.doc.addObject("Part::FeaturePython", "SeamShell")
        SeamGeometryFP(seam_shell, FreeCAD.ActiveDocument)

        # execute() should not raise and should not trigger drape
        seam_shell.Proxy.execute(seam_shell)


class TestSeamShellFP(TestFreeCADFP):
    """Tests for SeamShellFP — the extraction node."""

    def test_creation(self):
        """SeamShellFP is created with correct properties."""
        from Composites.features.SeamExtraction import SeamShellFP

        master, att = _make_composite_shells(self)

        ext = self.doc.addObject("Part::FeaturePython", "SeamExtraction")
        SeamShellFP(ext, master, att)

        self.assertIs(ext.Master, master)
        self.assertIs(ext.Attachment, att)
        self.assertIsNotNone(ext.SeamWidth)

    def test_has_seam_property(self):
        """SeamShellFP has a Seam property (not scattered Support/Laminate)."""
        from Composites.features.SeamExtraction import SeamShellFP

        master, att = _make_composite_shells(self)

        ext = self.doc.addObject("Part::FeaturePython", "SeamExtraction")
        SeamShellFP(ext, master, att)

        # The key assertion: Seam property exists
        self.assertTrue(hasattr(ext, "Seam"))

    def test_seam_property_exists_even_when_extraction_fails(self):
        """Seam property is always present, even when extraction fails."""
        from Composites.features.SeamExtraction import SeamShellFP

        master, att = _make_composite_shells(self)

        ext = self.doc.addObject("Part::FeaturePython", "SeamExtraction")
        SeamShellFP(ext, master, att)

        # Seam property must exist (even if None)
        self.assertTrue(hasattr(ext, "Seam"))

    def test_seam_shell_created_on_success(self):
        """When extraction succeeds, Seam points to a SeamGeometryFP child."""
        from Composites.features.SeamExtraction import SeamShellFP

        master, att = _make_composite_shells(self)

        ext = self.doc.addObject("Part::FeaturePython", "SeamExtraction")
        SeamShellFP(ext, master, att)

        # With adjacent-face geometry the extractor should succeed
        self.assertIsNotNone(
            ext.Seam,
            "Seam should be set when extraction succeeds",
        )
        self.assertIn(
            "SeamShell",
            ext.Seam.Name,
            "Seam should be a SeamGeometryFP child",
        )

    def test_on_changed_triggers_sync(self):
        """Changing Master/Attachment/SeamWidth triggers _sync_virtual_inputs."""
        from Composites.features.SeamExtraction import SeamShellFP

        master, att = _make_composite_shells(self)

        ext = self.doc.addObject("Part::FeaturePython", "SeamExtraction")
        SeamShellFP(ext, master, att)

        # Changing Master should trigger onChanged → _sync_virtual_inputs
        new_master, _ = _make_composite_shells(self)
        ext.Master = new_master

        # Should not raise
        self.assertIs(ext.Master, new_master)


class TestSeamFP(TestFreeCADFP):
    """Tests for SeamFP — basic Part-level extraction."""

    def test_creation(self):
        """SeamFP is created with correct properties."""
        from Composites.features.SeamExtraction import SeamFP

        master = self.doc.addObject("Part::Box", "Master")
        master.Length = 100
        master.Width = 50
        master.Height = 2

        att = self.doc.addObject("Part::Box", "Attachment")
        att.Length = 100
        att.Width = 50
        att.Height = 2

        ext = self.doc.addObject("Part::FeaturePython", "SeamExtraction")
        SeamFP(ext)
        ext.Master = master
        ext.Attachment = att
        ext.SeamWidth = 10.0

        self.assertIs(ext.Master, master)
        self.assertIs(ext.Attachment, att)
        self.assertEqual(float(ext.SeamWidth), 10.0)
        self.assertTrue(hasattr(ext, "Seam"))
        self.assertTrue(hasattr(ext, "Remainder"))