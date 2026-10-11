# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for CompositeShellFP."""

import io
import os
import tempfile
import unittest

import FreeCAD
import Part

from .example_materials import make_glass
from .test_base import TestFreeCADFP

from Composites.features.CompositeShell import (
    support_object,
    support_placement,
    support_shape,
)

# The FEM deck writer is an optional dependency of this Composites test
# module: without the FEM stack the shell-section assertions are skipped.
try:
    import ObjectsFem
    from femsolver.calculix.write_femelement_geometry import (
        write_femelement_geometry,
    )
except ImportError:
    ObjectsFem = None
    write_femelement_geometry = None


class _StubSolver:
    ModelSpace = "3D"
    ExcludeBendingStiffness = False


class _StubCcxWriter:
    """The two attributes write_femelement_geometry reads."""

    def __init__(self, mat_geo_sets):
        self.mat_geo_sets = mat_geo_sets
        self.solver_obj = _StubSolver()


class TestCompositeShellFP(TestFreeCADFP):
    """Tests for CompositeShellFP."""

    def test_basic_creation(self):
        shell = self._create_shell()
        self.assertIsNotNone(shell)
        self.assertFalse(shell.Shape.isNull())

    def test_save_load_document(self):
        shell = self._create_shell()
        filepath = os.path.join(tempfile.gettempdir(), "test_shell.FCStd")
        self._save_document(filepath)
        loaded_doc = self._load_document(filepath)
        try:
            loaded_shell = loaded_doc.getObject(shell.Name)
            self.assertIsNotNone(loaded_shell)
            self.assertFalse(loaded_shell.Shape.isNull())
        finally:
            try:
                loaded_doc.close()
            except Exception:
                pass
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_laminate_property(self):
        shell = self._create_shell()
        laminate = self._create_laminate()
        shell.Laminate = laminate
        self.assertIs(shell.Laminate, laminate)

    def test_solid_support_is_rejected_not_crashed(self):
        """A solid is not a drape surface: the solve must fail, not crash.

        The inherited fixture support is a solid cylinder; its periodic
        side face drives nextdrape's seam walk past the end of a one-entry
        adjacency list, carrying a null face into the lattice and
        segfaulting the C++ solver.  Rejecting the solid before the solve
        turns that input into a reported failure.
        """
        shell = self._create_shell()
        shell.Laminate = self._create_laminate()
        self.assertFalse(shell.DrapeValid)
        self.assertIn("not a solid", shell.DrapeQuality)

    def test_live_support_shape_tracks_moved_support(self):
        """Known-issue #6: geometry queries must read the live support, not
        the shell's cached Shape snapshot."""
        import FreeCAD
        import Part

        from Composites.features.CompositeShell import CompositeShellFP
        from Composites.util.geometry_util import live_support_shape

        support = self.doc.addObject("Part::Feature", "Support")
        support.Shape = Part.makePlane(100.0, 100.0)
        shell = self.doc.addObject("Part::FeaturePython", "Shell")
        CompositeShellFP(shell, support)
        self.doc.recompute()
        self.assertEqual(
            live_support_shape(shell).BoundBox.ZMax,
            support.Shape.BoundBox.ZMax,
        )

        # Move the support WITHOUT recomputing: the shell's own Shape is
        # still the pre-move snapshot, but the live query must track.
        support.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0.0, 0.0, 40.0), FreeCAD.Rotation()
        )
        self.assertLess(shell.Shape.BoundBox.ZMax, 39.0)
        self.assertGreater(live_support_shape(shell).BoundBox.ZMax, 39.0)

        # After a recompute the snapshot catches up.
        self.doc.recompute()
        self.assertGreater(shell.Shape.BoundBox.ZMax, 39.0)


