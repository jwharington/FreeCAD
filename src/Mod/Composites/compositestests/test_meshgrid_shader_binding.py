# SPDX-License-Identifier: LGPL-2.1-or-later

"""Regression test scaffold for MeshGridShader texcoord binding.

This guards against a subtle rendering regression where texcoords appeared to
reset per triangle (chevron artifacts) when using SoIndexedFaceSet +
textureCoordIndex with PER_VERTEX binding.
"""

import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import MagicMock


class TestMeshGridShaderBinding(unittest.TestCase):
    def setUp(self):
        # Minimal pivy.coin mock for importing MeshGridShader in isolation
        coin = MagicMock()
        pivy = types.ModuleType("pivy")
        pivy.coin = coin
        sys.modules["pivy"] = pivy
        sys.modules["pivy.coin"] = coin

        module_path = os.path.join(
            os.path.dirname(__file__), "..", "shaders", "MeshGridShader.py"
        )
        module_path = os.path.abspath(module_path)
        spec = importlib.util.spec_from_file_location("MeshGridShader_mod", module_path)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)

        self.coin = coin
        self.mod = mod

    def test_texture_binding_is_indexed_for_indexed_faces(self):
        shader = self.mod.MeshGridShader()
        self.assertEqual(
            shader.coord_binding.value,
            self.coin.SoTextureCoordinateBinding.PER_VERTEX_INDEXED,
            "SoIndexedFaceSet + textureCoordIndex requires PER_VERTEX_INDEXED",
        )


if __name__ == "__main__":
    unittest.main()
