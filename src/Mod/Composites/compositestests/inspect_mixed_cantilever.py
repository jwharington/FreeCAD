# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Measure a mixed shell-and-solid cantilever against the same model all solid.

Stage 7 of docs/plan-mixed-shell-solid-fem.md. The coupling route - a shell
meshed apart from a solid and joined by *TIE - is validated by bending a
composite cantilever and comparing its tip deflection with the same section
modelled entirely in solids.

The model is a spar 100 x 20 x 20 with a skin 100 x 20, thickness 5, sitting on
its top face so the two make a 25 mm deep section. The skin is a shell in the
mixed model and a solid slab in the reference. Both are fixed at x=0 and loaded
downward at the spar's tip edge (x=100, z=0), so the load's height, and thus its
moment arm, is identical in the two.

Two things make the comparison meaningful:

  * the shell's section offset is -0.5, so the shell occupies z=20..25. The
    manual defines OFFSET=0.5 as the reference surface being the top surface of
    the shell, so a skin resting *on* the spar is the negative case. Without an
    offset the shell would be a zero-thickness midsurface on z=20 and the two
    models would not have the same section.
  * the tip deflection is read from the .frd through FreeCAD's own result
    object, not from a hand-written *NODE PRINT: a FreeCAD deck writes *NODE
    FILE, so a *.dat readout would validate a deck no user can produce.

Tolerance, fixed before the run and never relaxed (repo rule): the mixed tip
deflection must be within 5% of the all-solid reference. It is: the mixed model
gives 6.4223e-02 mm against 6.4163e-02 mm, a difference of 0.09%.

Getting there exposed two defects, both now fixed:

  * a face reference on a solid resolved to a coincident shell, so a *TIE's
    master surface came out identical to its slave and ccx cascaded without
    solving (`meshtools.get_elements_by_reference_dimension`);
  * the tie wrote the shell slave surface as face 2 on every element, but
    CalculiX numbers a shell's faces 1 and 2 as the two sides of the shell's 3D
    expansion, and the section offset decides which one meets the master. With
    the skin on top, face 2 is a whole thickness away, so CalculiX generated no
    tied MPC at all and the skin floated: the mixed model then returned exactly
    the bare spar. That silent failure is what made the result look like a
    hinge (`write_constraint_tie._shell_slave_face`).

The probe still knows how to isolate those: `--model bare` is the spar alone,
`--model tied_solid` replaces the shell with a solid slab joined the same way,
`--model compound` points the two materials at a compound of solids and a
compound of faces rather than at bare shapes (and gives the tie the whole skin
compound as its slave), and `--phase write` stops before ccx.

Usage, from the repo root:

    ~/.pi/agent/skills/freecad-dev/scripts/run-script.sh \
        src/Mod/Composites/compositestests/inspect_mixed_cantilever.py [--ccx PATH] [--keep]

Run under FreeCADCmd: it meshes, writes the deck and reads the result through
FreeCAD.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import FreeCAD
import ObjectsFem
import Part
from FreeCAD import Vector

from femtools import ccxtools
from femmesh import meshtools
from femexamples.meshes import generate_mesh

DEFAULT_CCX = os.path.expanduser("~/.local/bin/ccx")

LENGTH = 100.0
WIDTH = 20.0
SPAR_HEIGHT = 20.0
SKIN_THICKNESS = 5.0
FORCE = 1000.0
YOUNGS_MODULUS = "210000 MPa"
POISSON_RATIO = "0.30"

# Bounded element size: the default lets Gmsh pick a much finer mesh than a
# tip-deflection comparison needs, and a finer mesh costs memory in ccx and
# again when the .frd is read back.
MESH_SIZE = 5.0

# Bending is the whole point of this model, and linear tets and triangles are
# far too stiff in bending to compare across two different discretisations.
# Second order gives C3D10 and S6, and S6 is one of the two shell forms the
# CalculiX manual allows for a composite *SHELL SECTION.
SECOND_ORDER = True

# ccx stops being interrupted only by a wall-clock bound, and its output kept to
# a cap, so a degenerate deck costs a bounded amount of memory instead of
# filling a machine.
CCX_TIMEOUT = 120.0
CCX_OUTPUT_CAP = 2_000_000

TOLERANCE = 0.05


def _spar_shape():
    return Part.makeBox(LENGTH, WIDTH, SPAR_HEIGHT)


