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

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path

import FreeCAD
import Part
import pytest

import Fem
import ObjectsFem

from femtools import ccxtools
from femtools import fem_extension_registry
from femtools import membertools
from femtools.checksanalysis import check_member_for_solver_calculix
from femtools.femutils import member_for_reference
from femmesh import meshsetsgetter
from femsolver.calculix import writer as ccx_writer
from femsolver.calculix import write_mesh as write_mesh_module
from femexamples import constraint_mixed_edge_coupling as edge_coupling
from femexamples import constraint_mixed_face_coupling as face_coupling
from femtools.mixedcoupling import (
    add_tie,
    extreme_face_reference,
    face_reference_on_axis,
    find_edge_reference,
    paired_faces_by_plane,
    shell_expansion_faces,
    tie_slave_side_and_tolerance,
)
from femexamples._mixed_coupling_common import (
    add_analysis,
    add_fixed,
    add_force,
    add_mesh,
    add_shape,
    add_shell_thickness,
    make_compound,
    mesh_parts_separately,
    planar_face,
)
from . import support_utils as testtools
from .support_utils import fcc_print

TOLERANCE = 1e-6
FACE_VARIANTS = ("f1", "f2", "f3", "f4")
EDGE_VARIANTS = ("e1", "e2", "e3")

MIXED_FLAG_PATH = "User parameter:BaseApp/Preferences/Mod/Fem/General"
MIXED_FLAG_NAME = "AllowMixedShellSolid"


@contextlib.contextmanager
def mixed_shell_solid_flag(enabled):
    """Turn the hidden mixed-elements flag on or off, restoring the old value."""
    group = FreeCAD.ParamGet(MIXED_FLAG_PATH)
    previous = group.GetBool(MIXED_FLAG_NAME, False)
    group.SetBool(MIXED_FLAG_NAME, enabled)
    try:
        yield
    finally:
        group.SetBool(MIXED_FLAG_NAME, previous)


def node_disjoint_brick_and_shell(quadratic=False):
    """A C3D8 brick plus a quad on one of its faces, on node ids of its own.

    The quad sits at the brick's bottom-face coordinates but shares no node with
    it, which is the merge route the mixed plan takes. A node-merged quad is the
    volume's own skin and getFacesOnly drops it - Trap A.

    ``quadratic`` adds the quad's mid-side nodes. A composite *SHELL SECTION is
    accepted only for S6 and S8R, so a laminate needs it and the plain linear
    quad is the case a composite section has to be refused for.
    """
    mesh = Fem.FemMesh()
    corners = [
        (x, y, z) for z in (0.0, 1.0) for x, y in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    ]
    for index, (x, y, z) in enumerate(corners, start=1):
        mesh.addNode(x, y, z, index)
    mesh.addVolume([1, 2, 3, 4, 5, 6, 7, 8])
    for node_id, (x, y, z) in enumerate(corners[:4], start=9):
        mesh.addNode(x, y, z, node_id)
    if not quadratic:
        mesh.addFace([9, 10, 11, 12])
        return mesh
    mid_side = ((0.5, 0.0, 0.0), (1.0, 0.5, 0.0), (0.5, 1.0, 0.0), (0.0, 0.5, 0.0))
    for node_id, (x, y, z) in enumerate(mid_side, start=13):
        mesh.addNode(x, y, z, node_id)
    mesh.addFace([9, 10, 11, 12, 13, 14, 15, 16])
    return mesh


def _square_face():
    """The quad of two_bricks_and_a_shell(), as a standalone face.

    It covers half of the first brick's top on purpose: a shell need not cover
    a whole solid face.
    """
    return Part.Face(
        Part.makePolygon(
            [
                FreeCAD.Vector(0.0, 0.0, 1.0),
                FreeCAD.Vector(0.5, 0.0, 1.0),
                FreeCAD.Vector(0.5, 1.0, 1.0),
                FreeCAD.Vector(0.0, 1.0, 1.0),
                FreeCAD.Vector(0.0, 0.0, 1.0),
            ]
        )
    )


def two_bricks_and_a_shell():
    """Two C3D8 bricks apart, plus a quad on the first brick's top face.

    Every element has node ids of its own, so the quad is a shell and not a
    brick's skin. The two bricks exist so each can carry a material of its own,
    which is the case a solid reference must not confuse with the shell.
    """
    mesh = Fem.FemMesh()
    corners = [
        (x, y, z) for z in (0.0, 1.0) for x, y in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    ]
    for index, (x, y, z) in enumerate(corners, start=1):
        mesh.addNode(x, y, z, index)
    mesh.addVolume([1, 2, 3, 4, 5, 6, 7, 8])
    for index, (x, y, z) in enumerate(corners, start=9):
        mesh.addNode(x + 2.0, y, z, index)
    mesh.addVolume([9, 10, 11, 12, 13, 14, 15, 16])
    # The quad covers only part of the brick's top: a shell need not cover a
    # whole solid, and the material it carries must still resolve to its own
    # dimension.
    for index, (x, y) in enumerate(((0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)), start=17):
        mesh.addNode(x, y, 1.0, index)
    mesh.addFace([17, 18, 19, 20])
    return mesh


