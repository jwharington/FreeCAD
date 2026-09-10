# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com
"""Smoke tests for the compositeexamples framework.

Uses real FreeCAD objects — no mocks — consistent with the Composites
testing philosophy.
"""

import os
import sys
import tempfile
import unittest
import zipfile

import FreeCAD  # noqa: E402

# ---------------------------------------------------------------------------
# Ensure repo root is on sys.path so package imports work.
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from Composites.compositeexamples import registry, runner  # noqa: E402
from Composites.compositeexamples.examples import (  # noqa: E402
    _shell_example_common,
    closed_ring_composite_shell,
    conical_panel_segment,
    cyl_sphere_seam,
    tubular_shell,
)


def _mode_switches(root_node):
    """All SoSwitch nodes under a ViewObject RootNode, depth-first."""
    from pivy import coin

    switches = []

    def walk(node):
        if node is None:
            return
        try:
            if node.getTypeId().isDerivedFrom(coin.SoSwitch.getClassTypeId()):
                switches.append(node)
        except AttributeError:
            return
        try:
            children = int(node.getNumChildren())
        except AttributeError:
            return
        for i in range(children):
            walk(node.getChild(i))

    walk(root_node)
    return switches


def _rosette_mode_switch(vobj):
    """The rosette VP's display-mode Switch — the one holding the named
    Standard branch (ViewProviderRosette names its mode group so the
    switch can be found across pivy wrapper identities)."""
    for switch in _mode_switches(vobj.RootNode):
        try:
            children = int(switch.getNumChildren())
        except Exception:
            continue
        for i in range(children):
            if (switch.getChild(i).getName() or "") == "RosetteStandardMode":
                return switch
    return None


def _assert_rosette_switches_visible(self, doc):
    """Every rosette VP's display-mode Switch must point at its symbol.

    Pin for the rosette-VP attach race: the rosette symbol lives in the
    Standard display mode behind the VP's mode Switch — a whichChild of
    NONE (-1) leaves the node in the scene graph but nothing rendered,
    which is exactly how the attach race presented.  Other switches
    under the RootNode (hidden datum/indicator symbology) are
    legitimately NONE and are not asserted.
    """
    from Composites.features.Rosette import ViewProviderRosette

    rosettes = [
        obj
        for obj in doc.Objects
        if isinstance(
            getattr(getattr(obj, "ViewObject", None), "Proxy", None),
            ViewProviderRosette,
        )
    ]
    self.assertTrue(rosettes, "no rosette view providers in the scene")
    for rosette in rosettes:
        switch = _rosette_mode_switch(rosette.ViewObject)
        self.assertIsNotNone(
            switch,
            f"{rosette.Name}: no display Switch holding the Standard branch",
        )
        self.assertEqual(
            switch.whichChild.getValue(),
            0,
            f"{rosette.Name}: display Switch not pointing at the symbol",
        )


class TestCompositeExamplesBase(unittest.TestCase):
    """Base class with automatic .FCStd file generation."""

    save_fcstd = True

    def tearDown(self):
        """Save .FCStd file after each test and close document."""
        try:
            if self.save_fcstd:
                docs = FreeCAD.listDocuments()
                if docs:
                    doc_name = list(docs.keys())[0]
                    filepath = os.path.join(
                        tempfile.gettempdir(),
                        f"{self.__class__.__name__}_{self._testMethodName}.FCStd",
                    )
                    doc = docs[doc_name]
                    doc.saveAs(filepath)
                    print(f"Saved: {filepath}")
            for doc_name in list(FreeCAD.listDocuments()):
                try:
                    FreeCAD.closeDocument(doc_name)
                except Exception:
                    pass
        except Exception as exc:
            print(f"Teardown error in {self._testMethodName}: {exc}")


class TestCompositeExamplesRegistry(TestCompositeExamplesBase):
    def test_list_examples_is_sorted(self):
        examples = registry.list_examples()
        self.assertEqual(examples, sorted(examples))
        self.assertIn("ud_plate_basic", examples)
        self.assertIn("quasi_iso_laminate_plate", examples)
        self.assertIn("tubular_shell", examples)
        self.assertIn("cylindrical_panel_segment", examples)
        self.assertIn("closed_ring_composite_shell", examples)
        self.assertIn("conical_panel_segment", examples)

    def test_get_example_module_unknown_raises(self):
        with self.assertRaises(ValueError) as ctx:
            registry.get_example_module("does_not_exist")

        msg = str(ctx.exception)
        self.assertIn("Unknown example 'does_not_exist'", msg)
        self.assertIn("Available examples", msg)