def _skin_shape():
    wire = Part.makePolygon(
        [
            Vector(0, 0, SPAR_HEIGHT),
            Vector(LENGTH, 0, SPAR_HEIGHT),
            Vector(LENGTH, WIDTH, SPAR_HEIGHT),
            Vector(0, WIDTH, SPAR_HEIGHT),
            Vector(0, 0, SPAR_HEIGHT),
        ]
    )
    return Part.Face(wire)


def _solid_reference_shape():
    return Part.makeBox(LENGTH, WIDTH, SPAR_HEIGHT + SKIN_THICKNESS)


def _skin_slab_shape():
    """The skin as a solid slab sitting on the spar, for the bonded reference."""
    return Part.makeBox(LENGTH, WIDTH, SKIN_THICKNESS, Vector(0, 0, SPAR_HEIGHT))


def _face_at_x(obj, x):
    """Reference to the face whose plane is x = ``x`` on a box-shaped part."""
    for index, face in enumerate(obj.Shape.Faces, start=1):
        if abs(face.CenterOfMass.x - x) < 1e-6:
            return (obj, f"Face{index}")
    raise ValueError(f"{obj.Name} has no face at x={x}")


def _edge_at_xz(obj, x, z):
    """Reference to the edge whose mid-point is (``x``, *, ``z``)."""
    for index, edge in enumerate(obj.Shape.Edges, start=1):
        point = edge.CenterOfMass
        if abs(point.x - x) < 1e-6 and abs(point.z - z) < 1e-6:
            return (obj, f"Edge{index}")
    raise ValueError(f"{obj.Name} has no edge at x={x}, z={z}")


def _material(doc, analysis, name, references):
    material = ObjectsFem.makeMaterialSolid(doc, name)
    steel = material.Material
    steel["Name"] = "CalculiX-Steel"
    steel["YoungsModulus"] = YOUNGS_MODULUS
    steel["PoissonRatio"] = POISSON_RATIO
    material.Material = steel
    material.References = references
    analysis.addObject(material)
    return material


def _add_material(analysis, doc, with_shell_thickness):
    material = ObjectsFem.makeMaterialSolid(doc, "MechanicalMaterial")
    steel = material.Material
    steel["Name"] = "CalculiX-Steel"
    steel["YoungsModulus"] = YOUNGS_MODULUS
    steel["PoissonRatio"] = POISSON_RATIO
    material.Material = steel
    analysis.addObject(material)

    if with_shell_thickness:
        thickness = ObjectsFem.makeElementGeometry2D(doc, SKIN_THICKNESS, "ShellThickness")
        # The manual: "OFFSET=0.5 means that the reference surface is the top
        # surface of the shell". The skin must sit *on* the spar, so it goes the
        # other way: -0.5 makes the reference surface the bottom and the section
        # occupies z=20..25, where the reference model's skin slab is.
        thickness.Offset = -0.5
        analysis.addObject(thickness)


def _add_solver(analysis, doc):
    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiXCcxTools")
    solver.WorkingDir = ""
    solver.SplitInputWriter = False
    solver.AnalysisType = "static"
    solver.GeometricalNonlinearity = False
    solver.ThermoMechSteadyState = False
    solver.MatrixSolverType = "default"
    solver.IterationsControlParameterTimeUse = False
    solver.ReducedIntegration = False
    analysis.addObject(solver)
    return solver


def _meshed_part(doc, name, shape):
    part = doc.addObject("Part::Feature", name)
    part.Shape = shape
    mesh_obj = ObjectsFem.makeMeshGmsh(doc, name + "Mesh")
    mesh_obj.Shape = part
    mesh_obj.CharacteristicLengthMax = MESH_SIZE
    mesh_obj.CharacteristicLengthMin = MESH_SIZE / 4.0
    mesh_obj.ElementOrder = "2nd" if SECOND_ORDER else "1st"
    mesh_obj.SecondOrderLinear = False
    mesh_obj.ParallelProcessing = False
    doc.recompute()
    if not generate_mesh.mesh_from_mesher(mesh_obj, "gmsh"):
        raise RuntimeError(f"meshing {name} failed")
    return part, mesh_obj