def brick_only_mesh():
    """A C3D8 brick with no shell elements of its own."""
    mesh = Fem.FemMesh()
    corners = [
        (x, y, z) for z in (0.0, 1.0) for x, y in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    ]
    for index, (x, y, z) in enumerate(corners, start=1):
        mesh.addNode(x, y, z, index)
    mesh.addVolume([1, 2, 3, 4, 5, 6, 7, 8])
    return mesh


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
    def test_tie_master_surface_is_the_solid_not_the_shell(self):
        # A face reference on a solid bounds its volume elements; it is not the
        # shell that merely lies on the same plane. Resolving the master as the
        # shell made the two tie surfaces identical, and ccx then cascaded on
        # the deck without ever solving it.
        doc = FreeCAD.newDocument("mixed_tie_surfaces")
        self.addCleanup(FreeCAD.closeDocument, doc.Name)
        face_coupling.setup(doc=doc, variant="f2")

        mesh = doc.getObject("Mesh").FemMesh
        volume_ids = set(mesh.Volumes)
        shell_ids = set(mesh.FacesOnly)
        self.assertTrue(volume_ids, "the fixture must have volume elements")
        self.assertTrue(shell_ids, "the fixture must have separate shell elements")

        fea = ccxtools.FemToolsCcx(doc.Analysis, doc.CalculiXCcxTools, test_mode=True)
        fea.update_objects()
        workdir = self._temp_dir("tie_surfaces")
        fea.setup_working_dir(str(workdir))
        with mixed_shell_solid_flag(True):
            self.assertFalse(fea.check_prerequisites(), "the gate must be open")
            self.assertFalse(fea.write_inp_file(), "the deck must be written")
        deck = (workdir / "Mesh.inp").read_text(encoding="utf-8")

        slave = {int(entry.split(",")[0]) for entry in self._surface_entries(deck, "TIE_DEPTie1")}
        master = {int(entry.split(",")[0]) for entry in self._surface_entries(deck, "TIE_INDTie1")}
        self.assertTrue(slave, "the slave surface must not be empty")
        self.assertTrue(master, "the master surface must not be empty")
        self.assertTrue(slave <= shell_ids, (slave - shell_ids))
        self.assertTrue(master <= volume_ids, (master - volume_ids))
        self.assertFalse(slave & master, "the two tie surfaces must not be the same")

    # ********************************************************************************************
    def test_tie_slave_side_follows_the_shell_offset(self):
        # CalculiX numbers a shell's faces 1 and 2 as the two sides of its 3D
        # expansion, and the section offset decides which side meets the master.
        # Writing the wrong one puts the joint a thickness away, inside no
        # tolerance, and no tied MPC is generated at all - with no error, and a
        # result that silently looks like the shell was never there.
        for offset, expected in ((-0.5, "S1"), (0.5, "S2"), (0.0, "S2")):
            doc = FreeCAD.newDocument(f"mixed_tie_side_{offset}")
            self.addCleanup(FreeCAD.closeDocument, doc.Name)
            face_coupling.setup(doc=doc, variant="f2")
            doc.getObject("ShellThickness").Offset = offset
            doc.recompute()

            fea = ccxtools.FemToolsCcx(doc.Analysis, doc.CalculiXCcxTools, test_mode=True)
            fea.update_objects()
            workdir = self._temp_dir(f"tie_side_{offset}")
            fea.setup_working_dir(str(workdir))
            with mixed_shell_solid_flag(True):
                self.assertFalse(fea.check_prerequisites(), "the gate must be open")
                self.assertFalse(fea.write_inp_file(), "the deck must be written")
            deck = (workdir / "Mesh.inp").read_text(encoding="utf-8")

            entries = self._surface_entries(deck, "TIE_DEPTie1")
            self.assertTrue(entries, offset)
            self.assertTrue(
                all(entry.endswith("," + expected) for entry in entries),
                (offset, entries[:3]),
            )

    # ********************************************************************************************
    def test_shell_expansion_faces_land_on_the_reference_surface(self):
        # gen3dfrom2d.f places the two outer nodes at ref - t*(0.5+offset) and
        # ref + t*(0.5-offset), so the offset decides which of S1/S2 is the
        # reference surface: -0.5 lands S1, +0.5 lands S2.
        self.assertEqual((0.0, 10.0), shell_expansion_faces(10.0, -0.5))
        self.assertEqual((-10.0, 0.0), shell_expansion_faces(10.0, 0.5))
        self.assertEqual((-5.0, 5.0), shell_expansion_faces(10.0, 0.0))

    # ********************************************************************************************
    def test_tie_side_follows_the_master_and_the_section(self):
        # The face to tie is the expanded face nearest the master, and the
        # tolerance has to reach it. At gap 0 the section's own offset decides;
        # once the master is away from the reference surface, the master side
        # does. Choosing by the offset sign alone named the far face whenever
        # the master was beyond the near one.
        slave = Part.makePlane(10.0, 10.0)
        for gap, offset, expected_side, expected_required in (
            (0.0, 0.0, 2, 5.0),
            (0.0, -0.5, 1, 0.0),
            (0.0, 0.5, 2, 0.0),
            (5.0, 0.0, 2, 0.0),
            (-5.0, 0.0, 1, 0.0),
            (50.0, 0.0, 2, 45.0),
            (-50.0, 0.0, 1, 45.0),
        ):
            master = Part.makePlane(10.0, 10.0).translated(FreeCAD.Vector(0.0, 0.0, gap))
            side, required, measured_gap = tie_slave_side_and_tolerance(
                slave, master, 10.0, offset
            )
            self.assertEqual(expected_side, side, (gap, offset))
            self.assertAlmostEqual(expected_required, required, places=9, msg=(gap, offset))
            self.assertAlmostEqual(gap, measured_gap, places=9, msg=(gap, offset))

    # ********************************************************************************************
    def test_member_for_reference_prefers_the_sections_own_reference(self):
        # A sandwich has one section per skin, offset in opposite directions.
        # Matching the slave's own reference must win over the catch-all: taking
        # the first section in the analysis names the far face, a whole
        # thickness out, and ccx reports it only as "too far away".
        doc = FreeCAD.newDocument("member_for_reference")
        self.addCleanup(FreeCAD.closeDocument, doc.Name)
        analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
        catch_all = analysis.addObject(ObjectsFem.makeElementGeometry2D(doc, 10, "CatchAll"))[0]
        shell = doc.addObject("Part::Feature", "Skin")
        shell.Shape = _square_face()
        own = analysis.addObject(ObjectsFem.makeElementGeometry2D(doc, 10, "OwnSection"))[0]
        own.Offset = -0.5
        own.References = [(shell, "Face1")]
        doc.recompute()

        members = membertools.AnalysisMember(analysis).geos_shellthickness
        self.assertIs(own, member_for_reference(members, (shell, "Face1")))
        self.assertIs(catch_all, member_for_reference(members, (shell, "Face2")))

    # ********************************************************************************************
    def test_tie_tolerance_below_the_geometry_is_refused(self):
        # A tolerance below the chosen face's distance from the master ties no
        # node, with no error from FreeCAD or CalculiX. The write must fail
        # naming both numbers and the offset that removes the distance.
        doc = self._build_meshed(face_coupling, "f2")
        doc.getObject("Tie1").Tolerance = 1.0
        doc.recompute()

        fea = ccxtools.FemToolsCcx(doc.Analysis, doc.CalculiXCcxTools, test_mode=True)
        fea.update_objects()
        with mixed_shell_solid_flag(True):
            message = fea.check_prerequisites()
        self.assertIn("Tie1", message)
        self.assertIn("raise the tolerance to 5 mm", message)
        self.assertIn("Set the shell section offset to 0.5", message)

    # ********************************************************************************************
    def test_edge_tie_slave_is_the_shells_edge_face(self):
        # An Edge on a shell is a side face of the shell's 3D expansion, which
        # CalculiX numbers S3-S6 - exactly the surface an edge interface ties.
        # Resolution must search the shell element table: the plain sub-element
        # search uses the mesh's highest dimension, which holds no shell in a
        # mixed mesh, so it finds nothing and the *SURFACE comes out empty.
        for variant in EDGE_VARIANTS:
            doc = self._build_meshed(edge_coupling, variant)
            shell_ids = set(doc.getObject("Mesh").FemMesh.FacesOnly)
            self.assertTrue(shell_ids, variant)

            fea = ccxtools.FemToolsCcx(doc.Analysis, doc.CalculiXCcxTools, test_mode=True)
            fea.update_objects()
            workdir = self._temp_dir(f"edge_face_{variant}")
            fea.setup_working_dir(str(workdir))
            with mixed_shell_solid_flag(True):
                self.assertFalse(fea.check_prerequisites(), f"{variant} must be accepted")
                self.assertFalse(fea.write_inp_file(), f"{variant} must write a deck")
            deck = (workdir / "Mesh.inp").read_text(encoding="utf-8")

            for tie in self._ties(doc):
                entries = self._surface_entries(deck, f"TIE_DEP{tie.Name}")
                self.assertTrue(entries, f"{variant}/{tie.Name} slave surface is empty")
                for entry in entries:
                    element, _, side = entry.partition(",")
                    self.assertIn(int(element), shell_ids, entry)
                    self.assertIn(side, ("S3", "S4", "S5", "S6"), entry)

    # ********************************************************************************************
    def test_edge_load_on_a_shell_reaches_the_deck(self):
        # A line load on a shell edge is carried by the shell elements. In a
        # mixed mesh the shared element table holds only the highest dimension -
        # the volumes - so without the dimension-2 table the *CLOAD is written
        # empty: the model solves to exactly zero with no error from FreeCAD or
        # CalculiX.
        for variant in EDGE_VARIANTS:
            doc = self._build_meshed(edge_coupling, variant)
            fea = ccxtools.FemToolsCcx(doc.Analysis, doc.CalculiXCcxTools, test_mode=True)
            fea.update_objects()
            workdir = self._temp_dir(f"edge_load_{variant}")
            fea.setup_working_dir(str(workdir))
            with mixed_shell_solid_flag(True):
                self.assertFalse(fea.check_prerequisites(), f"{variant} must be accepted")
                self.assertFalse(fea.write_inp_file(), f"{variant} must write a deck")
            deck = (workdir / "Mesh.inp").read_text(encoding="utf-8")
            self.assertTrue(self._cload_entries(deck), f"{variant} line load is empty")

    # ********************************************************************************************
    def test_tie_on_a_shell_edge_is_accepted(self):
        # ADR 0004 obligation 3, narrowed: an Edge on a shell resolves to the
        # shell's edge face, so it is a surface the tie can use. Only an Edge
        # on a solid - which has no such face - stays refused.
        doc = self._build(edge_coupling, "e2")
        analysis = doc.Analysis
        member = membertools.AnalysisMember(analysis)
        with mixed_shell_solid_flag(True):
            message = check_member_for_solver_calculix(
                analysis, doc.CalculiXCcxTools, doc.getObject("Mesh"), member
            )
        self.assertNotIn("not a face", message, message)

    # ********************************************************************************************
    def test_shape_dimension_follows_a_compound_contents(self):
        # A Compound is whatever it holds, and its ShapeType says only that it is
        # a compound. Calling a compound of faces a solid would send that
        # material to the volume pass and leave the shell unsectioned, which is
        # the mistake the dimension dispatch exists to avoid in the first place.
        from femmesh.meshtools import get_shape_dimension

        square = Part.makeFace(
            Part.makePolygon(
                [
                    FreeCAD.Vector(0.0, 0.0, 0.0),
                    FreeCAD.Vector(1.0, 0.0, 0.0),
                    FreeCAD.Vector(1.0, 1.0, 0.0),
                    FreeCAD.Vector(0.0, 1.0, 0.0),
                    FreeCAD.Vector(0.0, 0.0, 0.0),
                ]
            )
        )
        solid = Part.makeBox(1.0, 1.0, 1.0)
        self.assertEqual(2, get_shape_dimension(square))
        self.assertEqual(3, get_shape_dimension(solid))
        self.assertEqual(2, get_shape_dimension(Part.makeCompound([square, square.copy()])))
        self.assertEqual(3, get_shape_dimension(Part.makeCompound([solid, solid.copy()])))

    # ********************************************************************************************
    def test_two_solid_materials_do_not_claim_the_shell(self):
        # A material that references a solid resolves by node geometry
        # (get_femnodes_by_refshape), and get_material_elements runs its face
        # pass over every material, so a solid reference also reaches shell
        # faces whose nodes lie on that solid. One solid plus one shell dodges
        # this by leaving the solid material's references empty, but only one
        # material may do that, so two solids plus a shell has no working form
        # until the material lookup is dispatched by dimension.
        doc = FreeCAD.newDocument("two_solids_and_a_shell")
        self.addCleanup(FreeCAD.closeDocument, doc.Name)
        analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
        solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiXCcxTools")
        analysis.addObject(solver)
        analysis.addObject(ObjectsFem.makeElementGeometry2D(doc, 0.1, "ShellThickness"))

        box_a = doc.addObject("Part::Box", "BoxA")
        box_a.Length, box_a.Width, box_a.Height = 1.0, 1.0, 1.0
        box_b = doc.addObject("Part::Box", "BoxB")
        box_b.Length, box_b.Width, box_b.Height = 1.0, 1.0, 1.0
        box_b.Placement.Base = FreeCAD.Vector(2.0, 0.0, 0.0)
        shell = doc.addObject("Part::Feature", "Shell")
        shell.Shape = _square_face()

        mesh_obj = analysis.addObject(ObjectsFem.makeMeshGmsh(doc, "Mesh"))[0]
        mesh_obj.FemMesh = two_bricks_and_a_shell()
        compound = doc.addObject("Part::Compound", "Geometry")
        compound.Links = [box_a, box_b, shell]
        mesh_obj.Shape = compound

        material_a = self._steel_material(doc, analysis, "MaterialA")
        material_a.References = [(box_a, "Solid1")]
        material_b = self._steel_material(doc, analysis, "MaterialB")
        material_b.References = [(box_b, "Solid1")]
        material_shell = self._steel_material(doc, analysis, "MaterialShell")
        material_shell.References = [(shell, "Face1")]
        doc.recompute()

        member = membertools.AnalysisMember(analysis)
        getter = meshsetsgetter.MeshSetsGetter(analysis, solver, mesh_obj, member)
        with mixed_shell_solid_flag(True):
            getter.get_element_sets_material_and_femelement_geometry()

        by_name = {m["Object"].Name: m for m in member.mats_linear}
        solid_face_elements = set(by_name["MaterialA"]["FEMElementsByDim"].get(2, []))
        shell_face_elements = set(by_name["MaterialShell"]["FEMElementsByDim"].get(2, []))
        self.assertTrue(solid_face_elements.isdisjoint(shell_face_elements), solid_face_elements)
        self.assertFalse(
            solid_face_elements,
            "a material referencing a solid must not claim the shell's faces",
        )

    # ********************************************************************************************
    def test_compound_references_land_in_their_own_dimension(self):
        # A material may reference a Compound, and get_element resolves that to
        # a shape whose ShapeType is only "Compound". Which pass it belongs to
        # is decided by what the compound holds, so a compound of faces must not
        # be sent to the volume pass, nor a compound of solids to the face pass.
        doc = FreeCAD.newDocument("compound_references")
        self.addCleanup(FreeCAD.closeDocument, doc.Name)
        analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
        solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiXCcxTools")
        analysis.addObject(solver)
        analysis.addObject(ObjectsFem.makeElementGeometry2D(doc, 0.1, "ShellThickness"))

        box_a = doc.addObject("Part::Feature", "BoxA")
        box_a.Shape = Part.makeBox(1.0, 1.0, 1.0)
        box_b = doc.addObject("Part::Feature", "BoxB")
        box_b.Shape = Part.makeBox(1.0, 1.0, 1.0, FreeCAD.Vector(2.0, 0.0, 0.0))
        shell = doc.addObject("Part::Feature", "Shell")
        shell.Shape = _square_face()

        solids_compound = doc.addObject("Part::Feature", "SolidsCompound")
        solids_compound.Shape = Part.makeCompound([box_a.Shape, box_b.Shape])
        faces_compound = doc.addObject("Part::Feature", "FacesCompound")
        faces_compound.Shape = Part.makeCompound([shell.Shape])

        mesh_obj = analysis.addObject(ObjectsFem.makeMeshGmsh(doc, "Mesh"))[0]
        mesh_obj.FemMesh = two_bricks_and_a_shell()
        mesh_obj.Shape = solids_compound

        material_solids = self._steel_material(doc, analysis, "MaterialSolids")
        material_solids.References = [(solids_compound, "")]
        material_faces = self._steel_material(doc, analysis, "MaterialFaces")
        material_faces.References = [(faces_compound, "")]
        doc.recompute()

        member = membertools.AnalysisMember(analysis)
        getter = meshsetsgetter.MeshSetsGetter(analysis, solver, mesh_obj, member)
        with mixed_shell_solid_flag(True):
            getter.get_element_sets_material_and_femelement_geometry()

        by_name = {m["Object"].Name: m for m in member.mats_linear}
        solids = by_name["MaterialSolids"]["FEMElementsByDim"]
        faces = by_name["MaterialFaces"]["FEMElementsByDim"]
        self.assertTrue(solids.get(3), "a compound of solids sections the volumes")
        self.assertFalse(solids.get(2), "a compound of solids must not claim faces")
        self.assertTrue(faces.get(2), "a compound of faces sections the faces")
        self.assertFalse(faces.get(3), "a compound of faces must not claim volumes")

    # ********************************************************************************************
    def test_tie_resolves_a_compound_shell_slave(self):
        # A skin meshed as several faces is a Compound, and a *TIE may name that
        # compound as its slave. It must resolve to the shell elements; the
        # compound's ShapeType is only "Compound", so a dispatch that reads the
        # ShapeType alone sends it to the sub-element search instead.
        doc = FreeCAD.newDocument("tie_compound_slave")
        self.addCleanup(FreeCAD.closeDocument, doc.Name)
        analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
        solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiXCcxTools")
        analysis.addObject(solver)
        analysis.addObject(ObjectsFem.makeElementGeometry2D(doc, 0.1, "ShellThickness"))

        box_a = doc.addObject("Part::Box", "BoxA")
        box_a.Length, box_a.Width, box_a.Height = 1.0, 1.0, 1.0
        box_b = doc.addObject("Part::Box", "BoxB")
        box_b.Length, box_b.Width, box_b.Height = 1.0, 1.0, 1.0
        box_b.Placement.Base = FreeCAD.Vector(2.0, 0.0, 0.0)
        skin = doc.addObject("Part::Feature", "Skin")
        skin.Shape = Part.makeCompound([_square_face()])

        mesh_obj = analysis.addObject(ObjectsFem.makeMeshGmsh(doc, "Mesh"))[0]
        mesh_obj.FemMesh = two_bricks_and_a_shell()
        compound = doc.addObject("Part::Compound", "Geometry")
        compound.Links = [box_a, box_b, skin]
        mesh_obj.Shape = compound

        top_face = next(
            f"Face{index}"
            for index, face in enumerate(box_a.Shape.Faces, start=1)
            if abs(face.CenterOfMass.z - 1.0) < 1e-6
        )
        tie = ObjectsFem.makeConstraintTie(doc, "Tie")
        tie.References = [(skin, ""), (box_a, top_face)]
        tie.Tolerance = 1.0
        analysis.addObject(tie)
        doc.recompute()

        member = membertools.AnalysisMember(analysis)
        getter = meshsetsgetter.MeshSetsGetter(analysis, solver, mesh_obj, member)
        with mixed_shell_solid_flag(True):
            getter.get_constraints_tie_faces()

        tie_data = member.cons_tie[0]
        slave = tie_data["TieSlaveFaces"][0]
        master = tie_data["TieMasterFaces"][0]
        self.assertTrue(slave[1], "the slave surface must not be empty")
        self.assertFalse(slave[2], "a compound shell slave must resolve to shell elements")
        self.assertTrue(master[2], "the solid master resolves to its volume faces")

    # ********************************************************************************************
    def test_mixed_fixed_reaction_force_names_the_split_sets(self):
        # A mixed model splits a fixed constraint's nodes into a solid set and a
        # face-or-edge set, because only the latter carries rotational degrees
        # of freedom. The reaction-force request must name those sets: naming
        # the unsplit name asks ccx for a set that does not exist, and ccx
        # reports no reaction forces at all rather than failing.
        doc, analysis, solver, mesh_obj = self._mixed_analysis_document()
        fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=True)
        fea.update_objects()
        workdir = self._temp_dir("reaction_forces")
        fea.setup_working_dir(str(workdir))
        with mixed_shell_solid_flag(True):
            self.assertFalse(fea.check_prerequisites(), "the gate must be open")
            self.assertFalse(fea.write_inp_file(), "the deck must be written")
        deck = (workdir / "Mesh.inp").read_text(encoding="utf-8")

        self.assertNotIn("*NODE PRINT, NSET=Fixed, TOTALS=ONLY", deck)
        split_requests = sum(
            deck.count(f"*NODE PRINT, NSET=Fixed{suffix}, TOTALS=ONLY")
            for suffix in ("Solid", "FaceEdge")
        )
        self.assertGreater(split_requests, 0, "no reaction forces are requested at all")

    # ********************************************************************************************
    def test_mixed_flag_defaults_on(self):
        # Stage 9's promotion. With the parameter unset the mixed path is on, so
        # a mixed analysis passes the gate that used to refuse it.
        group = FreeCAD.ParamGet(MIXED_FLAG_PATH)
        previous = group.GetBool(MIXED_FLAG_NAME, True)
        group.RemBool(MIXED_FLAG_NAME)
        self.addCleanup(group.SetBool, MIXED_FLAG_NAME, previous)

        doc, analysis, solver, mesh_obj = self._mixed_analysis_document()
        fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=True)
        fea.update_objects()
        fea.setup_working_dir(str(self._temp_dir("default_on")))
        message = fea.check_prerequisites()
        self.assertNotIn(
            "Shell thicknesses defined but FEM mesh has volume elements.", message
        )

    # ********************************************************************************************
    def test_flag_on_still_refuses_a_shell_thickness_on_a_solid_mesh(self):
        # The hardening that makes the promotion safe: the flag says the mixed
        # path may be used, not that this mesh is mixed. A shell thickness on a
        # mesh with volumes but no shells stays an error however the flag is
        # set, or turning the flag on by default would quietly accept it.
        doc, analysis, solver, mesh_obj = self._mixed_analysis_document()
        mesh_obj.FemMesh = brick_only_mesh()
        doc.recompute()

        fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=True)
        fea.update_objects()
        fea.setup_working_dir(str(self._temp_dir("solid_only")))
        with mixed_shell_solid_flag(True):
            message = fea.check_prerequisites()
        self.assertIn("Shell thicknesses defined but FEM mesh has volume elements.", message)

    # ********************************************************************************************
    def test_mixed_deck_agrees_on_output_dimension(self):
        # V3. *EL FILE defaults to expanded nodes just as *NODE FILE does, so a
        # deck that sets only the nodal card to 2d puts element results on a
        # second, larger node set inside the same frd: one file, two node
        # numberings. Both cards must say 2d, and the solver's Output3d default
        # (True) must not win on a mixed mesh, because 3d is undisplayable.
        doc, analysis, solver, mesh_obj = self._mixed_analysis_document()
        self.assertTrue(solver.Output3d, "the fixture must exercise the 3d default")

        fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=True)
        fea.update_objects()
        workdir = self._temp_dir("output_dimension")
        fea.setup_working_dir(str(workdir))
        with mixed_shell_solid_flag(True):
            self.assertFalse(fea.check_prerequisites(), "the gate must be open")
            self.assertFalse(fea.write_inp_file(), "the deck must be written")
        deck = (workdir / "Mesh.inp").read_text(encoding="utf-8")

        self.assertIn("*NODE FILE, OUTPUT=2d", deck)
        self.assertIn("*EL FILE, OUTPUT=2d", deck)
        self.assertNotIn("OUTPUT=3d", deck)

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
    def test_flag_never_changes_a_solid_deck(self):
        # G3. A non-mixed mesh must write the same deck with the flag on and off:
        # the writer picks mode 2 only for a mesh that really is mixed.
        from femexamples.constraint_tie import setup

        doc = FreeCAD.newDocument("mixed_flag_inert_solid")
        self.addCleanup(FreeCAD.closeDocument, doc.Name)
        setup(doc, "ccxtools")

        fea = ccxtools.FemToolsCcx(doc.Analysis, doc.CalculiXCcxTools, test_mode=True)
        fea.update_objects()

        decks = {}
        for enabled in (False, True):
            workdir = self._temp_dir("flag_on" if enabled else "flag_off")
            fea.setup_working_dir(str(workdir))
            self.assertFalse(
                fea.check_prerequisites(), "a solid example must pass prerequisites"
            )
            with mixed_shell_solid_flag(enabled):
                self.assertFalse(fea.write_inp_file(), "writing the deck failed")
            decks[enabled] = workdir / "Mesh.inp"

        difference = testtools.compare_inp_files(str(decks[False]), str(decks[True]))
        self.assertFalse(difference, difference)

    # ********************************************************************************************
    def test_flag_selects_the_mixed_element_mode(self):
        # Stage 2's one line. With the flag off the shell never reaches the
        # deck; with it on the same mesh writes the volume and shell blocks
        # together, which is what element_param 2 means.
        doc, analysis, solver, mesh_obj = self._mixed_analysis_document()
        member = membertools.AnalysisMember(analysis)
        writer = ccx_writer.FemInputWriterCcx(
            analysis, solver, mesh_obj, member, str(self._temp_dir("writer")), []
        )
        writer.split_inpfile = False

        deck_off_path = self._written_deck(writer, self._temp_dir("mode_off"), False)
        deck_on_path = self._written_deck(writer, self._temp_dir("mode_on"), True)

        # Flag off: the shell never reaches the deck, which is why the flag exists.
        deck_off = deck_off_path.read_text(encoding="utf-8")
        self.assertIn("*Element, TYPE=C3D8, ELSET=Evolumes", deck_off)
        self.assertNotIn("ELSET=Efaces", deck_off)

        # Flag on: the volume and shell blocks together, against a committed golden.
        difference = testtools.compare_inp_files(str(self._fixture_golden()), str(deck_on_path))
        self.assertFalse(difference, difference)

    # ********************************************************************************************
    def test_flag_opens_the_mixed_prerequisites_gate(self):
        # Stage 3. The refusal of a shell thickness on a volume mesh is the
        # whole reason a mixed analysis cannot run; it must be gone with the
        # flag on and unchanged with it off.
        messages = {}
        for enabled in (False, True):
            doc, analysis, solver, mesh_obj = self._mixed_analysis_document()
            fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=True)
            fea.update_objects()
            fea.setup_working_dir(str(self._temp_dir("gate_on" if enabled else "gate_off")))
            with mixed_shell_solid_flag(enabled):
                messages[enabled] = fea.check_prerequisites()

        self.assertIn(
            "Shell thicknesses defined but FEM mesh has volume elements.", messages[False]
        )
        self.assertNotIn(
            "Shell thicknesses defined but FEM mesh has volume elements.", messages[True]
        )

        # And the analysis now reaches the writer instead of being refused. The
        # deck's mesh section is the Stage 2 golden; its sections are Stage 5's.
        doc, analysis, solver, mesh_obj = self._mixed_analysis_document()
        fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=True)
        fea.update_objects()
        fea.setup_working_dir(str(self._temp_dir("gate_write")))
        with mixed_shell_solid_flag(True):
            self.assertFalse(fea.check_prerequisites(), "the gate must be open")
            self.assertFalse(fea.write_inp_file(), "the deck must be written")

    # ********************************************************************************************
    def test_flag_still_refuses_beam_sections_with_shell_thickness(self):
        # Beams stay out of scope: the flag opens the shell-and-solid gate, and
        # nothing else.
        for enabled in (False, True):
            doc, analysis, solver, mesh_obj = self._mixed_analysis_document(with_beam_section=True)
            member = membertools.AnalysisMember(analysis)
            with mixed_shell_solid_flag(enabled):
                message = check_member_for_solver_calculix(analysis, solver, mesh_obj, member)
            self.assertIn(
                "Beam sections and shell thicknesses in one analysis are not "
                "supported at the moment.",
                message,
            )

    # ********************************************************************************************
    def test_tie_on_a_non_face_is_refused(self):
        # ADR 0004 obligation 3: a connection that cannot be expressed as a
        # surface must fail loudly. The tie check counted references but never
        # asked whether one *was* a face - the message said "two needed faces"
        # and no face was ever checked - so a tie on an edge passed validation
        # and the writer then built a *SURFACE whose face index came from an
        # edge mask. A deck that means nothing, produced silently.
        for sub_ref in ("Edge1", "Vertex1"):
            doc, analysis, solver, mesh_obj = self._mixed_analysis_document()
            box = doc.getObject("Box")
            tie = ObjectsFem.makeConstraintTie(doc, "Tie")
            tie.References = [(box, "Face1"), (box, sub_ref)]
            analysis.addObject(tie)
            doc.recompute()

            member = membertools.AnalysisMember(analysis)
            with mixed_shell_solid_flag(True):
                message = check_member_for_solver_calculix(analysis, solver, mesh_obj, member)
            self.assertIn(sub_ref, message, message)
            self.assertIn("not a face", message, message)

    # ********************************************************************************************
    def test_tie_on_two_faces_is_still_accepted(self):
        # The guard must refuse only what it is for. Two faces - including a
        # face of a solid, which resolves through the sub-element path rather
        # than the shell table - stay valid.
        doc, analysis, solver, mesh_obj = self._mixed_analysis_document()
        box = doc.getObject("Box")
        tie = ObjectsFem.makeConstraintTie(doc, "Tie")
        tie.References = [(box, "Face1"), (box, "Face2")]
        analysis.addObject(tie)
        doc.recompute()

        member = membertools.AnalysisMember(analysis)
        with mixed_shell_solid_flag(True):
            message = check_member_for_solver_calculix(analysis, solver, mesh_obj, member)
        self.assertNotIn("not a face", message, message)

    # ********************************************************************************************
    def test_mixed_deck_carries_a_solid_and_a_shell_section(self):
        # Stage 5. The deck must section the volumes once, the shell once, and
        # put no element in both.
        doc, analysis, solver, mesh_obj = self._mixed_analysis_document()
        fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=True)
        fea.update_objects()
        workdir = self._temp_dir("sections")
        fea.setup_working_dir(str(workdir))
        with mixed_shell_solid_flag(True):
            self.assertFalse(fea.check_prerequisites(), "the gate must be open")
            self.assertFalse(fea.write_inp_file(), "the deck must be written")
        deck = (workdir / "Mesh.inp").read_text(encoding="utf-8")

        self.assertEqual(1, deck.count("*SOLID SECTION"), deck)
        self.assertEqual(1, deck.count("*SHELL SECTION"), deck)
        self.assertIn("ELSET=Evolumes", deck)
        self.assertIn("ELSET=Efaces", deck)

    def _stub_composite_section(self):
        """Register a stand-in laminate section for the guard's own tests.

        The guard is Fem's, so its test must not need Composites: any provider
        that names COMPOSITE makes the card layered.
        """

        def composite_section(shellth_obj, matgeoset, orientation_name):
            return {"material": "COMPOSITE", "section_geo": "1.0\n"}

        fem_extension_registry.register_shell_section_provider(
            "test.composite_section", composite_section
        )
        self.addCleanup(
            fem_extension_registry.unregister_shell_section_provider, "test.composite_section"
        )

    # ********************************************************************************************
    def test_composite_section_on_a_linear_shell_is_refused(self):
        # The fixture's shell is a linear quad4 and a composite *SHELL SECTION is
        # accepted only for S6 and S8R, so CalculiX would refuse the deck after
        # FreeCAD had written it. The refusal has to happen here instead.
        self._stub_composite_section()
        doc, analysis, solver, mesh_obj = self._mixed_analysis_document()
        fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=True)
        fea.update_objects()
        fea.setup_working_dir(str(self._temp_dir("linear_shell")))
        with mixed_shell_solid_flag(True):
            self.assertFalse(fea.check_prerequisites(), "the gate must be open")
            with self.assertRaises(ValueError) as raised:
                fea.write_inp_file()
        self.assertIn("S6 or S8R", str(raised.exception))

    def test_composite_section_is_written_for_a_quadratic_shell(self):
        # The same model with the quad's mid-side nodes: the guard must let the
        # deck through, or it would refuse every laminate.
        self._stub_composite_section()
        doc, analysis, solver, mesh_obj = self._mixed_analysis_document(quadratic_shell=True)
        fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=True)
        fea.update_objects()
        workdir = self._temp_dir("quadratic_shell")
        fea.setup_working_dir(str(workdir))
        with mixed_shell_solid_flag(True):
            self.assertFalse(fea.write_inp_file(), "the deck must be written")
        deck = (workdir / "Mesh.inp").read_text(encoding="utf-8")
        self.assertIn("*SHELL SECTION", deck)
        self.assertIn("COMPOSITE", deck)

    # ********************************************************************************************
    def test_two_materials_section_their_own_dimension(self):
        # Stage 5, multiple materials. The solid material must section the
        # volumes and the shell material the faces, and neither may reach the
        # other's section - a mixed model's two materials reference different
        # kinds of sub-shape.
        doc = FreeCAD.newDocument("mixed_two_materials")
        self.addCleanup(FreeCAD.closeDocument, doc.Name)
        face_coupling.setup(doc=doc, variant="f2")
        analysis = doc.Analysis
        shell = doc.getObject("Shell")

        # The solid material keeps empty references: a reference to the solid
        # would match the shell patch lying on its face as well, which is the
        # ambiguity per-dimension sections exist to resolve. The shell material
        # names the shell face it is to section.
        shell_material = ObjectsFem.makeMaterialSolid(doc, "ShellMaterial")
        shell_steel = shell_material.Material
        shell_steel["Name"] = "ShellSteel"
        shell_steel["YoungsModulus"] = "210000 MPa"
        shell_steel["PoissonRatio"] = "0.30"
        shell_material.Material = shell_steel
        shell_material.References = [(shell, "Face1")]
        analysis.addObject(shell_material)
        doc.recompute()

        mesh_obj = doc.getObject("Mesh")
        member = membertools.AnalysisMember(analysis)
        getter = meshsetsgetter.MeshSetsGetter(analysis, doc.CalculiXCcxTools, mesh_obj, member)
        with mixed_shell_solid_flag(True):
            getter.get_element_sets_material_and_femelement_geometry()

        shells = [s for s in getter.mat_geo_sets if "shellthickness_obj" in s]
        solids = [s for s in getter.mat_geo_sets if "shellthickness_obj" not in s]
        self.assertEqual(1, len(solids), getter.mat_geo_sets)
        self.assertEqual(1, len(shells), getter.mat_geo_sets)
        self.assertTrue(solids[0]["ccx_elset"], solids[0])
        self.assertTrue(shells[0]["ccx_elset"], shells[0])
        self.assertFalse(
            set(solids[0]["ccx_elset"]) & set(shells[0]["ccx_elset"]),
            "an element may not appear in both sections",
        )
        self.assertEqual("MechanicalMaterial", solids[0]["mat_obj_name"])
        self.assertEqual("ShellMaterial", shells[0]["mat_obj_name"])

    # ********************************************************************************************
    def test_displacement_prescribes_rotation_only_on_shell_nodes(self):
        # Stage 6. A solid node has no rotational degree of freedom, so a
        # displacement's DOF 4-6 must name the shell nodes alone, while DOF 1-3
        # may name the whole set.
        doc = FreeCAD.newDocument("mixed_displacement_dof")
        self.addCleanup(FreeCAD.closeDocument, doc.Name)
        face_coupling.setup(doc=doc, variant="f2")
        shell = doc.getObject("Shell")

        disp = ObjectsFem.makeConstraintDisplacement(doc, "Displacement")
        disp.References = [(shell, "Face1")]
        disp.rotxFree = False
        analysis = doc.Analysis
        analysis.addObject(disp)
        doc.recompute()

        fea = ccxtools.FemToolsCcx(analysis, doc.CalculiXCcxTools, test_mode=True)
        fea.update_objects()
        workdir = self._temp_dir("displacement_dof")
        fea.setup_working_dir(str(workdir))
        with mixed_shell_solid_flag(True):
            self.assertFalse(fea.check_prerequisites(), "the gate must be open")
            self.assertFalse(fea.write_inp_file(), "the deck must be written")

        deck = (workdir / "Mesh.inp").read_text(encoding="utf-8")
        self.assertIn("*NSET,NSET=DisplacementFaceEdge", deck)
        self.assertIn("DisplacementFaceEdge,4,4,", deck)
        self.assertNotIn("Displacement,4,4,", deck)

    # ********************************************************************************************
    def test_every_variant_meshes_to_a_mixed_femmesh(self):
        # The live-Gmsh half: each variant's parts meshed alone and merged must
        # give one mesh holding volumes and separate faces. Counts only - a
        # live mesh is not byte-stable and must not be asserted as if it were.
        for module, variants in (
            (face_coupling, FACE_VARIANTS),
            (edge_coupling, EDGE_VARIANTS),
        ):
            for variant in variants:
                doc = FreeCAD.newDocument(f"mesh_{module.__name__[-4:]}_{variant}")
                self.addCleanup(FreeCAD.closeDocument, doc.Name)
                module.setup(doc=doc, variant=variant)
                mesh = doc.getObject("Mesh").FemMesh
                self.assertGreater(len(mesh.Volumes), 0, variant)
                self.assertGreater(len(mesh.FacesOnly), 0, variant)

    # ********************************************************************************************
    def test_example_meshes_to_a_runnable_mixed_deck(self):
        # The example's own geometry, each part meshed alone and merged, must
        # reach the writer with the flag on and section both of its parts. This
        # is the end of the route the merge helper exists for.
        doc = FreeCAD.newDocument("mixed_example_end_to_end")
        self.addCleanup(FreeCAD.closeDocument, doc.Name)
        face_coupling.setup(doc=doc, variant="f2")

        mesh_obj = doc.getObject("Mesh")
        self.assertGreater(len(mesh_obj.FemMesh.Volumes), 0)
        self.assertGreater(len(mesh_obj.FemMesh.FacesOnly), 0)

        fea = ccxtools.FemToolsCcx(doc.Analysis, doc.CalculiXCcxTools, test_mode=True)
        fea.update_objects()
        workdir = self._temp_dir("end_to_end")
        fea.setup_working_dir(str(workdir))
        with mixed_shell_solid_flag(True):
            self.assertFalse(fea.check_prerequisites(), "the gate must be open")
            self.assertFalse(fea.write_inp_file(), "the deck must be written")

        deck = (workdir / "Mesh.inp").read_text(encoding="utf-8")
        self.assertIn("ELSET=Evolumes", deck)
        self.assertIn("ELSET=Efaces", deck)
        self.assertIn("*SOLID SECTION", deck)
        self.assertIn("*SHELL SECTION", deck)

    def _mixed_analysis_document(self, with_beam_section=False, quadratic_shell=False):
        doc = FreeCAD.newDocument(f"{self._testMethodName}_analysis")
        self.addCleanup(FreeCAD.closeDocument, doc.Name)
        analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
        solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiXCcxTools")
        solver.ReducedIntegration = False
        analysis.addObject(solver)

        material = ObjectsFem.makeMaterialSolid(doc, "Material")
        steel = material.Material
        steel["Name"] = "CalculiX-Steel"
        steel["YoungsModulus"] = "210000 MPa"
        steel["PoissonRatio"] = "0.30"
        material.Material = steel
        analysis.addObject(material)

        analysis.addObject(ObjectsFem.makeElementGeometry2D(doc, 10, "ShellThickness"))
        if with_beam_section:
            analysis.addObject(ObjectsFem.makeElementGeometry1D(doc, name="BeamSection"))

        mesh_obj = analysis.addObject(ObjectsFem.makeMeshGmsh(doc, "Mesh"))[0]
        mesh_obj.FemMesh = node_disjoint_brick_and_shell(quadratic=quadratic_shell)

        # The fixture mesh has no geometry of its own; a unit box on the same
        # coordinates gives the constraints something to reference and the
        # analysis something to satisfy before it can be written.
        box = doc.addObject("Part::Box", "Box")
        mesh_obj.Shape = box
        fixed = ObjectsFem.makeConstraintFixed(doc, "Fixed")
        fixed.References = [(box, "Face1")]
        analysis.addObject(fixed)
        doc.recompute()
        return doc, analysis, solver, mesh_obj

    def _written_deck(self, writer, workdir, flag_enabled):
        writer.dir_name = str(workdir)
        writer.file_name = str(workdir / "Mesh.inp")
        with mixed_shell_solid_flag(flag_enabled):
            inpfile = write_mesh_module.write_mesh(writer)
        inpfile.close()
        return Path(writer.file_name)

    def _fixture_golden(self):
        return (
            Path(__file__).resolve().parent.parent
            / "data"
            / "calculix"
            / "mixed_shell_solid_fixture.inp"
        )

    def _temp_dir(self, name):
        root = Path(tempfile.gettempdir()) / "mixed_shell_solid" / f"{self._testMethodName}_{name}"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root

    # ********************************************************************************************
    def _build(self, module, variant):
        doc = FreeCAD.newDocument(f"{self.__class__.__name__}_{variant}")
        self.addCleanup(FreeCAD.closeDocument, doc.Name)
        module.setup(doc=doc, variant=variant, test_mode=True)
        return doc

    def _build_meshed(self, module, variant):
        """Build and mesh a variant, for tests that need a real mixed mesh."""
        doc = FreeCAD.newDocument(f"{self.__class__.__name__}_{variant}_meshed")
        self.addCleanup(FreeCAD.closeDocument, doc.Name)
        module.setup(doc=doc, variant=variant)
        return doc

    def _solids(self, doc):
        return [obj for obj in doc.Objects if obj.Name.startswith("Solid")]

    def _ties(self, doc):
        return [obj for obj in doc.Objects if obj.Name.startswith("Tie")]

    def _steel_material(self, doc, analysis, name):
        material = ObjectsFem.makeMaterialSolid(doc, name)
        data = material.Material
        data["Name"] = name
        data["YoungsModulus"] = "210000 MPa"
        data["PoissonRatio"] = "0.30"
        material.Material = data
        analysis.addObject(material)
        return material

    def _subname(self, reference):
        subname = reference[1]
        if isinstance(subname, (list, tuple)):
            return subname[0]
        return subname

    def _surface_entries(self, deck, name):
        entries, collecting = [], False
        for line in deck.splitlines():
            if line.startswith("*SURFACE"):
                collecting = f"NAME={name}" in line
                continue
            if line.startswith("*"):
                collecting = False
                continue
            if collecting and line.strip():
                entries.append(line.strip())
        return entries

    def _cload_entries(self, deck):
        entries, collecting = [], False
        for line in deck.splitlines():
            if line.startswith("**"):
                continue
            if line.startswith("*CLOAD"):
                collecting = True
                continue
            if line.startswith("*"):
                collecting = False
                continue
            if collecting and line.strip():
                entries.append(line.strip())
        return entries


