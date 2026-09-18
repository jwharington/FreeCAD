# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Integration tests for the iterative-solve TransferRosette feature.

These tests run inside a real FreeCAD process (they exercise the C++ nextdrape
solver). Run them with:

    FreeCADCmd -P <repo-root>
        Composites/compositestests/run_freecad_integration_tests.py
"""

import math
import os
import sys
import tempfile
import types
import unittest

import FreeCAD

# Some existing modules import CompositesWB by name.
if "CompositesWB" not in sys.modules:
    import Composites as _composites_wb

    sys.modules["CompositesWB"] = _composites_wb

import Composites as CompositesWB
from Composites.compositeexamples import runner as example_runner
from Composites.compositeexamples.examples._shell_example_common import (
    create_composite_feature_stack,
)


def _stub_freecadgui():
    import FreeCADGui

    if not hasattr(FreeCADGui, "addCommand"):
        FreeCADGui.addCommand = lambda *a, **k: None
    if not hasattr(FreeCADGui, "Selection"):
        FreeCADGui.Selection = types.SimpleNamespace(
            getSelectionEx=lambda *a, **k: [],
            clearSelection=lambda *a, **k: None,
        )
    if not hasattr(FreeCADGui, "Control"):
        FreeCADGui.Control = types.SimpleNamespace(
            showDialog=lambda *a, **k: None,
            closeDialog=lambda *a, **k: None,
        )


def _face_from_pts(pts):
    """Build a planar face from a closed polyline of FreeCAD points."""
    import Part

    wire = Part.makePolygon(pts + [pts[0]])
    return Part.Face(wire)


class TestTransferRosette(unittest.TestCase):
    """Headless integration tests for Composite::TransferRosette."""

    save_fcstd = True

    def tearDown(self):
        """Save .FCStd file after each test."""
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
        except Exception:
            pass
        # Close any remaining documents
        for dn in list(FreeCAD.listDocuments()):
            try:
                FreeCAD.closeDocument(dn)
            except Exception:
                pass

    def _close_doc_if_exists(self, doc_name):
        if doc_name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(doc_name)

    def _build_two_shell_fixture(self, doc, master_angle_deg=30.0,
                                 flip_attachment=False):
        """Two coplanar CompositeShells sharing the boundary edge at x=0.

        The master shell drapes on x in [0, 200]; the attachment shell drapes
        on x in [-200, 0]. ``master.Shape.section(attachment.Shape)`` yields
        the shared edge along the y-axis. The master rosette is set to
        ``master_angle_deg``; the transfer rosette's angle is solved to match.

        ``flip_attachment`` winds the attachment face the other way, so its
        support normal is OPPOSITE the master's: one physical plane carrying
        two opposed faces — the panel/foot geometry of a stiffener lap
        joint, with nothing else attached.
        """
        master_face = _face_from_pts(
            [
                FreeCAD.Vector(0, -100, 0),
                FreeCAD.Vector(200, -100, 0),
                FreeCAD.Vector(200, 100, 0),
                FreeCAD.Vector(0, 100, 0),
            ]
        )
        if flip_attachment:
            attachment_face = _face_from_pts(
                [
                    FreeCAD.Vector(-200, -100, 0),
                    FreeCAD.Vector(-200, 100, 0),
                    FreeCAD.Vector(0, 100, 0),
                    FreeCAD.Vector(0, -100, 0),
                ]
            )
        else:
            attachment_face = _face_from_pts(
                [
                    FreeCAD.Vector(-200, -100, 0),
                    FreeCAD.Vector(0, -100, 0),
                    FreeCAD.Vector(0, 100, 0),
                    FreeCAD.Vector(-200, 100, 0),
                ]
            )
        master_sup = doc.addObject("Part::Feature", "MasterSupport")
        master_sup.Shape = master_face
        attachment_sup = doc.addObject("Part::Feature", "AttachmentSupport")
        attachment_sup.Shape = attachment_face

        # The case definition, checked not assumed: the master face is
        # wound +Z; the attachment matches it unless wound flipped (-Z).
        self.assertAlmostEqual(self._face_normal(master_face).z, 1.0, places=6)
        expected_attachment_z = -1.0 if flip_attachment else 1.0
        self.assertAlmostEqual(
            self._face_normal(attachment_face).z, expected_attachment_z, places=6
        )

        master_stack = create_composite_feature_stack(
            doc, master_sup, name_prefix="Master", skip_view_providers=True,
        )
        master_shell = master_stack["shell"]
        master_rosette = master_stack["rosette"]
        master_rosette.Angle = float(master_angle_deg)
        doc.recompute()
        self.assertTrue(master_shell.Proxy.get_draper().is_valid())

        attachment_stack = create_composite_feature_stack(
            doc, attachment_sup, name_prefix="Attachment",
            skip_view_providers=True,
        )
        attachment_shell = attachment_stack["shell"]
        doc.recompute()
        self.assertTrue(attachment_shell.Proxy.get_draper().is_valid())

        # The two support faces share a real boundary edge.
        shared = master_shell.Shape.section(attachment_shell.Shape)
        self.assertTrue(shared.Edges)
        self.assertGreater(max(e.Length for e in shared.Edges), 1.0)

        return master_shell, attachment_shell

    @staticmethod
    def _face_normal(face):
        """World normal at a face's parametric centre."""
        u0, u1, v0, v1 = face.ParameterRange
        return face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)

    def test_is_transfer_rosette_helper(self):
        _stub_freecadgui()
        from Composites.features.TransferRosette import (
            TransferRosetteFP,
            is_transfer_rosette,
        )

        doc_name = "TransferRosetteTypeTest"
        self._close_doc_if_exists(doc_name)
        doc = FreeCAD.newDocument(doc_name)
        obj = doc.addObject("App::FeaturePython", "TransferRosette")
        TransferRosetteFP(obj)
        doc.recompute()
        self.assertTrue(is_transfer_rosette(obj))
        self.assertEqual(obj.Proxy.Type, "Composite::TransferRosette")
        FreeCAD.closeDocument(doc_name)

    def test_transfer_rosette_solves_coplanar_shared_edge(self):
        """Attachment rosette angle must converge to the master rosette angle."""
        _stub_freecadgui()
        from Composites.features.TransferRosette import TransferRosetteFP

        master_angle = 30.0
        doc_name = "TransferRosetteSolveTest"
        self._close_doc_if_exists(doc_name)
        doc = FreeCAD.newDocument(doc_name)

        master_shell, attachment_shell = self._build_two_shell_fixture(
            doc, master_angle_deg=master_angle,
        )

        tr = doc.addObject("App::FeaturePython", "TransferRosette")
        TransferRosetteFP(tr, support=(attachment_shell.Support, ["Face1"]))
        # Wire the attachment shell to the transfer rosette BEFORE setting the
        # defining references, so the solve sees a live attachment drape.
        attachment_shell.Rosette = tr
        doc.recompute()
        tr.MasterShell = master_shell
        tr.AttachmentShell = attachment_shell
        doc.recompute()

        solved = float(tr.Angle)
        residual_rad = tr.Proxy._edge_angle_error(tr)
        residual_deg = math.degrees(residual_rad)

        self.assertAlmostEqual(
            solved, master_angle, delta=1.0,
            msg=f"solved angle {solved} != master {master_angle}",
        )
        self.assertLess(
            abs(residual_deg), 1.0,
            msg=f"edge-angle residual {residual_deg} deg exceeds 1 deg",
        )

        FreeCAD.closeDocument(doc_name)

    def test_flipped_coplanar_joint_inherits_the_warp_not_its_mirror(self):
        """A flipped coplanar joint must carry the master's world warp.

        The attachment support is the SAME plane as the master, wound so
        its normal is opposite: one physical sheet, two opposed faces.
        The transfer's contract — the same warp across the shared edge —
        then means the two rosette frames are one line in global
        coordinates, parallel or anti-parallel, never mirrored.  A
        residual measured about each frame's OWN normal reads the mirror
        as continuity, so the solve converges to the mirrored fibre.
        """
        _stub_freecadgui()
        from Composites.features.TransferRosette import TransferRosetteFP
        from Composites.compositestests.test_stiffener_composite_shell import (
            line_offset_deg,
            warp_axis,
        )

        doc_name = "TransferRosetteFlippedTest"
        self._close_doc_if_exists(doc_name)
        doc = FreeCAD.newDocument(doc_name)

        master_shell, attachment_shell = self._build_two_shell_fixture(
            doc, master_angle_deg=30.0, flip_attachment=True,
        )

        tr = doc.addObject("App::FeaturePython", "TransferRosette")
        TransferRosetteFP(tr, support=(attachment_shell.Support, ["Face1"]))
        attachment_shell.Rosette = tr
        doc.recompute()
        tr.MasterShell = master_shell
        tr.AttachmentShell = attachment_shell
        doc.recompute()

        # The solve being satisfied is the trap, not the proof.
        residual_deg = math.degrees(tr.Proxy._edge_angle_error(tr))
        self.assertLess(
            abs(residual_deg), 1.0,
            msg=f"edge-angle residual {residual_deg} deg exceeds 1 deg",
        )

        offset = line_offset_deg(warp_axis(master_shell), warp_axis(attachment_shell))
        self.assertLess(
            offset, 1.0,
            msg=(f"flipped joint landed {offset:.2f} deg off the master warp "
                 f"(solved Angle {float(tr.Angle):+.2f} deg): the mirrored "
                 f"fibre, not the master's"),
        )

        FreeCAD.closeDocument(doc_name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
