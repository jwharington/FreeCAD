# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Mixed shell+solid example: a composite stiffener on a solid spar.

B2.1's case. The stiffener half of the mixed coverage existed only as bare
geometry (the e2 web on a solid plate); here a real ``StiffenerFP`` — with its
own laminate and the web/foot shells it creates — sits on a panel shell that is
declared on a **solid** spar and coupled to it with a ``*TIE``.

The panel is a QI ``Composite::Shell`` on the spar's top face, deliberately
``IsotropicEquivalent`` so the example stays off the drape backend, exactly as
``mixed_shell_solid_plate`` does; the stiffener's own laminate is QI for the
same reason.  What is exercised is the feature — the stiffener's web/foot
split, its combined laminate, and its FEM shell sections — on the mixed path.
"""

import FreeCAD
import Part

import ObjectsFem

from femtools.mixedcoupling import (
    add_load_direction,
    add_tie,
    edge_reference_at,
    face_reference_on_axis,
    max_displacement,
)

from femexamples.meshes.merged_mesh import mesh_parts_separately

from ...features.CompositeShell import CompositeShellFP
from ...features.Stiffener import (
    StiffenerFP,
    ViewProviderStiffener,
    add_stiffener_filters,
)
from ...features.StiffenerCompositeShell import ensure_stiffener_shells_visible
from ._shell_example_common import (
    _add_analysis_member,
    _add_shell_section_and_material,
    _create_fem_base,
    _run_ccx,
    _set_constraint_refs,
    ensure_document,
    make_qi_laminate,
)
from .stiffener import _make_shape_object, _make_sketch, _z_profile, plate_cut_surface

SPAR_LENGTH = 100.0
SPAR_WIDTH = 20.0
SPAR_HEIGHT = 20.0
FORCE_N = 1000.0
STEEL = {"YoungsModulus": "210000 MPa", "PoissonRatio": "0.30"}

DOCUMENT_NAME = "Composites_Mixed_Shell_Solid_Stiffener"
TAG = "MixedShellSolidStiffener"


def _make_spar(doc):
    spar = doc.addObject("Part::Box", "Spar")
    spar.Length = SPAR_LENGTH
    spar.Width = SPAR_WIDTH
    spar.Height = SPAR_HEIGHT
    return spar


def _make_panel_support(doc):
    support = doc.addObject("Part::Feature", "PanelSupport")
    support.Shape = Part.makePlane(SPAR_LENGTH, SPAR_WIDTH)
    support.Placement.Base = FreeCAD.Vector(0.0, 0.0, SPAR_HEIGHT)
    return support


def _make_panel(doc, support):
    laminate = make_qi_laminate(doc, "PanelLaminate")
    panel = doc.addObject("Part::FeaturePython", "PanelShell")
    CompositeShellFP(panel, support, laminate=laminate, rosette=None)
    doc.recompute()
    return panel


def _make_stiffener(doc, panel):
    laminate = make_qi_laminate(doc, "StiffenerLaminate")
    stiffener = doc.addObject("Part::FeaturePython", "ZStiffener")
    StiffenerFP(
        stiffener,
        support=panel,
        cut_surface=_make_shape_object(
            doc, "ZStiffenerCutSurface", plate_cut_surface(SPAR_LENGTH, SPAR_WIDTH)
        ),
        profile=_make_sketch(doc, "ZStiffenerProfile", _z_profile()),
    )
    stiffener.Laminate = laminate
    if FreeCAD.GuiUp:
        ViewProviderStiffener(stiffener.ViewObject)
    add_stiffener_filters(doc, stiffener)
    doc.recompute()
    ensure_stiffener_shells_visible(stiffener)
    return stiffener


def _add_spar_material(doc, analysis, spar):
    material = ObjectsFem.makeMaterialSolid(doc, f"{TAG}_SparMaterial")
    data = material.Material
    data["Name"] = "SparSteel"
    data.update(STEEL)
    material.Material = data
    _set_constraint_refs(material, [(spar, "")])
    _add_analysis_member(analysis, material)


def _add_load_case(doc, analysis, spar):
    fixed = ObjectsFem.makeConstraintFixed(doc, f"{TAG}_Fixed")
    _set_constraint_refs(fixed, [face_reference_on_axis(spar, "x", 0.0)])
    _add_analysis_member(analysis, fixed)

    force = ObjectsFem.makeConstraintForce(doc, f"{TAG}_Force")
    _set_constraint_refs(force, [edge_reference_at(spar, x=SPAR_LENGTH, z=0.0)])
    force.Force = f"{FORCE_N} N"
    direction = add_load_direction(doc, f"{TAG}_LoadDirection", (0.0, 0.0, -1.0))
    force.Direction = (direction, [])
    _add_analysis_member(analysis, force)


def _run_mixed_fem(doc, spar, support, shells):
    """Mesh the shells and the solid apart, section each, tie, and solve."""
    assembly = _make_shape_object(
        doc, f"{TAG}_ShellAssembly", Part.makeCompound([s.Support.Shape for s in shells])
    )
    doc.recompute()

    analysis, solver, mesh_obj = _create_fem_base(doc, TAG)
    _add_spar_material(doc, analysis, spar)
    for index, shell in enumerate(shells):
        thickness, material = _add_shell_section_and_material(
            doc, analysis, shell.Support, f"{TAG}{index}", shell_obj=shell
        )
        faces = [f"Face{i}" for i in range(1, len(shell.Shape.Faces) + 1)]
        for obj in (thickness, material):
            if obj is not None:
                _set_constraint_refs(obj, [(shell, faces)])

    add_tie(
        doc,
        analysis,
        f"{TAG}_Tie",
        (support, "Face1"),
        face_reference_on_axis(spar, "z", SPAR_HEIGHT),
        1.0,
    )
    _add_load_case(doc, analysis, spar)

    # The shell assembly is meshed as one part so its folds stay conforming;
    # the solid is meshed on its own so the panel can be tied to it.
    mesh_obj.FemMesh = mesh_parts_separately(doc, [spar, assembly])
    geometry = doc.addObject("Part::Compound", f"{TAG}_Geometry")
    geometry.Links = [spar, support]
    mesh_obj.Shape = geometry
    doc.recompute()

    solve_result, fem = _run_ccx(analysis, solver, mesh_obj)
    return analysis, solver, mesh_obj, solve_result, fem


def build(doc=None, run_solver=False):
    """Build the mixed stiffener-on-a-solid spar; ``run_solver=True`` solves it."""
    doc = ensure_document(doc, DOCUMENT_NAME)

    spar = _make_spar(doc)
    support = _make_panel_support(doc)
    panel = _make_panel(doc, support)
    stiffener = _make_stiffener(doc, panel)

    web_shell = doc.getObject(f"{stiffener.Name}_Web")
    foot_shell = doc.getObject(f"{stiffener.Name}_Foot")

    result = {
        "doc": doc,
        "spar": spar,
        "panel_support": support,
        "panel_shell": panel,
        "stiffener": stiffener,
        "web_shell": web_shell,
        "foot_shell": foot_shell,
        "fem_job": None,
    }
    if not run_solver:
        return result

    shells = [
        s for s in (panel, web_shell, foot_shell) if s is not None and s.Support is not None
    ]
    analysis, solver, mesh_obj, solve_result, fem = _run_mixed_fem(
        doc, spar, support, shells
    )
    result["fem_job"] = {
        "analysis": analysis,
        "solver": solver,
        "mesh": mesh_obj,
        "solve_result": solve_result,
        "inp_file": fem.inp_file_name,
    }
    return result


def main():
    case = build(run_solver=True)
    job = case["fem_job"]
    tip = max_displacement(job["analysis"])
    print(
        f"mixed_shell_solid_stiffener: solved={job['solve_result']} "
        f"tip={tip} inp={job['inp_file']}"
    )


if __name__ == "__main__":
    main()
