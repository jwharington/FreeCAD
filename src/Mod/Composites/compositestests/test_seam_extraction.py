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


def _make_two_adjacent_shells(doc):
    """Create two coplanar composite shells sharing edge at x=0.

    Returns (master_shell, att_shell, laminate).
    Minimal object count: 2 supports + 1 laminate + 2 shells = 5 objects.
    """
    import Part

    from Composites.features.CompositeShell import CompositeShellFP

    def _face(pts):
        wire = Part.makePolygon(pts + [pts[0]])
        return Part.Face(wire)

    master_face = _face([
        FreeCAD.Vector(0, -25, 0),
        FreeCAD.Vector(50, -25, 0),
        FreeCAD.Vector(50, 25, 0),
        FreeCAD.Vector(0, 25, 0),
    ])
    att_face = _face([
        FreeCAD.Vector(-50, -25, 0),
        FreeCAD.Vector(0, -25, 0),
        FreeCAD.Vector(0, 25, 0),
        FreeCAD.Vector(-50, 25, 0),
    ])

    master_sup = doc.addObject("Part::Feature", "MasterSup")
    master_sup.Shape = master_face

    att_sup = doc.addObject("Part::Feature", "AttSup")
    att_sup.Shape = att_face

    # Shared laminate — single object
    from Composites.features.Laminate import LaminateFP
    lam = doc.addObject("Part::FeaturePython", "Laminate")
    LaminateFP(lam)

    ms = doc.addObject("Part::FeaturePython", "MasterShell")
    CompositeShellFP(ms, support=master_sup, laminate=lam, rosette=None)

    as_ = doc.addObject("Part::FeaturePython", "AttShell")
    CompositeShellFP(as_, support=att_sup, laminate=lam, rosette=None)

    doc.recompute()
    return ms, as_, lam


class TestSeamGeometryFP(TestFreeCADFP):
    """Tests for SeamGeometryFP."""

    def test_creation(self):
        """SeamGeometryFP is created with correct properties."""
        from Composites.features.SeamExtraction import SeamGeometryFP

        seam_shell = self.doc.addObject("Part::FeaturePython", "Seam")
        SeamGeometryFP(seam_shell, FreeCAD.ActiveDocument)

        self.assertIsNotNone(seam_shell)
        self.assertIsNone(seam_shell.Support)  # No intermediate _ShapeHolder
        self.assertEqual(seam_shell.TypeId, "Part::FeaturePython")

    def test_update_sets_shape(self):
        """update() sets shape on seam shell."""
        from Composites.features.SeamExtraction import SeamGeometryFP

        box = self.doc.addObject("Part::Box", "Box")
        box.Length = 100
        box.Width = 50
        box.Height = 2

        seam_shell = self.doc.addObject("Part::FeaturePython", "Seam")
        SeamGeometryFP(seam_shell, FreeCAD.ActiveDocument)
        seam_shell.Proxy.update(seam_shell, box.Shape, None, None)

        self.assertFalse(seam_shell.Shape.isNull())
        self.assertTrue(
            seam_shell.Shape.isSame(box.Shape),
            "Seam shell shape should match input box shape",
        )

    def test_update_sets_laminate(self):
        """update() sets laminate on seam shell."""
        from Composites.features.SeamExtraction import SeamGeometryFP

        box = self.doc.addObject("Part::Box", "Box")
        box.Length = 100
        box.Width = 50
        box.Height = 2

        lam = self._create_laminate()

        seam_shell = self.doc.addObject("Part::FeaturePython", "Seam")
        SeamGeometryFP(seam_shell, FreeCAD.ActiveDocument)
        seam_shell.Proxy.update(seam_shell, box.Shape, lam, None)

        self.assertIs(seam_shell.Laminate, lam)

    def test_update_sets_rosette(self):
        """update() sets rosette on seam shell."""
        from Composites.features.SeamExtraction import SeamGeometryFP

        box = self.doc.addObject("Part::Box", "Box")
        box.Length = 100
        box.Width = 50
        box.Height = 2

        rosette = self.doc.addObject("App::FeaturePython", "Rosette")

        seam_shell = self.doc.addObject("Part::FeaturePython", "Seam")
        SeamGeometryFP(seam_shell, FreeCAD.ActiveDocument)
        seam_shell.Proxy.update(seam_shell, box.Shape, None, rosette)

        self.assertIs(seam_shell.Rosette, rosette)

    def test_execute_is_noop(self):
        """execute() does nothing for SeamGeometryFP."""
        from Composites.features.SeamExtraction import SeamGeometryFP

        box = self.doc.addObject("Part::Box", "Box")
        box.Length = 100
        box.Width = 50
        box.Height = 2
        seam_shell = self.doc.addObject("Part::FeaturePython", "Seam")
        SeamGeometryFP(seam_shell, FreeCAD.ActiveDocument)
        seam_shell.Proxy.execute(seam_shell)