class TestCompositeExamplesRunner(TestCompositeExamplesBase):
    """Test runner plumbing with real FreeCAD geometry."""

    def test_run_calls_example_build(self):
        """runner.run delegates to the example's build function."""
        result = runner.run("ud_plate_basic", run_solver=False, doc=None)
        self._saved_doc = result.get("doc")

        self.assertIn("laminate", result)
        self.assertIsNotNone(result["laminate"])

    def test_run_forwards_run_solver_flag(self):
        """run_solver=True still succeeds (geometry only, no solver)."""
        result = runner.run("ud_plate_basic", run_solver=True, doc=None)
        self._saved_doc = result.get("doc")

        self.assertIn("laminate", result)
        self.assertIsNotNone(result["laminate"])


class TestFailurePostprocess(TestCompositeExamplesBase):
    def test_evaluate_failure_criteria_returns_hotspots(self):
        import types

        result_obj = types.SimpleNamespace(
            TypeId="Fem::FemResultMechanical",
            Name="ResultMechanical",
            PropertiesList=["StressXX", "StressYY", "StressXY"],
            StressXX={1: 100.0, 2: 250.0},
            StressYY={1: 10.0, 2: 25.0},
            StressXY={1: 5.0, 2: 12.0},
        )
        analysis = types.SimpleNamespace(Group=[result_obj])

        report = _shell_example_common.evaluate_failure_criteria(analysis)

        self.assertTrue(report["available"])
        self.assertGreater(report["max_failure_index"], 0.0)
        self.assertTrue(report["hotspots"])
        self.assertEqual(report["hotspots"][0]["element_id"], 2)


class TestSeamExampleBuildSolves(TestCompositeExamplesBase):
    """Known-issue #11: the seam example's transfer wiring used to drape
    the cap shell while the transfer rosette's LCS was still unplaced —
    an origin seed that failed the solve deterministically and was only
    healed by a later recompute.  The build must issue zero failed
    solves, whatever the recompute ordering heals afterwards."""

    save_fcstd = False

    def test_seam_example_build_issues_no_failed_solves(self):
        from Composites.compositeexamples.examples import cyl_sphere_seam
        from Composites.tools import drape_backend_nextdrape

        failures = []
        original = drape_backend_nextdrape.NextDrapeBackend._run_solve

        def _recording_run_solve(backend):
            result = original(backend)
            if not result.get("success"):
                failures.append(result.get("error", "solve failed"))
            return result

        drape_backend_nextdrape.NextDrapeBackend._run_solve = (
            _recording_run_solve
        )
        try:
            result = cyl_sphere_seam.build(doc=None)
        finally:
            drape_backend_nextdrape.NextDrapeBackend._run_solve = original

        self._saved_doc = result.get("doc")
        self.assertEqual(
            failures,
            [],
            f"example build issued {len(failures)} failed drape solve(s): "
            f"{failures}",
        )
        self.assertTrue(result["cap_shell"].DrapeValid)
        self.assertTrue(result["shell_shell"].DrapeValid)


