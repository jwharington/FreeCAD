# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Texture plan example — ply boundaries unwrapped from a draped shell.

A flat plate carries a CompositeShell with a demo laminate; the
``Composites_TexturePlan`` feature unwraps each ply's boundary curves from
the shell's drape into one wire per ply orientation, laid out as the plan
shape of the lay-up.
"""

import FreeCAD
import Part

from ...features.TexturePlan import TexturePlanFP
from ...features.CompositeShell import CompositeShellFP
from ...features.Rosette import RosetteFP
from ._shell_example_common import (
    _carbon_material,
    _prepare_feature_import_environment,
    _resin_material,
    _to_length_mm,
)

PLATE_SIDE = 100.0
LAMINA_ANGLES = (0.0, 45.0, -45.0, 90.0)


PLATE_SIDE = 100.0


def _new_document(doc, name):
    """Return ``doc`` or open a fresh document with the given name."""
    if doc is not None:
        return doc
    if name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(name)
    return FreeCAD.newDocument(name)


def _laminate(doc, name):
    """A lay-up of four UD laminae as document features, wrapped in a laminate."""
    # These feature classes pull in material task panels, which need the
    # headless stubs prepared before import.
    _prepare_feature_import_environment()
    from Composites.features.CompositeLaminate import CompositeLaminateFP
    from Composites.features.FibreCompositeLamina import FibreCompositeLaminaFP
    from Composites.objects import WeaveType

    laminae = []
    for idx, angle in enumerate(LAMINA_ANGLES, start=1):
        lamina = doc.addObject("App::FeaturePython", f"{name}Lamina{idx}")
        FibreCompositeLaminaFP(lamina)
        lamina.FibreMaterial = _carbon_material()
        lamina.FibreVolumeFraction = 55
        lamina.Thickness = _to_length_mm(FreeCAD, 0.2)
        lamina.Angle = angle
        lamina.WeaveType = WeaveType.UD.name
        laminae.append(lamina)

    laminate = doc.addObject("App::FeaturePython", f"{name}Laminate")
    CompositeLaminateFP(laminate, laminae=laminae)
    laminate.ResinMaterial = _resin_material()
    return laminate


def build(doc=None, run_solver=False):
    """Build the texture plan example into one document.

    Parameters
    ----------
    doc
        Optional FreeCAD document; a new one is opened when omitted.
    run_solver
        Accepted for runner parity; the shell's drape and the plan's unwrap
        both run during the recompute.

    Returns
    -------
    dict
        ``doc`` plus ``shell`` and ``texture_plan``.
    """
    doc = _new_document(doc, "Composites_TexturePlan")

    support = doc.addObject("Part::Feature", "PlateSupport")
    support.Shape = Part.makePlane(PLATE_SIDE, PLATE_SIDE)

    rosette = doc.addObject("Part::FeaturePython", "Rosettes_Rosette")
    RosetteFP(rosette, support=(support, ["Face1"]))

    shell = doc.addObject("Part::FeaturePython", "PlateShell")
    CompositeShellFP(shell, support=support, laminate=_laminate(doc, "Plate"), rosette=rosette)
    doc.recompute()

    plan = doc.addObject("Part::FeaturePython", "TexturePlan")
    TexturePlanFP(plan, shells=[shell])
    doc.recompute()

    return {"doc": doc, "shell": shell, "rosette": rosette, "texture_plan": plan}


def main():
    """Run the texture plan example."""
    result = build()
    plan = result["texture_plan"]
    print(f"texture plan wires: {len(plan.Shape.Edges)} edges in {plan.Shape.ShapeType}")


if __name__ == "__main__":
    main()
