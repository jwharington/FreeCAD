# SPDX-License-Identifier: LGPL-2.1-or-later

import os
import sys
import types
import unittest

import FreeCAD  # noqa: E402
import Part  # noqa: E402

# Ensure repo root is on sys.path so package imports work.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import Composites  # noqa: E402, F401  (canonical package init order first)
import Composites.objects  # noqa: E402, F401  (initialise objects before mechanics)

from Composites.fem.drape_laminate_provider import (  # noqa: E402
    register_drape_laminate_providers,
    shell_orientation_provider,
    shell_section_provider,
)
from Composites.util.fem_util import (  # noqa: E402
    format_material_name,
    write_lamina_material_ccx,
)

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


class _StrictFemMesh:
    """Stand-in that fails the test the moment the provider touches it.

    The mock boundary is the FEM side (per §7.5) — the Composites objects
    are always real. For a QI shell the orientation provider must never
    walk the mesh, so any access is a failure.
    """

    def __getattr__(self, name):
        raise AssertionError(f"femmesh touched: {name}")


class _ShellThicknessStub:
    """Minimal ElementGeometry2D stand-in: References[0][0] = the shell."""

    def __init__(self, compshell):
        self.References = [(compshell, "Face1")]


class _DrapedLaminateFixture:
    """Build real laminate features (draped and QI) in a scratch doc."""

    def _make_doc(self, name):
        if name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(name)
        return FreeCAD.newDocument(name)

    def _make_ply(self, doc, laminate_name, angle, thickness=0.5):
        from Composites.features.HomogeneousLamina import HomogeneousLaminaFP

        ply = doc.addObject(
            "Part::FeaturePython", f"{laminate_name}_Ply{int(angle):+03d}"
        )
        HomogeneousLaminaFP(ply)
        ply.Angle = angle
        ply.Thickness = thickness
        ply.Material = CARBON
        return ply

    def _make_laminate(self, doc, name, angles, isotropic=False):
        from Composites.features.Laminate import LaminateFP

        laminate = doc.addObject("Part::FeaturePython", name)
        LaminateFP(laminate)
        laminate.Layers = [
            self._make_ply(doc, name, angle) for angle in angles
        ]
        if isotropic:
            laminate.Symmetry = "Even"
            laminate.IsotropicEquivalent = True
        doc.recompute()
        return laminate

    def _make_shell(self, doc, name, laminate):
        from Composites.features.CompositeShell import CompositeShellFP

        support = doc.addObject("Part::Feature", f"{name}_Support")
        support.Shape = Part.makePlane(100.0, 100.0)
        shell = doc.addObject("Part::FeaturePython", name)
        CompositeShellFP(shell, support)
        shell.Laminate = laminate
        doc.recompute()
        return shell

    def tearDown(self):
        for doc_name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(doc_name)


class TestDrapeLaminateProviderRegistration(unittest.TestCase):
    def test_register_drape_laminate_providers(self):
        called_orientation = []
        called_section = []
        called_indirect = []

        def register_shell_orientation_provider(name, fn):
            called_orientation.append((name, fn))

        def register_shell_section_provider(name, fn):
            called_section.append((name, fn))

        def register_indirect_material_provider(name, fn):
            called_indirect.append((name, fn))

        fake_module = types.SimpleNamespace(
            register_shell_orientation_provider=register_shell_orientation_provider,
            register_shell_section_provider=register_shell_section_provider,
            register_indirect_material_provider=register_indirect_material_provider,
        )
        sys.modules["femtools.fem_extension_registry"] = fake_module

        try:
            ok = register_drape_laminate_providers()
        finally:
            del sys.modules["femtools.fem_extension_registry"]

        self.assertTrue(ok)
        self.assertEqual(called_orientation[0][0], "compositeswb.drape")
        self.assertEqual(called_section[0][0], "compositeswb.laminate")
        self.assertEqual(called_indirect[0][0], "compositeswb.laminate")


class TestDrapedPathNegativeControl(
    _DrapedLaminateFixture, unittest.TestCase
):
    """§7.5 negative control: for a NON-QI stack the provider changes
    produce byte-identical output to the pre-QI path.

    The draped section output is pinned to the unchanged underlying
    writers (write_shell_section_ccx / format_material_name) with the
    same arguments the pre-QI provider passed — the changed provider
    must delegate to exactly those.
    """

    def test_draped_section_provider_output_is_unchanged(self):
        doc = self._make_doc("DrapedNegControl")
        laminate = self._make_laminate(doc, "Laminate", (0.0, 45.0))
        shell = self._make_shell(doc, "DrapedShell", laminate)
        shellth = _ShellThicknessStub(shell)

        # The draped real case: the writer only reaches the override with
        # ORIENTATION= when it also writes the matching *ORIENTATION card,
        # which it does exactly when matgeoset carries a frame.  Any
        # truthy stand-in models that; the provider reads presence, not
        # the rotation.
        out = shell_section_provider(shellth, {"orientation": True},
                                     "_OR_E1")
        self.assertEqual(
            out,
            {
                "material": "COMPOSITE,ORIENTATION=_OR_E1",
                "section_geo": write_shell_section_ccx_for(laminate),
            },
        )
        # The pinned composite format: ply lines, no plain-material name.
        self.assertIn("COMPOSITE,ORIENTATION=", out["material"])
        self.assertNotIn("TYPE=ISO", materials_text(laminate))

    def test_layered_shell_without_orientation_omits_orientation(self):
        """A layered shell with no drape frame must not name an orientation.

        The writer writes a *ORIENTATION card only when the orientation
        provider supplied a frame.  A card that names an orientation no
        card defines stops ccx at parse time (ERROR reading *SHELL
        SECTION: nonexistent orientation) — the failure that killed the
        layered bulkhead plate deck.  The layers then run on the global
        axes: the manual's orientationless COMPOSITE form.
        """
        doc = self._make_doc("LayeredNoFrame")
        laminate = self._make_laminate(doc, "Laminate", (0.0, 45.0))
        shell = self._make_shell(doc, "NoFrameShell", laminate)
        shellth = _ShellThicknessStub(shell)

        for matgeoset in ({}, {"orientation": None}):
            out = shell_section_provider(shellth, matgeoset, "_OR_E1")
            self.assertEqual(
                out,
                {
                    "material": "COMPOSITE",
                    "section_geo": write_shell_section_ccx_for(laminate),
                },
                matgeoset,
            )
            self.assertNotIn("ORIENTATION=", out["material"])


