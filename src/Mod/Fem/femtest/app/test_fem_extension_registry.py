# ***************************************************************************
# *   Copyright (c) 2026                                                     *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# ***************************************************************************

import unittest

from .support_utils import fcc_print


class TestFemExtensionRegistry(unittest.TestCase):
    fcc_print("import TestFemExtensionRegistry")

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestFemExtensionRegistry tests {2}\n{0}".format(
                100 * "*", 10 * "*", 43 * "*"
            )
        )

    def test_shell_orientation_provider(self):
        from femtools import fem_extension_registry as registry

        def provider(shellth_obj, femmesh_obj, elements, orientation):
            return {"orientation": "provider-orientation", "element_ids": [1, 2]}

        registry.register_shell_orientation_provider("test.provider", provider)
        try:
            result = registry.get_shell_orientation_overrides(None, None, [10, 20])
        finally:
            registry.unregister_shell_orientation_provider("test.provider")

        self.assertEqual(result["orientation"], "provider-orientation")
        self.assertEqual(result["element_ids"], [1, 2])

    def test_shell_section_provider(self):
        from femtools import fem_extension_registry as registry

        def provider(shellth_obj, matgeoset, orientation_name):
            return {"material": "COMPOSITE,ORIENTATION=foo", "section_geo": "1.0\n"}

        registry.register_shell_section_provider("test.provider", provider)
        try:
            result = registry.get_shell_section_override(None, {}, "foo")
        finally:
            registry.unregister_shell_section_provider("test.provider")

        self.assertEqual(result["material"], "COMPOSITE,ORIENTATION=foo")
        self.assertEqual(result["section_geo"], "1.0\n")

    def test_indirect_material_provider(self):
        from femtools import fem_extension_registry as registry

        class Dummy:
            pass

        obj = Dummy()

        def provider(geos_shellthickness):
            return [obj]

        registry.register_indirect_material_provider("test.provider", provider)
        try:
            result = registry.get_indirect_materials([])
        finally:
            registry.unregister_indirect_material_provider("test.provider")

        self.assertEqual(result, [obj])
