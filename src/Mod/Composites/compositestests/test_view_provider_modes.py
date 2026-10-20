# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""View-provider display-mode contract tests.

Every view provider must offer its default display mode. A default outside
the offered set leaves the C++ ModeSwitch pointing at a nonexistent branch:
the feature's shape renders nothing (the texture plan greys out —
seen 2026-09-18, `ViewProviderTexturePlan` defaulted to "Wireframe" while
`VPCompositePart` only offered "Flat Lines").

These checks are pure Python: they run headless (no ViewObject attach).
"""

import importlib
import inspect
import pkgutil
import types
import unittest

import Composites.features as features_pkg


def iter_feature_modules():
    """Yield (module_name, module_or_None, import_error) for features/*.py.

    Modules whose import needs the GUI (e.g. taskpanels importing MatGui)
    yield None with the error — the caller must report them as skipped so
    GUI-only view providers never silently escape this contract.
    """
    for mod_info in pkgutil.iter_modules(features_pkg.__path__):
        name = f"Composites.features.{mod_info.name}"
        try:
            yield name, importlib.import_module(name), None
        except ImportError as exc:
            yield name, None, exc


def iter_view_provider_classes():
    """Yield (module, name, class) for every importable view-provider class."""
    seen = set()
    for module_name, module, _err in iter_feature_modules():
        if module is None:
            continue
        for name, cls in vars(module).items():
            if not inspect.isclass(cls):
                continue
            if not name.startswith("ViewProvider"):
                continue
            if not cls.__module__.startswith("Composites.features"):
                continue
            key = (cls.__module__, name)
            if key in seen:
                continue
            seen.add(key)
            yield module_name, name, cls


class TestViewProviderDisplayModeContract(unittest.TestCase):
    def test_feature_modules_import_headless(self):
        """Every features module must import headless, or fail ONLY because
        it needs the GUI (reported as a skip — never silently dropped)."""
        gui_only = []
        for module_name, module, err in iter_feature_modules():
            if module is None:
                self.assertIn("Gui", str(err), f"{module_name}: {err}")
                gui_only.append(module_name)
        if gui_only:
            print(f"[skip: GUI-only modules] {', '.join(sorted(gui_only))}")

    def test_default_display_mode_is_offered(self):
        for module_name, name, cls in sorted(
            iter_view_provider_classes(), key=lambda t: (t[0], t[1])
        ):
            with self.subTest(vp=name, module=module_name):
                dummy = types.SimpleNamespace()
                modes = cls.getDisplayModes(dummy, None)
                self.assertTrue(
                    modes,
                    f"{name} offers no display modes",
                )
                default = cls.getDefaultDisplayMode(dummy)
                self.assertIn(
                    default,
                    modes,
                    f"{name} defaults to '{default}' which it does not offer — "
                    "the C++ ModeSwitch points at a nonexistent branch and the "
                    "shape renders nothing",
                )


class TestViewProviderRestoreWiring(unittest.TestCase):
    """A feature must name its view provider so restore can repair the proxy.

    FreeCAD serialises the VP proxy as an int (a memory address) on save, so
    after a reload it is not a Python object and icons, claimChildren and task
    panels all break. CompositeBaseFP.onDocumentRestored re-attaches the class
    named by the feature's own ``view_provider_class``.

    Only the mould features are checked. The rest of the package has not been
    swept and still has unwired features, so asserting the contract across
    every feature would report failures this change did not create.
    """

    def test_mould_analysis_names_its_view_provider(self):
        from Composites.features.MouldAnalysis import (
            MouldAnalysisFP,
            ViewProviderMouldAnalysis,
        )

        self.assertIs(MouldAnalysisFP.view_provider_class,
                      ViewProviderMouldAnalysis)

    def test_mould_fixture_names_its_view_provider(self):
        from Composites.features.MouldFixture import (
            MouldFixtureFP,
            ViewProviderMouldFixture,
        )

        self.assertIs(MouldFixtureFP.view_provider_class,
                      ViewProviderMouldFixture)


if __name__ == "__main__":
    unittest.main(verbosity=2)
