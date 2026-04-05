# SPDX-License-Identifier: LGPL-2.1-or-later
# Tests for commits:
#   aa9155ed05  Assembly: add FemLink module infrastructure
#   d369c72d37  Assembly: add LinkBody command and FemLink integration
#   73538fc78f  Assembly: add force command and refactor task utilities

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


# ---------------------------------------------------------------------------
# d369c72d37 – FPBase infrastructure (FemLink.FPBase)
# ---------------------------------------------------------------------------


class TestFPBase(unittest.TestCase):

    def setUp(self):
        self.doc = _make_doc(self.__class__.__name__)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_fpbase_getstate_returns_empty_dict(self):
        """FPBase.__getstate__ must return {} for serialisation."""
        _msg("  Test FPBase.__getstate__")
        from FemLink.FPBase import FPBase

        class ConcreteFP(FPBase):
            pass

        obj = self.doc.addObject("App::FeaturePython", "FP")
        fp = ConcreteFP(obj)
        self.assertEqual(fp.__getstate__(), {})

    def test_fpbase_setstate_returns_none(self):
        """FPBase.__setstate__ must return None (no-op restore)."""
        _msg("  Test FPBase.__setstate__")
        from FemLink.FPBase import FPBase

        class ConcreteFP(FPBase):
            pass

        obj = self.doc.addObject("App::FeaturePython", "FP2")
        fp = ConcreteFP(obj)
        self.assertIsNone(fp.__setstate__({}))

    def test_fpbase_getassembly_returns_none_for_standalone(self):
        """FPBase.getAssembly returns None when object has no Assembly parent."""
        _msg("  Test FPBase.getAssembly standalone")
        from FemLink.FPBase import FPBase

        class ConcreteFP(FPBase):
            pass

        obj = self.doc.addObject("App::FeaturePython", "FP3")
        fp = ConcreteFP(obj)
        self.assertIsNone(fp.getAssembly(obj))


# ---------------------------------------------------------------------------
# 73538fc78f – force command and task utilities (ForceObject)
# ---------------------------------------------------------------------------


class TestForceObject(unittest.TestCase):

    def setUp(self):
        self.doc = _make_doc(self.__class__.__name__)
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        self.assembly.newObject("Assembly::JointGroup", "Joints")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_force_types_list_integrity(self):
        """ForceTypes and TranslatedForceTypes must have the same length and expected values."""
        _msg("  Test ForceTypes list integrity")
        import ForceObject

        self.assertEqual(len(ForceObject.ForceTypes), len(ForceObject.TranslatedForceTypes))
        self.assertIn("General", ForceObject.ForceTypes)
        self.assertIn("InLine", ForceObject.ForceTypes)

    def test_force_torque_general_has_force_type_property(self):
        """ForceTorqueGeneral must initialise with a ForceType property set to 'General'."""
        _msg("  Test ForceTorqueGeneral ForceType property")
        import ForceObject

        force_obj = self.assembly.newObject("App::FeaturePython", "Force")
        ForceObject.ForceTorqueGeneral(force_obj)
        self.assertTrue(hasattr(force_obj, "ForceType"))
        self.assertEqual(force_obj.ForceType, "General")

    def test_force_torque_inline_has_force_type_property(self):
        """ForceTorqueInLine must initialise with a ForceType property set to 'InLine'."""
        _msg("  Test ForceTorqueInLine ForceType property")
        import ForceObject

        force_obj = self.assembly.newObject("App::FeaturePython", "ForceInLine")
        ForceObject.ForceTorqueInLine(force_obj)
        self.assertTrue(hasattr(force_obj, "ForceType"))
        self.assertEqual(force_obj.ForceType, "InLine")

    def test_force_torque_general_has_reference_properties(self):
        """ForceTorqueGeneral must initialise Reference1 and Reference2 properties."""
        _msg("  Test ForceTorqueGeneral reference properties")
        import ForceObject

        force_obj = self.assembly.newObject("App::FeaturePython", "Force2")
        ForceObject.ForceTorqueGeneral(force_obj)
        self.assertTrue(hasattr(force_obj, "Reference1"))
        self.assertTrue(hasattr(force_obj, "Reference2"))
