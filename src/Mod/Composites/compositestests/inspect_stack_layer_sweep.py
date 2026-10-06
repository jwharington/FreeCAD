# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Layer-count sweep for the merged-deck CalculiX round trip (diagnosis).

The merged single-layer presentation crashes ccx on the §7.6 plate while the
form-identical presentation solves at article scale — and the plate crash
clears as soon as one section anywhere carries two layers.  This tool maps
the boundary directly: it builds the same plate with k sub-laminates (each
collapsing to one merged layer under SmearedFabric), so the deck presents
exactly k merged layers per section, and solves k = 1..8 through the real
writer → deck → ccx path.

For every k that fails, the deck is kept and re-tried with the section
``ORIENTATION=`` references stripped (the cards remain) — separating "the
merged deck at this layer count" from "the merged deck plus orientation
references".  Each row reports the deck's actual layer counts, any
undefined-material faults, and the solve outcome.

Run from the Composites source root via the FreeCAD interpreter, e.g.
``FreeCADCmd -c "exec(open('compositestests/inspect_stack_layer_sweep.py').read())"``.
"""

import re
import subprocess
import sys
import os

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import FreeCAD
import Part

import Composites  # noqa: E402, F401
import Composites.objects  # noqa: E402, F401

from Composites.compositeexamples.examples._shell_example_common import (  # noqa: E402
    _add_analysis_member,
    _add_fixed_constraint,
    _add_shell_section_and_material,
    _create_fem_base,
    _mesh_support,
    _prepare_feature_import_environment,
    _run_ccx,
    _set_constraint_refs,
)

from compositestests.test_quasi_iso_fem import (  # noqa: E402
    CARBON,
    PLATE_LENGTH,
    PLATE_WIDTH,
    RESIN,
    _add_edge_force,
    _edge_names_by_x,
)
from compositestests.test_stack_model_ccx import (  # noqa: E402
    _deck_faults,
    _shell_section_blocks,
)

_SUB_PLY_COUNT = 2
_SUB_PLY_THICKNESS = "0.2 mm"
_MESH_MAX_SIZE = 15.0


def _build_case(k, name):
    """Plate whose merged deck presents exactly k layers per section.

    k sub-laminates of two same-angle plies each, assembled asymmetrically
    into a top laminate: SmearedFabric merges one nesting level, so each
    sub-laminate collapses to one merged layer and the deck presents k.
    """
    _prepare_feature_import_environment()
    from Composites.features.CompositeLaminate import CompositeLaminateFP
    from Composites.features.CompositeShell import CompositeShellFP
    from Composites.features.FibreCompositeLamina import (
        FibreCompositeLaminaFP,
    )
    from Composites.features.Rosette import RosetteFP
    from Composites.objects import SymmetryType, WeaveType

    doc = FreeCAD.newDocument(name)
    support = doc.addObject("Part::Feature", f"{name}_Support")
    support.Shape = Part.makePlane(PLATE_LENGTH, PLATE_WIDTH)

    def _ply(idx, tag):
        ply = doc.addObject("App::FeaturePython", f"{tag}_Ply{idx:02d}")
        FibreCompositeLaminaFP(ply)
        ply.FibreMaterial = CARBON
        ply.FibreVolumeFraction = 55
        ply.Thickness = FreeCAD.Units.Quantity(_SUB_PLY_THICKNESS)
        ply.Angle = 0.0
        ply.WeaveType = WeaveType.UD.name
        return ply

    subs = []
    for sub_idx in range(k):
        tag = f"{name}_Sub{sub_idx:02d}"
        sub = doc.addObject("Part::FeaturePython", tag)
        CompositeLaminateFP(
            sub, laminae=[_ply(1, tag), _ply(2, tag)]
        )
        sub.ResinMaterial = RESIN
        sub.FibreVolumeFraction = 55
        sub.Symmetry = SymmetryType.Assymmetric.name
        subs.append(sub)

    top_tag = f"{name}_Laminate"
    top = doc.addObject("Part::FeaturePython", top_tag)
    CompositeLaminateFP(top, laminae=subs)
    top.ResinMaterial = RESIN
    top.FibreVolumeFraction = 55
    top.Symmetry = SymmetryType.Assymmetric.name
    top.IsotropicEquivalent = False
    top.StackModelType = "SmearedFabric"
    doc.recompute()

    shell = doc.addObject("Part::FeaturePython", f"{name}_Shell")
    CompositeShellFP(shell, support, laminate=top, rosette=None)
    rosette = doc.addObject("Part::FeaturePython", f"{name}_Rosette")
    RosetteFP(rosette, support=(support, ["Face1"]))
    rosette.Angle = 0.0
    shell.Rosette = rosette
    shell.DrapePitch = 5.0
    doc.recompute()

    analysis, solver, mesh_obj = _create_fem_base(doc, name)
    mesh_obj.CharacteristicLengthMax = _MESH_MAX_SIZE
    _add_shell_section_and_material(
        doc, analysis, support, name, shell_obj=shell
    )
    _mesh_support(mesh_obj, support)
    min_edge, max_edge = _edge_names_by_x(support)
    _add_fixed_constraint(doc, analysis, support, min_edge, name)
    _add_edge_force(doc, analysis, support, max_edge, name)
    doc.recompute()
    return doc, analysis, solver, mesh_obj


def _solve(analysis, solver, mesh_obj, name):
    try:
        solve_result, fem = _run_ccx(analysis, solver, mesh_obj)
    except Exception as exc:  # the writer/mesher can also fail; report it
        return False, None, str(exc)
    return bool(solve_result), fem.inp_file_name, None


def _deck_layer_counts(deck):
    return sorted({len(b) for b in _shell_section_blocks(deck)})


_REF_RE = re.compile(r",ORIENTATION=_OR_[^,\n]*")


def _no_ref_variant(inp_file):
    """Copy of the deck with section ORIENTATION= references stripped."""
    text = open(inp_file, encoding="utf-8", errors="ignore").read()
    out = inp_file.replace(".inp", "_noref.inp")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(_REF_RE.sub("", text))
    return out


def _run_ccx_on(inp_file):
    job = os.path.basename(inp_file)[: -len(".inp")]
    proc = subprocess.run(
        ["ccx", job],
        cwd=os.path.dirname(inp_file),
        capture_output=True,
        text=True,
        timeout=600,
    )
    return proc.returncode, "".join(
        line for line in (proc.stdout + proc.stderr).splitlines(True)
        if "ERROR" in line or "realloc" in line or "Segmentation" in line
    )[:200]


def _build_case_qi(name, mesh_max_size, model_type="SmearedCore"):
    """The standard §7.6 QI plate with a stack model, as the tests build it."""
    _prepare_feature_import_environment()
    from Composites.features.CompositeLaminate import CompositeLaminateFP
    from Composites.features.CompositeShell import CompositeShellFP
    from Composites.features.FibreCompositeLamina import (
        FibreCompositeLaminaFP,
    )
    from Composites.features.Rosette import RosetteFP
    from Composites.objects import SymmetryType, WeaveType

    doc = FreeCAD.newDocument(name)
    support = doc.addObject("Part::Feature", f"{name}_Support")
    support.Shape = Part.makePlane(PLATE_LENGTH, PLATE_WIDTH)

    plies = []
    for idx, angle in enumerate((0.0, 45.0, -45.0, 90.0), start=1):
        ply = doc.addObject("App::FeaturePython", f"{name}_Ply{idx:02d}")
        FibreCompositeLaminaFP(ply)
        ply.FibreMaterial = CARBON
        ply.FibreVolumeFraction = 55
        ply.Thickness = FreeCAD.Units.Quantity("0.2 mm")
        ply.Angle = angle
        ply.WeaveType = WeaveType.UD.name
        plies.append(ply)
    laminate = doc.addObject("Part::FeaturePython", f"{name}_Laminate")
    CompositeLaminateFP(laminate, laminae=plies)
    laminate.ResinMaterial = RESIN
    laminate.FibreVolumeFraction = 55
    laminate.Symmetry = SymmetryType.Even.name
    laminate.IsotropicEquivalent = False
    laminate.StackModelType = model_type
    doc.recompute()

    shell = doc.addObject("Part::FeaturePython", f"{name}_Shell")
    CompositeShellFP(shell, support, laminate=laminate, rosette=None)
    rosette = doc.addObject("Part::FeaturePython", f"{name}_Rosette")
    RosetteFP(rosette, support=(support, ["Face1"]))
    rosette.Angle = 0.0
    shell.Rosette = rosette
    shell.DrapePitch = 5.0
    doc.recompute()

    analysis, solver, mesh_obj = _create_fem_base(doc, name)
    mesh_obj.CharacteristicLengthMax = mesh_max_size
    _add_shell_section_and_material(
        doc, analysis, support, name, shell_obj=shell
    )
    _mesh_support(mesh_obj, support)
    min_edge, max_edge = _edge_names_by_x(support)
    _add_fixed_constraint(doc, analysis, support, min_edge, name)
    _add_edge_force(doc, analysis, support, max_edge, name)
    doc.recompute()
    return doc, analysis, solver, mesh_obj


def _face_element_count(inp_file):
    with open(inp_file, encoding="utf-8", errors="ignore") as fh:
        in_faces = False
        n = 0
        for line in fh:
            if line.startswith("*ELSET, ELSET=Efaces"):
                in_faces = True
            elif in_faces:
                if line.startswith("*"):
                    break
                if "," in line:
                    n += 1
        return n


def main(k_values=range(1, 9)):
    print(f"{'k':>2} {'deck layers':>12} {'faults':>8} "
          f"{'solve':>8} {'no-ref solve':>13}  note")
    for k in k_values:
        name = f"LayerSweep{k}"
        doc, analysis, solver, mesh_obj = _build_case(k, name)
        ok, inp_file, err = _solve(analysis, solver, mesh_obj, name)
        counts = faults = "-"
        note = err or ""
        noref = "-"
        if inp_file:
            with open(inp_file, encoding="utf-8", errors="ignore") as fh:
                deck = fh.read()
            counts = ",".join(str(c) for c in _deck_layer_counts(deck))
            faults = str(len(_deck_faults(deck)))
            if not ok:
                no_ref_inp = _no_ref_variant(inp_file)
                rc, ccx_err = _run_ccx_on(no_ref_inp)
                noref = f"rc={rc}"
                if ccx_err:
                    note = ccx_err.strip()
            else:
                note = ""
        print(f"{k:>2} {counts:>12} {faults:>8} "
              f"{'OK' if ok else 'FAIL':>8} {noref:>13}  {note}")
        FreeCAD.closeDocument(name)


def sweep_mesh(name="MeshSweep", model_type="SmearedCore",
               sizes=(30.0, 15.0, 10.0, 7.5, 5.0, 2.5)):
    """The QI plate under one stack model across mesh densities."""
    print(f"{'clmax':>6} {'elements':>9} {'solve':>8}  note")
    for size in sizes:
        tag = f"{name}{int(size * 10)}"
        doc, analysis, solver, mesh_obj = _build_case_qi(
            tag, size, model_type=model_type
        )
        ok, inp_file, err = _solve(analysis, solver, mesh_obj, tag)
        count = _face_element_count(inp_file) if inp_file else "-"
        note = err or ""
        print(f"{size:>6} {count:>9} {'OK' if ok else 'FAIL':>8}  {note}")
        FreeCAD.closeDocument(tag)


def sweep_test_order(name="OrderSweep", mesh_max_size=5.0):
    """Discrete, then SmearedFabric, then SmearedCore — the test's order,
    documents left open, one process.  Isolates process-state effects."""
    for model in ("Discrete", "SmearedFabric", "SmearedCore"):
        tag = f"{name}{model}"
        doc, analysis, solver, mesh_obj = _build_case_qi(
            tag, mesh_max_size, model_type=model
        )
        ok, inp_file, err = _solve(analysis, solver, mesh_obj, tag)
        count = _face_element_count(inp_file) if inp_file else "-"
        print(f"{model:>14}  elements {count}  "
              f"{'OK' if ok else 'FAIL'}  {err or ''}")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "--test-order":
        sweep_test_order()
    elif argv and argv[0] == "--mesh-sweep":
        model = argv[1] if len(argv) > 1 else "SmearedCore"
        sizes = [float(s) for s in argv[2:]] or None
        sweep_mesh(model_type=model,
                   sizes=tuple(sizes) if sizes else (30.0, 15.0, 10.0,
                                                    7.5, 5.0, 2.5))
    else:
        main()