# ---------------------------------------------------------------------------
# One real solve, so this suite is not all deck text.
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_a_mixed_face_deck_solves_through_the_fem_solver(tmp_path):
    """ccx accepts a mixed deck and a result comes back.

    The fixtures in this file carry no constraints and no loads - they exist
    to assert deck text and mesh structure - so the solve runs on the f1
    face-coupling example, which has both.  What is asserted here is the Fem
    layer only: the deck solves and a result is read back.  What the result
    *means* - the tied skin against an all-solid rebuild, and each face
    family's untied-node count - belongs to the Composites suite's
    ``test_mixed_coupling_numerical.py``, which drives the composite pipeline;
    repeating that comparison here would be a second copy of it.
    """
    doc = face_coupling.setup(variant="f1")
    try:
        fea = ccxtools.FemToolsCcx(analysis=doc.Analysis, solver=doc.CalculiXCcxTools)
        with mixed_shell_solid_flag(True):
            fea.setup_working_dir(str(tmp_path))
            solved = fea.run()
        assert solved, "ccx refused the mixed deck; see the log above"
        results = [
            o for o in doc.Analysis.Group
            if o.isDerivedFrom("Fem::FemResultObject")
        ]
        assert results, "the mixed deck solved but no result was read back"
        displacements = [float(v) for v in results[0].DisplacementLengths]
        assert displacements, "the result carries no displacement"
        assert max(displacements) > 0.0, "the mixed deck solved to zero displacement"
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_mesh_parts_separately_returns_no_groups_for_one_part():
    """One part and several parts must return a mesh of the same shape.

    ``mesh_parts_separately`` meshes each part alone.  A part meshed alone
    keeps gmsh's groups for its own sub-shapes, and those carry no document
    object's name, so ``get_solid_element_sets`` takes its group path, matches
    nothing, fails the element count check, and resolves the mesh again down
    the search path.  Two or more parts are merged, and ``merge_femmeshes``
    copies no groups, so the several-part route only ever runs the search path.
    The single-part route has to agree, group count zero included.
    """
    doc = FreeCAD.newDocument("mesh_part_groups")
    try:
        box = add_shape(doc, "Box", Part.makeBox(20.0, 10.0, 10.0))
        other = add_shape(
            doc, "Other", Part.makeBox(20.0, 10.0, 10.0, FreeCAD.Vector(30.0, 0.0, 0.0))
        )
        assembly = make_compound(doc, "Assembly", [box, other])
        doc.recompute()

        single = mesh_parts_separately(doc, [assembly], max_size=5.0)
        several = mesh_parts_separately(doc, [box, other], max_size=5.0)

        assert single.VolumeCount > 0
        assert single.GroupCount == 0, (
            "a part meshed alone kept its gmsh groups; the element-set resolver "
            "will take the group path and find nothing"
        )
        assert several.GroupCount == 0
        assert single.VolumeCount == several.VolumeCount
    finally:
        FreeCAD.closeDocument(doc.Name)


