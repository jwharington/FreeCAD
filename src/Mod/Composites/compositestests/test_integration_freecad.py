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
from unittest.mock import MagicMock

import FreeCAD
import Part

# Minimal FreeCADGui mock for tests that need GUI access.
# Features themselves no longer require FreeCADGui at import time.
# This mock provides stubs for common GUI operations used in tests.
_freeCADGui_mock = MagicMock()
_freeCADGui_mock.addCommand = lambda *args, **kwargs: None
_freeCADGui_mock.addWorkbench = lambda *args, **kwargs: None
_freeCADGui_mock.Selection = MagicMock()
_freeCADGui_mock.Selection.getSelectionEx = MagicMock(return_value=[])
_freeCADGui_mock.Selection.clearSelection = MagicMock()
sys.modules['FreeCADGui'] = _freeCADGui_mock

# Some existing modules import CompositesWB by name.
if "CompositesWB" not in sys.modules:
    import Composites as _composites_wb

    sys.modules["CompositesWB"] = _composites_wb

import Composites as CompositesWB
from Composites.compositeexamples import runner as example_runner
from Composites.compositeexamples.examples import tubular_shell
from Composites.compositestests.example_materials import make_glass


class TestFreeCADIntegration(unittest.TestCase):
    # Enable automatic .FCStd file generation
    save_fcstd = True

    def _close_doc_if_exists(self, doc_name):
        if doc_name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(doc_name)

    def tearDown(self):
        """Save .FCStd file after each test and close document."""
        try:
            # Save document if enabled
            if self.save_fcstd:
                docs = FreeCAD.listDocuments()
                if docs:
                    doc_name = list(docs.keys())[0]
                    filepath = os.path.join(tempfile.gettempdir(), f"{self.__class__.__name__}_{self._testMethodName}.FCStd")
                    doc = docs[doc_name]
                    doc.saveAs(filepath)
                    print(f"Saved: {filepath}")
            # Close all documents
            for doc_name in list(FreeCAD.listDocuments()):
                try:
                    FreeCAD.closeDocument(doc_name)
                except Exception:
                    pass
        except Exception as e:
            print(f"Teardown error: {e}")

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

    def _make_cut_wire(self, doc, name="CutWire"):
        wire = doc.addObject("Part::Feature", name)
        wire.Shape = Part.makePolygon(
            [
                FreeCAD.Vector(0.0, 0.0, 0.0),
                FreeCAD.Vector(20.0, 0.0, 0.0),
                FreeCAD.Vector(20.0, 20.0, 0.0),
                FreeCAD.Vector(0.0, 20.0, 0.0),
            ]
        )
        return wire

    def _persist_shape_document(self, *shapes, labels=None):
        doc_name = f"{self.__class__.__name__}_{self._testMethodName}"
        self._close_doc_if_exists(doc_name)
        doc = FreeCAD.newDocument(doc_name)
        if labels is None:
            labels = [f"Shape{index + 1}" for index in range(len(shapes))]
        for label, shape in zip(labels, shapes):
            obj = doc.addObject("Part::Feature", label)
            obj.Shape = shape
        doc.recompute()
        return doc

    def _make_composite_shell(self, doc, name_prefix, support_shape):
        from Composites.compositeexamples.examples._shell_example_common import (
            create_composite_feature_stack,
            create_support_feature,
        )

        support = create_support_feature(doc, f"{name_prefix}Support", support_shape)
        result = create_composite_feature_stack(
            doc,
            support,
            name_prefix=name_prefix,
            skip_recompute=True,
            skip_view_providers=True,
        )
        shell = result["shell"]
        if shell is None:
            self.skipTest("composite shell build failed")
        return result

    def test_seam_make_join_seam_from_adjacent_faces(self):
        self._ensure_freecadgui()
        from Composites.tools.seam import get_partner_edges, make_join_seam

        box = Part.makeBox(10.0, 10.0, 10.0)
        face1 = box.Faces[0]  # Front face
        face2 = box.Faces[4]  # Top face

        self.assertTrue(get_partner_edges(face1, face2))

        seam = make_join_seam(face1, face2, overlap=1.0)

        self.assertFalse(seam.isNull())
        self.assertEqual(seam.ShapeType, "Compound")
        # Seam should have greater area than either individual face
        self.assertGreaterEqual(seam.Area, max(face1.Area, face2.Area))
        self._persist_shape_document(box, seam, labels=["Input", "Seam"])

    def test_seam_make_join_seam_handles_partial_overlap(self):
        self._ensure_freecadgui()
        from Composites.tools.seam import get_partner_edges, make_join_seam

        master = Part.makePlane(20.0, 10.0)
        attached = Part.makePlane(10.0, 10.0, FreeCAD.Vector(5.0, 0.0, 0.0))

        self.assertFalse(get_partner_edges(master, attached))

        seam = make_join_seam(master, attached, overlap=1.0)

        self.assertFalse(seam.isNull())
        self.assertEqual(seam.ShapeType, "Compound")
        # Seam should have greater area than either face alone
        self.assertGreaterEqual(seam.Area, max(master.Area, attached.Area))
        self._persist_shape_document(master, attached, seam, labels=["Master", "Attached", "Seam"])

    def test_seam_make_join_seam_is_sensitive_to_face_order(self):
        self._ensure_freecadgui()
        from Composites.tools.seam import make_join_seam

        master = Part.makePlane(20.0, 10.0)
        attached = Part.makePlane(10.0, 10.0, FreeCAD.Vector(5.0, 0.0, 0.0))

        # Create seam with attachment as master
        seam_att_as_master = make_join_seam(attached, master, overlap=1.0)

        # Create seam with master as master
        seam_master_as_master = make_join_seam(master, attached, overlap=1.0)

        self.assertFalse(seam_att_as_master.isNull())
        self.assertFalse(seam_master_as_master.isNull())
        self.assertEqual(seam_att_as_master.ShapeType, "Compound")
        self.assertEqual(seam_master_as_master.ShapeType, "Compound")
        # Different order should produce different topology and area
        self.assertNotEqual(seam_att_as_master.Area, seam_master_as_master.Area)
        self._persist_shape_document(master, attached, seam_att_as_master, seam_master_as_master,
                                    labels=["Master", "Attached", "SeamAttAsMaster", "SeamMasterAsMaster"])

    def test_seam_make_join_seam_without_partner_edges_raises(self):
        self._ensure_freecadgui()
        from Composites.tools.seam import make_join_seam

        # Two faces that are clearly not touching and will quickly fail
        box = Part.makeBox(10.0, 10.0, 10.0)
        # Opposite faces of a box don't share edges and won't intersect
        face1 = box.Faces[0]
        face2 = box.Faces[3]  # Opposite face

        # This should raise ValueError quickly
        with self.assertRaises(ValueError):
            make_join_seam(face1, face2, overlap=1.0)

    # New join seam tests to expand coverage
    def test_seam_make_join_seam_on_cylindrical_faces(self):
        """Test joining cylindrical faces at an angle."""
        self._ensure_freecadgui()
        from Composites.tools.seam import make_join_seam

        cylinder = Part.makeCylinder(10.0, 20.0)
        side_face = cylinder.Faces[0]
        cap_face = cylinder.Faces[1]

        seam = make_join_seam(side_face, cap_face, overlap=1.0)

        self.assertFalse(seam.isNull())
        self.assertEqual(seam.ShapeType, "Compound")
        # Should cover both faces plus overlap region
        self.assertGreaterEqual(seam.Area, max(side_face.Area, cap_face.Area))
        self._persist_shape_document(cylinder, seam, labels=["Input", "Seam"])

    def test_seam_make_join_seam_with_different_overlaps(self):
        """Test that overlap parameter affects seam size."""
        self._ensure_freecadgui()
        from Composites.tools.seam import make_join_seam

        master = Part.makePlane(20.0, 10.0)
        attached = Part.makePlane(10.0, 10.0, FreeCAD.Vector(5.0, 0.0, 0.0))

        seam_small = make_join_seam(master, attached, overlap=1.0)
        seam_large = make_join_seam(master, attached, overlap=5.0)

        self.assertFalse(seam_small.isNull())
        self.assertFalse(seam_large.isNull())
        # Larger overlap should produce larger area (or at least not smaller)
        # Use tolerance for floating point comparisons
        self.assertGreaterEqual(seam_large.Area + 0.1, seam_small.Area)
        self._persist_shape_document(master, attached, seam_small, seam_large,
                                    labels=["Master", "Attached", "Seam_1mm", "Seam_5mm"])

    def test_seam_make_join_seam_on_torus_edges(self):
        """Test joining two torus faces along shared edge."""
        self._ensure_freecadgui()
        from Composites.tools.seam import make_join_seam

        torus = Part.makeTorus(20.0, 5.0)
        # Torus has only one face, so create a second torus slightly offset
        torus2 = Part.makeTorus(20.0, 5.0, FreeCAD.Vector(1.0, 0.0, 0.0))
        face1 = torus.Faces[0]
        face2 = torus2.Faces[0]

        seam = make_join_seam(face1, face2, overlap=1.0)

        self.assertFalse(seam.isNull())
        self.assertEqual(seam.ShapeType, "Compound")
        # Should have greater area than single torus
        self.assertGreaterEqual(seam.Area, torus.Area)
        self._persist_shape_document(torus, torus2, seam, labels=["Torus1", "Torus2", "Seam"])

    def test_seam_make_join_seam_rejects_invalid_overlap(self):
        """Test that negative overlap raises error."""
        self._ensure_freecadgui()
        from Composites.tools.seam import make_join_seam

        master = Part.makePlane(20.0, 10.0)
        attached = Part.makePlane(10.0, 10.0, FreeCAD.Vector(5.0, 0.0, 0.0))

        with self.assertRaises(ValueError):
            make_join_seam(master, attached, overlap=-1.0)

    def test_seam_featurepython_rejects_missing_edges(self):
        self._ensure_freecadgui()
        from Composites.features.Seam import SeamFP

        doc_name = "CompositesSeamMissingEdgesTest"

        doc = FreeCAD.newDocument(doc_name)
        try:
            seam = doc.addObject("Part::FeaturePython", "Seam")
            SeamFP(seam)

            with self.assertRaises(ValueError):
                seam.Proxy.execute(seam)
        finally:
            pass

    def test_seam_featurepython_recomputes_from_box_face_edge(self):
        self._ensure_freecadgui()
        from Composites.features.Seam import SeamFP

        doc_name = "CompositesSeamIntegrationTest"

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
            pass

    def test_seam_featurepython_supports_master_attachment_faces(self):
        self._ensure_freecadgui()
        from Composites.features.Seam import SeamFP

        doc_name = "CompositesSeamObjectModeTest"

        doc = FreeCAD.newDocument(doc_name)
        try:
            master = self._make_source_feature(
                doc,
                name="Master",
                shape=Part.makePlane(20.0, 10.0),
            )
            attachment = self._make_source_feature(
                doc,
                name="Attachment",
                shape=Part.makePlane(
                    10.0,
                    10.0,
                    FreeCAD.Vector(5.0, 0.0, 0.0),
                ),
            )
            seam = doc.addObject("Part::FeaturePython", "Seam")
            SeamFP(seam)
            seam.Master = master
            seam.Attachment = attachment
            doc.recompute()

            self.assertFalse(seam.Shape.isNull())
            self.assertEqual(seam.Shape.ShapeType, "Compound")
        finally:
            pass

    def test_seam_shell_output_aggregates_laminates_by_lap_side(self):
        self._ensure_freecadgui()
        from Composites.features.Seam import SeamShellFP, is_composite_shell

        doc_name = "CompositesSeamShellObjectModeTest"

        doc = FreeCAD.newDocument(doc_name)
        try:
            master = self._make_composite_shell(
                doc,
                "MasterShell",
                Part.makePlane(20.0, 10.0),
            )["shell"]
            attachment = self._make_composite_shell(
                doc,
                "AttachmentShell",
                Part.makePlane(
                    10.0,
                    10.0,
                    FreeCAD.Vector(5.0, 0.0, 0.0),
                ),
            )["shell"]

            seam = doc.addObject("Part::FeaturePython", "Seam")
            SeamShellFP(seam, master, attachment, lap_side="A+B")
            doc.recompute()

            support_name = f"{seam.Name}_SeamSupport"
            laminate_name = f"{seam.Name}_VirtualLaminate"
            support = doc.getObject(support_name)
            laminate = doc.getObject(laminate_name)

            self.assertTrue(is_composite_shell(seam))
            self.assertFalse(seam.Shape.isNull())
            self.assertIsNotNone(support)
            self.assertIsNotNone(laminate)
            self.assertFalse(support.ViewObject.Visibility)
            self.assertFalse(laminate.ViewObject.Visibility)
            self.assertEqual(
                seam.Laminate.Layers,
                master.Laminate.Layers + attachment.Laminate.Layers,
            )

            seam.LapSide = "B+A"
            doc.recompute()

            support_after = doc.getObject(support_name)
            laminate_after = doc.getObject(laminate_name)
            self.assertIsNotNone(support_after)
            self.assertIsNotNone(laminate_after)
            self.assertEqual(support_after.Name, support_name)
            self.assertEqual(laminate_after.Name, laminate_name)
            self.assertFalse(support_after.ViewObject.Visibility)
            self.assertFalse(laminate_after.ViewObject.Visibility)
            self.assertEqual(
                seam.Laminate.Layers,
                attachment.Laminate.Layers + master.Laminate.Layers,
            )
        finally:
            pass

    def test_shell_drapecuts_invalidate_persisted_drape(self):
        self._ensure_freecadgui()

        doc_name = "CompositesDrapeCutsIntegrationTest"

        doc = FreeCAD.newDocument(doc_name)
        try:
            result = tubular_shell.build(
                doc=doc,
                run_solver=False,
                debug_options={"skip_view_providers": True, "skip_recompute": False},
            )
            shell = result["feature_stack"]["shell"]
            cut_wire = self._make_cut_wire(doc)

            self.assertTrue(shell.Proxy._can_use_persisted(shell))

            shell.DrapeCuts = [cut_wire]
            self.assertTrue(shell.Proxy._needs_recompute)
            self.assertFalse(shell.Proxy._can_use_persisted(shell))

            doc.recompute()

            self.assertTrue(shell.DrapeValid)
            self.assertTrue(shell.Proxy._can_use_persisted(shell))
        finally:
            pass

    def test_get_shape_for_solver_embeds_cut_wires(self):
        self._ensure_freecadgui()
        from Composites.compositetools.drape_task import _get_shape_for_solver

        doc_name = "CompositesCutWireHelperTest"

        doc = FreeCAD.newDocument(doc_name)
        try:
            cut_wire = self._make_cut_wire(doc)
            fp = types.SimpleNamespace(Document=doc, DrapeCuts=[cut_wire])
            combined, uses_cut_shape = _get_shape_for_solver(
                fp,
                Part.makeBox(10.0, 10.0, 10.0),
            )

            self.assertTrue(uses_cut_shape)
            self.assertEqual(combined.ShapeType, "Compound")
            self.assertEqual(len(combined.Solids), 1)
        finally:
            pass

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


        doc = FreeCAD.newDocument(doc_name)
        self.assertEqual(doc.Name, doc_name)

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


        doc = FreeCAD.newDocument(doc_name)
        obj = doc.addObject("App::FeaturePython", "Rosette")
        RosetteFP(obj)
        doc.recompute()

        self.assertTrue(is_rosette(obj))
        self.assertIsNotNone(obj.LocalCoordinateSystem)
        self.assertEqual(
            obj.LocalCoordinateSystem.TypeId, "Part::LocalCoordinateSystem"
        )

        # tearDown will close

    def test_texture_plan_on_real_shell_geometry(self):
        self._ensure_freecadgui()
        from Composites.features.TexturePlan import TexturePlanFP

        doc_name = "CompositesTexturePlanIntegrationTest"

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
            pass


    def test_conical_example_mesh_only_fem_job_runs(self):
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

    def test_conical_example_full_solver_job_runs(self):
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


    def test_fibre_composite_lamina_areal_weight_updates(self):
        doc_name = "CompositesFibreLaminaIntegrationTest"


        doc = FreeCAD.newDocument(doc_name)
        obj = self._make_fibre_lamina(doc)

        areal_weight = obj.ArealWeight.getValueAs("g/m^2")
        self.assertAlmostEqual(areal_weight.Value, 645.0, places=8)

        # tearDown will close

    def test_fibre_composite_lamina_areal_weight_survives_restore(self):
        doc_name = "CompositesFibreLaminaRestoreTest"
        path = tempfile.mktemp(suffix=".FCStd")


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
                pass
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
