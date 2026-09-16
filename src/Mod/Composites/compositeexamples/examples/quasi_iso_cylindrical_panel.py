# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""QI cylindrical shell panel segment (PRD quasi_isotropic_laminate.md §8.5).

Curvature is irrelevant to the QI path: a validated QI laminate is
isotropic in-plane, so a curved panel needs **no drape and no rosette** —
the shell renders plain and the FEM export is the same plain ``TYPE=ISO``
path as the flat plate.  Primarily a demo (the flat plate carries the
discriminating coverage).
"""

from ._shell_example_common import (
    _prepare_feature_import_environment,
    create_support_feature,
    ensure_document,
    import_geometry_modules,
    largest_face,
    run_full_shell_job,
)
from .quasi_iso_stiffener_panel import _make_qi_laminate

GEOMETRY = {
    "radius_mm": 100.0,
    "height_mm": 200.0,
    "arc_deg": 90.0,
    "pitch_mm": 5.0,
}

BOUNDARY_CONDITIONS = {
    "support": "Constrain both straight longitudinal edges",
    "load": "Apply uniform external pressure normal to the cylindrical midsurface",
}

DOCUMENT_NAME = "Composites_QuasiIso_Cylindrical_Panel"


def build(doc=None, run_solver=False, debug_options=None):
    """Build the QI curved panel; ``run_solver=True`` solves it via CalculiX."""
    from ...features.CompositeShell import CompositeShellFP

    doc = ensure_document(doc, DOCUMENT_NAME)
    FreeCAD, Part = import_geometry_modules()

    cyl = Part.makeCylinder(
        GEOMETRY["radius_mm"],
        GEOMETRY["height_mm"],
        FreeCAD.Vector(0.0, 0.0, 0.0),
        FreeCAD.Vector(0.0, 0.0, 1.0),
        GEOMETRY["arc_deg"],
    )
    support = create_support_feature(doc, "CylindricalPanelSupport", largest_face(cyl))

    # QI laminate + QI shell: no rosette, no drape (D4/D5).
    laminate = _make_qi_laminate(doc, "QILaminate")
    _prepare_feature_import_environment()
    shell = doc.addObject("Part::FeaturePython", "QICylPanel")
    CompositeShellFP(shell, support, laminate=laminate)
    doc.recompute()

    fem_job = None
    if run_solver:
        fem_job = run_full_shell_job(
            doc,
            support,
            case_id="cylindrical_panel_segment",
            boundary_conditions=BOUNDARY_CONDITIONS,
            solve=True,
            shell_obj=shell,
        )

    return {
        "doc": doc,
        "laminate": laminate,
        "support": support,
        "shell": shell,
        "geometry": GEOMETRY,
        "analysis_setup": BOUNDARY_CONDITIONS,
        "rosette": None,
        "isotropic": bool(laminate.IsotropicEquivalent),
        "draped": bool(getattr(shell, "DrapeValid", False)),
        "fem_job": fem_job,
    }


def main():
    case = build()
    print(
        f"quasi_iso_cylindrical_panel: isotropic={case['isotropic']} "
        f"draped={case['draped']}"
    )


if __name__ == "__main__":
    main()
