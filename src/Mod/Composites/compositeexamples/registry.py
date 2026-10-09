# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Registry of runnable Composites examples."""

from importlib import import_module


EXAMPLES = {
    "ud_plate_basic": {
        "module": ".examples.ud_plate_basic",
        "name": "Unidirectional plate (basic)",
    },
    "quasi_iso_laminate_plate": {
        "module": ".examples.quasi_iso_laminate_plate",
        "name": "Quasi-isotropic laminate plate",
    },
    "tubular_shell": {
        "module": ".examples.tubular_shell",
        "name": "Tubular shell",
    },
    "cylindrical_panel_segment": {
        "module": ".examples.cylindrical_panel_segment",
        "name": "Cylindrical panel segment",
    },
    "closed_ring_composite_shell": {
        "module": ".examples.closed_ring_composite_shell",
        "name": "Composite shell on a closed cylindrical ring",
    },
    "conical_panel_segment": {
        "module": ".examples.conical_panel_segment",
        "name": "Conical panel segment",
    },
    "mould_analysis": {
        "module": ".examples.mould_analysis",
        "name": "Parametric mould analysis (MouldAnalysis feature)",
    },
    "place_dart": {
        "module": ".examples.place_dart",
        "name": "Place dart (project wire cut onto shell)",
    },
    "seam_extraction": {
        "module": ".examples.seam_extraction",
        "name": "Seam extraction (two-panel overlap)",
    },
    "bulkhead_section": {
        "module": ".examples.bulkhead_section",
        "name": "Bulkhead section on the fixture skin",
    },
    "stiffener_rect_plate": {
        "module": ".examples.stiffener_rect_plate",
        "name": "Rect-section stiffener on a planar plate",
    },
    "stiffener_z_plate": {
        "module": ".examples.stiffener_z_plate",
        "name": "Z-section stiffener on a planar plate",
    },
    "stiffener_z_cyl_ring": {
        "module": ".examples.stiffener_z_cyl_ring",
        "name": "Z-section annular stiffener frame on a cylinder",
    },
    "stiffener_z_cone_ring": {
        "module": ".examples.stiffener_z_cone_ring",
        "name": "Z-section annular stiffener frame on a cone",
    },
    "stiffener_t_cone_panel": {
        "module": ".examples.stiffener_t_cone_panel",
        "name": "Thin-T stiffener on a conical panel",
    },
    "non_planar_mould_demo_box": {
        "module": ".examples.non_planar_mould_demo_box",
        "name": "Non-planar mould parting demo — box (degenerate planar part line)",
    },
    "non_planar_mould_demo_loft": {
        "module": ".examples.non_planar_mould_demo_loft",
        "name": "Non-planar mould parting demo — cambered loft",
    },
    "non_planar_mould_demo_blade": {
        "module": ".examples.non_planar_mould_demo_blade",
        "name": "Non-planar mould parting demo — twisted blade profile",
    },
    "rosette": {
        "module": ".examples.rosette",
        "name": "Rosette (fibre orientation datum on a draped shell)",
    },
    "align_fibre_rosette": {
        "module": ".examples.align_fibre_rosette",
        "name": "AlignFibreRosette (fibre angle solved through a picked point)",
    },
    "transfer_rosette": {
        "module": ".examples.transfer_rosette",
        "name": "TransferRosette (master orientation carried to another shell)",
    },
    "cyl_sphere_seam": {
        "module": ".examples.cyl_sphere_seam",
        "name": "TransferRosette (cylindrical panel to spherical cap across the seam)",
    },
    "texture_plan": {
        "module": ".examples.texture_plan",
        "name": "Texture plan (ply boundaries unwrapped from a shell)",
    },
    "seam_composite_laminate": {
        "module": ".examples.seam_composite_laminate",
        "name": "SeamCompositeLaminate (combined layup at an overlap seam)",
    },
    "stiffener_composite_shell": {
        "module": ".examples.stiffener_composite_shell",
        "name": "StiffenerCompositeShell (combined layup at a stiffener joint)",
    },
    "quasi_iso_stiffener_panel": {
        "module": ".examples.quasi_iso_stiffener_panel",
        "name": "Quasi-isotropic stiffener panel (QI presentation at a stiffener joint)",
    },
    "quasi_iso_seam": {
        "module": ".examples.quasi_iso_seam",
        "name": "Quasi-isotropic seam (QI presentation at an overlap seam)",
    },
    "quasi_iso_fem_plate": {
        "module": ".examples.quasi_iso_fem_plate",
        "name": "Quasi-isotropic FEM plate (isotropic presentation through CalculiX)",
    },
    "mixed_shell_solid_plate": {
        "module": ".examples.mixed_shell_solid_plate",
        "name": "Mixed shell and solid plate (laminate skin over a solid spar)",
    },
    "mixed_shell_solid_wing": {
        "module": ".examples.mixed_shell_solid_wing",
        "name": (
            "Mixed shell and solid wing (biaxial carbon skins over a foam core)"
        ),
    },
    "quasi_iso_cylindrical_panel": {
        "module": ".examples.quasi_iso_cylindrical_panel",
        "name": "Quasi-isotropic cylindrical panel (curvature needs no drape)",
    },
}


def list_examples():
    """Return sorted example identifiers available to the runner."""

    return sorted(EXAMPLES.keys())


def get_example_module(example_id):
    """Load and return the Python module implementing ``example_id``."""

    if example_id not in EXAMPLES:
        available = ", ".join(list_examples())
        raise ValueError(
            f"Unknown example '{example_id}'. Available examples: {available}",
        )

    module_name = EXAMPLES[example_id]["module"]
    return import_module(module_name, package=__package__)