class TestFrameSeedValidation(TestFreeCADFP):
    """Known-issue #11: the drape seed must lie on the support surface.

    ``_build_seed`` used to treat any object carrying a ``Placement`` as
    a fibre frame.  An unplaced rosette LCS (the shell re-drapes mid
    transfer wiring, before the transfer's own LCS has been placed) and
    the rosette-less fallback of the support feature itself both present
    the identity placement — an origin seed that lands inside the
    geometry and fails the solve deterministically.  Whether the failure
    was healed depended on recompute ordering, which presented as the
    intermittent fine-pitch ``solver_failure`` of the seam example.
    """

    ON_SURFACE_TOL = 1e-4

    def _cap_face(self):
        from Composites.compositeexamples.examples.cyl_sphere_seam import (
            _spherical_cap,
        )

        return _spherical_cap()

    def _assert_seed_on_surface(self, backend):
        import Part

        seed = backend._build_seed()
        point = seed["point"]
        vertex = Part.Vertex(*point)
        dist = backend._shape.distToShape(vertex)[0]
        self.assertLess(
            dist,
            self.ON_SURFACE_TOL,
            f"seed {point} lies {dist} off the support surface",
        )
        return seed

    def test_unplaced_lcs_frame_falls_back_to_com_projection(self):
        """An identity-placement LCS is not a frame: fall back to the
        known-issue #7 COM projection instead of seeding at the origin."""
        from Composites.tools.drape_backend_nextdrape import NextDrapeBackend

        cap = self._cap_face()

        class _UnplacedLcs:
            Placement = FreeCAD.Placement()  # identity — never executed

        backend = NextDrapeBackend(mesh=None, lcs=_UnplacedLcs(), shape=cap)
        self._assert_seed_on_surface(backend)

    def test_support_as_lcs_falls_back_to_com_projection(self):
        """The rosette-less path hands the support feature itself as the
        'lcs' (CompositeShell.get_lcs fallback); its identity placement
        must not become an origin seed either."""
        from Composites.tools.drape_backend_nextdrape import NextDrapeBackend

        cap = self._cap_face()
        support = self.doc.addObject("Part::Feature", "CapSupport")
        support.Shape = cap
        backend = NextDrapeBackend(mesh=None, lcs=support, shape=cap)
        self._assert_seed_on_surface(backend)

    def test_unplaced_lcs_still_solves(self):
        """End to end: with the frame rejected, the fallback seed drapes
        the cap instead of failing with solver_failure."""
        from Composites.tools.drape_backend_nextdrape import NextDrapeBackend

        cap = self._cap_face()

        class _UnplacedLcs:
            Placement = FreeCAD.Placement()

        backend = NextDrapeBackend(mesh=None, lcs=_UnplacedLcs(), shape=cap)
        result = backend._run_solve()
        self.assertTrue(
            result.get("success"), f"solve failed: {result.get('error')}"
        )

    def test_placed_rosette_frame_is_used(self):
        """A genuine rosette frame (LCS placed by RosetteFP, origin on the
        face) must still seed the drape — the validation must not reject
        real frames."""
        from Composites.features.Rosette import _frame_rotation
        from Composites.tools.drape_backend_nextdrape import NextDrapeBackend

        cap = self._cap_face()
        position, rotation = _frame_rotation(cap, 41.0)

        class _PlacedLcs:
            Placement = FreeCAD.Placement(position, rotation)

        backend = NextDrapeBackend(mesh=None, lcs=_PlacedLcs(), shape=cap)
        seed = self._assert_seed_on_surface(backend)
        self.assertEqual(seed["point"], [position.x, position.y, position.z])
        warp = rotation.multVec(FreeCAD.Vector(1.0, 0.0, 0.0))
        self.assertEqual(
            seed["warp_direction"], [warp.x, warp.y, warp.z]
        )


