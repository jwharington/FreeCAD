# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for PlaceDart command functionality."""

import os
import tempfile
from unittest.mock import patch

import FreeCAD
import Part

from .test_base import TestFreeCADFP


class TestPlaceDartFP(TestFreeCADFP):
    """Tests for PlaceDart command functionality."""

    def _make_shell(self, name="CompositeShell", support_shape=None):
        from Composites.features.CompositeShell import CompositeShellFP
        support = self.doc.addObject("Part::Feature", "Support")
        support.Shape = support_shape or Part.makeCylinder(10.0, 20.0)
        shell = self.doc.addObject("Part::FeaturePython", name)
        CompositeShellFP(shell, support)
        self.doc.recompute()
        return shell

    def _make_wire_source(self, name, shape):
        wire = self.doc.addObject("Part::Feature", name)
        wire.Shape = shape
        self.doc.recompute()
        return wire

    def _simulate_command_activation(self, shell, wires):
        """Helper to simulate PlaceDart command activation."""
        from Composites.features.PlaceDart import PlaceDartCommand

        class MockEntry:
            def __init__(self, obj):
                self.Object = obj

        selection_ex = [MockEntry(shell)] + [MockEntry(w) for w in wires]

        with patch('FreeCADGui.Selection.getSelectionEx', return_value=selection_ex):
            cmd = PlaceDartCommand()
            cmd.Activated()

    def test_placeholder(self):
        """Placeholder test - will be replaced with real tests."""
        self.assertTrue(True)

    def test_place_dart_adds_wire_to_drape_cuts(self):
        """Test that PlaceDart adds projected wires to DrapeCuts property."""
        shell = self._make_shell()
        wire = self._make_wire_source("WireSource", Part.makePolygon([
            FreeCAD.Vector(-5.0, -5.0, 0.0),
            FreeCAD.Vector(5.0, -5.0, 0.0),
            FreeCAD.Vector(5.0, 5.0, 0.0),
            FreeCAD.Vector(-5.0, 5.0, 0.0),
            FreeCAD.Vector(-5.0, -5.0, 0.0),
        ]))

        self._simulate_command_activation(shell, [wire])

        self.assertIsNotNone(shell.DrapeCuts)
        self.assertEqual(len(shell.DrapeCuts), 1)
        projected = shell.DrapeCuts[0]
        self.assertIsNotNone(projected.Shape)
        self.assertFalse(projected.Shape.isNull())

    def test_place_dart_multiple_wires(self):
        """Test PlaceDart with multiple wire sources."""
        shell = self._make_shell()
        wire1 = self._make_wire_source("Wire1", Part.makePolygon([
            FreeCAD.Vector(-5.0, -5.0, 0.0),
            FreeCAD.Vector(5.0, -5.0, 0.0),
            FreeCAD.Vector(5.0, 5.0, 0.0),
            FreeCAD.Vector(-5.0, 5.0, 0.0),
            FreeCAD.Vector(-5.0, -5.0, 0.0),
        ]))
        wire2 = self._make_wire_source("Wire2", Part.makePolygon([
            FreeCAD.Vector(-3.0, -3.0, 5.0),
            FreeCAD.Vector(3.0, -3.0, 5.0),
            FreeCAD.Vector(3.0, 3.0, 5.0),
            FreeCAD.Vector(-3.0, 3.0, 5.0),
            FreeCAD.Vector(-3.0, -3.0, 5.0),
        ]))

        self._simulate_command_activation(shell, [wire1, wire2])
        self.assertEqual(len(shell.DrapeCuts), 2)

    def test_place_dart_closed_wire_closure(self):
        """Test that closed wires are properly closed after projection."""
        shell = self._make_shell()
        wire = self._make_wire_source("ClosedWire", Part.makePolygon([
            FreeCAD.Vector(-5.0, -5.0, 0.0),
            FreeCAD.Vector(5.0, -5.0, 0.0),
            FreeCAD.Vector(5.0, 5.0, 0.0),
            FreeCAD.Vector(-5.0, 5.0, 0.0),
            FreeCAD.Vector(-5.0, -5.0, 0.0),
        ]))

        self._simulate_command_activation(shell, [wire])
        projected = shell.DrapeCuts[0]
        self.assertTrue(projected.Shape.isClosed())

    def test_place_dart_empty_selection(self):
        """Test that PlaceDart does nothing with empty selection."""
        shell = self._make_shell()
        self.assertEqual(shell.DrapeCuts, [])

        from Composites.features.PlaceDart import PlaceDartCommand

        class MockEntry:
            def __init__(self, obj):
                self.Object = obj

        selection_ex = [MockEntry(shell)]

        with patch('FreeCADGui.Selection.getSelectionEx', return_value=selection_ex):
            cmd = PlaceDartCommand()
            cmd.Activated()

        self.assertEqual(shell.DrapeCuts, [])

    def test_place_dart_no_shell_selection(self):
        """Test that PlaceDart does nothing without shell selection."""
        wire = self._make_wire_source("Wire", Part.makePolygon([
            FreeCAD.Vector(-5.0, -5.0, 0.0),
            FreeCAD.Vector(5.0, -5.0, 0.0),
            FreeCAD.Vector(5.0, 5.0, 0.0),
            FreeCAD.Vector(-5.0, 5.0, 0.0),
            FreeCAD.Vector(-5.0, -5.0, 0.0),
        ]))

        from Composites.features.PlaceDart import PlaceDartCommand

        class MockEntry:
            def __init__(self, obj):
                self.Object = obj

        selection_ex = [MockEntry(wire)]

        with patch('FreeCADGui.Selection.getSelectionEx', return_value=selection_ex):
            cmd = PlaceDartCommand()
            cmd.Activated()

        self.assertFalse(hasattr(wire, "DrapeCuts"))

    def test_place_dart_projection_object_visibility(self):
        """Test that projection objects are created and hidden."""
        shell = self._make_shell()
        wire = self._make_wire_source("Wire", Part.makePolygon([
            FreeCAD.Vector(-5.0, -5.0, 0.0),
            FreeCAD.Vector(5.0, -5.0, 0.0),
            FreeCAD.Vector(5.0, 5.0, 0.0),
            FreeCAD.Vector(-5.0, 5.0, 0.0),
            FreeCAD.Vector(-5.0, -5.0, 0.0),
        ]))

        self._simulate_command_activation(shell, [wire])

        projection_name = f"{shell.Name}_{wire.Name}_PlaceDartCut"
        projected_obj = self.doc.getObject(projection_name)
        self.assertIsNotNone(projected_obj)
        self.assertFalse(projected_obj.Visibility)

    def test_place_dart_projection_object_reuse(self):
        """Test that existing projection objects are reused and hidden."""
        shell = self._make_shell()
        wire = self._make_wire_source("Wire", Part.makePolygon([
            FreeCAD.Vector(-5.0, -5.0, 0.0),
            FreeCAD.Vector(5.0, -5.0, 0.0),
            FreeCAD.Vector(5.0, 5.0, 0.0),
            FreeCAD.Vector(-5.0, 5.0, 0.0),
            FreeCAD.Vector(-5.0, -5.0, 0.0),
        ]))

        self._simulate_command_activation(shell, [wire])
        projection_name = f"{shell.Name}_{wire.Name}_PlaceDartCut"
        projected_obj = self.doc.getObject(projection_name)
        first_count = len(shell.DrapeCuts)

        self._simulate_command_activation(shell, [wire])
        self.assertEqual(len(shell.DrapeCuts), first_count)
        self.assertEqual(shell.DrapeCuts[0], projected_obj)