def _bulkhead_document(shell_thickness=5.0):
    """A shell bulkhead spanning a hollow solid hull, tied round its perimeter.

    B2.1: the stiffener half of the mixed coverage exists geometrically (the
    e2 web on a plate), but a *bulkhead* is defined by being bonded all round —
    here four edge interfaces, one per cavity wall, which is the E family B6
    made solvable.
    """
    doc = FreeCAD.newDocument("mixed_bulkhead")
    hull = add_shape(
        doc,
        "Hull",
        Part.makeBox(100.0, 50.0, 50.0).cut(
            Part.makeBox(90.0, 40.0, 40.0, FreeCAD.Vector(5.0, 5.0, 5.0))
        ),
    )
    bulkhead = add_shape(
        doc,
        "Bulkhead",
        planar_face([(5.0, 25.0, 5.0), (95.0, 25.0, 5.0), (95.0, 25.0, 45.0), (5.0, 25.0, 45.0)]),
    )
    make_compound(doc, "MixedGeometry", [hull, bulkhead])

    analysis = add_analysis(doc, "ccxtools")
    add_shell_thickness(doc, analysis, shell_thickness)
    add_fixed(doc, analysis, extreme_face_reference(hull, axis=0, sign=-1))
    add_force(doc, analysis, (bulkhead, "Face1"), magnitude=100.0, direction=(0, 0, -1))

    # One tie per cavity wall the perimeter meets: floor, ceiling, and both
    # side walls. The slave edge is on the shell, the master is the solid face.
    for name, edge, master_axis, master_value in (
        ("TieFloor", ((5.0, 25.0, 5.0), (95.0, 25.0, 5.0)), "z", 5.0),
        ("TieCeiling", ((5.0, 25.0, 45.0), (95.0, 25.0, 45.0)), "z", 45.0),
        ("TieLeft", ((5.0, 25.0, 5.0), (5.0, 25.0, 45.0)), "x", 5.0),
        ("TieRight", ((95.0, 25.0, 5.0), (95.0, 25.0, 45.0)), "x", 95.0),
    ):
        add_tie(
            doc,
            analysis,
            name,
            find_edge_reference(bulkhead, *edge),
            face_reference_on_axis(hull, master_axis, master_value, planar_only=True),
            shell_thickness,
        )

    mesh_obj = add_mesh(doc, analysis, doc.getObject("MixedGeometry"))
    mesh_obj.FemMesh = mesh_parts_separately(doc, [hull, bulkhead])
    doc.recompute()
    return doc


