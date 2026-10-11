# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""A skin declared on the solid's own face, tied by the pass (B7).

The plate example declares its skin on a separate support object and writes
the ``*TIE`` by hand. This one follows the convention the tie pass reads: the
skin's ``SupportReference`` **is** the solid and names the face it lies on, so
the interface is stated rather than searched for, and ``auto_tie`` creates the
coupling from that declaration alone.

The difference is deliberately the only one: same spar, same laminate, same
load case, so the two examples' displacements can be read side by side. The
skin is ``IsotropicEquivalent`` to stay off the drape backend.
"""

import os

import FreeCAD
import Part

from femexamples.meshes.merged_mesh import mesh_parts_separately
from femtools.mixedcoupling import (
    add_load_direction,
    edge_reference_at,
    face_reference_on_axis,
    max_displacement,
)

from ...features.CompositeShell import CompositeShellFP, support_object
from ...fem.auto_tie import auto_tie
from ._shell_example_common import (
    _add_analysis_member,
    _add_shell_section_and_material,
    _create_fem_base,
    _run_ccx,
    _set_constraint_refs,
    ensure_document,
    make_qi_laminate,
)

SPAR_LENGTH = 100.0
SPAR_WIDTH = 20.0
SPAR_HEIGHT = 20.0
FORCE_N = 1000.0
STEEL = {"YoungsModulus": "210000 MPa", "PoissonRatio": "0.30"}

DOCUMENT_NAME = "Composites_Mixed_Shell_Solid_AutoTie"


def _make_spar(doc):
    spar = doc.addObject("Part::Box", "Spar")
    spar.Length = SPAR_LENGTH
    spar.Width = SPAR_WIDTH
    spar.Height = SPAR_HEIGHT
    return spar


def _make_skin(doc, spar, face):
    """A skin whose support *is* ``spar``, declared on one of its faces."""
    laminate = make_qi_laminate(doc, "QILaminate")
    shell = doc.addObject("Part::FeaturePython", "SkinShell")
    CompositeShellFP(shell, support=None, laminate=laminate, rosette=None)
    shell.SupportReference = (spar, [face])
    doc.recompute()
    return shell, laminate


def _add_spar_material(doc, analysis, spar, tag):
    import ObjectsFem

    material = ObjectsFem.makeMaterialSolid(doc, f"{tag}_SparMaterial")
    data = material.Material
    data["Name"] = "SparSteel"
    data.update(STEEL)
    material.Material = data
    # An empty sub-element names the solid itself, so this material reaches
    # volumes only - the skin's faces belong to the other material.
    _set_constraint_refs(material, [(spar, "")])
    _add_analysis_member(analysis, material)
    return material


def _add_load_case(doc, analysis, spar, tag):
    import ObjectsFem

    fixed = ObjectsFem.makeConstraintFixed(doc, f"{tag}_Fixed")
    _set_constraint_refs(fixed, [face_reference_on_axis(spar, "x", 0.0)])
    _add_analysis_member(analysis, fixed)

    force = ObjectsFem.makeConstraintForce(doc, f"{tag}_Force")
    _set_constraint_refs(force, [edge_reference_at(spar, x=SPAR_LENGTH, z=0.0)])
    force.Force = f"{FORCE_N} N"
    # The load is global -Z, and the loaded edge runs along Y, so the axis has
    # to come from its own element rather than from the reference.
    direction = add_load_direction(doc, f"{tag}_LoadDirection", (0.0, 0.0, -1.0))
    force.Direction = (direction, [])
    _add_analysis_member(analysis, force)


def build(doc=None, run_solver=False):
    """Build the convention-following skin-on-spar cantilever and tie it."""
    doc = ensure_document(doc, DOCUMENT_NAME)
    tag = "MixedShellSolidAutoTie"

    spar = _make_spar(doc)
    doc.recompute()
    face = face_reference_on_axis(spar, "z", SPAR_HEIGHT)[1]
    shell, laminate = _make_skin(doc, spar, face)

    result = {"doc": doc, "spar": spar, "shell": shell, "laminate": laminate, "tie": None}
    if not run_solver:
        return result

    analysis, solver, mesh_obj = _create_fem_base(doc, tag)
    _add_shell_section_and_material(
        doc, analysis, support_object(shell), tag, shell_obj=shell
    )
    _add_spar_material(doc, analysis, spar, tag)
    _add_load_case(doc, analysis, spar, tag)

    # The mesher never sees the two together: a skin sharing the spar's nodes
    # would be a hinge, and would stop being detected as a shell. The pass
    # refuses exactly that, so it runs after the mesh exists.
    mesh_obj.FemMesh = mesh_parts_separately(doc, [spar, shell])
    geometry = doc.addObject("Part::Compound", f"{tag}_Geometry")
    geometry.Links = [spar, shell]
    mesh_obj.Shape = geometry
    doc.recompute()

    ties = auto_tie(analysis)
    if len(ties) != 1:
        raise RuntimeError(f"the tie pass created {len(ties)} ties, expected one")
    result["tie"] = ties[0]

    solve_result, fem = _run_ccx(analysis, solver, mesh_obj)
    if not solve_result:
        raise RuntimeError("CalculiX solve failed for the auto-tied skin-on-spar model")

    with open(fem.inp_file_name, encoding="utf-8", errors="ignore") as fh:
        solver_input = fh.read()

    result.update(
        {
            "analysis": analysis,
            "solver": solver,
            "mesh": mesh_obj,
            "max_displacement": max_displacement(analysis),
            "inp_file": os.path.abspath(fem.inp_file_name),
            "solver_input": solver_input,
        }
    )
    return result


def main():
    case = build(run_solver=True)
    print(
        f"mixed_shell_solid_auto_tie: tie={case['tie'].Name} "
        f"max_displacement={case['max_displacement']}"
    )


if __name__ == "__main__":
    main()
