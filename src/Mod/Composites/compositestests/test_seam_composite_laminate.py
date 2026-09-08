# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Scenario tests for the SeamCompositeLaminate feature.

Covers the phase-1 acceptance criteria that do not need the full
SeamShellFP wiring: stack ordering, symmetry pinning, wiring-failure
loudness, and section round-trip.  The transfer rosettes are plain
Rosette features carrying solved angles — the solve itself belongs to
the TransferRosette suite; these tests pin how the angles are consumed.
"""

import FreeCAD
import Part

from .test_base import TestFreeCADFP

RESIN = {
    "Name": "Epoxy",
    "Density": "1100.0 kg/m^3",
    "YoungsModulus": "3.500 GPa",
    "PoissonRatio": "0.36",
}

STEEL = {
    "Name": "Steel",
    "Density": "7850.0 kg/m^3",
    "YoungsModulus": "200 GPa",
    "PoissonRatio": "0.3",
}


class TestSeamCompositeLaminate(TestFreeCADFP):
    """SeamCompositeLaminate stack, symmetry, and failure scenarios."""

    def _make_laminate(self, angles, thicknesses, materials, name="Laminate"):
        from Composites.features.HomogeneousLamina import HomogeneousLaminaFP
        from Composites.features.Laminate import LaminateFP

        laminate = self.doc.addObject("Part::FeaturePython", name)
        LaminateFP(laminate)
        ply_objs = []
        for k, (angle, thickness, material) in enumerate(
            zip(angles, thicknesses, materials)
        ):
            ply = self.doc.addObject(
                "Part::FeaturePython", f"{name}_Ply{k}"
            )
            HomogeneousLaminaFP(ply)
            ply.Angle = angle
            ply.Thickness = thickness
            ply.Material = material
            ply_objs.append(ply)
        laminate.Layers = ply_objs
        self.doc.recompute()
        return laminate

    def _make_shell(self, name, angles, thicknesses, materials):
        from Composites.features.CompositeShell import CompositeShellFP

        support = self.doc.addObject("Part::Feature", f"{name}_Support")
        support.Shape = Part.makePlane(100.0, 100.0)
        laminate = self._make_laminate(
            angles,
            thicknesses,
            materials,
            name=f"{name}_Laminate",
        )
        shell = self.doc.addObject("Part::FeaturePython", name)
        CompositeShellFP(shell, support)
        shell.Laminate = laminate
        self.doc.recompute()
        return shell

    def _make_seam_shell(self, name="SeamShell"):
        from Composites.features.CompositeShell import CompositeShellFP

        # A flat strip standing off the plates' edge is not what the
        # extraction produces, but shared-edge detection only needs two
        # surfaces touching along a real edge; a thin box sharing its
        # edge with both plates models the overlap strip adequately.
        support = self.doc.addObject("Part::Feature", f"{name}_Support")
        support.Shape = Part.makeBox(1.0, 100.0, 1.0)
        shell = self.doc.addObject("Part::FeaturePython", name)
        CompositeShellFP(shell, support)
        self.doc.recompute()
        return shell

    def _make_rosette(self, name, angle):
        from Composites.features.Rosette import RosetteFP

        rosette = self.doc.addObject("Part::FeaturePython", name)
        RosetteFP(rosette)
        rosette.Angle = angle
        self.doc.recompute()
        return rosette

    def _make_scl(
        self,
        name="SeamCompositeLaminate",
        master_angles=(0.0, 90.0),
        attachment_angles=(45.0,),
        master_angle_at_seam=10.0,
        attachment_angle_at_seam=25.0,
        combination_model=None,
    ):
        from Composites.features.SeamCompositeLaminate import (
            SeamCompositeLaminateFP,
        )

        master = self._make_shell(
            "Master",
            angles=list(master_angles),
            thicknesses=[0.5] * len(master_angles),
            materials=[STEEL] * len(master_angles),
        )
        attachment = self._make_shell(
            "Attachment",
            angles=list(attachment_angles),
            thicknesses=[0.4] * len(attachment_angles),
            materials=[RESIN] * len(attachment_angles),
        )
        seam = self._make_seam_shell()
        master_tr = self._make_rosette("MasterTransfer", master_angle_at_seam)
        attachment_tr = self._make_rosette(
            "AttachmentTransfer", attachment_angle_at_seam
        )

        scl = self.doc.addObject("Part::FeaturePython", name)
        SeamCompositeLaminateFP(scl)
        scl.Master = master
        scl.Attachment = attachment
        scl.SeamRegion = seam
        scl.MasterTransfer = master_tr
        scl.AttachmentTransfer = attachment_tr
        scl.ResinMaterial = RESIN
        if combination_model is not None:
            scl.CombinationModel = combination_model
        self.doc.recompute()
        return scl

    # ── stack ordering ────────────────────────────────────────────

    def test_stack_master_over_attachment(self):
        scl = self._make_scl()
        self.assertNotIn("Invalid", scl.State)
        model = scl.Proxy.get_model(scl)
        orientations = [layer.orientation for layer in model.layers]
        thicknesses = [layer.thickness for layer in model.layers]
        # attachment plies below, master plies above
        self.assertEqual(
            orientations,
            [45.0 + 25.0, 0.0 + 10.0, 90.0 + 10.0],
        )
        self.assertEqual(thicknesses, [0.4, 0.5, 0.5])
        self.assertAlmostEqual(scl.Thickness.Value, 1.4)

    def test_stack_attachment_over_master(self):
        from Composites.features.SeamCompositeLaminate import CombinationModel

        scl = self._make_scl(
            combination_model=CombinationModel.StackAttachmentOverMaster
        )
        model = scl.Proxy.get_model(scl)
        orientations = [layer.orientation for layer in model.layers]
        self.assertEqual(
            orientations,
            [0.0 + 10.0, 90.0 + 10.0, 45.0 + 25.0],
        )

    def test_effective_offset_angle(self):
        scl = self._make_scl()
        self.assertAlmostEqual(
            scl.EffectiveOffsetAngle.Value, 25.0 - 10.0
        )
        report = scl.SideAngleReport
        self.assertEqual(report["master_angle_at_seam"], "10")
        self.assertEqual(report["attachment_angle_at_seam"], "25")

    # ── symmetry pinned ───────────────────────────────────────────

    def test_symmetry_pinned_no_mirrored_plies(self):
        from Composites.objects import SymmetryType

        scl = self._make_scl()
        self.assertEqual(
            scl.Symmetry, SymmetryType.Assymmetric.name
        )
        model = scl.Proxy.get_model(scl)
        # 2 master + 1 attachment plies, NOT mirrored to 6
        self.assertEqual(len(model.layers), 3)
        # ReadOnly only restricts the GUI editor, so a Python writer can
        # flip Symmetry — execute must re-pin it and keep the stack
        # literal (self-healing, not silently mirrored).
        scl.Symmetry = SymmetryType.Odd.name
        scl.recompute()
        self.assertEqual(
            scl.Symmetry, SymmetryType.Assymmetric.name
        )
        model = scl.Proxy.get_model(scl)
        self.assertEqual(len(model.layers), 3)

    # ── wiring failures (loud) ────────────────────────────────────

    def test_attachment_not_shell_raises(self):
        scl = self._make_scl()
        stray = self.doc.addObject("Part::Feature", "Stray")
        stray.Shape = Part.makeBox(10, 10, 1)
        scl.Attachment = stray
        self.doc.recompute()
        self.assertIn("Invalid", scl.State)
        self.assertIn("Attachment", scl.Proxy.last_error)

    def test_missing_shared_edge_raises(self):
        from Composites.features.CompositeShell import CompositeShellFP

        scl = self._make_scl()
        far = self.doc.addObject("Part::FeaturePython", "FarShell")
        support = self.doc.addObject("Part::Feature", "FarSupport")
        far_shape = Part.makeBox(100.0, 100.0, 1.0)
        far_shape.translate(FreeCAD.Vector(500.0, 0.0, 0.0))
        support.Shape = far_shape
        CompositeShellFP(far, support)
        self.doc.recompute()
        scl.SeamRegion = far
        self.doc.recompute()
        self.assertIn("Invalid", scl.State)
        self.assertIn("boundary", scl.Proxy.last_error)

    def test_missing_transfer_raises(self):
        scl = self._make_scl()
        scl.AttachmentTransfer = None
        self.doc.recompute()
        self.assertIn("Invalid", scl.State)
        self.assertIn("AttachmentTransfer", scl.Proxy.last_error)

    def test_error_recorded_on_failure(self):
        scl = self._make_scl()
        self.assertNotIn("Invalid", scl.State)
        scl.MasterTransfer = None
        self.doc.recompute()
        self.assertIn("Invalid", scl.State)
        self.assertIsNotNone(scl.Proxy.last_error)
        self.assertIn("MasterTransfer", scl.Proxy.last_error)

    # ── SeamShellFP wiring (step 2) ───────────────────────────────

    def _make_seam_extraction(self, master, attachment, name="SeamX"):
        """Full seam extraction on two overlapping plate shells.

        The plates overlap in the region x in [75, 100]: the extraction
        cuts the seam strip out of the attachment.
        """
        from Composites.features.SeamExtraction import SeamShellFP

        seam_x = self.doc.addObject("Part::FeaturePython", name)
        SeamShellFP(seam_x, master, attachment, seam_width="10.0 mm")
        self.doc.recompute()
        return seam_x

    def _make_offset_pair(self):
        """Master + attachment shells with 30° fabric, edge-sharing.

        Coplanar planar faces meeting at the x=100 edge — the seam
        extractor's input model (it partitions the attachment outward
        from the master–attachment intersection, as in the
        seam_extraction example).
        """
        from Composites.features.Rosette import RosetteFP

        master = self._make_shell(
            "Master30", angles=[30.0], thicknesses=[0.5],
            materials=[STEEL],
        )
        attachment = self._make_shell(
            "Attachment30", angles=[30.0], thicknesses=[0.4],
            materials=[RESIN],
        )
        att_sup = attachment.Support
        att_shape = Part.makePlane(100.0, 100.0)
        att_shape.translate(FreeCAD.Vector(100.0, 0.0, 0.0))
        att_sup.Shape = att_shape
        self.doc.recompute()
        # Rosettes on each shell's own support.
        for shell in (master, attachment):
            ros = self.doc.addObject(
                "Part::FeaturePython", f"{shell.Name}_Ros"
            )
            RosetteFP(ros, support=(shell.Support, ["Face1"]))
            shell.Rosette = ros
        self.doc.recompute()
        return master, attachment

    def test_seam_extraction_builds_seam_composite_laminate(self):
        from Composites.features.SeamCompositeLaminate import (
            SeamCompositeLaminateFP,
        )

        master, attachment = self._make_offset_pair()
        seam_x = self._make_seam_extraction(master, attachment)
        seam_shell = seam_x.Seam
        self.assertIsNotNone(seam_shell)
        scl = seam_shell.Laminate
        self.assertIsNotNone(scl)
        self.assertIsInstance(scl.Proxy, SeamCompositeLaminateFP)
        self.assertEqual(scl.Master, master)
        self.assertEqual(scl.Attachment, attachment)
        self.assertEqual(scl.SeamRegion, seam_shell)
        self.assertIsNotNone(scl.MasterTransfer)
        self.assertIsNotNone(scl.AttachmentTransfer)
        self.assertNotIn("Invalid", scl.State)

    def test_remainder_laminate_is_attachments_own(self):
        master, attachment = self._make_offset_pair()
        seam_x = self._make_seam_extraction(master, attachment)
        remainder = seam_x.Remainder
        self.assertIsNotNone(remainder)
        # The remainder carries the attachment's own laminate — the
        # combined stack never applies beyond the overlap.
        self.assertEqual(remainder.Laminate, attachment.Laminate)

    def test_seam_transfer_angles_are_solved(self):
        """The seam rosette is a solved TransferRosette, not a copy.

        With a 30° fabric on both plates and zero distortion on flat
        plates, the solved angles equal the sides' rosette angles; the
        effective offset must be ~0 (identical fabrics), NOT the naive
        concatenation's implicit mismatch.
        """
        master, attachment = self._make_offset_pair()
        seam_x = self._make_seam_extraction(master, attachment)
        scl = seam_x.Seam.Laminate
        self.assertAlmostEqual(
            scl.EffectiveOffsetAngle.Value, 0.0, delta=2.0
        )
        # Combined stack: one ply per side, both at 30° (+ frame angle).
        model = scl.Proxy.get_model(scl)
        self.assertEqual(len(model.layers), 2)
        for layer in model.layers:
            self.assertAlmostEqual(layer.orientation % 180.0, 30.0, delta=2.0)

    def test_support_move_updates_seam_angles(self):
        master, attachment = self._make_offset_pair()
        seam_x = self._make_seam_extraction(master, attachment)
        scl = seam_x.Seam.Laminate
        before = scl.EffectiveOffsetAngle.Value
        # Rotate the master's rosette: the seam angles must follow.
        master_ros = master.Rosette
        master_ros.Angle = 60.0
        self.doc.recompute()
        after = scl.EffectiveOffsetAngle.Value
        self.assertNotAlmostEqual(before, after)
        self.assertNotIn("Invalid", scl.State)

    # ── section round-trip ────────────────────────────────────────

    def test_section_round_trip(self):
        from Composites.util.fem_util import (
            write_lamina_materials_ccx,
            write_shell_section_ccx,
        )

        scl = self._make_scl()
        materials = write_lamina_materials_ccx(
            prefix=scl.Name, layers=scl.Proxy.FEMLayers
        )
        section = write_shell_section_ccx(
            prefix=scl.Name, layers=scl.Proxy.FEMLayers
        )
        # 3 plies → 3 material blocks, 3 section rows
        self.assertEqual(materials.count("*MATERIAL"), 3)
        self.assertEqual(len(section.strip().splitlines()), 3)
        # thickness column round-trips
        rows = section.strip().splitlines()
        values = [float(row.split(",")[0]) for row in rows]
        self.assertEqual(values, [0.4, 0.5, 0.5])

    # ── reserved models raise loudly ──────────────────────────────

    def test_interleaved_not_implemented_raises(self):
        from Composites.features.SeamCompositeLaminate import CombinationModel

        scl = self._make_scl()
        scl.CombinationModel = CombinationModel.Interleaved
        # An enum change is not dependency-driven, so doc.recompute()
        # would skip the object — force the recompute.
        scl.enforceRecompute()
        self.doc.recompute()
        self.assertIn("not implemented", scl.Proxy.last_error)
        with self.assertRaises(NotImplementedError):
            scl.Proxy.get_model(scl)
