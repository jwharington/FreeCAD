# ***************************************************************************
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *                                                                         *
# ***************************************************************************

__title__ = "Mixed shell and solid geometry unit tests"
__author__ = "The FreeCAD community"
__url__ = "https://www.freecad.org"

import unittest

import FreeCAD

from femexamples import constraint_mixed_edge_coupling as edge_coupling
from femexamples import constraint_mixed_face_coupling as face_coupling
from femexamples._mixed_coupling_common import paired_faces_by_plane
from .support_utils import fcc_print

TOLERANCE = 1e-6
FACE_VARIANTS = ("f1", "f2", "f3", "f4")
EDGE_VARIANTS = ("e1", "e2", "e3")


class TestMixedShellSolid(unittest.TestCase):
    fcc_print("import TestMixedShellSolid")

    # ********************************************************************************************
    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestMixedShellSolid tests {2}\n{0}".format(
                100 * "*", 10 * "*", 60 * "*"
            )
        )

    # ********************************************************************************************
    def test_face_variants_build_a_solid_and_a_shell(self):
        # Every F variant is one real solid plus a shell that is not a solid,
        # so a single mesh object over the compound sees both dimensions.
        for variant in FACE_VARIANTS:
            doc = self._build(face_coupling, variant)
            solid = doc.getObject("Solid")
            shell = doc.getObject("Shell")
            self.assertGreater(solid.Shape.Volume, 0.0)
            self.assertEqual(1, len(solid.Shape.Solids))
            self.assertEqual(0, len(shell.Shape.Solids))
            self.assertGreaterEqual(len(shell.Shape.Faces), 1)

    # ********************************************************************************************
    def test_edge_variants_build_a_solid_and_a_shell(self):
        for variant in EDGE_VARIANTS:
            doc = self._build(edge_coupling, variant)
            shell = doc.getObject("Shell")
            self.assertEqual(0, len(shell.Shape.Solids))
            for solid in self._solids(doc):
                self.assertGreater(solid.Shape.Volume, 0.0)
                self.assertEqual(1, len(solid.Shape.Solids))

    # ********************************************************************************************
    def test_covered_and_patched_shells_lie_on_the_solid(self):
        # f1 and f2 are the coincident interfaces: the shell's common volume
        # with the solid must have area, and its faces pair to the solid's own.
        for variant, expected_pairs in (("f1", 6), ("f2", 1)):
            doc = self._build(face_coupling, variant)
            solid = doc.getObject("Solid")
            shell = doc.getObject("Shell")
            self.assertGreater(shell.Shape.common(solid.Shape).Area, 0.0)
            pairs = paired_faces_by_plane(solid.Shape, shell.Shape, 1.0)
            self.assertEqual(expected_pairs, len(pairs))

    # ********************************************************************************************
    def test_offset_and_bag_shells_clear_the_solid_by_the_gap(self):
        # f3 stands off a core face and f4 surrounds it: no coincident area,
        # and the two surfaces stay the gap apart that the tie tolerance covers.
        for variant in ("f3", "f4"):
            doc = self._build(face_coupling, variant)
            solid = doc.getObject("Solid")
            shell = doc.getObject("Shell")
            self.assertLess(shell.Shape.common(solid.Shape).Area, TOLERANCE)
            distance = shell.Shape.distToShape(solid.Shape)[0]
            self.assertAlmostEqual(50.0, distance, delta=TOLERANCE)

    # ********************************************************************************************
    def test_edge_variants_share_only_an_edge(self):
        # The E family's interface has no area: the shell meets the solid at
        # zero distance but the common of the two shapes is a line, not a face.
        for variant in EDGE_VARIANTS:
            doc = self._build(edge_coupling, variant)
            shell = doc.getObject("Shell")
            for solid in self._solids(doc):
                self.assertLess(shell.Shape.common(solid.Shape).Area, TOLERANCE)
                self.assertLess(shell.Shape.distToShape(solid.Shape)[0], TOLERANCE)

    # ********************************************************************************************
    def test_tie_references_match_the_interface_measure(self):
        # A surface interface may tie face to face. An edge interface must tie
        # a shell Edge to a solid Face, which is the reference the tree cannot
        # resolve yet: this pins the gap instead of hiding it behind a hinge.
        for variant, expected_ties in (("f1", 6), ("f2", 1), ("f3", 1), ("f4", 6)):
            doc = self._build(face_coupling, variant)
            ties = self._ties(doc)
            self.assertEqual(expected_ties, len(ties))
            for tie in ties:
                self.assertTrue(self._subname(tie.References[0]).startswith("Face"))
                self.assertTrue(self._subname(tie.References[1]).startswith("Face"))

        for variant, expected_ties in (("e1", 1), ("e2", 1), ("e3", 2)):
            doc = self._build(edge_coupling, variant)
            ties = self._ties(doc)
            self.assertEqual(expected_ties, len(ties))
            for tie in ties:
                self.assertTrue(self._subname(tie.References[0]).startswith("Edge"))
                self.assertTrue(self._subname(tie.References[1]).startswith("Face"))

    # ********************************************************************************************
    def test_compound_links_the_solid_and_the_shell(self):
        for module, variant in (
            (face_coupling, "f1"),
            (face_coupling, "f4"),
            (edge_coupling, "e2"),
            (edge_coupling, "e3"),
        ):
            doc = self._build(module, variant)
            compound = doc.getObject("MixedGeometry")
            linked = {obj.Name for obj in compound.Links}
            self.assertIn("Shell", linked)
            self.assertTrue(any(name.startswith("Solid") for name in linked))

    # ********************************************************************************************
    def _build(self, module, variant):
        doc = FreeCAD.newDocument(f"{self.__class__.__name__}_{variant}")
        self.addCleanup(FreeCAD.closeDocument, doc.Name)
        module.setup(doc=doc, variant=variant)
        return doc

    def _solids(self, doc):
        return [obj for obj in doc.Objects if obj.Name.startswith("Solid")]

    def _ties(self, doc):
        return [obj for obj in doc.Objects if obj.Name.startswith("Tie")]

    def _subname(self, reference):
        subname = reference[1]
        if isinstance(subname, (list, tuple)):
            return subname[0]
        return subname