@pytest.mark.slow
def test_a_mixed_bulkhead_couples_and_solves(tmp_path):
    """A shell bulkhead tied round its perimeter into a solid hull.

    B2.1's exit: a mixed case that puts a shell bulkhead on a solid feature.
    Every perimeter edge is an E-family interface, so this also exercises what
    B6 made solvable, and a solve that converges with no untied node is the
    evidence the four ties couple.
    """
    doc = _bulkhead_document()
    try:
        fea = ccxtools.FemToolsCcx(analysis=doc.Analysis, solver=doc.CalculiXCcxTools)
        with mixed_shell_solid_flag(True):
            fea.setup_working_dir(str(tmp_path))
            solved = fea.run()
        assert solved, "ccx refused the mixed bulkhead deck; see the log above"
        assert not fea.has_missed_ties(), (
            "a perimeter tie generated no MPC for slave nodes that found no "
            "master face"
        )
        results = [o for o in doc.Analysis.Group if o.isDerivedFrom("Fem::FemResultObject")]
        assert results, "the mixed bulkhead deck solved but no result was read back"
        displacements = [float(v) for v in results[0].DisplacementLengths]
        assert max(displacements) > 0.0, "the mixed bulkhead deck solved to zero displacement"
    finally:
        FreeCAD.closeDocument(doc.Name)


