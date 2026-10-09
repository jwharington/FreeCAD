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

import Fem
import ObjectsFem

from femtools import ccxtools
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


def node_disjoint_brick_and_shell():
    """A C3D8 brick plus a quad on one of its faces, on node ids of its own.

    The quad sits at the brick's bottom-face coordinates but shares no node with
    it, which is the merge route the mixed plan takes. A node-merged quad is the
    volume's own skin and getFacesOnly drops it - Trap A.
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
    mesh.addFace([9, 10, 11, 12])
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

    def _mixed_analysis_document(self, with_beam_section=False):
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
        mesh_obj.FemMesh = node_disjoint_brick_and_shell()

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

    def _subname(self, reference):
        subname = reference[1]
        if isinstance(subname, (list, tuple)):
            return subname[0]
        return subname
