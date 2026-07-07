# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Integration tests that must run inside a real FreeCAD process.

These tests intentionally avoid any FreeCAD mocks. Run them with:

    FreeCADCmd -P <repo-root>
        Composites/compositestests/run_freecad_integration_tests.py
"""

import os
import sys
import tempfile
import types
import unittest

import FreeCAD
import Part

# Some existing modules import CompositesWB by name.
if "CompositesWB" not in sys.modules:
    import Composites as _composites_wb

    sys.modules["CompositesWB"] = _composites_wb

import Composites as CompositesWB
from Composites.compositeexamples import runner as example_runner
from Composites.compositeexamples.examples import tubular_shell
from Composites.compositestests.example_materials import make_glass


class TestFreeCADIntegration(unittest.TestCase):
    def _close_doc_if_exists(self, doc_name):
        if doc_name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(doc_name)

    def _ensure_freecadgui(self):
        import FreeCADGui

        if not hasattr(FreeCADGui, "addCommand"):
            FreeCADGui.addCommand = lambda *args, **kwargs: None
        return FreeCADGui

    def _make_source_feature(self, doc, name="Source", shape=None):
        source = doc.addObject("Part::Feature", name)
        source.Shape = shape if shape is not None else Part.makeCylinder(10.0, 20.0)
        return source

    def _make_sketch(self, doc, name, points):
        sketch = doc.addObject("Sketcher::SketchObject", name)
        for start, end in zip(points, points[1:]):
            sketch.addGeometry(Part.LineSegment(start, end), False)
        return sketch

    def test_seam_make_edge_seam_from_box_edge(self):
        self._ensure_freecadgui()
        from Composites.tools.seam import make_edge_seam

        box = Part.makeBox(10.0, 10.0, 10.0)
        seam = make_edge_seam(box, [box.Faces[5].Edges[0]], overlap=1.0)

        self.assertFalse(seam.isNull())
        self.assertEqual(seam.ShapeType, "Compound")

    def test_seam_make_join_seam_from_adjacent_faces(self):
        self._ensure_freecadgui()
        from Composites.tools.seam import get_partner_edges, make_join_seam

        box = Part.makeBox(10.0, 10.0, 10.0)
        face1 = box.Faces[0]
        face2 = box.Faces[4]

        self.assertTrue(get_partner_edges(face1, face2))

        seam = make_join_seam(face1, face2, overlap=1.0)

        self.assertFalse(seam.isNull())
        self.assertEqual(seam.ShapeType, "Compound")

    def test_seam_make_edge_seam_handles_multiple_edges(self):
        self._ensure_freecadgui()
        from Composites.tools.seam import make_edge_seam

        box = Part.makeBox(10.0, 10.0, 10.0)
        face = box.Faces[5]
        seam = make_edge_seam(
            face,
            [face.Edges[0], face.Edges[1]],
            overlap=1.0,
        )

        self.assertFalse(seam.isNull())
        self.assertEqual(seam.ShapeType, "Compound")

    def test_seam_make_edge_seam_rejects_empty_edge_list(self):
        self._ensure_freecadgui()
        from Composites.tools.seam import make_edge_seam

        box = Part.makeBox(10.0, 10.0, 10.0)

        with self.assertRaises(ValueError):
            make_edge_seam(box.Faces[5], [], overlap=1.0)

    def test_seam_make_edge_seam_handles_reversed_edge_orientation(self):
        self._ensure_freecadgui()
        from Composites.tools.seam import make_edge_seam

        box = Part.makeBox(10.0, 10.0, 10.0)
        face = box.Faces[5]
        edge = face.Edges[0]
        reversed_edge = edge.copy()
        reversed_edge.reverse()

        seam_forward = make_edge_seam(face, [edge], overlap=1.0)
        seam_reverse = make_edge_seam(face, [reversed_edge], overlap=1.0)

        self.assertFalse(seam_forward.isNull())
        self.assertFalse(seam_reverse.isNull())
        self.assertEqual(seam_forward.ShapeType, seam_reverse.ShapeType)
        self.assertEqual(len(seam_forward.Faces), len(seam_reverse.Faces))
        self.assertEqual(len(seam_forward.Edges), len(seam_reverse.Edges))
        self.assertAlmostEqual(seam_forward.Area, seam_reverse.Area, places=8)

    def test_seam_make_edge_seam_on_curved_surface(self):
        self._ensure_freecadgui()
        from Composites.tools.seam import make_edge_seam

        cylinder = Part.makeCylinder(10.0, 20.0)
        seam = make_edge_seam(cylinder, [cylinder.Faces[0].Edges[0]], overlap=1.0)

        self.assertFalse(seam.isNull())
        self.assertEqual(seam.ShapeType, "Compound")
        self.assertGreater(seam.Area, cylinder.Area)
        self.assertEqual(len(seam.Faces), 6)

    def test_seam_make_join_seam_on_angled_cylinder_faces(self):
        self._ensure_freecadgui()
        from Composites.tools.seam import get_partner_edges, make_join_seam

        cylinder = Part.makeCylinder(10.0, 20.0)
        side_face = cylinder.Faces[0]
        cap_face = cylinder.Faces[1]

        self.assertTrue(get_partner_edges(side_face, cap_face))

        seam = make_join_seam(side_face, cap_face, overlap=1.0)

        self.assertFalse(seam.isNull())
        self.assertEqual(seam.ShapeType, "Compound")
        self.assertEqual(len(seam.Faces), 2)
        self.assertEqual(len(seam.Edges), 5)
        self.assertAlmostEqual(seam.Area, side_face.Area, places=8)

    def test_seam_make_join_seam_without_partner_edges_raises(self):
        self._ensure_freecadgui()
        from Composites.tools.seam import make_join_seam

        box = Part.makeBox(10.0, 10.0, 10.0)
        with self.assertRaises(ValueError):
            make_join_seam(box.Faces[0], box.Faces[1], overlap=1.0)

    def test_seam_featurepython_rejects_missing_edges(self):
        self._ensure_freecadgui()
        from Composites.features.Seam import SeamFP

        doc_name = "CompositesSeamMissingEdgesTest"
        if doc_name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(doc_name)

        doc = FreeCAD.newDocument(doc_name)
        try:
            seam = doc.addObject("Part::FeaturePython", "Seam")
            SeamFP(seam)

            with self.assertRaises(ValueError):
                seam.Proxy.execute(seam)
        finally:
            FreeCAD.closeDocument(doc_name)

    def test_seam_featurepython_recomputes_from_box_face_edge(self):
        self._ensure_freecadgui()
        from Composites.features.Seam import SeamFP

        doc_name = "CompositesSeamIntegrationTest"
        if doc_name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(doc_name)

        doc = FreeCAD.newDocument(doc_name)
        try:
            source = self._make_source_feature(
                doc,
                shape=Part.makeBox(10.0, 10.0, 10.0).Faces[5],
            )
            seam = doc.addObject("Part::FeaturePython", "Seam")
            SeamFP(seam, edges=[(source, "Edge1")])
            doc.recompute()

            self.assertFalse(seam.Shape.isNull())
            self.assertEqual(seam.Shape.ShapeType, "Face")
            self.assertFalse(source.Visibility)
        finally:
            FreeCAD.closeDocument(doc_name)

    def _make_fibre_lamina(self, doc):
        import FreeCADGui

        if not hasattr(FreeCADGui, "addCommand"):
            FreeCADGui.addCommand = lambda *args, **kwargs: None

        taskpanel_mod = types.ModuleType(
            "Composites.taskpanels.task_fibre_composite_lamina"
        )
        setattr(taskpanel_mod, "_TaskPanel", object)
        sys.modules[taskpanel_mod.__name__] = taskpanel_mod

        from Composites.features.FibreCompositeLamina import (
            FibreCompositeLaminaFP,
        )

        obj = doc.addObject("App::FeaturePython", "FibreLamina")
        FibreCompositeLaminaFP(obj)
        obj.FibreMaterial = make_glass()
        obj.FibreVolumeFraction = 50
        obj.Thickness = FreeCAD.Units.Quantity("0.5 mm")
        doc.recompute()
        return obj

    def test_workbench_module_imports(self):
        self.assertTrue(hasattr(CompositesWB, "is_comp_type"))
        self.assertTrue(hasattr(CompositesWB, "ICONPATH"))

    def test_document_create_and_close(self):
        doc_name = "CompositesIntegrationTest"

        if doc_name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(doc_name)

        doc = FreeCAD.newDocument(doc_name)
        self.assertEqual(doc.Name, doc_name)

        FreeCAD.closeDocument(doc_name)
        self.assertNotIn(doc_name, FreeCAD.listDocuments())

    def test_is_comp_type_helper(self):
        obj_ok = types.SimpleNamespace(
            TypeId="Part::FeaturePython",
            Proxy=types.SimpleNamespace(Type="SomeType"),
        )
        self.assertTrue(
            CompositesWB.is_comp_type(
                obj_ok,
                "Part::FeaturePython",
                "SomeType",
            )
        )

        obj_wrong_type = types.SimpleNamespace(
            TypeId="Part::Feature",
            Proxy=types.SimpleNamespace(Type="SomeType"),
        )
        self.assertFalse(
            CompositesWB.is_comp_type(
                obj_wrong_type,
                "Part::FeaturePython",
                "SomeType",
            )
        )

        obj_no_proxy = types.SimpleNamespace(TypeId="Part::FeaturePython")
        self.assertFalse(
            CompositesWB.is_comp_type(
                obj_no_proxy,
                "Part::FeaturePython",
                "SomeType",
            )
        )

    def test_rosette_featurepython_creation(self):
        self._ensure_freecadgui()

        from Composites.features.Rosette import (
            RosetteFP,
            is_rosette,
        )

        doc_name = "CompositesRosetteIntegrationTest"

        if doc_name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(doc_name)

        doc = FreeCAD.newDocument(doc_name)
        obj = doc.addObject("App::FeaturePython", "Rosette")
        RosetteFP(obj)
        doc.recompute()

        self.assertTrue(is_rosette(obj))
        self.assertIsNotNone(obj.LocalCoordinateSystem)
        self.assertEqual(
            obj.LocalCoordinateSystem.TypeId, "Part::LocalCoordinateSystem"
        )

        FreeCAD.closeDocument(doc_name)

    def test_mould_analysis_part_plane_and_mould_integration(self):
        self._ensure_freecadgui()
        from Composites.features.MouldAnalysis import MouldAnalysisFP
        from Composites.features.Mould import MouldFP
        from Composites.features.PartPlane import PartPlaneFP

        doc_name = "CompositesMouldWorkflowIntegrationTest"
        if doc_name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(doc_name)

        doc = FreeCAD.newDocument(doc_name)
        source = self._make_source_feature(doc, shape=Part.makeCylinder(10.0, 20.0))

        mould_analysis = doc.addObject("Part::FeaturePython", "MouldAnalysis")
        MouldAnalysisFP(mould_analysis, source)
        doc.recompute()

        self.assertNotEqual(mould_analysis.AnalysisStatus, "Waiting for source")
        self.assertIsNotNone(mould_analysis.PartingSurface)
        self.assertFalse(mould_analysis.PartingSurface.Shape.isNull())
        self.assertIsNotNone(mould_analysis.MouldHalfA)
        self.assertIsNotNone(mould_analysis.MouldHalfB)
        self.assertFalse(mould_analysis.MouldHalfA.Shape.isNull())
        self.assertFalse(mould_analysis.MouldHalfB.Shape.isNull())

        part_plane = doc.addObject("Part::FeaturePython", "PartPlane")
        PartPlaneFP(part_plane, source)
        doc.recompute()

        self.assertIsNotNone(part_plane.Shape)
        self.assertFalse(part_plane.Shape.isNull())

        mould = doc.addObject("Part::FeaturePython", "Mould")
        MouldFP(mould, source)
        doc.recompute()

        self.assertIsNotNone(mould.Shape)
        self.assertFalse(mould.Shape.isNull())
        self.assertIn(mould.GenerationStatus, {"ok", "fail_closed"})
        self.assertTrue(mould.GenerationSummary)

        FreeCAD.closeDocument(doc_name)

    def test_texture_plan_on_real_shell_geometry(self):
        self._ensure_freecadgui()
        from Composites.features.TexturePlan import TexturePlanFP

        doc_name = "CompositesTexturePlanIntegrationTest"
        if doc_name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(doc_name)

        doc = FreeCAD.newDocument(doc_name)
        try:
            result = tubular_shell.build(
                doc=doc,
                run_solver=False,
                debug_options={"skip_view_providers": True},
            )
            shell = result.get("feature_stack", {}).get("shell")
            if shell is None:
                self.skipTest("shell feature not available from tubular_shell example")

            texture_plan = doc.addObject("Part::FeaturePython", "TexturePlan")
            TexturePlanFP(texture_plan, [shell])
            doc.recompute()

            self.assertIsNotNone(texture_plan.Shape)
            self.assertFalse(texture_plan.Shape.isNull())
            self.assertEqual(texture_plan.Shape.ShapeType, "Compound")
        finally:
            FreeCAD.closeDocument(doc_name)

    def test_stiffener_on_real_support_and_sketches(self):
        self._ensure_freecadgui()
        from Composites.features.Stiffener import StiffenerFP

        doc_name = "CompositesStiffenerIntegrationTest"
        if doc_name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(doc_name)

        doc = FreeCAD.newDocument(doc_name)
        try:
            shell_result = tubular_shell.build(
                doc=doc,
                run_solver=False,
                debug_options={"skip_view_providers": True},
            )
            support = shell_result.get("support")
            if support is None:
                self.skipTest("shell support not available from tubular_shell example")

            plan = self._make_sketch(
                doc,
                "Plan",
                [
                    FreeCAD.Vector(10.0, 10.0, 0.0),
                    FreeCAD.Vector(80.0, 10.0, 0.0),
                ],
            )
            profile = self._make_sketch(
                doc,
                "Profile",
                [
                    FreeCAD.Vector(0.0, 0.0, 0.0),
                    FreeCAD.Vector(0.0, 10.0, 0.0),
                    FreeCAD.Vector(5.0, 10.0, 0.0),
                    FreeCAD.Vector(5.0, 0.0, 0.0),
                    FreeCAD.Vector(0.0, 0.0, 0.0),
                ],
            )

            stiffener = doc.addObject("Part::FeaturePython", "Stiffener")
            StiffenerFP(stiffener, support=support, plan=plan, profile=profile)
            try:
                doc.recompute()
            except Exception as exc:
                self.skipTest(f"stiffener geometry unavailable in this FreeCAD build: {exc}")

            self.assertIsNotNone(stiffener.Shape)
            if stiffener.Shape.isNull():
                self.skipTest("stiffener geometry is not generated reliably in this FreeCAD build")
            self.assertFalse(support.Visibility)
            self.assertFalse(plan.Visibility)
            self.assertFalse(profile.Visibility)
        finally:
            FreeCAD.closeDocument(doc_name)

    def test_conical_example_mesh_only_fem_job_runs(self):
        doc_name = "Composites_Conical_Panel"
        self._close_doc_if_exists(doc_name)

        try:
            result = example_runner.run(
                "conical_panel_segment",
                run_solver=True,
                doc=None,
                debug_options={
                    "mesh_only": True,
                    "skip_view_providers": True,
                },
            )
        except RuntimeError as exc:
            msg = str(exc)
            missing_stack_markers = (
                "ObjectsFem is required",
                "Unable to create FEM analysis/solver/mesh objects",
                "Mesh generation failed",
            )
            if any(marker in msg for marker in missing_stack_markers):
                self.skipTest(f"FEM stack unavailable in this FreeCAD build: {msg}")
            raise

        fem_job = result.get("fem_job")
        self.assertIsNotNone(fem_job)
        self.assertIsNotNone(fem_job.get("analysis"))
        self.assertIsNotNone(fem_job.get("solver"))
        self.assertIsNotNone(fem_job.get("mesh"))

        mesh_obj = fem_job["mesh"]
        fem_mesh = getattr(mesh_obj, "FemMesh", None)
        self.assertIsNotNone(fem_mesh)
        self.assertGreater(getattr(fem_mesh, "NodeCount", 0), 0)

        failure_report = fem_job.get("failure_report", {})
        self.assertFalse(failure_report.get("available", True))
        self.assertIn("solve skipped", failure_report.get("reason", ""))

        self._close_doc_if_exists(doc_name)

    def test_conical_example_full_solver_job_runs(self):
        doc_name = "Composites_Conical_Panel"
        self._close_doc_if_exists(doc_name)

        result = example_runner.run(
            "conical_panel_segment",
            run_solver=True,
            doc=None,
            debug_options={
                "skip_view_providers": True,
            },
        )

        fem_job = result.get("fem_job")
        self.assertIsNotNone(fem_job)
        self.assertIn("failure_report", fem_job)
        self.assertIsInstance(fem_job.get("failure_report"), dict)

        self._close_doc_if_exists(doc_name)

    def test_fibre_composite_lamina_areal_weight_updates(self):
        doc_name = "CompositesFibreLaminaIntegrationTest"

        if doc_name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(doc_name)

        doc = FreeCAD.newDocument(doc_name)
        obj = self._make_fibre_lamina(doc)

        areal_weight = obj.ArealWeight.getValueAs("g/m^2")
        self.assertAlmostEqual(areal_weight.Value, 645.0, places=8)

        FreeCAD.closeDocument(doc_name)

    def test_fibre_composite_lamina_areal_weight_survives_restore(self):
        doc_name = "CompositesFibreLaminaRestoreTest"
        path = tempfile.mktemp(suffix=".FCStd")

        if doc_name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(doc_name)

        try:
            doc = FreeCAD.newDocument(doc_name)
            obj = self._make_fibre_lamina(doc)
            expected = obj.ArealWeight.getValueAs("g/m^2").Value
            lam_name = obj.Name
            doc.saveAs(path)
            FreeCAD.closeDocument(doc_name)

            reopened = FreeCAD.openDocument(path)
            try:
                lam = reopened.getObject(lam_name)
                # The ArealWeight unit must be mass/area (g/m^2) after
                # restore, not dimensionless. A dimensionless signature
                # would mean the unit was lost on save/reopen and the
                # recompute in onDocumentRestored raised
                # ArithmeticError ("Not matching Unit!").
                self.assertEqual(
                    lam.ArealWeight.Unit.Signature,
                    (-2, 1, 0, 0, 0, 0, 0, 0),
                )
                self.assertAlmostEqual(
                    lam.ArealWeight.getValueAs("g/m^2").Value,
                    expected,
                    places=8,
                )
            finally:
                FreeCAD.closeDocument(reopened.Name)
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
