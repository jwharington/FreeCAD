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

import Fem
import ObjectsFem

from femtools import ccxtools
from femtools import fem_extension_registry
from femtools import membertools
from femtools.checksanalysis import check_member_for_solver_calculix
from femmesh import meshsetsgetter
from femsolver.calculix import writer as ccx_writer
from femsolver.calculix import write_mesh as write_mesh_module
from femexamples import constraint_mixed_edge_coupling as edge_coupling
from femexamples import constraint_mixed_face_coupling as face_coupling
from femexamples._mixed_coupling_common import paired_faces_by_plane
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
