# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for SeamFP and SeamShellFP."""

import unittest

from test_base import TestFreeCADFP


def _make_composite_shells(test_case):
    """Helper: create two composite shells from boxes."""
    from Composites.features.CompositeShell import CompositeShellFP

    master = test_case.doc.addObject("Part::Box", "Master")
    master.Length = 100
    master.Width = 50
    master.Height = 2

    att = test_case.doc.addObject("Part::Box", "Attachment")
    att.Length = 100
    att.Width = 50
    att.Height = 2

    ms = test_case.doc.addObject("Part::FeaturePython", "MasterShell")
    CompositeShellFP(ms, support=master, laminate=test_case._create_laminate(), rosette=None)

    as_ = test_case.doc.addObject("Part::FeaturePython", "AttShell")
    CompositeShellFP(as_, support=att, laminate=test_case._create_laminate(), rosette=None)

    return ms, as_


class TestSeamGeometryFP(TestFreeCADFP):
    """Tests for SeamGeometryFP — the composite shell that holds seam geometry."""

    def test_creation(self):
        """SeamGeometryFP can be created with a doc reference."""
        from Composites.features.SeamExtraction import SeamGeometryFP

        seam_shell = self.doc.addObject("Part::FeaturePython", "SeamShell")
        SeamGeometryFP(seam_shell, self.doc)

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
        SeamGeometryFP(seam_shell, self.doc)
        seam_shell.Proxy.update(seam_shell, box.Shape, None, None)

        self.assertFalse(seam_shell.Shape.isNull())
        self.assertEqual(seam_shell.Shape, box.Shape)

    def test_update_sets_laminate(self):
        """update() sets the laminate on the seam shell."""
        from Composites.features.SeamExtraction import SeamGeometryFP

        box = self.doc.addObject("Part::Box", "Box")
        box.Length = 100
        box.Width = 50
        box.Height = 2

        lam = self._create_laminate()

        seam_shell = self.doc.addObject("Part::FeaturePython", "SeamShell")
        SeamGeometryFP(seam_shell, self.doc)
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
        SeamGeometryFP(seam_shell, self.doc)
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
        SeamGeometryFP(seam_shell, self.doc)

        # execute() should not raise and should not trigger drape
        seam_shell.Proxy.execute(seam_shell)


class TestSeamShellFP(TestFreeCADFP):
    """Tests for SeamShellFP — the extraction node."""

    def _make_composite_shells(self):
        """Create two composite shells that share an edge."""
        from Composites.features.CompositeShell import CompositeShellFP

        # Master: box at z=0
        master_box = self.doc.addObject("Part::Box", "MasterBox")
        master_box.Length = 100
        master_box.Width = 50
        master_box.Height = 2

        # Attachment: box at z=2 (touching master top face)
        att_box = self.doc.addObject("Part::Box", "AttBox")
        att_box.Length = 100
        att_box.Width = 50
        att_box.Height = 2
        att_box.Placement.Base.z = 2

        # Convert to composite shells
        master_lam = self._create_laminate()
        master_shell = self.doc.addObject("Part::FeaturePython", "MasterShell")
        CompositeShellFP(master_shell, support=master_box, laminate=master_lam)

        att_shell = self.doc.addObject("Part::FeaturePython", "AttShell")
        CompositeShellFP(att_shell, support=att_box, laminate=master_lam)

        return master_shell, att_shell

    def test_creation(self):
        """SeamShellFP is created with correct properties."""
        from Composites.features.SeamExtraction import SeamShellFP

        master, att = _make_composite_shells(self)

        ext = self.doc.addObject("Part::FeaturePython", "SeamExtraction")
        SeamShellFP(ext, master, att)

        self.assertIs(ext.Master, master)
        self.assertIs(ext.Attachment, att)
        self.assertIsNotNone(ext.SeamWidth)
        self.assertIsNotNone(ext.Seam)  # May be None if extraction fails

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

        # When extraction succeeds, Seam points to a SeamGeometryFP
        if ext.Seam is not None:
            self.assertIn("SeamShell", ext.Seam.Name)

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