def _build_mixed(doc):
    spar, spar_mesh = _meshed_part(doc, "Spar", _spar_shape())
    skin, skin_mesh = _meshed_part(doc, "Skin", _skin_shape())
    merged, _, _ = meshtools.merge_femmeshes(spar_mesh.FemMesh, skin_mesh.FemMesh)
    doc.removeObject(spar_mesh.Name)
    doc.removeObject(skin_mesh.Name)

    compound = doc.addObject("Part::Compound", "MixedGeometry")
    compound.Links = [spar, skin]

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = _add_solver(analysis, doc)
    _add_material(analysis, doc, with_shell_thickness=True)

    fixed = ObjectsFem.makeConstraintFixed(doc, "Fixed")
    fixed.References = [_face_at_x(spar, 0.0)]
    analysis.addObject(fixed)

    force = ObjectsFem.makeConstraintForce(doc, "Force")
    force.References = [_edge_at_xz(spar, LENGTH, 0.0)]
    force.Force = f"{FORCE} N"
    force.DirectionVector = Vector(0, 0, -1)
    analysis.addObject(force)

    tie = ObjectsFem.makeConstraintTie(doc, "Tie")
    tie.References = [_top_face(skin), _top_face(spar)]
    # A zero position tolerance makes CalculiX cascade over an under-determined
    # constraint set and never converge; the examples use 1.0 mm here too.
    tie.Tolerance = 1.0
    analysis.addObject(tie)

    mesh_obj = analysis.addObject(ObjectsFem.makeMeshGmsh(doc, "Mesh"))[0]
    mesh_obj.Shape = compound
    mesh_obj.ElementOrder = "2nd" if SECOND_ORDER else "1st"
    mesh_obj.FemMesh = merged
    doc.recompute()
    return analysis, solver, mesh_obj


def _top_face(obj):
    return _face_at_z(obj, SPAR_HEIGHT)


def _face_at_z(obj, z):
    for index, face in enumerate(obj.Shape.Faces, start=1):
        if abs(face.CenterOfMass.z - z) < 1e-6:
            return (obj, f"Face{index}")
    raise ValueError(f"{obj.Name} has no face at z={z}")


def _build_bare(doc):
    """The spar alone: the measured baseline the skin has to beat."""
    spar, spar_mesh = _meshed_part(doc, "Spar", _spar_shape())
    solid_mesh = spar_mesh.FemMesh
    doc.removeObject(spar_mesh.Name)

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = _add_solver(analysis, doc)
    _add_material(analysis, doc, with_shell_thickness=False)

    fixed = ObjectsFem.makeConstraintFixed(doc, "Fixed")
    fixed.References = [_face_at_x(spar, 0.0)]
    analysis.addObject(fixed)

    force = ObjectsFem.makeConstraintForce(doc, "Force")
    force.References = [_edge_at_xz(spar, LENGTH, 0.0)]
    force.Force = f"{FORCE} N"
    force.DirectionVector = Vector(0, 0, -1)
    analysis.addObject(force)

    mesh_obj = analysis.addObject(ObjectsFem.makeMeshGmsh(doc, "Mesh"))[0]
    mesh_obj.Shape = spar
    mesh_obj.ElementOrder = "2nd" if SECOND_ORDER else "1st"
    mesh_obj.FemMesh = solid_mesh
    doc.recompute()
    return analysis, solver, mesh_obj


def _build_tied_solid(doc):
    """The skin as a solid slab, tied to the spar at z=20.

    Same two materials and the same disjoint-node join as the mixed model, so
    the only difference is that the skin is a volume rather than a shell. If the
    result is the bonded one, the tie is fine and the shell is the problem; if
    it matches the spar alone, the join itself does not bond.
    """
    spar, spar_mesh = _meshed_part(doc, "Spar", _spar_shape())
    slab, slab_mesh = _meshed_part(doc, "Skin", _skin_slab_shape())
    merged, _, _ = meshtools.merge_femmeshes(spar_mesh.FemMesh, slab_mesh.FemMesh)
    doc.removeObject(spar_mesh.Name)
    doc.removeObject(slab_mesh.Name)

    compound = doc.addObject("Part::Compound", "BondedGeometry")
    compound.Links = [spar, slab]

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = _add_solver(analysis, doc)
    _add_material(analysis, doc, with_shell_thickness=False)

    fixed = ObjectsFem.makeConstraintFixed(doc, "Fixed")
    fixed.References = [_face_at_x(spar, 0.0)]
    analysis.addObject(fixed)

    force = ObjectsFem.makeConstraintForce(doc, "Force")
    force.References = [_edge_at_xz(spar, LENGTH, 0.0)]
    force.Force = f"{FORCE} N"
    force.DirectionVector = Vector(0, 0, -1)
    analysis.addObject(force)

    tie = ObjectsFem.makeConstraintTie(doc, "Tie")
    tie.References = [_face_at_z(slab, SPAR_HEIGHT), _face_at_z(spar, SPAR_HEIGHT)]
    tie.Tolerance = 1.0
    analysis.addObject(tie)

    mesh_obj = analysis.addObject(ObjectsFem.makeMeshGmsh(doc, "Mesh"))[0]
    mesh_obj.Shape = compound
    mesh_obj.ElementOrder = "2nd" if SECOND_ORDER else "1st"
    mesh_obj.FemMesh = merged
    doc.recompute()
    return analysis, solver, mesh_obj


