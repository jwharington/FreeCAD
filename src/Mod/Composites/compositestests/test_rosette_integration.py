# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Integration tests for the Rosette family — must run inside a real FreeCAD.

These tests intentionally avoid any FreeCAD mocks. Run them with:

    FreeCADCmd -P <repo-root>
        Composites/compositestests/run_freecad_integration_tests.py

The iterative solves here exercise the real nextdrape C++ drape backend; each
drape solve takes ~1-2s and the rosette solver performs several evaluations,
so each test is ~10-30s.
"""

import os
import unittest

import FreeCAD

# The native drape .so lives in the install tree, not the source tree; point
# the loader at it so headless runs against src/Mod can solve.
os.environ.setdefault(
    "COMPOSITES_DRAPE_SO",
    "/home/jmw/opt/FreeCAD/.pixi/envs/default/Mod/Composites/ext/_native/"
    "Composites_drape.so",
)

import FreeCADGui  # noqa: E402

if not hasattr(FreeCADGui, "addCommand"):
    FreeCADGui.addCommand = lambda *a, **k: None  # noqa: E731

import Draft  # noqa: E402

from Composites.compositeexamples import runner as example_runner  # noqa: E402
from Composites.features.AlignFibreRosette import (  # noqa: E402
    AlignFibreRosetteFP,
    ViewProviderAlignFibreRosette,
    is_align_fibre_rosette,
)
from Composites.features.CompositeShell import is_composite_shell  # noqa: E402


class TestRosetteIntegration(unittest.TestCase):
    """Headless integration tests for the Rosette family."""

    def _close_doc_if_exists(self, doc_name):
        if doc_name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(doc_name)

    def test_align_fibre_rosette_solves_warp_through_second_point(self):
        """AlignFibreRosette solves its Angle so a warp fibre (v=0) passes
        through a second interior point on the draped shell.

        Asserts the solved angle is strictly interior and the residual
        v-coordinate is within tolerance (< 0.5 mm in fabric-pitch units).
        """
        doc_name = "Composites_AlignFibreRosetteTest"
        self._close_doc_if_exists(doc_name)

        result = example_runner.run(
            "conical_panel_segment",
            run_solver=False,
            doc=None,
            debug_options={"skip_view_providers": True},
        )
        doc = result["doc"]
        support = result["support"]
        shell = result["feature_stack"]["shell"]

        self.assertIsNotNone(shell)
        self.assertTrue(is_composite_shell(shell))

        # Force a real drape solve so the draper is valid.
        doc.recompute()
        draper = shell.Proxy.get_draper()
        self.assertIsNotNone(draper)
        self.assertTrue(draper.is_valid())

        # Interior second point: diagonally offset from the rosette origin
        # (face parametric centre) so the solved angle is strictly interior,
        # well inside the drape region so v varies smoothly with angle.
        face = support.Shape.Face1
        u0, u1, v0, v1 = face.ParameterRange
        um = (u0 + u1) / 2.0
        vm = (v0 + v1) / 2.0
        du = (u1 - u0) * 0.10
        dv = (v1 - v0) * 0.15
        p_second = face.valueAt(um + du, vm + dv)

        point_obj = Draft.make_point(p_second)
        point_obj.Label = "AlignSecondPoint"
        doc.recompute()

        # Sanity: v at the second point with the default rosette (angle 0)
        # is non-trivial (otherwise there is nothing to solve).
        tc0 = draper.get_tex_coord_at_point(p_second, 0)
        self.assertNotAlmostEqual(float(tc0[1]), 0.0, places=1)

        # Build the AlignFibreRosette and make it the shell's rosette so its
        # Angle drives the shell's drape.
        align = doc.addObject("App::FeaturePython", "AlignFibreRosette")
        AlignFibreRosetteFP(align, support=(support, ["Face1"]))
        if getattr(align, "ViewObject", None) is not None:
            ViewProviderAlignFibreRosette(align.ViewObject)
        doc.recompute()

        self.assertTrue(is_align_fibre_rosette(align))

        shell.Rosette = align
        align.CompositeShell = shell
        doc.recompute()

        # The rosette starts at the default angle (0).
        self.assertAlmostEqual(float(align.Angle), 0.0, places=6)

        # Setting SecondPoint triggers the iterative solve (CompositeShell +
        # Support already set). The solved angle is written back to Angle.
        align.SecondPoint = (point_obj, ["Vertex1"])

        solved_angle = float(align.Angle)

        # Verify: with the solved angle, v at the second point ~ 0.
        doc.recompute()
        draper2 = shell.Proxy.get_draper()
        tc = draper2.get_tex_coord_at_point(p_second, 0)
        v_val = float(tc[1])

        # The solved angle must be non-trivial and strictly interior (not a
        # bracket boundary) and the residual must be ~0.
        self.assertGreater(abs(solved_angle), 1.0)
        self.assertLess(abs(solved_angle), 89.0)
        self.assertLess(abs(v_val), 0.5)

        # ── Rehydrate round-trip: save/close/reopen/recompute ─────
        # The solved Angle is persisted and must survive the round-trip,
        # and the shell's draper must rehydrate valid. (This is the
        # regression test for the restore crash where onChanged fired the
        # iterative solve during document restore.)
        path = os.path.join(
            os.path.dirname(__file__), "_rosette_rehydrate_tmp.FCStd"
        )
        doc.saveAs(path)
        align_name = align.Name
        shell_name = shell.Name
        point_name = point_obj.Name
        actual_doc_name = doc.Name
        FreeCAD.closeDocument(actual_doc_name)

        doc2 = FreeCAD.openDocument(path)
        doc2.recompute()

        align2 = doc2.getObject(align_name)
        shell2 = doc2.getObject(shell_name)
        self.assertIsNotNone(align2)
        self.assertIsNotNone(shell2)
        self.assertAlmostEqual(
            float(align2.Angle), solved_angle, places=4
        )
        self.assertTrue(shell2.Proxy.get_draper().is_valid())
        point2 = doc2.getObject(point_name)
        tc2 = shell2.Proxy.get_draper().get_tex_coord_at_point(
            point2.Shape.Point, 0
        )
        self.assertLess(abs(float(tc2[1])), 0.5)

        try:
            os.remove(path)
        except OSError:
            pass
        # FreeCAD also writes a timestamped .FCBak backup next to the save.
        import glob
        for bak in glob.glob(os.path.splitext(path)[0] + ".*.FCBak"):
            try:
                os.remove(bak)
            except OSError:
                pass
        FreeCAD.closeDocument(doc2.Name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
