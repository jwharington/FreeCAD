# SPDX-License-Identifier: LGPL-2.1-or-later
# Tests for commit aa9155ed05:
#   Assembly: add FemLink module infrastructure

import unittest

import FreeCAD as App


def _msg(text):
    App.Console.PrintMessage(text + "\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(name):
    if App.ActiveDocument and App.ActiveDocument.Name == name:
        App.closeDocument(name)
    doc = App.newDocument(name)
    App.setActiveDocument(name)
    return doc


# ---------------------------------------------------------------------------
# aa9155ed05 – FemLink module infrastructure
# ---------------------------------------------------------------------------


class TestFemLinkUtils(unittest.TestCase):

    def setUp(self):
        self.doc = _make_doc(self.__class__.__name__)
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_find_common_group_objects_empty(self):
        """find_common_group_objects returns [] when no objects of that type exist."""
        _msg("  Test find_common_group_objects empty")
        from FemLink.UtilsFemLink import find_common_group_objects

        result = find_common_group_objects(self.assembly, "App::Link")
        self.assertEqual(result, [])

    def test_get_assembly_bodies_empty(self):
        """get_assembly_bodies returns [] for an empty assembly."""
        _msg("  Test get_assembly_bodies empty")
        from FemLink.UtilsFemLink import get_assembly_bodies

        result = get_assembly_bodies(self.assembly)
        self.assertEqual(result, [])

    def test_get_simgroup_returns_none_when_missing(self):
        """get_simgroup returns None when no SimulationGroup is present."""
        _msg("  Test get_simgroup missing")
        from FemLink.UtilsFemLink import get_simgroup

        result = get_simgroup(self.assembly)
        self.assertIsNone(result)

    def test_get_simulations_returns_empty_when_no_simgroup(self):
        """get_simulations returns [] when no SimulationGroup is present."""
        _msg("  Test get_simulations no simgroup")
        from FemLink.UtilsFemLink import get_simulations

        result = get_simulations(self.assembly)
        self.assertEqual(result, [])

    def test_get_femlinks_returns_empty_for_empty_assembly(self):
        """get_femlinks returns [] for assembly with no group objects."""
        _msg("  Test get_femlinks empty")
        from FemLink.UtilsFemLink import get_femlinks

        result = get_femlinks(self.assembly)
        self.assertEqual(result, [])