class TestRosettelessFallbackSeed(TestFreeCADFP):
    """Known-issue #7: a rosette-less shell seeds its drape from the
    support's centre of mass projected onto the surface.  On a closed
    surface the COM lies on the axis and the old bounding-box clamp
    landed off-surface (solver_failure); the true nearest-point
    projection lands on the shell."""

    save_fcstd = False

    def test_closed_cylinder_com_seed_lands_on_surface(self):
        import Part

        from Composites.tools.drape_backend_nextdrape import NextDrapeBackend

        cylinder = next(
            f for f in Part.makeCylinder(10.0, 20.0).Faces
            if isinstance(f.Surface, Part.Cylinder)
        )
        backend = NextDrapeBackend(mesh=None, lcs=None, shape=cylinder)
        com = cylinder.CenterOfMass
        seed = backend._project_point_to_surface([com.x, com.y, com.z])

        # The projected seed must lie ON the shell (distance ~0), not on
        # a bbox face.
        dist = cylinder.distToShape(Part.Vertex(seed[0], seed[1], seed[2]))[0]
        self.assertLess(dist, 1e-6)
        # The axis COM was radius=10 away — the clamp never got this close.
        self.assertGreater(com.x ** 2 + com.y ** 2, 0.0)

    def test_rosetteless_open_cylinder_drapes(self):
        """The full lazy solve: a rosette-less shell on an open cylinder
        must produce a valid drape from the COM fallback seed.

        A *closed* cylinder still fails the march itself — that is the
        wrap-around lattice-closing problem (known-issue #3), not the
        seed: the projected seed is on-surface (previous test)."""
        import Part

        from Composites.tools.drape_backend_nextdrape import NextDrapeBackend

        solid = Part.makeCylinder(10.0, 20.0, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 270.0)
        panel = next(
            f for f in solid.Faces
            if isinstance(f.Surface, Part.Cylinder)
        )
        backend = NextDrapeBackend(mesh=None, lcs=None, shape=panel)
        result = backend._run_solve()
        self.assertTrue(result.get("success"), f"solve failed: {result.get('error')}")
        self.assertTrue(backend.is_valid())


class TestCompositeShellOffset(TestFreeCADFP):
    """Per-skin laminate offset routed into the FEM shell section.

    The offset makes a skin bonded to a solid core's face stiffer than the
    un-offset mid-surface default; a reversed sign puts both skins inboard
    and makes the sandwich softer than no offset at all, so the sign is
    pinned to the CalculiX manual: OFFSET is the signed position of the
    reference surface measured from the mid-surface, in units of thickness,
    +0.5 putting the reference surface on the face the shell normal points
    to and -0.5 on the opposite face.
    """

    def _make_laminate(self, name):
        from Composites.features.HomogeneousLamina import HomogeneousLaminaFP
        from Composites.features.Laminate import LaminateFP

        laminate = self.doc.addObject("Part::FeaturePython", name)
        LaminateFP(laminate)
        plies = []
        for angle in (0.0, 45.0):
            ply = self.doc.addObject(
                "Part::FeaturePython", f"{name}_Ply{int(angle)}"
            )
            HomogeneousLaminaFP(ply)
            ply.Angle = angle
            ply.Thickness = 0.5
            ply.Material = make_glass()
            plies.append(ply)
        laminate.Layers = plies
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

    def _deck(self, shells):
        """Run the real FEM section writer over the given shells."""
        from Composites.fem.drape_laminate_provider import (
            register_drape_laminate_providers,
        )

        register_drape_laminate_providers()
        mat_geo_sets = []
        thickness_by_shell = {}
        for shell in shells:
            thickness = ObjectsFem.makeElementGeometry2D(
                self.doc, 0.8, f"{shell.Name}_ShellThickness"
            )
            thickness.References = [(shell, "Face1")]
            thickness_by_shell[shell.Name] = thickness
            mat_geo_sets.append(
                {
                    "ccx_elset": True,
                    "ccx_elset_name": f"E_{shell.Name}",
                    "mat_obj_name": f"MAT_{shell.Name}",
                    "shellthickness_obj": thickness,
                }
            )
        buffer = io.StringIO()
        write_femelement_geometry(buffer, _StubCcxWriter(mat_geo_sets))
        return buffer.getvalue().splitlines(), thickness_by_shell

    def test_offset_defaults_to_zero(self):
        shell = self._make_shell("Shell", self._make_laminate("Laminate"))
        self.assertEqual(shell.Offset, 0.0)

    def test_default_offset_deck_is_unchanged(self):
        """An unset offset must leave the section card as it was before."""
        if write_femelement_geometry is None:
            self.skipTest("FEM stack unavailable")
        shell = self._make_shell("Shell", self._make_laminate("Laminate"))
        lines, thickness_by_shell = self._deck([shell])
        self.assertIn(
            "*SHELL SECTION, ELSET=E_Shell, COMPOSITE, OFFSET=0", lines
        )
        self.assertEqual(thickness_by_shell["Shell"].Offset, 0.0)

    def test_offset_reaches_shell_section_deck(self):
        if write_femelement_geometry is None:
            self.skipTest("FEM stack unavailable")
        shell = self._make_shell("Shell", self._make_laminate("Laminate"))
        shell.Offset = -0.5
        lines, thickness_by_shell = self._deck([shell])
        self.assertIn(
            "*SHELL SECTION, ELSET=E_Shell, COMPOSITE, OFFSET=-0.5", lines
        )
        self.assertEqual(thickness_by_shell["Shell"].Offset, -0.5)

    def test_two_skins_offset_in_opposite_directions(self):
        """A sandwich's two skins take opposite signs in one analysis."""
        if write_femelement_geometry is None:
            self.skipTest("FEM stack unavailable")
        top = self._make_shell("TopSkin", self._make_laminate("TopLaminate"))
        bottom = self._make_shell(
            "BottomSkin", self._make_laminate("BottomLaminate")
        )
        top.Offset = -0.5
        bottom.Offset = 0.5
        lines, thickness_by_shell = self._deck([top, bottom])
        self.assertIn(
            "*SHELL SECTION, ELSET=E_TopSkin, COMPOSITE, OFFSET=-0.5", lines
        )
        self.assertIn(
            "*SHELL SECTION, ELSET=E_BottomSkin, COMPOSITE, OFFSET=0.5", lines
        )
        self.assertEqual(thickness_by_shell["TopSkin"].Offset, -0.5)
        self.assertEqual(thickness_by_shell["BottomSkin"].Offset, 0.5)


