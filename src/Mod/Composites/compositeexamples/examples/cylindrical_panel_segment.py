# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com
"""Create a cylindrical panel segment with composite laminate and draping."""

from __future__ import annotations

import math

import FreeCAD
import Part

from Composites.features.CompositeShell import CompositeShellFP
from Composites.features.CompositeLaminate import CompositeLaminateFP
from Composites.features.FibreCompositeLamina import FibreCompositeLaminaFP
from Composites.features.Rosette import RosetteFP


def _carbon_material() -> dict:
    """Return a quasi-isotropic carbon/epoxy lamina material dict."""
    return {
        "Name": "Carbon",
        "Density": "1750.0 kg/m^3",
        "PoissonRatioXY": "0.27",
        "PoissonRatioXZ": "0.27",
        "PoissonRatioYZ": "0.45",
        "ShearModulusXY": "5000 MPa",
        "ShearModulusXZ": "5000 MPa",
        "ShearModulusYZ": "3500 MPa",
        "YoungsModulusX": "135 GPa",
        "YoungsModulusY": "9.5 GPa",
        "YoungsModulusZ": "9.5 GPa",
    }


def _resin_material() -> dict:
    """Return an epoxy resin material dict."""
    return {
        "Name": "Epoxy",
        "Density": "1180.0 kg/m^3",
        "YoungsModulus": "3.300 GPa",
        "PoissonRatio": "0.35",
    }


def create_cylindrical_panel(
    name: str = "CylindricalPanel",
    radius: float = 100.0,
    height: float = 200.0,
    arc_deg: float = 90.0,
    pitch: float = 5.0,
) -> FreeCAD.Document:
    """Create a cylindrical panel segment with composite laminate.

    Parameters
    ----------
    name : str
        Document name.
    radius : float
        Cylinder radius (mm).
    height : float
        Cylinder height (mm).
    arc_deg : float
        Arc extent in degrees (0-360).
    pitch : float
        Draping mesh pitch (mm).

    Returns
    -------
    FreeCAD.Document
        The created document containing SupportShape, Rosette, Laminae,
        Laminate, and CompositeShell objects.
    """
    doc = FreeCAD.newDocument(name)

    # ── 1. Cylindrical support surface ──────────────────────────
    cyl = Part.makeCylinder(radius, height)
    curved_face = max(cyl.Faces, key=lambda f: f.Area)

    support = doc.addObject("Part::Feature", "SupportShape")
    support.Shape = curved_face

    # ── 2. Rosette (provides LCS for seed point/direction) ─────
    rosette = doc.addObject("App::FeaturePython", "Rosette")
    RosetteFP(rosette)
    rosette.Support = (support, "Face1")
    rosette.Angle = 0.0

    # ── 3. Quasi-isotropic laminae [0/45/-45/90] ───────────────
    carbon_mat = _carbon_material()
    laminae: list[FreeCAD.DocumentObject] = []
    angles = [0.0, 45.0, -45.0, 90.0]

    for idx, angle in enumerate(angles, start=1):
        lam = doc.addObject("App::FeaturePython", f"Lamina{idx:02d}")
        FibreCompositeLaminaFP(lam)
        lam.FibreMaterial = carbon_mat
        lam.FibreVolumeFraction = 55
        lam.Thickness = 0.2
        lam.Angle = angle
        lam.WeaveType = "UD"
        laminae.append(lam)

    # ── 4. Laminate ────────────────────────────────────────────
    laminate = doc.addObject("App::FeaturePython", "Laminate")
    CompositeLaminateFP(laminate, laminae=laminae)
    laminate.ResinMaterial = _resin_material()

    # ── 5. CompositeShell (triggers draping) ───────────────────
    shell = doc.addObject("Part::FeaturePython", "CompositeShell")
    CompositeShellFP(shell)
    shell.Support = support
    shell.Rosette = rosette
    shell.Laminate = laminate
    shell.MaxLength = pitch

    doc.recompute()

    # ── 6. Attach ViewProviders (needed for tree view children) ──
    from Composites.features.CompositeShell import (
        ViewProviderCompositeShell,
    )
    from Composites.features.CompositeLaminate import (
        ViewProviderCompositeLaminate,
    )
    from Composites.features.FibreCompositeLamina import (
        ViewProviderFibreCompositeLamina,
    )
    from Composites.features.Rosette import ViewProviderRosette

    if laminate.ViewObject:
        vp = ViewProviderCompositeLaminate(laminate.ViewObject)
        vp.attach(laminate.ViewObject)
    for lam in laminae:
        if lam.ViewObject:
            vp = ViewProviderFibreCompositeLamina(lam.ViewObject)
            vp.attach(lam.ViewObject)
    if rosette.ViewObject:
        vp = ViewProviderRosette(rosette.ViewObject)
        vp.attach(rosette.ViewObject)
    if shell.ViewObject:
        vp = ViewProviderCompositeShell(shell.ViewObject)
        vp.attach(shell.ViewObject)

    # ── 7. Force recompute to trigger draping and shader loading ─
    doc.recompute()

    # ── 8. Switch to isometric view and fit all ────────────────
    import FreeCADGui

    gui_doc = FreeCADGui.getDocument(doc.Name)
    view = gui_doc.ActiveView
    if view:
        view.viewIsometric()
        view.fitAll()

    # Hide the support shape — its surface was consumed by the draper
    # and the draped CompositeShell mesh is what the user wants to see.
    if support.ViewObject:
        support.ViewObject.Visibility = False

    # ── 9. Report results ──────────────────────────────────────
    print(f"Document: {doc.Name}")
    print(f"Objects: {[o.Name for o in doc.Objects]}")
    print(f"Shell diagnostics: {shell.DrapeDiagnostics}")

    for obj in doc.Objects:
        if obj.Name == "DrapeMesh" and obj.Mesh:
            print(f"DrapeMesh facets: {obj.Mesh.CountFacets}")

    return doc


if __name__ == "__main__":
    create_cylindrical_panel()