@pytest.mark.slow
@pytest.mark.parametrize("variant", EDGE_VARIANTS)
def test_a_mixed_edge_deck_solves_through_the_fem_solver(tmp_path, variant):
    """ccx accepts a mixed edge-interface deck and a result comes back.

    The E family couples a shell's edge face (S3-S6) to a solid face, and its
    line load rides on the shell edge.  With no tie the shell is a disconnected
    part and the deck is singular, so a solve that reaches a result with the tie
    uncoupled-refusal clear is the Fem-layer evidence that the edge face
    coupled.  What the result *means* - a moment carried at the tied edge
    against a clamped root - belongs to the Composites suite, as it does for
    the face family.
    """
    doc = edge_coupling.setup(variant=variant)
    try:
        fea = ccxtools.FemToolsCcx(analysis=doc.Analysis, solver=doc.CalculiXCcxTools)
        with mixed_shell_solid_flag(True):
            fea.setup_working_dir(str(tmp_path))
            solved = fea.run()
        assert solved, f"ccx refused the mixed {variant} edge deck; see the log above"
        assert not fea.has_missed_ties(), (
            f"{variant}: the *TIE generated no MPC for slave nodes that found "
            "no master face; the edge face did not couple"
        )
        results = [
            o for o in doc.Analysis.Group
            if o.isDerivedFrom("Fem::FemResultObject")
        ]
        assert results, "the mixed edge deck solved but no result was read back"
        displacements = [float(v) for v in results[0].DisplacementLengths]
        assert displacements, "the result carries no displacement"
        assert max(displacements) > 0.0, "the mixed edge deck solved to zero displacement"
    finally:
        FreeCAD.closeDocument(doc.Name)


