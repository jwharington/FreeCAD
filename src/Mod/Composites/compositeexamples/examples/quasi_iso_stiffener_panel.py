# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Quasi-isotropic stiffener panel example (PRD quasi_isotropic_laminate.md §8.2).

The stiffener-panel scenario with QI laminates — the QI property
exercised through the full composition path:

1. the panel stays a draped composite shell (the realistic baseline);
2. the stiffener's own laminate is QI ``[0/45/-45/90]s`` declared
   ``IsotropicEquivalent`` — no web rosette is created, the web shell
   has no drape and renders plain;
3. the foot combined laminate (stiffener ⊕ panel) is draped, mixed:
   the panel-side foot transfer still solves; the QI side enters the
   record at nominal angles with rotation 0 (D8);
4. ``panel_qi=True`` makes the panel laminate also QI — foot and
   assembly become fully orientation-free (the FEM-export shortcut end
   to end).

See docs/quasi_isotropic_laminate.md and
docs/adr/0003-quasi-isotropic-presentation-contract.md.
"""

import FreeCAD
import Part

from ...features.Stiffener import (
    StiffenerFP,
    ViewProviderStiffener,
    add_stiffener_filters,
)
from ...features.StiffenerCompositeShell import (
    ensure_stiffener_shells_visible,
)
from ...objects import SymmetryType, WeaveType
from ._shell_example_common import (
    _carbon_material,
    _resin_material,
    _prepare_feature_import_environment,
    _to_length_mm,
    create_composite_feature_stack,
    ensure_document,
)
from .stiffener import (
    PLATE_LENGTH,
    PLATE_WIDTH,
    _make_shape_object,
    _make_sketch,
    plate_cut_surface,
    _z_profile,
)

FABRIC_OFFSET_ANGLE = 30.0  # fabric laid at 30 degrees on the draped panel
DRAPE_PITCH = 5.0
QI_ANGLES = (0.0, 45.0, -45.0, 90.0)

DOCUMENT_NAME = "Composites_QuasiIso_Stiffener_Panel"


def _make_qi_laminate(doc, name):
    """A QI [0/45/-45/90]s UD laminate, declared IsotropicEquivalent."""
    _prepare_feature_import_environment()
    from ...features.CompositeLaminate import CompositeLaminateFP
    from ...features.FibreCompositeLamina import FibreCompositeLaminaFP

    plies = []
    for idx, angle in enumerate(QI_ANGLES, start=1):
        ply = doc.addObject("App::FeaturePython", f"{name}_Ply{idx:02d}")
        FibreCompositeLaminaFP(ply)
        ply.FibreMaterial = _carbon_material()
        ply.FibreVolumeFraction = 55
        ply.Thickness = _to_length_mm(FreeCAD, 0.2)
        ply.Angle = angle
        ply.WeaveType = WeaveType.UD.name
        plies.append(ply)

    laminate = doc.addObject("App::FeaturePython", name)
    CompositeLaminateFP(laminate, laminae=plies)
    laminate.ResinMaterial = _resin_material()
    laminate.FibreVolumeFraction = 55
    # A QI stack must be symmetric (B = 0) for isotropic presentation.
    laminate.Symmetry = SymmetryType.Even.name
    laminate.IsotropicEquivalent = True
    doc.recompute()
    return laminate


def _make_qi_panel(doc, name="QIPanel"):
    """A QI-declared composite panel shell — no rosette, no drape."""
    _prepare_feature_import_environment()
    from ...features.CompositeShell import CompositeShellFP

    support = _make_shape_object(
        doc, f"{name}Plate", Part.makePlane(PLATE_LENGTH, PLATE_WIDTH)
    )
    laminate = _make_qi_laminate(doc, f"{name}Laminate")
    shell = doc.addObject("Part::FeaturePython", name)
    CompositeShellFP(shell, support, laminate=laminate)
    doc.recompute()
    return shell


def _edge_names_by_x(shape):
    """Names of the min-x and max-x edges (the tensile load case)."""
    min_edge = max_edge = None
    min_x = max_x = None
    for idx, edge in enumerate(shape.Edges, start=1):
        x = sum(v.Point.x for v in edge.Vertexes) / len(edge.Vertexes)
        if min_x is None or x < min_x:
            min_x, min_edge = x, f"Edge{idx}"
        if max_x is None or x > max_x:
            max_x, max_edge = x, f"Edge{idx}"
    return min_edge, max_edge


def _solve_assembly(doc, panel_shell, shells):
    """Solve the panel + web + foot shells as one shell assembly.

    Meshes a compound of the shells' supports and gives each shell its own
    shell-section + material, then runs an in-plane (membrane) load case on
    the panel.  QI shells export plain ``TYPE=ISO`` with no ``*ORIENTATION``
    (D5); a draped side keeps the composite section.
    """
    import Part

    from ._shell_example_common import (
        _add_fixed_constraint,
        _add_force_constraint,
        _add_shell_section_and_material,
        _create_fem_base,
        _mesh_support,
        _run_ccx,
        _set_constraint_refs,
    )

    compound = _make_shape_object(
        doc,
        "StiffenerAssemblySupport",
        Part.makeCompound([s.Support.Shape for s in shells]),
    )
    doc.recompute()

    analysis, solver, mesh_obj = _create_fem_base(doc, "StiffenerAssembly")
    for idx, shell in enumerate(shells):
        thickness, material = _add_shell_section_and_material(
            doc,
            analysis,
            shell.Support,
            f"StiffenerAssembly{idx}",
            shell_obj=shell,
        )
        # After the stiffener split the panel/web remainder is more than
        # one face; referencing only "Face1" leaves the other faces'
        # elements sectionless (gen3delem: first thickness).  Reference
        # every face of the shell's current shape.
        faces = [f"Face{i}" for i in range(1, len(shell.Shape.Faces) + 1)]
        for obj in (thickness, material):
            if obj is not None:
                _set_constraint_refs(obj, [(shell, faces)])
    _mesh_support(mesh_obj, compound)

    min_edge, max_edge = _edge_names_by_x(panel_shell.Support.Shape)
    _add_fixed_constraint(
        doc, analysis, panel_shell.Support, min_edge, "StiffenerAssembly"
    )
    _add_force_constraint(
        doc, analysis, panel_shell.Support, max_edge, "StiffenerAssembly"
    )
    doc.recompute()

    solve_result, fem = _run_ccx(analysis, solver, mesh_obj)
    solver_input = None
    if fem.inp_file_name:
        with open(fem.inp_file_name, encoding="utf-8", errors="ignore") as fh:
            solver_input = fh.read()
    return {
        "analysis": analysis,
        "solver": solver,
        "mesh": mesh_obj,
        "solve_result": solve_result,
        "solver_input": solver_input,
        "inp_file": fem.inp_file_name,
    }


def build(doc=None, run_solver=False, panel_qi=False):
    """Build the QI stiffener panel (``panel_qi=True``: QI panel too)."""
    doc = ensure_document(doc, DOCUMENT_NAME)

    if panel_qi:
        panel = {"shell": _make_qi_panel(doc)}
    else:
        # The panel: a draped composite shell at 30 degrees (baseline).
        panel_plate = _make_shape_object(
            doc, "PanelPlate", Part.makePlane(PLATE_LENGTH, PLATE_WIDTH)
        )
        panel = create_composite_feature_stack(doc, panel_plate, name_prefix="Panel")
        panel["rosette"].Angle = FABRIC_OFFSET_ANGLE
        panel["shell"].DrapePitch = DRAPE_PITCH
        doc.recompute()

    # The stiffener: Z-section along the panel, with its own QI laminate.
    # No web rosette is created and the web shell never drapes (D8).
    stiffener_laminate = _make_qi_laminate(doc, "StiffenerLaminate")
    stiffener = doc.addObject("Part::FeaturePython", "ZStiffener")
    StiffenerFP(
        stiffener,
        support=panel["shell"],
        cut_surface=_make_shape_object(
            doc, "ZStiffenerCutSurface", plate_cut_surface()
        ),
        profile=_make_sketch(doc, "ZStiffenerProfile", _z_profile()),
    )
    stiffener.Laminate = stiffener_laminate
    if FreeCAD.GuiUp:
        ViewProviderStiffener(stiffener.ViewObject)
    add_stiffener_filters(doc, stiffener)
    doc.recompute()

    # Visibility must be set after the creating recompute settles (the
    # GUI leaves recompute-born shells invisible).
    ensure_stiffener_shells_visible(stiffener)

    web_shell = doc.getObject(f"{stiffener.Name}_Web")
    foot_shell = doc.getObject(f"{stiffener.Name}_Foot")
    scl = foot_shell.Laminate if foot_shell is not None else None

    fem_job = None
    if run_solver:
        shells = [
            s for s in (panel["shell"], web_shell, foot_shell)
            if s is not None and getattr(s, "Support", None) is not None
        ]
        fem_job = _solve_assembly(doc, panel["shell"], shells)

    return {
        "doc": doc,
        "stiffener": stiffener,
        "panel_shell": panel["shell"],
        "web_shell": web_shell,
        "foot_shell": foot_shell,
        "combined_laminate": scl,
        "web_rosette": stiffener.Rosette,
        "panel_qi": panel_qi,
        "combined_isotropic": (
            scl.IsotropicEquivalent if scl is not None else None
        ),
        "web_draped": bool(web_shell.DrapeValid) if web_shell else None,
        "foot_draped": bool(foot_shell.DrapeValid) if foot_shell else None,
        "panel_draped": bool(panel["shell"].DrapeValid),
        "fem_job": fem_job,
    }


def main():
    case = build()
    scl = case["combined_laminate"]
    print(
        f"quasi_iso_stiffener_panel: combined={scl.Name if scl is not None else None} "
        f"derived_isotropic={case['combined_isotropic']} "
        f"web_rosette={case['web_rosette']}"
    )


if __name__ == "__main__":
    main()
