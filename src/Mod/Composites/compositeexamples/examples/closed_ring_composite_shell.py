# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Composite shell on a full closed cylindrical ring.

The support is a full 360° cylindrical midsurface — a self-connected
shape whose parameter wrap line is the physical seam.  The CompositeShell
drapes through nextdrape's periodic-seam stop law (baseline10): the seed
relocates away from the seam automatically, both fronts grow outward and
stop at the seam, so the drape covers the ring exactly once with one
butt joint.  The ``Composites_TexturePlan`` feature unwraps the ply
boundaries into the plan shape — one sheet per ply orientation, no
double-drawn laps.
"""

from ._shell_example_common import (
    _carbon_material,
    _prepare_feature_import_environment,
    _resin_material,
    _to_length_mm,
)

import FreeCAD
import Part

GEOMETRY = {
    "radius_mm": 100.0,
    "length_mm": 300.0,
    "sweep_deg": 360.0,
    "pitch_mm": 5.0,
}

LAMINA_ANGLES = (0.0, 45.0, -45.0, 90.0)


def _new_document(doc, name):
    """Return ``doc`` or open a fresh document with the given name."""
    if doc is not None:
        return doc
    if name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(name)
    return FreeCAD.newDocument(name)


def _laminate(doc, name):
    """A lay-up of four UD laminae as document features, wrapped in a laminate."""
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
    """Build the closed-ring composite shell example into one document.

    The shell's drape runs during the recompute (the seam stop and seed
    relocation are solver-side; no example-level seed handling is needed).

    Returns
    -------
    dict
        ``doc``, ``support``, ``rosette``, ``shell`` and (on request)
        ``texture_plan``.
    """
    doc = _new_document(doc, "Composites_ClosedRing_Shell")

    axis_origin = FreeCAD.Vector(0.0, 0.0, 0.0)
    axis_dir = FreeCAD.Vector(0.0, 0.0, 1.0)
    ring = Part.makeCylinder(
        GEOMETRY["radius_mm"],
        GEOMETRY["length_mm"],
        axis_origin,
        axis_dir,
        GEOMETRY["sweep_deg"],
    )
    support = doc.addObject("Part::Feature", "ClosedRingSupport")
    # The lateral (cylindrical) face of the solid is the midsurface ring.
    support.Shape = [
        f for f in ring.Faces
        if abs(f.Area - 2.0 * 3.14159265358979323846
               * GEOMETRY["radius_mm"] * GEOMETRY["length_mm"])
        < 1.0e-6
    ][0]

    _prepare_feature_import_environment()
    from Composites.features.Rosette import RosetteFP, ViewProviderRosette
    from Composites.features.CompositeShell import (
        CompositeShellFP,
        ViewProviderCompositeShell,
    )

    gui_up = bool(getattr(FreeCAD, "GuiUp", False))

    rosette = doc.addObject("Part::FeaturePython", "ClosedRingRosette")
    RosetteFP(rosette, support=(support, ["Face1"]))
    rosette.Angle = 0.0
    if gui_up and getattr(rosette, "ViewObject", None):
        ViewProviderRosette(rosette.ViewObject)

    shell = doc.addObject("Part::FeaturePython", "ClosedRingShell")
    CompositeShellFP(
        shell,
        support=support,
        laminate=_laminate(doc, "ClosedRing"),
        rosette=rosette,
    )
    shell.DrapePitch = GEOMETRY["pitch_mm"]
    if gui_up and getattr(shell, "ViewObject", None):
        try:
            ViewProviderCompositeShell(shell.ViewObject)
        except Exception:
            # FreeCAD's C++ attach may have already run the VP constructor
            # (the recompute race); the Proxy is set either way.
            pass
    doc.recompute()

    texture_plan = None
    try:
        from Composites.features.TexturePlan import TexturePlanFP

        texture_plan = doc.addObject("Part::FeaturePython", "ClosedRingTexturePlan")
        TexturePlanFP(texture_plan, shells=[shell])
        doc.recompute()
    except Exception:
        texture_plan = None

    return {
        "doc": doc,
        "support": support,
        "rosette": rosette,
        "shell": shell,
        "texture_plan": texture_plan,
        "geometry": GEOMETRY,
    }


def main():
    """Run the closed-ring composite shell example headlessly."""
    result = build(doc=None)
    shell = result["shell"]
    print(f"closed-ring shell: drape_valid={shell.DrapeValid}")


if __name__ == "__main__":
    main()
