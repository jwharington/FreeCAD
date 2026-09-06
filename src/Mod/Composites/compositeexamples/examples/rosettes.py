# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Rosette examples — fibre orientation datums on draped shells.

One document with the three rosette feature types over a flat master plate
and a cylindrical attachment shell:

1. ``Rosettes_Rosette`` — a plain Rosette anchored on the master plate face;
   the shell's drape is seeded from it.
2. ``Rosettes_AlignFibre`` — an AlignFibreRosette on the same shell: its
   angle is solved so the warp fibre passes through a picked vertex. The
   vertex sits at 45 degrees from the rosette origin, so the solve must
   land on 45. A solve that cannot converge leaves the feature Invalid —
   a failed alignment is never silent.
3. ``Rosettes_Transfer`` — a TransferRosette carrying the master plate's
   orientation onto the cylindrical attachment shell.
"""

import FreeCAD
import Part

from ...features.Rosette import RosetteFP
from ...features.AlignFibreRosette import AlignFibreRosetteFP
from ...features.TransferRosette import TransferRosetteFP
from ...features.CompositeShell import CompositeShellFP
from ._shell_example_common import (
    _carbon_material,
    _prepare_feature_import_environment,
    _resin_material,
    _to_length_mm,
)

PLATE_SIDE = 100.0
CYLINDER_RADIUS = 50.0
CYLINDER_HEIGHT = 100.0
SECOND_POINT = FreeCAD.Vector(60.0, 60.0, 0.0)
LAMINA_ANGLES = (0.0, 45.0, -45.0, 90.0)


def _new_document(doc, name):
    """Return ``doc`` or open a fresh document with the given name."""
    if doc is not None:
        return doc
    if name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(name)
    return FreeCAD.newDocument(name)


def _support(doc, name, shape):
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = shape
    return obj


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


def _shell(doc, name, support, rosette=None):
    """A CompositeShell over ``support``, draped from ``rosette``'s orientation."""
    shell = doc.addObject("Part::FeaturePython", name)
    CompositeShellFP(shell, support=support, laminate=_laminate(doc, name), rosette=rosette)
    return shell


def build(doc=None, run_solver=False):
    """Build the rosette examples into one document.

    Parameters
    ----------
    doc
        Optional FreeCAD document; a new one is opened when omitted.
    run_solver
        Accepted for runner parity; the drapes and the AlignFibreRosette
        solve are driven by their own references.

    Returns
    -------
    dict
        ``doc`` plus the three rosette features: ``rosette``,
        ``align_fibre`` and ``transfer``.
    """
    doc = _new_document(doc, "Composites_Rosettes")

    plate = _support(doc, "PlateSupport", Part.makePlane(PLATE_SIDE, PLATE_SIDE))
    cylinder = _support(
        doc,
        "CylinderSupport",
        next(
            face
            for face in Part.makeCylinder(CYLINDER_RADIUS, CYLINDER_HEIGHT).Faces
            if isinstance(face.Surface, Part.Cylinder)
        ),
    )

    # The AlignFibreRosette IS the master shell's rosette: the solver steers
    # the drape by mutating its Angle, so the shell must seed from it.
    align = doc.addObject("Part::FeaturePython", "Rosettes_AlignFibre")
    AlignFibreRosetteFP(align, support=(plate, ["Face1"]), composite_shell=None)
    master = _shell(doc, "PlateShell", plate, rosette=align)
    attachment = _shell(doc, "CylinderShell", cylinder)
    doc.recompute()

    align.CompositeShell = master
    doc.recompute()

    point = doc.addObject("Part::Feature", "SecondPoint")
    point.Shape = Part.makeSphere(0.1, SECOND_POINT)
    doc.recompute()
    # (60, 60) sits at 45 degrees from the rosette origin at the face centre,
    # so the warp fibre through the point is the 45-degree direction.
    align.SecondPoint = (point, ["Vertex1"])

    rosette = doc.addObject("Part::FeaturePython", "Rosettes_Rosette")
    RosetteFP(rosette, support=(plate, ["Face1"]))
    doc.recompute()

    transfer = doc.addObject("Part::FeaturePython", "Rosettes_Transfer")
    TransferRosetteFP(
        transfer,
        support=(cylinder, ["Face1"]),
        master_shell=master,
        attachment_shell=attachment,
    )
    doc.recompute()

    return {
        "doc": doc,
        "rosette": rosette,
        "align_fibre": align,
        "transfer": transfer,
    }


def main():
    """Run the rosette examples."""
    result = build()
    align = result["align_fibre"]
    print(f"align fibre solved angle: {align.Angle:.3f} deg (expected 45)")
    print(f"align state: {align.State}")


if __name__ == "__main__":
    main()