class TestCompositeShellSupportReference(TestFreeCADFP):
    """A shell's surface declared as faces of another object (B7.1).

    ``Composite::Shell.Support`` is a whole-object link, so a skin on one face
    of a solid had to declare a separate face object.  ``SupportReference`` is an
    optional ``(object, [faces])`` alternative, and the three resolvers prefer
    it when set; a shell that sets it declares its interface on the solid's own
    object, which is what the tie pass pairs on.
    """

    def _shell_on_a_face(self):
        from Composites.features.CompositeShell import CompositeShellFP

        solid = self.doc.addObject("Part::Box", "Solid")
        solid.Length = solid.Width = solid.Height = 10.0
        shell = self.doc.addObject("Part::FeaturePython", "Skin")
        CompositeShellFP(shell, support=None)
        shell.SupportReference = (solid, ["Face6"])
        self.doc.recompute()
        return shell, solid

    def test_whole_object_support_is_unchanged(self):
        # The original form must behave exactly as before: no reference, and
        # the resolvers read the Support object and its shape.
        shell = self._create_shell()
        self.assertIsNone(shell.SupportReference)
        self.assertIs(shell.Support, support_object(shell))
        self.assertTrue(support_shape(shell).isSame(shell.Support.Shape))
        self.assertEqual(
            shell.Support.Placement.Base, support_placement(shell).Base
        )

    def test_reference_resolves_the_named_face(self):
        shell, solid = self._shell_on_a_face()
        self.assertIs(solid, support_object(shell))
        resolved = support_shape(shell)
        self.assertEqual(1, len(resolved.Faces))
        face = solid.Shape.Faces[5]
        self.assertTrue(resolved.Faces[0].isSame(face))

    def test_reference_takes_precedence_over_support(self):
        # A shell may carry both while a model is migrated; the declaration of
        # faces is the interface and wins.
        shell, solid = self._shell_on_a_face()
        cylinder = self.doc.addObject("Part::Feature", "Cylinder")
        cylinder.Shape = Part.makeCylinder(5.0, 10.0)
        shell.Support = cylinder
        self.doc.recompute()
        self.assertIs(solid, support_object(shell))
        self.assertTrue(support_shape(shell).Faces[0].isSame(solid.Shape.Faces[5]))

    def test_reference_moves_the_shell_shape(self):
        # The no-laminate branch mirrors the support onto the shell, so the
        # referenced face is what the shell becomes - the surface a later drape
        # and the FEM section are built from.
        shell, solid = self._shell_on_a_face()
        self.assertFalse(shell.Shape.isNull())
        self.assertAlmostEqual(
            solid.Shape.Faces[5].CenterOfMass.z,
            shell.Shape.CenterOfMass.z,
            places=6,
        )