class TestCompositeExamplesSmoke(TestCompositeExamplesBase):
    """End-to-end smoke tests using real FreeCAD geometry."""

    def test_rosette_vp_switch_survives_attach_and_raise(self):
        """Pin for the rosette-VP attach race (rosette-visibility work,
        2026-07-15): the seam example exercises both orderings — stack
        rosettes whose VPs attach BEFORE their shell exists, and transfer
        rosettes created mid-recompute (RootNode nested under a group).
        After the build, every rosette display Switch must point at its
        symbol (whichChild == 0), and raise_render_order's re-parenting
        must not reset it.
        """
        if not getattr(FreeCAD, "GuiUp", False):
            self.skipTest("GUI not available — scene graph requires MCP/GUI mode")
        result = cyl_sphere_seam.build(doc=None)
        doc = result["doc"]
        # Let the GUI's deferred new-object finalization run — it is
        # exactly what can re-derive the mode switch after attach.
        import FreeCADGui

        FreeCADGui.updateGui()
        _assert_rosette_switches_visible(self, doc)

        # raise_render_order re-parents the rosette RootNode to the end
        # of the scene graph; the display Switch must survive the move.
        from Composites.features.Rosette import ViewProviderRosette

        for obj in doc.Objects:
            proxy = getattr(getattr(obj, "ViewObject", None), "Proxy", None)
            if isinstance(proxy, ViewProviderRosette):
                proxy.raise_render_order()
        _assert_rosette_switches_visible(self, doc)

    def test_tubular_shell_builds(self):
        """tubular_shell builds successfully with real FreeCAD objects."""
        result = tubular_shell.build(doc=None, run_solver=False)
        self._saved_doc = result.get("doc")
        self.assertIn("laminate", result)
        self.assertIsNotNone(result["laminate"])

    def test_closed_ring_shell_drapes_single_cover(self):
        """Composite shell on a full closed ring: the drape covers the ring
        exactly once (periodic seam stop, seed relocated off the seam) and
        the texture plan unwraps without laps."""
        result = closed_ring_composite_shell.build(doc=None)
        self._saved_doc = result.get("doc")
        shell = result["shell"]
        self.assertTrue(shell.DrapeValid)
        # Single cover: no meet-line holes, seam = the only joint.
        plan = result.get("texture_plan")
        self.assertIsNotNone(plan)
        self.assertGreater(len(plan.Shape.Edges), 0)

    def test_conical_panel_full_pipeline_round_trip(self):
        """The conical panel example drives the full drape-to-FEM pipeline."""
        try:
            result = runner.run(
                "conical_panel_segment",
                run_solver=True,
                doc=None,
                debug_options={"skip_view_providers": True},
            )
        except RuntimeError as exc:
            msg = str(exc)
            missing_stack_markers = (
                "ObjectsFem is required",
                "Unable to create FEM analysis/solver/mesh objects",
                "Mesh generation failed",
            )
            if any(marker in msg for marker in missing_stack_markers):
                self.skipTest(
                    f"FEM stack unavailable in this FreeCAD build: {msg}",
                )
            raise

        self._saved_doc = result.get("doc")
        shell = result.get("feature_stack", {}).get("shell")
        fem_job = result.get("fem_job")
        self.assertIsNotNone(shell)
        self.assertTrue(shell.DrapeValid)
        self.assertTrue(shell.Proxy._can_use_persisted(shell))
        self.assertIsNotNone(fem_job)
        self.assertIsNotNone(fem_job.get("analysis"))
        self.assertIsNotNone(fem_job.get("solver"))
        self.assertIsNotNone(fem_job.get("mesh"))
        self.assertIsNotNone(fem_job.get("shell_section"))
        self.assertIsNotNone(fem_job.get("material"))

        for key in ("shell_section", "material"):
            refs = getattr(fem_job[key], "References", None)
            self.assertTrue(refs, msg=f"{key} missing shell reference")
            self.assertEqual(refs[0][0].Name, shell.Name)
            ref_sub = refs[0][1]
            if isinstance(ref_sub, (tuple, list)):
                ref_sub = ref_sub[0]
            self.assertEqual(ref_sub, "Face1")

        doc = result["doc"]
        path = os.path.join(
            tempfile.gettempdir(),
            f"{self.__class__.__name__}_{self._testMethodName}.FCStd",
        )
        doc.saveAs(path)

        with zipfile.ZipFile(path) as archive:
            xml = archive.read("Document.xml").decode("utf-8", errors="ignore")
            for prop_name in (
                "TexCoordsJSON",
                "NodePositionsJSON",
                "QuadsJSON",
                "StrainsJSON",
                "QualityJSON",
                "ShapeFingerprint",
                "_LastRosetteAngle",
                "_LastDrapePitch",
                "_DrapeCutsFingerprint",
            ):
                self.assertNotIn(prop_name, xml)

        doc_name = doc.Name
        shell_name = shell.Name
        FreeCAD.closeDocument(doc_name)

        reopened = FreeCAD.openDocument(path)
        try:
            reopened.recompute()
            shell2 = reopened.getObject(shell_name)
            self.assertIsNotNone(shell2)
            self.assertTrue(shell2.DrapeValid)
            self.assertTrue(shell2.Proxy._can_use_persisted(shell2))
        finally:
            try:
                reopened.close()
            except Exception:
                pass
            if os.path.exists(path):
                os.remove(path)
            import glob

            for bak in glob.glob(os.path.splitext(path)[0] + ".*.FCBak"):
                try:
                    os.remove(bak)
                except OSError:
                    pass

    def test_conical_panel_uses_shader_only_scene_graph(self):
        """The conical panel example keeps the shader scene graph mesh-free."""
        if not getattr(FreeCAD, "GuiUp", False):
            self.skipTest("GUI not available — scene graph requires MCP/GUI mode")
        result = conical_panel_segment.build(doc=None, run_solver=False)
        shell = result.get("feature_stack", {}).get("shell")
        self.assertIsNotNone(shell)

        vp = getattr(shell.ViewObject, "Proxy", None)
        mode_switch = getattr(vp, "mode_switch", None)
        self.assertIsNotNone(mode_switch)
        self.assertNotEqual(mode_switch.whichChild.getValue(), -1)

        drape_host = getattr(vp, "drape_host", None)
        self.assertIsNotNone(drape_host)
        self.assertEqual(drape_host.getNumChildren(), 1)

        child = drape_host.getChild(0)
        self.assertEqual(child.getName(), "shader_state")
        self.assertEqual(child.getNumChildren(), 9)

        geometry = child.getChild(int(child.getNumChildren()) - 1)
        self.assertEqual(geometry.getName(), "SupportSurface")
        self.assertEqual(geometry.getTypeId().getName(), "Separator")
        self.assertEqual(geometry.getNumChildren(), 3)

        child_names = []
        for i in range(int(drape_host.getNumChildren())):
            child_names.append(drape_host.getChild(i).getName())
        self.assertNotIn("DrapedMeshGeometry", child_names)

    def test_conical_panel_can_hide_drape_mesh(self):
        """The debug toggle must not hide the support surface or restore the drape mesh."""
        if not getattr(FreeCAD, "GuiUp", False):
            self.skipTest("GUI not available — scene graph requires MCP/GUI mode")
        result = conical_panel_segment.build(
            doc=None,
            run_solver=False,
            debug_options={"hide_drape_mesh": True},
        )
        shell = result.get("feature_stack", {}).get("shell")
        self.assertIsNotNone(shell)
        vp = getattr(shell.ViewObject, "Proxy", None)
        mode_switch = getattr(vp, "mode_switch", None)
        self.assertIsNotNone(mode_switch)
        # The support surface (native display branch) must remain visible.
        self.assertNotEqual(mode_switch.whichChild.getValue(), -1)

        drape_host = getattr(vp, "drape_host", None)
        self.assertIsNotNone(drape_host)
        self.assertEqual(drape_host.getNumChildren(), 1)

        shader_state = drape_host.getChild(0)
        self.assertEqual(shader_state.getName(), "shader_state")
        self.assertEqual(shader_state.getNumChildren(), 9)
        geometry = shader_state.getChild(int(shader_state.getNumChildren()) - 1)
        self.assertEqual(geometry.getName(), "SupportSurface")
        self.assertEqual(geometry.getTypeId().getName(), "Separator")
        self.assertEqual(geometry.getNumChildren(), 3)

        child_names = []
        for i in range(int(drape_host.getNumChildren())):
            child_names.append(drape_host.getChild(i).getName())
        self.assertNotIn("DrapedMeshGeometry", child_names)

    def test_all_examples_build(self):
        """Every example builds successfully with run_solver=False."""
        for example_id in registry.list_examples():
            with self.subTest(example=example_id):
                result = runner.run(example_id, run_solver=False, doc=None)
                self._saved_doc = result.get("doc")
                self.assertIn("doc", result)
                self.assertIsNotNone(result["doc"])
                if "laminate" in result:
                    self.assertIsNotNone(result["laminate"])


if __name__ == "__main__":
    unittest.main(verbosity=2)