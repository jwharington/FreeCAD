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


def _peak_displacement(result):
    return max(float(v) for v in result.DisplacementLengths)


def _snapshots(cases):
    return [{
        "ConstraintReaction": {
            "Force": case["Force"],
            "Torque": case["Torque"],
            "Origin": ORIGIN,
        }
    } for case in cases]


class _ReactionModel:
    """The reaction example, built once, so every deck a test writes is
    carried on the same mesh.

    gmsh's element count varies between meshes of the same geometry, so two
    decks built from two separate meshes disagree at the 1e-5 level for a
    reason that has nothing to do with how a step delivers its load.  Compar-
    ing decks only says anything about the steps if they share a mesh.
    """

    def __init__(self):
        self.doc = reaction_example.setup()
        self.analysis = self.doc.getObject("Analysis")
        self.solver = next(o for o in self.analysis.Group
                           if o.isDerivedFrom("Fem::FemSolverObject"))
        from femtools.ccxtools import FemToolsCcx

        self.ccx = FemToolsCcx(analysis=self.analysis, solver=self.solver)
        self.ccx.update_objects()

    def close(self):
        FreeCAD.closeDocument(self.doc.Name)

    def write(self, cases, working_dir):
        """Write one deck carrying one *STEP per case onto this mesh."""
        self.solver.WorkingDir = str(working_dir)
        self.ccx.step_count = len(cases)
        self.ccx.reaction_snapshots = _snapshots(cases)
        self.ccx.set_inp_file_name()
        self.ccx.write_inp_file()
        return self.ccx

    def solve(self, cases, working_dir):
        """Solve a deck and return each step's peak displacement, in step
        order."""
        working_dir.mkdir(parents=True, exist_ok=True)
        ccx = self.write(cases, working_dir)
        assert ccx.ccx_run() == 0, "ccx failed on a %d-case deck" % len(cases)
        ccx.purge_results()
        ccx.load_results()
        results = [o for o in self.analysis.Group
                   if o.isDerivedFrom("Fem::FemResultObject")]
        assert len(results) == len(cases), (
            "%d cases but %d result increments came back — one increment "
            "per step is what maps a result back onto its case" % (len(cases),
                                                                   len(results)))
        return [_peak_displacement(o) for o in results]

    def deck(self, cases, working_dir):
        """The written input of a deck, for checks that need no solve."""
        return self.write(cases, working_dir).inp_file_name


@pytest.mark.slow
def test_multistep_deck_has_one_step_per_case(tmp_path):
    model = _ReactionModel()
    try:
        inp = model.deck(CASES, tmp_path)
        _nodes, preamble, steps = support_utils.parse_calculix_deck(inp)
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
        model.close()


@pytest.mark.slow
def test_multistep_deck_delivers_each_case(tmp_path):
    model = _ReactionModel()
    try:
        nodes, _preamble, steps = support_utils.parse_calculix_deck(
            model.deck(CASES, tmp_path))
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
        model.close()


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


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ccx") is None, reason="needs ccx")
def test_batch_matches_the_same_cases_run_one_at_a_time(tmp_path):
    """The acceptance gate for batching: N cases in one deck must give the
    same answers as N runs of one case each.

    The model is linear elastic with no NLGEOM and every step is a single
    increment, so there is nothing here that could legitimately make a step
    depend on its neighbours — the two paths must agree to solver
    round-off.  A gap of any real size means a step carried load over from
    the case before it, and the per-step resultant checks above are what to
    read first.
    """
    model = _ReactionModel()
    try:
        batched = model.solve(CASES, tmp_path / "deck")
        one_at_a_time = [model.solve([case], tmp_path / ("single%d" % i))
                         for i, case in enumerate(CASES)]
    finally:
        model.close()

    assert len(batched) == len(CASES)
    for index, (deck_peak, singles) in enumerate(zip(batched, one_at_a_time)):
        assert (deck_peak / singles[0]) - 1.0 == pytest.approx(0.0, abs=1e-9), (
            "case %d: %g in the deck vs %g run alone — ratio %.10g"
            % (index + 1, deck_peak, singles[0], deck_peak / singles[0]))
