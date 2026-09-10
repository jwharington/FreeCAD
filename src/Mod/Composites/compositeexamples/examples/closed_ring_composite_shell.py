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

# Fibre offset angle: the rosette's primary fibre direction, measured from
# the ring's circumferential axis.  45 deg = the ±45 bias-ply orientation.
ROSETTE_ANGLE_DEG = 45.0

LAMINA_ANGLES = (0.0, 45.0, -45.0, 90.0)


def _new_document(doc, name):
    """Return ``doc`` or open a fresh document with the given name."""
    if doc is not None:
        return doc
    if name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(name)
    return FreeCAD.newDocument(name)


def _stiffener_laminate(doc, name):
    """A compact UD laminate for a ring stiffener's own structure."""
    from Composites.features.CompositeLaminate import CompositeLaminateFP
    from Composites.features.FibreCompositeLamina import FibreCompositeLaminaFP
    from Composites.objects import SymmetryType, WeaveType

    plies = []
    for idx, angle in enumerate((0.0, 90.0), start=1):
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
    laminate.SymmetryType if False else None
    laminate.Symmetry = SymmetryType.Assymmetric.name
    return laminate


def _ring_stiffener(doc, shell, name, z_centre, laminate):
    """One circumferential ring stiffener on the closed ring.

    The cut surface is a plane perpendicular to the ring axis at ``z_centre``:
    its intersection with the cylindrical shell is the ring path the profile
    sweeps.  The Z-profile rides the shell (base flange), web and top flange
    free — same world-XY profile and horizontal cut plane recipe as the
    stiffener example's ring case.
    """
    from Composites.features.Stiffener import (
        StiffenerFP,
        ViewProviderStiffener,
        add_stiffener_filters,
    )
    from .stiffener import _make_shape_object, _make_sketch, _z_profile

    side = 3.0 * GEOMETRY["radius_mm"]
    cut = Part.makePlane(
        side,
        side,
        FreeCAD.Vector(-side / 2.0, -side / 2.0, z_centre),
        FreeCAD.Vector(0, 0, 1),
    )
    cut_surface = _make_shape_object(doc, f"{name}CutSurface", cut)
    profile = _make_sketch(doc, f"{name}Profile", _z_profile())

    stiffener = doc.addObject("Part::FeaturePython", name)
    StiffenerFP(
        stiffener,
        support=shell,
        cut_surface=cut_surface,
        profile=profile,
    )
    stiffener.Laminate = laminate
    if getattr(FreeCAD, "GuiUp", False) and getattr(stiffener, "ViewObject", None):
        ViewProviderStiffener(stiffener.ViewObject)
    add_stiffener_filters(doc, stiffener)
    doc.recompute()
    return stiffener


def _add_ring_stiffeners(doc, shell):
    """Two composite ring stiffeners, one near each end of the tube."""
    from Composites.features.StiffenerCompositeShell import (
        ensure_stiffener_shells_visible,
    )

    length = GEOMETRY["length_mm"]
    offset = 40.0  # axial inset of each ring from its tube end
    stiffeners = []
    laminate_a = _stiffener_laminate(doc, "RingStiffenerALaminate")
    stiffeners.append(
        _ring_stiffener(doc, shell, "RingStiffenerA", offset, laminate_a)
    )
    laminate_b = _stiffener_laminate(doc, "RingStiffenerBLaminate")
    stiffeners.append(
        _ring_stiffener(doc, shell, "RingStiffenerB", length - offset, laminate_b)
    )
    doc.recompute()
    for stiffener in stiffeners:
        ensure_stiffener_shells_visible(stiffener)
    doc.recompute()
    return stiffeners


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
    rosette.Angle = ROSETTE_ANGLE_DEG
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

    stiffeners = _add_ring_stiffeners(doc, shell)
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
        "stiffeners": stiffeners,
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