def write_shell_section_ccx_for(laminate):
    from Composites.util.fem_util import write_shell_section_ccx

    return write_shell_section_ccx(
        prefix=laminate.Name,
        layers=laminate.Proxy.fem_layers(laminate),
    )


def materials_text(laminate):
    return "".join(
        write_lamina_material_ccx(layer, prefix=laminate.Name)
        for layer in laminate.Proxy.fem_layers(laminate)
    )


class TestQuasiIsotropicProvider(_DrapedLaminateFixture, unittest.TestCase):
    """§7.5: the QI provider shortcut path."""

    def test_orientation_provider_skips_mesh_for_qi_shell(self):
        doc = self._make_doc("QIProvider")
        laminate = self._make_laminate(
            doc, "QILaminate", (0.0, 45.0, -45.0, 90.0), isotropic=True
        )
        shell = self._make_shell(doc, "QIShell", laminate)
        shellth = _ShellThicknessStub(shell)

        out = shell_orientation_provider(
            shellth, _StrictFemMesh(), [1, 2, 3], None
        )
        # No orientation frame, no element_ids, and the mesh was never
        # touched (the strict stand-in raises on any access).
        self.assertEqual(out, {"orientation": None})

    def test_orientation_provider_walks_mesh_for_draped_shell(self):
        doc = self._make_doc("DrapedProvider")
        laminate = self._make_laminate(doc, "Laminate", (0.0, 45.0))
        shell = self._make_shell(doc, "DrapedShell", laminate)
        shellth = _ShellThicknessStub(shell)

        with self.assertRaises(AssertionError):
            # The draped path walks the mesh: the strict stand-in must
            # be touched (this pins that the QI skip above is a real
            # behavioural difference, not a universal early return).
            shell_orientation_provider(
                shellth, _StrictFemMesh(), [1, 2, 3], None
            )

    def test_section_provider_single_plain_layer_for_qi(self):
        doc = self._make_doc("QISection")
        laminate = self._make_laminate(
            doc, "QILaminate", (0.0, 45.0, -45.0, 90.0), isotropic=True
        )
        shell = self._make_shell(doc, "QIShell", laminate)
        shellth = _ShellThicknessStub(shell)

        out = shell_section_provider(shellth, {}, "_OR_E1")
        layer = laminate.Proxy.FEMLayers[0]
        expected_name = format_material_name(
            layer.description, prefix=laminate.Name
        )
        self.assertNotIn("ORIENTATION=", out["material"])
        self.assertNotIn("COMPOSITE", out["material"])
        self.assertEqual(out["material"], f"MATERIAL={expected_name}")
        # Single layer: exactly one thickness line.
        lines = [ln for ln in out["section_geo"].splitlines() if ln]
        self.assertEqual(len(lines), 1)
        self.assertAlmostEqual(float(lines[0]), layer.thickness, places=9)

    def test_qi_material_written_as_isotropic(self):
        doc = self._make_doc("QIMaterial")
        laminate = self._make_laminate(
            doc, "QILaminate", (0.0, 45.0, -45.0, 90.0), isotropic=True
        )
        text = materials_text(laminate)
        self.assertIn("*ELASTIC,TYPE=ISO", text.replace(" ", ""))
        self.assertNotIn("ENGINEERING CONSTANTS", text)
        self.assertIn("*DENSITY", text)

    def test_failure_models_are_inert_for_qi(self):
        from Composites.fem.failure_models_composites import (
            calc_failure_hashin,
            calc_failure_tsai_wu,
        )

        options = {
            "XT": 1000.0,
            "XC": 800.0,
            "YT": 60.0,
            "YC": 200.0,
            "ZT": 60.0,
            "ZC": 200.0,
            "S12": 80.0,
            "S13": 80.0,
            "S23": 60.0,
        }
        # A QI shell exports one smeared isotropic layer; the criteria
        # see plain stresses and must stay finite (no orientation or
        # laminate state involved).
        stress = [100.0, 90.0, 0.0, 5.0, 5.0, 2.0]
        strain = [0.0] * 6
        for value in (
            calc_failure_tsai_wu(stress, strain, options),
            calc_failure_hashin(stress, strain, options),
        ):
            self.assertTrue(units_finite(value))


def units_finite(value):
    import math

    return isinstance(value, float) and math.isfinite(value)