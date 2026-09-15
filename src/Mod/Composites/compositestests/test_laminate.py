# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for LaminateFP, including the quasi-isotropic feature contract."""

from unittest.mock import patch

import Part

from .test_base import TestFreeCADFP

CARBON = {
    "Name": "Carbon",
    "Density": "1750.0 kg/m^3",
    "PoissonRatioXY": "0.27",
    "PoissonRatioXZ": "0.27",
    "PoissonRatioYZ": "0.45",
    "ShearModulusXY": "5000 MPa",
    "ShearModulusXZ": "5000 MPa",
    "ShearModulusYZ": "3500 MPa",
    "YoungsModulusX": "135 GPa",
    "YoungsModulusY": "9.5 GPa",
    "YoungsModulusZ": "9.5 GPa",
}


class TestLaminateFP(TestFreeCADFP):
    """Tests for LaminateFP."""

    def test_basic_creation(self):
        laminate = self._create_laminate()
        self.assertIsNotNone(laminate)

    def test_layers_property(self):
        laminate = self._create_laminate()
        laminate.Layers = []
        self.assertEqual(len(laminate.Layers), 0)


class TestQuasiIsotropicLaminateFeature(TestFreeCADFP):
    """QI declaration on Composite::Laminate (PRD §5.1/§5.3, tests §7.3)."""

    def _make_laminate(
        self,
        angles,
        thicknesses=None,
        name="QILaminate",
        isotropic=False,
        approximate=False,
        model_type=None,
    ):
        from Composites.features.HomogeneousLamina import HomogeneousLaminaFP
        from Composites.features.Laminate import LaminateFP

        if thicknesses is None:
            thicknesses = [0.5] * len(angles)
        laminate = self.doc.addObject("Part::FeaturePython", name)
        LaminateFP(laminate)
        plies = []
        for k, (angle, thickness) in enumerate(zip(angles, thicknesses)):
            ply = self.doc.addObject("Part::FeaturePython", f"{name}_Ply{k}")
            HomogeneousLaminaFP(ply)
            ply.Angle = angle
            ply.Thickness = thickness
            ply.Material = CARBON
            plies.append(ply)
        laminate.Layers = plies
        laminate.Symmetry = "Even"
        laminate.IsotropicEquivalent = isotropic
        laminate.ApproximateIsotropicEquivalent = approximate
        if model_type is not None:
            laminate.StackModelType = model_type
        self.doc.recompute()
        return laminate

    def _assert_all_valid(self, *features):
        for obj in features:
            self.assertNotIn("Invalid", obj.State)

    def test_qi_declaration_collapses_to_single_isotropic_layer(self):
        laminate = self._make_laminate(
            (0, 45, -45, 90), isotropic=True
        )
        self._assert_all_valid(laminate, *laminate.Layers)
        layers = laminate.Proxy.FEMLayers
        self.assertEqual(len(layers), 1)
        merged = layers[0]
        self.assertNotIn("YoungsModulusX", merged.material)
        self.assertIn("YoungsModulus", merged.material)
        self.assertIn("PoissonRatio", merged.material)
        self.assertIn("Density", merged.material)
        # 4 plies x 0.5, doubled by Even symmetry
        self.assertAlmostEqual(laminate.Thickness.Value, 4.0, places=6)

    def test_qi_declaration_overrides_stack_model_type(self):
        for model_type in ("Discrete", "Smeared", "SmearedFabric"):
            laminate = self._make_laminate(
                (0, 45, -45, 90),
                isotropic=True,
                model_type=model_type,
            )
            self._assert_all_valid(laminate, *laminate.Layers)
            self.assertEqual(len(laminate.Proxy.FEMLayers), 1)

    def test_qi_unbalanced_declaration_fails_loudly(self):
        laminate = self._make_laminate((0, 45), isotropic=True)
        self.assertIn("Invalid", laminate.State)
        self.assertTrue(laminate.Proxy.last_error)
        self.assertIn("quasi-isotropic", laminate.Proxy.last_error)

    def test_qi_approximate_declaration_passes_and_records(self):
        laminate = self._make_laminate(
            (0, 45, -45, 90),
            thicknesses=[1.0, 1.05, 1.05, 1.0],
            approximate=True,
        )
        self._assert_all_valid(laminate, *laminate.Layers)
        self.assertEqual(len(laminate.Proxy.FEMLayers), 1)
        residuals = dict(laminate.ApproximateIsotropicResiduals)
        self.assertTrue(residuals)
        self.assertGreater(max(float(v) for v in residuals.values()), 1e-6)

    def test_qi_exact_declaration_records_no_residuals(self):
        laminate = self._make_laminate((0, 45, -45, 90), isotropic=True)
        self._assert_all_valid(laminate, *laminate.Layers)
        self.assertEqual(dict(laminate.ApproximateIsotropicResiduals), {})

    def test_bom_record_unchanged_for_qi(self):
        declared = self._make_laminate((0, 45, -45, 90), isotropic=True)
        undeclared = self._make_laminate(
            (0, 45, -45, 90), name="PlainLaminate"
        )
        self._assert_all_valid(declared, undeclared, *declared.Layers)
        self.assertEqual(
            declared.Proxy.get_stack_assembly(declared),
            undeclared.Proxy.get_stack_assembly(undeclared),
        )