def _build_compound(doc):
    """The cantilever again, with the materials referencing compounds.

    A material may point at a Compound rather than a bare solid or face, and its
    reference must still land in the pass for its own dimension. Here the spar
    is a compound of solids and the skin a compound of faces, so both compound
    forms go through the writer and ccx, not only through the sets getter.
    """
    spar, spar_mesh = _meshed_part(doc, "Spar", Part.makeCompound([_spar_shape()]))
    skin, skin_mesh = _meshed_part(doc, "Skin", Part.makeCompound([_skin_shape()]))
    merged, _, _ = meshtools.merge_femmeshes(spar_mesh.FemMesh, skin_mesh.FemMesh)
    doc.removeObject(spar_mesh.Name)
    doc.removeObject(skin_mesh.Name)

    compound = doc.addObject("Part::Compound", "MixedGeometry")
    compound.Links = [spar, skin]

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = _add_solver(analysis, doc)
    _material(doc, analysis, "SolidMaterial", [(spar, "")])
    _material(doc, analysis, "ShellMaterial", [(skin, "")])
    thickness = ObjectsFem.makeElementGeometry2D(doc, SKIN_THICKNESS, "ShellThickness")
    thickness.Offset = -0.5
    analysis.addObject(thickness)

    fixed = ObjectsFem.makeConstraintFixed(doc, "Fixed")
    fixed.References = [_face_at_x(spar, 0.0)]
    analysis.addObject(fixed)

    force = ObjectsFem.makeConstraintForce(doc, "Force")
    force.References = [_edge_at_xz(spar, LENGTH, 0.0)]
    force.Force = f"{FORCE} N"
    force.DirectionVector = Vector(0, 0, -1)
    analysis.addObject(force)

    tie = ObjectsFem.makeConstraintTie(doc, "Tie")
    # The slave is the whole skin compound, which is what a multi-patch skin
    # would be, rather than one named face of it.
    tie.References = [(skin, ""), _top_face(spar)]
    tie.Tolerance = 1.0
    analysis.addObject(tie)

    mesh_obj = analysis.addObject(ObjectsFem.makeMeshGmsh(doc, "Mesh"))[0]
    mesh_obj.Shape = compound
    mesh_obj.ElementOrder = "2nd" if SECOND_ORDER else "1st"
    mesh_obj.FemMesh = merged
    doc.recompute()
    return analysis, solver, mesh_obj


def _build_all_solid(doc):
    body, body_mesh = _meshed_part(doc, "Body", _solid_reference_shape())
    solid_mesh = body_mesh.FemMesh
    doc.removeObject(body_mesh.Name)

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = _add_solver(analysis, doc)
    _add_material(analysis, doc, with_shell_thickness=False)

    fixed = ObjectsFem.makeConstraintFixed(doc, "Fixed")
    fixed.References = [_face_at_x(body, 0.0)]
    analysis.addObject(fixed)

    force = ObjectsFem.makeConstraintForce(doc, "Force")
    force.References = [_edge_at_xz(body, LENGTH, 0.0)]
    force.Force = f"{FORCE} N"
    force.DirectionVector = Vector(0, 0, -1)
    analysis.addObject(force)

    mesh_obj = analysis.addObject(ObjectsFem.makeMeshGmsh(doc, "Mesh"))[0]
    mesh_obj.Shape = body
    mesh_obj.ElementOrder = "2nd" if SECOND_ORDER else "1st"
    mesh_obj.FemMesh = solid_mesh
    doc.recompute()
    return analysis, solver, mesh_obj


def _write_deck(analysis, solver, workdir):
    os.makedirs(workdir, exist_ok=True)
    fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=True)
    fea.update_objects()
    fea.setup_working_dir(workdir)
    error = fea.check_prerequisites()
    if error:
        raise RuntimeError(str(error).strip())
    error = fea.write_inp_file()
    if error:
        raise RuntimeError(str(error).strip())
    return fea


