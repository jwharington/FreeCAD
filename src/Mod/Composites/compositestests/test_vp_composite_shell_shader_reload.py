# SPDX-License-Identifier: LGPL-2.1-or-later

"""Tests for CompositeShell shader reload/orientation update behavior."""

import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import MagicMock


class _FakeCoin:
    SO_SWITCH_NONE = -1


class _FakeLaminate:
    def __init__(self, stack_orientation):
        self.StackOrientation = stack_orientation


class _FakeFeature:
    def __init__(self, display_layer, stack_orientation):
        self.ViewObject = types.SimpleNamespace(DisplayLayer=display_layer)
        self.Laminate = _FakeLaminate(stack_orientation)


class _FakeShader:
    def __init__(self, attached=True):
        self._attached = attached
        self.calls = []

    def set_offset_angle(self, value):
        self.calls.append(value)


class TestVPCompositeShellShaderReload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pivy_mod = types.ModuleType("pivy")
        pivy_mod.coin = _FakeCoin()
        sys.modules["pivy"] = pivy_mod
        sys.modules["pivy.coin"] = pivy_mod.coin

        composites_pkg = types.ModuleType("Composites")
        composites_pkg.COMPOSITE_SHELL_TOOL_ICON = "icon"
        composites_pkg.__path__ = []
        sys.modules["Composites"] = composites_pkg

        features_pkg = types.ModuleType("Composites.features")
        features_pkg.__path__ = []
        sys.modules["Composites.features"] = features_pkg

        module_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "features",
                "VPCompositeShell.py",
            )
        )
        spec = importlib.util.spec_from_file_location(
            "Composites.features.VPCompositeShell",
            module_path,
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)

        cls.mod = mod
        cls.ViewProviderCompositeShell = mod.ViewProviderCompositeShell

    def _make_vp(self, feature, shader_attached=True):
        vp = self.ViewProviderCompositeShell.__new__(self.ViewProviderCompositeShell)
        vp.Object = feature
        vp.grid_shader = _FakeShader(attached=shader_attached)
        vp._last_offset_angle_deg = None
        vp.reload_shader = MagicMock()
        return vp

    def test_get_offset_angle_accepts_string_keys_and_values(self):
        feature = _FakeFeature(display_layer=1, stack_orientation={"1": "+045"})
        vp = self._make_vp(feature)

        self.assertEqual(vp.get_offset_angle(feature), 45.0)

    def test_display_layer_change_updates_orientation_without_reload(self):
        feature = _FakeFeature(display_layer="L2", stack_orientation={"L2": "+030"})
        view_obj = types.SimpleNamespace(Object=feature)
        vp = self._make_vp(feature, shader_attached=True)

        vp.onChanged(view_obj, "DisplayLayer")

        self.assertEqual(vp.grid_shader.calls, [30.0])
        vp.reload_shader.assert_not_called()

    def test_display_layer_change_falls_back_to_reload_when_not_attached(self):
        feature = _FakeFeature(display_layer="L2", stack_orientation={"L2": "+030"})
        view_obj = types.SimpleNamespace(Object=feature)
        vp = self._make_vp(feature, shader_attached=False)

        vp.onChanged(view_obj, "DisplayLayer")

        self.assertEqual(vp.grid_shader.calls, [])
        vp.reload_shader.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
