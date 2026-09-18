# SPDX-License-Identifier: LGPL-2.1-or-later

"""Oriented-frame (LCS) tests for the drape backend.

The frame the FEM exporter emits must be the *material* frame: X is the
drape warp direction at the element — the direction the solver actually
laid the fibre down — rotated by the shell's rosette angle, Z the surface
normal, Y completing the right-handed set.

Two properties are pinned, neither of which the suite checked before:

* the frame is **input-independent** (it must not be a function of the
  caller's triangle; the defect these tests were written for built the
  basis from the triangle's first edge, so the exported orientation was
  whatever direction the FEM mesh edge happened to point);
* the frame **folds in the rosette angle**, matching the definition in
  ``features/Rosette.py`` (fibre 0 deg = face-U rotated by Angle about the
  normal) and therefore the rendered weave.
"""

import math
import os
import sys
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

from Composites.features.CompositeShell import CompositeShellFP  # noqa: E402
from Composites.features.HomogeneousLamina import HomogeneousLaminaFP  # noqa: E402
from Composites.features.Laminate import LaminateFP  # noqa: E402
from Composites.features.Rosette import RosetteFP  # noqa: E402
from Composites.compositeexamples import runner  # noqa: E402
from Composites.fem.drape_laminate_provider import (  # noqa: E402
    get_drape_lcs as provider_get_drape_lcs,
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

PLATE_SIDE = 100.0
WARP_TOL = 1e-6

# The drape warp is recovered from the solver's discretised quad field, so
# it tracks the analytic direction to within the mesh resolution (~2e-5
# observed on a 100 mm plate) rather than exactly.  This bounds that
# discretisation; a wrong angle is off by ~0.5 in a component, so the test
# still fails loudly for a doubled, missing, or negated rotation.
WARP_TOL_DISCRETE = 1e-3


class _QuadMesh:
    """Minimal FEM-mesh stand-in exposing one 4-node element."""

    def __init__(self, points):
        self._points = points
        self.walked = False

    def getElementNodes(self, element):
        return [0, 1, 2, 3]

    def getNodeById(self, index):
        return self._points[index]


class _FrameFixture(unittest.TestCase):
    """A draped flat plate, optionally with a rosette at a given angle."""

    def setUp(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)
        self.doc = FreeCAD.newDocument("DrapeLcsFrame")

    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def _make_shell(self, rosette_angle=None):
        support = self.doc.addObject("Part::Feature", "Plate")
        support.Shape = Part.makePlane(PLATE_SIDE, PLATE_SIDE)

        laminate = self.doc.addObject("Part::FeaturePython", "Laminate")
        LaminateFP(laminate)
        ply = self.doc.addObject("Part::FeaturePython", "Ply")
        HomogeneousLaminaFP(ply)
        ply.Angle = 0.0
        ply.Thickness = 0.5
        ply.Material = CARBON
        laminate.Layers = [ply]

        shell = self.doc.addObject("Part::FeaturePython", "Shell")
        CompositeShellFP(shell, support)
        shell.Laminate = laminate

        if rosette_angle is not None:
            rosette = self.doc.addObject("Part::FeaturePython", "Rosette")
            RosetteFP(rosette, support=(support, ["Face1"]))
            rosette.Angle = rosette_angle
            shell.Rosette = rosette

        self.doc.recompute()
        return shell

    @staticmethod
    def _face_frame(shell, u=0.5, v=0.5):
        """Return (point, face-U direction, face normal) at (u, v)."""
        face = shell.Support.Shape.Face1
        point = face.valueAt(u, v)
        u_axis = face.valueAt(min(u + 1e-4, 1.0), v) - point
        u_axis.normalize()
        return point, u_axis, face.normalAt(u, v)

    @staticmethod
    def _warp(placement):
        return placement.Rotation.multVec(FreeCAD.Vector(1.0, 0.0, 0.0))

    def _triangle(self, point, u_axis, normal):
        """A small triangle at *point*; the frame must not care about it."""
        return [
            point,
            point + u_axis * 2.0,
            point + normal.cross(u_axis) * 2.0,
        ]

    def assertVectorAlmostEqual(self, got, want, delta=WARP_TOL, msg=""):
        for a, b in ((got.x, want.x), (got.y, want.y), (got.z, want.z)):
            self.assertAlmostEqual(a, b, delta=delta, msg=msg)


class TestDrapeFrameIsMaterialDerived(_FrameFixture):
    def test_frame_does_not_depend_on_the_input_triangle(self):
        """The frame is a material property, not a mesh artefact.

        Three triangles with the same centroid but different first edges
        must yield the same warp.  Before the fix the warp *was* the
        caller's ``v1 - v0``, so a per-element mesh walk produced a
        different (wrong) orientation per element.
        """
        shell = self._make_shell(rosette_angle=0.0)
        point, u_axis, normal = self._face_frame(shell)
        v_axis = normal.cross(u_axis)
        triangles = [
            [point, point + u_axis, point + v_axis],
            [point, point + v_axis, point + u_axis],
            [point, point + u_axis + v_axis, point - v_axis],
        ]

        warps = [self._warp(shell.Proxy.get_drape_lcs(t)) for t in triangles]
        for warp in warps[1:]:
            self.assertVectorAlmostEqual(
                warp,
                warps[0],
                msg="frame changed with the input triangle — not material-derived",
            )

    def test_warp_is_the_face_u_direction_at_zero_rosette(self):
        """Independent reference: the drape lays the warp along u.

        ``Part.makePlane``'s parametric u direction is +X, so with no
        rosette offset the frame X must be the face-U direction.
        """
        shell = self._make_shell(rosette_angle=0.0)
        point, u_axis, normal = self._face_frame(shell)
        warp = self._warp(
            shell.Proxy.get_drape_lcs(self._triangle(point, u_axis, normal))
        )
        self.assertVectorAlmostEqual(warp, u_axis)

    def test_rosette_angle_rotates_the_warp(self):
        """The rosette angle folds in as face-U rotated about the normal.

        Independent reference: ``features/Rosette.py`` defines the fibre
        0 deg axis as ``Rotation(normal, Angle).multVec(face_U)``.
        """
        angle = 30.0
        shell = self._make_shell(rosette_angle=angle)
        point, u_axis, normal = self._face_frame(shell)
        expected = FreeCAD.Rotation(normal, angle).multVec(u_axis)
        warp = self._warp(
            shell.Proxy.get_drape_lcs(self._triangle(point, u_axis, normal))
        )
        self.assertVectorAlmostEqual(warp, expected, delta=WARP_TOL_DISCRETE)

    def test_rosette_angle_is_applied_by_the_shell_not_the_caller(self):
        """The shell's own rosette angle is used without being passed in."""
        plain = self._make_shell(rosette_angle=0.0)
        point, u_axis, normal = self._face_frame(plain)
        unrotated = self._warp(
            plain.Proxy.get_drape_lcs(self._triangle(point, u_axis, normal))
        )

        rotated_shell = self._make_shell(rosette_angle=90.0)
        point, u_axis, normal = self._face_frame(rotated_shell)
        rotated = self._warp(
            rotated_shell.Proxy.get_drape_lcs(
                self._triangle(point, u_axis, normal)
            )
        )
        # 90 degrees about +Z maps +X to +Y.
        self.assertVectorAlmostEqual(
            rotated, normal.cross(unrotated), delta=WARP_TOL_DISCRETE
        )


class TestDrapeFrameBatch(_FrameFixture):
    def test_batch_matches_individual_calls(self):
        """The bulk path must agree with the one-at-a-time path."""
        shell = self._make_shell(rosette_angle=30.0)
        triangles = []
        for u, v in ((0.3, 0.3), (0.5, 0.5), (0.7, 0.6)):
            point, u_axis, normal = self._face_frame(shell, u, v)
            triangles.append(self._triangle(point, u_axis, normal))

        batch = shell.Proxy.get_drape_lcs_batch(triangles)
        self.assertEqual(len(batch), len(triangles))
        for tri, frame in zip(triangles, batch):
            self.assertIsNotNone(frame)
            self.assertVectorAlmostEqual(
                self._warp(frame), self._warp(shell.Proxy.get_drape_lcs(tri))
            )

    def test_batch_does_not_re_enter_the_solve(self):
        """Efficiency guard: the batch resolves in one query, not per item.

        The field is built once; afterwards no element may trigger another
        solve entry (previously every element did, plus a debug-file write).
        """
        shell = self._make_shell(rosette_angle=0.0)
        backend = shell.Proxy.get_draper()
        backend._lcs_field()

        original = backend._run_solve
        calls = []

        def counting_solve():
            calls.append(1)
            return original()

        backend._run_solve = counting_solve
        try:
            triangles = []
            for u in (0.2, 0.4, 0.6, 0.8):
                point, u_axis, normal = self._face_frame(shell, u, u)
                triangles.append(self._triangle(point, u_axis, normal))
            frames = shell.Proxy.get_drape_lcs_batch(triangles)
        finally:
            backend._run_solve = original

        self.assertEqual(len(frames), len(triangles))
        self.assertEqual(
            calls, [], "batch re-entered the solve once per element"
        )

    def test_provider_gives_quad_elements_a_frame(self):
        """A 4-node element must receive a frame.

        The former provider passed all four vertices to a triangle-only
        lookup, so every quad element silently got ``None`` — no
        orientation at all.
        """
        shell = self._make_shell(rosette_angle=0.0)
        point, u_axis, normal = self._face_frame(shell)
        v_axis = normal.cross(u_axis)
        mesh = _QuadMesh(
            [
                point - u_axis - v_axis,
                point + u_axis - v_axis,
                point + u_axis + v_axis,
                point - u_axis + v_axis,
            ]
        )

        frames = provider_get_drape_lcs(shell, mesh, [7])
        self.assertIn(7, frames)
        self.assertIsNotNone(frames[7], "quad element received no frame")
        self.assertVectorAlmostEqual(self._warp(frames[7]), u_axis)


class TestFrameAgreesWithTheRosetteOnARealAssembly(_FrameFixture):
    """The frame must match the shell's own rosette across the surface.

    The plain-plate tests miss this: there the drape happens to be seeded
    from the rosette, so a naive dP/du agrees by construction.  The
    stiffener panel's 120x60 plate is where the defect showed -- the
    drape's parametrisation folds on its mid-line, and a frame taken
    straight from dP/du disagreed with the declared fibre there (measured
    8.1 deg and 12.8 deg against a rosette of 30), while a mesh-edge frame
    disagreed everywhere.  Every point must also yield a frame: the field
    is defined on the whole surface, never ``None``.
    """

    PLATE_LENGTH = 120.0
    PLATE_WIDTH = 60.0
    MAX_OFFSET_DEG = 1.0

    def test_the_whole_panel_matches_its_rosette(self):
        result = runner.run("quasi_iso_stiffener_panel", run_solver=False)
        shell = result["panel_shell"]
        rosette = shell.Rosette
        self.assertIsNotNone(rosette, "the panel must carry its rosette")
        fibre = rosette.LocalCoordinateSystem.Placement.Rotation.multVec(
            FreeCAD.Vector(1.0, 0.0, 0.0)
        )

        checked = 0
        for ix in range(1, 12):
            for iy in range(1, 6):
                x = self.PLATE_LENGTH * ix / 12.0
                y = self.PLATE_WIDTH * iy / 6.0
                point = FreeCAD.Vector(x, y, 0.0)
                frame = shell.Proxy.get_drape_lcs(
                    [
                        point,
                        point + FreeCAD.Vector(1.0, 0.0, 0.0),
                        point + FreeCAD.Vector(0.0, 1.0, 0.0),
                    ]
                )
                self.assertIsNotNone(
                    frame,
                    msg=f"no frame at ({x:.1f}, {y:.1f}) — field not defined",
                )
                warp = self._warp(frame)
                dot = max(-1.0, min(1.0, warp.dot(fibre)))
                offset = math.degrees(math.acos(dot))
                self.assertLess(
                    offset,
                    self.MAX_OFFSET_DEG,
                    msg=(
                        f"frame at ({x:.1f}, {y:.1f}) is {offset:.2f} deg "
                        "off the rosette fibre"
                    ),
                )
                checked += 1
        self.assertGreaterEqual(checked, 50)


if __name__ == "__main__":
    unittest.main()