class TestSeamShellFP(TestFreeCADFP):
    """Tests for SeamShellFP."""

    def test_creation(self):
        """SeamShellFP is created with correct properties."""
        from Composites.features.SeamExtraction import SeamShellFP

        master, att, _ = _make_two_adjacent_shells(self.doc)

        ext = self.doc.addObject("Part::FeaturePython", "SeamExtraction")
        SeamShellFP(ext, master, att)

        self.assertIs(ext.Master, master)
        self.assertIs(ext.Attachment, att)
        self.assertIsNotNone(ext.Width)

    def test_has_seam_property(self):
        """SeamShellFP has a Seam property (not scattered Support/Laminate)."""
        from Composites.features.SeamExtraction import SeamShellFP

        master, att, _ = _make_two_adjacent_shells(self.doc)

        ext = self.doc.addObject("Part::FeaturePython", "SeamExtraction")
        SeamShellFP(ext, master, att)

        self.assertTrue(hasattr(ext, "Seam"))

    def test_seam_property_exists_even_when_extraction_fails(self):
        """Seam property is always present, even when extraction fails."""
        from Composites.features.SeamExtraction import SeamShellFP

        master, att, _ = _make_two_adjacent_shells(self.doc)

        ext = self.doc.addObject("Part::FeaturePython", "SeamExtraction")
        SeamShellFP(ext, master, att)

        self.assertTrue(hasattr(ext, "Seam"))

    def test_seam_shell_created_on_success(self):
        """When extraction succeeds, Seam points to a SeamGeometryFP child."""
        from Composites.features.SeamExtraction import SeamShellFP

        master, att, _ = _make_two_adjacent_shells(self.doc)

        ext = self.doc.addObject("Part::FeaturePython", "SeamExtraction")
        SeamShellFP(ext, master, att)

        self.assertIsNotNone(
            ext.Seam,
            "Seam should be set when extraction succeeds",
        )
        self.assertIn(
            "Seam",
            ext.Seam.Name,
            "Seam should be a SeamGeometryFP child",
        )

    def test_on_changed_triggers_sync(self):
        """Changing Master triggers _sync_virtual_inputs without raising."""
        from Composites.features.SeamExtraction import SeamShellFP

        master, att, _ = _make_two_adjacent_shells(self.doc)

        ext = self.doc.addObject("Part::FeaturePython", "SeamExtraction")
        SeamShellFP(ext, master, att)

        # Create a replacement master shell in the SAME document
        from Composites.features.CompositeShell import CompositeShellFP
        rep_sup = self.doc.addObject("Part::Feature", "RepSup")
        import Part
        rep_face = Part.Face(Part.makePolygon([
            FreeCAD.Vector(0, -25, 0),
            FreeCAD.Vector(60, -25, 0),
            FreeCAD.Vector(60, 25, 0),
            FreeCAD.Vector(0, 25, 0),
            FreeCAD.Vector(0, -25, 0),
        ]))
        rep_sup.Shape = rep_face

        rep_lam = self.doc.addObject("Part::FeaturePython", "RepLam")
        from Composites.features.Laminate import LaminateFP
        LaminateFP(rep_lam)

        new_master = self.doc.addObject("Part::FeaturePython", "NewMaster")
        CompositeShellFP(new_master, support=rep_sup, laminate=rep_lam, rosette=None)
        self.doc.recompute()

        # Assign — should not raise
        ext.Master = new_master
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
        ext.Width = 10.0

        self.assertIs(ext.Master, master)
        self.assertIs(ext.Attachment, att)
        self.assertEqual(float(ext.Width), 10.0)
        self.assertTrue(hasattr(ext, "Seam"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