class TestQuasiIsotropicShell(TestFreeCADFP):
    """CompositeShell draping bypass and protocol backstop (§7.2)."""

    def _make_qi_laminate(self, name="QILaminate"):
        from Composites.features.HomogeneousLamina import HomogeneousLaminaFP
        from Composites.features.Laminate import LaminateFP

        laminate = self.doc.addObject("Part::FeaturePython", name)
        LaminateFP(laminate)
        plies = []
        for k, angle in enumerate((0, 45, -45, 90)):
            ply = self.doc.addObject("Part::FeaturePython", f"{name}_Ply{k}")
            HomogeneousLaminaFP(ply)
            ply.Angle = angle
            ply.Thickness = 0.5
            ply.Material = CARBON
            plies.append(ply)
        laminate.Layers = plies
        laminate.Symmetry = "Even"
        laminate.IsotropicEquivalent = True
        self.doc.recompute()
        return laminate

    def _make_draped_laminate(self, name="DrapedLaminate"):
        from Composites.features.HomogeneousLamina import HomogeneousLaminaFP
        from Composites.features.Laminate import LaminateFP

        laminate = self.doc.addObject("Part::FeaturePython", name)
        LaminateFP(laminate)
        ply = self.doc.addObject("Part::FeaturePython", f"{name}_Ply0")
        HomogeneousLaminaFP(ply)
        ply.Angle = 30.0
        ply.Thickness = 0.5
        ply.Material = CARBON
        laminate.Layers = [ply]
        self.doc.recompute()
        return laminate

    def _make_shell(self, name, laminate):
        from Composites.features.CompositeShell import CompositeShellFP

        support = self.doc.addObject("Part::Feature", f"{name}_Support")
        support.Shape = Part.makePlane(100.0, 100.0)
        shell = self.doc.addObject("Part::FeaturePython", name)
        CompositeShellFP(shell, support)
        shell.Laminate = laminate
        self.doc.recompute()
        return shell

    def _assert_all_valid(self, *features):
        for obj in features:
            self.assertNotIn("Invalid", obj.State)

    def test_isotropic_shell_bypasses_draping(self):
        laminate = self._make_qi_laminate()
        shell = self._make_shell("QIShell", laminate)
        self._assert_all_valid(shell, laminate, *laminate.Layers)
        # Structural bypass: no backend, no drape result
        self.assertIsNone(shell.Proxy._backend)
        self.assertFalse(shell.DrapeValid)
        # Shape/placement stay synced with the support
        self.assertTrue(
            shell.Shape.isPartner(
                shell.Support.Shape
            )
        )
        self.assertAlmostEqual(
            shell.Placement.Base.z, shell.Support.Placement.Base.z, places=9
        )

    def test_isotropic_shell_protocol_backstop_raises(self):
        laminate = self._make_qi_laminate()
        shell = self._make_shell("QIShell", laminate)
        self._assert_all_valid(shell, laminate)
        with self.assertRaises(RuntimeError) as ctx:
            shell.Proxy.get_drape_lcs(None)
        self.assertIn("no drape frame", str(ctx.exception))
        with self.assertRaises(RuntimeError):
            shell.Proxy.get_draper()

    def test_isotropic_shell_rejects_rosette(self):
        from Composites.features.Rosette import RosetteFP

        laminate = self._make_qi_laminate()
        rosette = self.doc.addObject("Part::FeaturePython", "QIRosette")
        RosetteFP(rosette)
        rosette.Angle = 0.0
        shell = self.doc.addObject("Part::FeaturePython", "QIShell")
        from Composites.features.CompositeShell import CompositeShellFP

        support = self.doc.addObject("Part::Feature", "QIShell_Support")
        support.Shape = Part.makePlane(100.0, 100.0)
        CompositeShellFP(shell, support)
        shell.Laminate = laminate
        shell.Rosette = rosette
        self.doc.recompute()
        # Wiring error (§5.3): loud on recompute, greyed icon
        self.assertIn("Invalid", shell.State)

    def test_isotropic_shell_headless_render_does_not_raise(self):
        laminate = self._make_qi_laminate()
        shell = self._make_shell("QIShell", laminate)
        # D7 render fallback: no weave geometry is produced and the
        # recompute stays valid (GUI plain-colour confirmation is Tier C).
        self._assert_all_valid(shell, laminate)
        self.assertFalse(shell.DrapeValid)

    def test_draped_shell_still_drapes(self):
        laminate = self._make_draped_laminate()
        shell = self._make_shell("DrapedShell", laminate)
        self.assertNotIn("Invalid", laminate.State)
        # Regression guard: without a QI declaration the drape path is
        # untouched (the solve itself runs; the backend must be present
        # or the drape failure recorded — neither is the QI bypass).
        bypassed = shell.Proxy._backend is None and not shell.DrapeValid
        drape_failed = "error" in (shell.DrapeDiagnostics or "")
        self.assertFalse(bypassed and not drape_failed)


