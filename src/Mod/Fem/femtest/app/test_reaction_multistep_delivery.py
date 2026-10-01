"""Does one CalculiX deck carrying N reaction snapshots solve N independent
load cases?

The multi-load-case plan batches every load case of a model variant into one
deck as N *STEP blocks, so the mesh and the per-element laminate blocks are
written once instead of once per case.  That only works if two things hold,
and neither is stated anywhere in CalculiX's documentation:

1. each step's *CLOAD must fully replace the previous step's, because a
   *CLOAD value is a per-step total rather than an increment — an entry a
   step does not repeat carries over;
2. the results must come back one per step, in step order, so a caller can
   map them onto its cases without guessing.

This module pins both against the committed reaction example, which is the
cheapest model that exercises the real delivery path.
"""

import shutil
import subprocess

import FreeCAD
import pytest

from femexamples import constraint_reaction as reaction_example
from femtest.app import support_utils

Vector = FreeCAD.Vector

# the moment reference the example ships with; every snapshot below shares it
# so a step differs from the next only in its wrench, exactly as a load-case
# sweep does.
ORIGIN = FreeCAD.Placement(Vector(4000, 1000, 1000), FreeCAD.Rotation())

# Distinct wrenches on purpose: if the writer emitted one snapshot for every
# step, or a step inherited its predecessor's loads by carry-over, the
# per-step resultants below would collapse onto each other and agree by
# accident.
CASES = (
    {"Force": Vector(0, 0, -2000), "Torque": Vector(10, 0, 0)},
    {"Force": Vector(0, 0, -2000), "Torque": Vector(0, 0, 0)},
    {"Force": Vector(0, 0, 4000), "Torque": Vector(-5, 0, 0)},
)


def _displacement(result):
    """Node number to displacement vector, as the frd importer stored them."""
    return dict(zip(result.NodeNumbers, result.DisplacementVectors))


def _snapshots(cases):
    return [{
        "ConstraintReaction": {
            "Force": case["Force"],
            "Torque": case["Torque"],
            "Origin": ORIGIN,
        }
    } for case in cases]


def _write_deck(tmp_path, cases):
    """Build the example and write a deck with one step per case.

    The caller owns the returned document and must close it.
    """
    doc = reaction_example.setup()
    analysis = doc.getObject("Analysis")
    solver = next(o for o in analysis.Group
                  if o.isDerivedFrom("Fem::FemSolverObject"))
    solver.WorkingDir = str(tmp_path)
    from femtools.ccxtools import FemToolsCcx

    fem = FemToolsCcx(analysis=analysis, solver=solver)
    fem.update_objects()
    fem.step_count = len(cases)
    fem.reaction_snapshots = _snapshots(cases)
    fem.set_inp_file_name()
    fem.write_inp_file()
    return doc, fem


@pytest.mark.slow
def test_multistep_deck_has_one_step_per_case(tmp_path):
    doc, fem = _write_deck(tmp_path, CASES)
    try:
        _nodes, preamble, steps = support_utils.parse_calculix_deck(
            fem.inp_file_name)
        assert len(steps) == len(CASES), (
            "wrote %d steps for %d cases" % (len(steps), len(CASES)))
        # a load written outside every step belongs to step 1, so case 2
        # would inherit it for the rest of the deck.  The reaction is
        # step-dependent, so there must be none.
        assert preamble["entries"] == [], (
            "%d *CLOAD entries written before the first *STEP — they would "
            "apply to every step" % len(preamble["entries"]))
        for index, step in enumerate(steps):
            # without OP=NEW a step only overrides the dofs it repeats and
            # silently keeps the previous case's loads on all the others.
            assert step["op_new"], "a step wrote *CLOAD without OP=NEW"
            assert step["entries"], "step %d wrote no load at all" % (index + 1)
        # The entry *count* is deliberately not compared between steps: the
        # nodal distribution of a wrench depends on the wrench, so two
        # different load cases legitimately load different node sets.  What
        # makes that safe is OP=NEW above, which is asserted per step, and
        # what makes it correct is the resultant in the test below.
    finally:
        FreeCAD.closeDocument(doc.Name)