def _run_ccx_bounded(cmd, workdir, timeout, cap=CCX_OUTPUT_CAP):
    """Run ccx, keeping at most ``cap`` bytes of its combined output.

    A tie that degenerates makes ccx print constraint warnings without end.
    Reading that with ``subprocess.run(capture_output=True)`` grows a Python
    string until memory is gone; here the output is drained line by line and
    everything past the cap is dropped.
    """
    proc = subprocess.Popen(
        cmd, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    kept, total, truncated = [], 0, False
    deadline = time.monotonic() + timeout
    with proc.stdout:
        for line in proc.stdout:
            if total < cap:
                kept.append(line)
                total += len(line)
            else:
                truncated = True
            if time.monotonic() > deadline:
                proc.kill()
                break
    proc.wait()
    return proc.returncode, "".join(kept), truncated


def _report_result_visibility(mesh_obj, result, displacements):
    """V1 and V2 of the plan's section 8.9: is the result drawable at all?

    V1 is the panel gate itself - the frd's node set must equal the mesh's.
    V2 is the one that matters: a shell missing from the result as opposed to
    missing from the deck cannot be seen in deck text, so check that the shell
    nodes and the solid nodes both carry a displacement.
    """
    femmesh = mesh_obj.FemMesh
    print(
        f"    V1 frd nodes={len(result.NodeNumbers)} mesh nodes={femmesh.NodeCount} "
        f"gate={'PASS' if len(result.NodeNumbers) == femmesh.NodeCount else 'FAIL'}"
    )
    shell_nodes = {n for eid in femmesh.FacesOnly for n in femmesh.getElementNodes(eid)}
    solid_nodes = {n for eid in femmesh.Volumes for n in femmesh.getElementNodes(eid)}
    shell_moved = [displacements[n].Length for n in shell_nodes if n in displacements]
    solid_moved = [displacements[n].Length for n in solid_nodes if n in displacements]
    print(
        f"    V2 shell nodes moving={len(shell_moved)}/{len(shell_nodes)} "
        f"max={max(shell_moved, default=0.0):.3e} | "
        f"solid nodes moving={len(solid_moved)}/{len(solid_nodes)} "
        f"max={max(solid_moved, default=0.0):.3e} | "
        f"{'PASS' if shell_moved and solid_moved else 'FAIL'}"
    )


def _check_tie_warnings(output, base):
    """Refuse a run where a *TIE coupled fewer nodes than it was given.

    CalculiX writes the node numbers for two unrelated reasons to the same
    ``.nam`` file, and only stdout tells them apart, so the classification lives
    in ``ccxtools.tied_mpc_warning_counts``. Only the first kind is a defect.
    A user's own model may contain the benign kind and still be fine; this probe
    checks a model whose whole point is to be compared with an all-solid
    rebuild, so it must not pass a solve that has the other kind.
    """
    not_coupled, already_constrained = ccxtools.tied_mpc_warning_counts(output)
    if not_coupled:
        raise RuntimeError(
            f"{not_coupled} slave node(s) found no opposite master face, so the "
            f"*TIE does not couple them - see stdout for the distances and "
            f"{base}_WarnNodeMissTiedContact.nam for the node numbers"
        )
    if already_constrained:
        print(
            f"    tie: {already_constrained} DOF(s) were already constrained, "
            f"so no tie MPC was needed (benign; not an uncoupling)"
        )


def _run_and_read_tip(analysis, solver, mesh_obj, workdir, ccx):
    fea = _write_deck(analysis, solver, workdir)
    base = os.path.basename(os.path.splitext(fea.inp_file_name)[0])
    code, output, truncated = _run_ccx_bounded([ccx, "-i", base], workdir, CCX_TIMEOUT)
    if code != 0 or "Job finished" not in output:
        note = " (output truncated)" if truncated else ""
        raise RuntimeError(f"ccx did not finish (exit {code}){note}:\n{output[-4000:]}")
    _check_tie_warnings(output, base)

    fea.load_results()
    result = next(
        (obj for obj in analysis.Group if obj.isDerivedFrom("Fem::FemResultObject")), None
    )
    if result is None:
        raise RuntimeError("no result object after loading the frd")

    displacements = dict(zip(result.NodeNumbers, result.DisplacementVectors))
    _report_result_visibility(mesh_obj, result, displacements)
    tip_nodes = [
        node_id
        for node_id, node in mesh_obj.FemMesh.Nodes.items()
        if abs(node.x - LENGTH) < 1e-6 and abs(node.z) < 1e-6
    ]
    values = [abs(displacements[n].z) for n in tip_nodes if n in displacements]
    if not values:
        raise RuntimeError("no tip displacement recovered")
    return sum(values) / len(values)


def _measure(builder, name, args):
    doc = FreeCAD.newDocument(name)
    try:
        analysis, solver, mesh_obj = builder(doc)
        if args.output3d is not None:
            solver.Output3d = args.output3d
        femmesh = mesh_obj.FemMesh
        print(
            f"[{name}] nodes={femmesh.NodeCount} volumes={femmesh.VolumeCount} "
            f"faces={femmesh.FaceCount} edges={femmesh.EdgeCount}"
        )
        if args.phase == "mesh":
            return None
        workdir = os.path.join(args.workdir, name)
        if args.phase == "write":
            fea = _write_deck(analysis, solver, workdir)
            size = os.path.getsize(fea.inp_file_name)
            print(f"[{name}] deck {fea.inp_file_name} ({size} bytes)")
            return None
        tip = _run_and_read_tip(analysis, solver, mesh_obj, workdir, args.ccx)
        print(f"[{name}] tip |uz| = {tip:.6e} mm")
        return tip
    finally:
        FreeCAD.closeDocument(doc.Name)


BUILDERS = {
    "mixed": _build_mixed,
    "solid": _build_all_solid,
    "bare": _build_bare,
    "tied_solid": _build_tied_solid,
    "compound": _build_compound,
}


def measure(builder, name, workdir, ccx=DEFAULT_CCX, phase="run", output3d=None):
    """Build and run one model, returning its tip deflection, or None if not run.

    The entry point for callers other than main(). The numerical test would
    otherwise have to fabricate an argparse namespace to reach a model, and
    holding the model definitions in one place is the point - a second copy
    would be free to drift away from the one whose numbers the plan quotes.
    """
    args = argparse.Namespace(phase=phase, workdir=workdir, ccx=ccx, output3d=output3d)
    return _measure(builder, name, args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ccx", default=DEFAULT_CCX, help="path to the ccx binary")
    parser.add_argument("--keep", action="store_true", help="keep the work directories")
    parser.add_argument(
        "--phase",
        choices=["mesh", "write", "run"],
        default="run",
        help="stop after meshing, after writing the deck, or run ccx too",
    )
    parser.add_argument(
        "--output3d",
        choices=["on", "off"],
        default=None,
        help="set the solver's Output3d flag; default leaves it as built",
    )
    parser.add_argument(
        "--model",
        choices=["mixed", "solid", "bare", "tied_solid", "compound", "all"],
        default="all",
        help="which model(s) to build",
    )
    args = parser.parse_args(argv)
    if args.output3d is not None:
        args.output3d = args.output3d == "on"

    args.workdir = (
        os.path.join(tempfile.gettempdir(), "mixed_cantilever")
        if args.keep
        else tempfile.mkdtemp(prefix="mixed_cantilever_")
    )
    shutil.rmtree(args.workdir, ignore_errors=True)

    if args.phase == "run" and not os.path.exists(args.ccx):
        print(f"ccx not found at {args.ccx}; use --ccx to point at one", file=sys.stderr)
        return 2

    # The mixed model needs the flag on; the old value is put back afterwards.
    group = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/General")
    previous_flag = group.GetBool("AllowMixedShellSolid", False)
    group.SetBool("AllowMixedShellSolid", True)

    names = ["mixed", "solid"] if args.model == "all" else [args.model]
    results = {}
    try:
        for name in names:
            results[name] = _measure(BUILDERS[name], name, args)
    finally:
        group.SetBool("AllowMixedShellSolid", previous_flag)
        if args.keep:
            print(f"work directories kept under {args.workdir}")
        else:
            shutil.rmtree(args.workdir, ignore_errors=True)

    if args.phase != "run" or len(results) < 2:
        return 0

    mixed = results["mixed"]
    solid = results["solid"]
    relative = abs(mixed - solid) / solid
    print(f"mixed/all-solid = {mixed / solid:.4f} (relative difference {relative:.2%})")
    print(f"tolerance stated before the run: {TOLERANCE:.0%}")
    if relative <= TOLERANCE:
        print("VERDICT: the tied skin carries the section within tolerance")
        return 0
    print("VERDICT: DIFFERS from the all-solid reference beyond tolerance")
    return 1


if __name__ == "__main__":
    status = main()
    sys.stdout.flush()
    raise SystemExit(status)