class TestQuasiIsotropicEntryGuards(TestFreeCADFP):
    """D7: drape-dependent commands blocked at entry on isotropic shells."""

    def _make_qi_shell(self, name="QIShell"):
        from Composites.features.CompositeShell import CompositeShellFP
        from Composites.features.HomogeneousLamina import HomogeneousLaminaFP
        from Composites.features.Laminate import LaminateFP

        laminate = self.doc.addObject("Part::FeaturePython", f"{name}_Lam")
        LaminateFP(laminate)
        plies = []
        for k, angle in enumerate((0, 45, -45, 90)):
            ply = self.doc.addObject(
                "Part::FeaturePython", f"{name}_Lam_Ply{k}"
            )
            HomogeneousLaminaFP(ply)
            ply.Angle = angle
            ply.Thickness = 0.5
            ply.Material = CARBON
            plies.append(ply)
        laminate.Layers = plies
        laminate.Symmetry = "Even"
        laminate.IsotropicEquivalent = True
        support = self.doc.addObject("Part::Feature", f"{name}_Support")
        support.Shape = Part.makePlane(100.0, 100.0)
        shell = self.doc.addObject("Part::FeaturePython", name)
        CompositeShellFP(shell, support)
        shell.Laminate = laminate
        self.doc.recompute()
        return shell

    def _make_draped_shell(self, name="DrapedShell"):
        from Composites.features.CompositeShell import CompositeShellFP
        from Composites.features.HomogeneousLamina import HomogeneousLaminaFP
        from Composites.features.Laminate import LaminateFP

        laminate = self.doc.addObject("Part::FeaturePython", f"{name}_Lam")
        LaminateFP(laminate)
        ply = self.doc.addObject("Part::FeaturePython", f"{name}_Lam_Ply0")
        HomogeneousLaminaFP(ply)
        ply.Angle = 30.0
        ply.Thickness = 0.5
        ply.Material = CARBON
        laminate.Layers = [ply]
        support = self.doc.addObject("Part::Feature", f"{name}_Support")
        support.Shape = Part.makePlane(100.0, 100.0)
        shell = self.doc.addObject("Part::FeaturePython", name)
        CompositeShellFP(shell, support)
        shell.Laminate = laminate
        self.doc.recompute()
        return shell

    def test_texture_plan_blocked_at_entry(self):
        from Composites.features.TexturePlan import TexturePlanCommand

        shell = self._make_qi_shell()
        cmd = TexturePlanCommand()
        reason = cmd.validate_selection({"shells": [shell]})
        self.assertIsNotNone(reason)
        self.assertIn(shell.Name, reason)
        self.assertIn("no texture plan", reason)

    def test_texture_plan_allowed_on_draped_shell(self):
        from Composites.features.TexturePlan import TexturePlanCommand

        shell = self._make_draped_shell()
        cmd = TexturePlanCommand()
        self.assertIsNone(cmd.validate_selection({"shells": [shell]}))

    def test_texture_plan_activation_creates_nothing(self):
        from Composites.features.TexturePlan import TexturePlanCommand

        shell = self._make_qi_shell()
        before = set(o.Name for o in self.doc.Objects)

        class MockEntry:
            def __init__(self, obj):
                self.Object = obj

        with patch(
            "FreeCADGui.Selection.getSelectionEx",
            return_value=[MockEntry(shell)],
        ):
            TexturePlanCommand().Activated()
        after = set(o.Name for o in self.doc.Objects)
        self.assertEqual(before, after)

    def test_align_fibre_rosette_blocked_at_entry(self):
        from Composites.features.AlignFibreRosette import (
            AlignFibreRosetteCommand,
        )

        shell = self._make_qi_shell()
        cmd = AlignFibreRosetteCommand()
        reason = cmd.validate_selection({"composite_shell": shell})
        self.assertIsNotNone(reason)
        self.assertIn(shell.Name, reason)
        self.assertIn("no fibre direction", reason)

    def test_align_fibre_rosette_allowed_on_draped_shell(self):
        from Composites.features.AlignFibreRosette import (
            AlignFibreRosetteCommand,
        )

        shell = self._make_draped_shell()
        cmd = AlignFibreRosetteCommand()
        self.assertIsNone(cmd.validate_selection({"composite_shell": shell}))


if __name__ == "__main__":
    unittest.main()