@pytest.mark.slow
def test_a_mixed_deck_with_the_landing_offset_solves_with_no_untied_node(tmp_path):
    """The offset that lands the expanded face on the master rescues a small tolerance.

    The partner of the refusal test: the same under-toleranced model, with the
    section offset set so the tie's chosen face coincides with the master. The
    write passes and CalculiX reports no untied node, which is the evidence that
    the face the writer named is the one that reaches.
    """
    doc = face_coupling.setup(variant="f2")
    try:
        doc.getObject("ShellThickness").Offset = -0.5
        doc.getObject("Tie1").Tolerance = 1.0
        doc.recompute()
        fea = ccxtools.FemToolsCcx(analysis=doc.Analysis, solver=doc.CalculiXCcxTools)
        with mixed_shell_solid_flag(True):
            fea.setup_working_dir(str(tmp_path))
            solved = fea.run()
        assert solved, "ccx refused the landing-offset deck; see the log above"
        assert not fea.has_missed_ties(), (
            "the *TIE generated no MPC for slave nodes that found no master face"
        )
        results = [
            o for o in doc.Analysis.Group
            if o.isDerivedFrom("Fem::FemResultObject")
        ]
        assert results, "the deck solved but no result was read back"
        displacements = [float(v) for v in results[0].DisplacementLengths]
        assert max(displacements) > 0.0, "the deck solved to zero displacement"
    finally:
        FreeCAD.closeDocument(doc.Name)