@pytest.mark.slow
def test_multistep_deck_delivers_each_case(tmp_path):
    doc, fem = _write_deck(tmp_path, CASES)
    try:
        nodes, _preamble, steps = support_utils.parse_calculix_deck(
            fem.inp_file_name)
        origin = ORIGIN.Base
        # the writer delivers -Force / -Torque of the constraint object
        expected = [(-case["Force"], -case["Torque"]) for case in CASES]
        for index, (step, (want_force, want_moment)) in enumerate(
                zip(steps, expected)):
            force, moment = support_utils.cload_resultant(
                step["entries"], nodes, origin)
            assert (force - want_force).Length < 1e-6, (
                "step %d delivered %s, expected %s"
                % (index + 1, force, want_force))
            assert (moment - want_moment).Length < 1e-3, (
                "step %d delivered moment %s, expected %s"
                % (index + 1, moment, want_moment))
    finally:
        FreeCAD.closeDocument(doc.Name)


# One cube, bottom face fixed, -100 N in z on the top nodes.  Step 2 hands
# nodes 5-7 to CalculiX and says nothing about node 8; step 3 says explicitly
# that node 8 carries zero.  Batching load cases is only sound if those two
# steps agree, because a load case that happens to miss a node out of its
# distribution is otherwise silently contaminated by the case before it.
_OMITVERSUS_ZERO_DECK = """**
*NODE
1,0,0,0
2,10,0,0
3,10,10,0
4,0,10,0
5,0,0,10
6,10,0,10
7,10,10,10
8,0,10,10
**
*NSET,NSET=BOT
1,
2,
3,
4,
**
*ELEMENT,TYPE=C3D8,ELSET=E1
1,1,2,3,4,5,6,7,8
**
*MATERIAL,NAME=AL
*ELASTIC
70000.,0.3
*SOLID SECTION,ELSET=E1,MATERIAL=AL
**
*STEP
*STATIC
1.,2.
*BOUNDARY
BOT,1,6,0.
*CLOAD, OP=NEW
5,3,-100.
6,3,-100.
7,3,-100.
8,3,-100.
*NODE FILE
U
*END STEP
**
*STEP
*STATIC
1.,2.
*CLOAD, OP=NEW
5,3,-100.
6,3,-100.
7,3,-100.
*NODE FILE
U
*END STEP
**
*STEP
*STATIC
1.,2.
*CLOAD, OP=NEW
5,3,-100.
6,3,-100.
7,3,-100.
8,3,0.
*NODE FILE
U
*END STEP
"""


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ccx") is None, reason="needs ccx")
def test_opnew_clears_an_entry_the_step_omits(tmp_path):
    inp = tmp_path / "omit_versus_zero.inp"
    inp.write_text(_OMITVERSUS_ZERO_DECK)
    subprocess.run([shutil.which("ccx"), inp.stem], cwd=tmp_path, check=True,
                   capture_output=True)

    doc = FreeCAD.newDocument("opnew_clears")
    try:
        analysis = doc.addObject("App::DocumentObjectGroup", "Analysis")
        import feminout.importCcxFrdResults as importCcxFrdResults

        importCcxFrdResults.importFrd(
            str(inp.with_suffix(".frd")), analysis, "CCX_", "static")
        results = [o for o in analysis.Group
                   if o.isDerivedFrom("Fem::FemResultObject")]
        assert len(results) == 3, (
            "ccx wrote 3 one-increment steps but %d result objects came back "
            "— the case-to-result mapping cannot rely on ordering" % len(results))

        omitted = _displacement(results[1])[8]
        zeroed = _displacement(results[2])[8]
        loaded = _displacement(results[0])[8]
        assert loaded.z < 0, "the reference step did not even load node 8"
        assert (omitted - zeroed).Length < 1e-12, (
            "omitting node 8 from an OP=NEW card is not the same as zeroing "
            "it: %s vs %s — the step inherited the previous case's load"
            % (omitted, zeroed))
    finally:
        FreeCAD.closeDocument(doc.Name)
