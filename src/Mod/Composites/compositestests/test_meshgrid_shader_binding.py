# SPDX-License-Identifier: LGPL-2.1-or-later

"""Regression test scaffold for MeshGridShader texcoord binding.

This guards against a subtle rendering regression where texcoords appeared to
reset per triangle (chevron artifacts) when using SoIndexedFaceSet +
textureCoordIndex with PER_VERTEX binding.
"""

import importlib.util
import math
import os
import unittest

from pivy import coin


class TestMeshGridShaderBinding(unittest.TestCase):
    def setUp(self):
        # Load MeshGridShader from source using real pivy.coin
        module_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "shaders",
            "MeshGridShader.py",
        )
        spec = importlib.util.spec_from_file_location(
            "MeshGridShader_mod", module_path
        )
        self.mod = spec.loader.load_module(spec.name)

    def test_texture_binding_is_indexed_for_indexed_faces(self):
        shader = self.mod.MeshGridShader()
        self.assertEqual(
            shader.coord_binding.value.getValue(),
            self.mod.coin.SoTextureCoordinateBinding.PER_VERTEX_INDEXED,
            "SoIndexedFaceSet + textureCoordIndex requires PER_VERTEX_INDEXED",
        )

    def test_offset_angle_uniform_exists_and_defaults_to_zero(self):
        shader = self.mod.MeshGridShader()
        self.assertEqual(shader.offset_angle.name.getValue(), "offset_angle")
        self.assertEqual(shader.offset_angle.value.getValue(), 0.0)

    def test_grid_spacing_uniform_defaults_to_10_mm(self):
        shader = self.mod.MeshGridShader()
        self.assertEqual(shader.grid_spacing_mm.name.getValue(), "grid_spacing_mm")
        self.assertEqual(shader.grid_spacing_mm.value.getValue(), 10.0)
        self.assertEqual(shader.GridSpacingMM, 10.0)

    def test_set_offset_angle_writes_radians_to_uniform(self):
        shader = self.mod.MeshGridShader()
        shader.set_offset_angle(45.0)
        self.assertAlmostEqual(shader.offset_angle.value.getValue(), math.radians(45.0))

    def _make_dummy_geometry(self):
        root = coin.SoSeparator()
        geom = coin.SoSeparator()
        geom.setName("DummyGeometry")

        coords = coin.SoCoordinate3()
        coords.point.setValues(
            0,
            4,
            [
                coin.SbVec3f(0.0, 0.0, 0.0),
                coin.SbVec3f(1.0, 0.0, 0.0),
                coin.SbVec3f(1.0, 1.0, 0.0),
                coin.SbVec3f(0.0, 1.0, 0.0),
            ],
        )

        face_set = coin.SoIndexedFaceSet()
        indices = [0, 1, 2, -1, 0, 2, 3, -1, -1]
        face_set.coordIndex.setValues(0, len(indices), indices)

        geom.addChild(coords)
        geom.addChild(face_set)
        root.addChild(geom)
        return root, geom, face_set

    def test_attach_with_controlled_dummy_geometry(self):
        shader = self.mod.MeshGridShader()
        root, geom, face_set = self._make_dummy_geometry()
        tex_coords = [
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [0.0, 1.0],
        ]

        shader.attach(root, tex_coords, 30.0)

        self.assertTrue(shader._attached)
        self.assertEqual(shader._coin_geo.getName(), "DummyGeometry")
        self.assertEqual(shader._find_coin_geometry(root).getName(), "DummyGeometry")
        self.assertAlmostEqual(shader.offset_angle.value.getValue(), math.radians(30.0))
        self.assertEqual(shader.grid_spacing_mm.value.getValue(), 10.0)
        self.assertGreaterEqual(shader.grp.getNumChildren(), 9)
        self.assertGreater(len(face_set.textureCoordIndex.getValues()), 0)


if __name__ == "__main__":
    unittest.main()
