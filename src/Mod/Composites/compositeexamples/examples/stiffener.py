# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Stiffener examples — sweep profiles along plans on supports.

Each stiffener lives in its own document (avoids cross-object clutter and
the stale-document issues that a single shared document causes). Builds:

1. ``Composites_Stiffener_RectPlate`` — rectangular section on a planar
   plate (the basic case).
2. ``Composites_Stiffener_ZPlate`` — Z-section on a planar plate. The Z is
   an OPEN polyline (bottom flange, web, top flange), so the stiffener is
   the web + top flange (an L), distinct from the closed rect box.
3. ``Composites_Stiffener_ZCylShell`` / ``Composites_Stiffener_ZConePanel``
   — Z-section on a cylindrical/conical shell panel. These are KNOWN
   FAILURES: the tool's makeParallelProjection cannot produce a correct
   circumferential stiffener on a curved surface (it sweeps the full shell
   height). They are attempted and the failure is reported, not raised.
"""

import FreeCAD
import Part

from ...features.Stiffener import StiffenerFP, ViewProviderStiffener


def _new_document(doc, name):
    """Return ``doc`` or open a fresh document with the given name."""
    if doc is not None:
        return doc
    if name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(name)
    return FreeCAD.newDocument(name)


def _make_sketch(doc, name, points):
    """Create a sketch from a list of points (line segments)."""
    sketch = doc.addObject("Sketcher::SketchObject", name)
    for start, end in zip(points, points[1:]):
        sketch.addGeometry(Part.LineSegment(start, end), False)
    return sketch


def _rect_profile():
    """A rectangular section: surface edge at y=0, free edges at y=10."""
    return [
        FreeCAD.Vector(0.0, 0.0, 0.0),
        FreeCAD.Vector(0.0, 10.0, 0.0),
        FreeCAD.Vector(20.0, 10.0, 0.0),
        FreeCAD.Vector(20.0, 0.0, 0.0),
        FreeCAD.Vector(0.0, 0.0, 0.0),
    ]


def _z_profile():
    """A Z-section as an OPEN polyline: bottom flange, web, top flange.

    The bottom flange (y=0) is the surface edge; the web and top flange are
    the free edges swept along the plan. No closing edge — a closing edge
    would create a spurious wall and collapse the Z into a box.
    """
    return [
        FreeCAD.Vector(0.0, 0.0, 0.0),
        FreeCAD.Vector(20.0, 0.0, 0.0),
        FreeCAD.Vector(20.0, 10.0, 0.0),
        FreeCAD.Vector(0.0, 10.0, 0.0),
    ]


def _plan_line():
    """A straight plan line (plate case), at z=0."""
    return [
        FreeCAD.Vector(10.0, 10.0, 0.0),
        FreeCAD.Vector(80.0, 10.0, 0.0),
    ]


def _tangential_plan_line(outboard=50.0, z=60.0):
    """A straight plan line, tangential to the axis, outboard and centered.

    The line runs along X at y=``outboard`` (outside the surface) and height
    ``z``, with its midpoint at (0, outboard, z) — directly outboard of the
    near-face point. The tool projects it radially onto the surface.
    """
    return [
        FreeCAD.Vector(-10.0, outboard, z),
        FreeCAD.Vector(10.0, outboard, z),
    ]


def _curved_panel(kind):
    """A partial cylindrical/conical shell panel (curved face only)."""
    if kind == "cylinder":
        solid = Part.makeCylinder(
            40.0, 120.0, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 270.0
        )
        curved = [f for f in solid.Faces if "Cylinder" in str(f.Surface)]
    else:
        solid = Part.makeCone(
            45.0, 20.0, 120.0, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 270.0
        )
        curved = [f for f in solid.Faces if "Cone" in str(f.Surface)]
    return Part.makeShell([curved[0]])


def _add_stiffener(doc, name, support, plan_points, profile_points):
    """Create a StiffenerFP feature in ``doc`` with support/plan/profile."""
    plan = _make_sketch(doc, f"{name}Plan", plan_points)
    profile = _make_sketch(doc, f"{name}Profile", profile_points)
    stiffener = doc.addObject("Part::FeaturePython", name)
    StiffenerFP(stiffener, support=support, plan=plan, profile=profile)
    if FreeCAD.GuiUp:
        ViewProviderStiffener(stiffener.ViewObject)
    return stiffener


def _build_rect_plate(doc):
    """Rect section on a planar plate, in its own document."""
    doc = _new_document(doc, "Composites_Stiffener_RectPlate")
    support = doc.addObject("Part::Feature", "PlateSupport")
    support.Shape = Part.makePlane(120.0, 60.0)
    stiffener = _add_stiffener(doc, "RectOnPlate", support, _plan_line(), _rect_profile())
    doc.recompute()
    return {"doc": doc, "stiffener": stiffener, "shape": stiffener.Shape}


def _build_z_plate(doc):
    """Z-section on a planar plate, in its own document."""
    doc = _new_document(doc, "Composites_Stiffener_ZPlate")
    support = doc.addObject("Part::Feature", "PlateSupport")
    support.Shape = Part.makePlane(120.0, 60.0)
    stiffener = _add_stiffener(doc, "ZOnPlate", support, _plan_line(), _z_profile())
    doc.recompute()
    return {"doc": doc, "stiffener": stiffener, "shape": stiffener.Shape}


def _build_z_curved(doc, kind):
    """Z-section on a curved panel. Known failure — returns the error, not raises.

    Returns a dict with ``doc``, ``ok`` and ``error``.
    """
    name = "ZCylShell" if kind == "cylinder" else "ZConePanel"
    docname = "Composites_Stiffener_ZCylShell" if kind == "cylinder" else "Composites_Stiffener_ZConePanel"
    doc = _new_document(doc, docname)
    try:
        support = doc.addObject("Part::Feature", f"{name}Support")
        support.Shape = _curved_panel(kind)
        # Plan: 3D wire line, tangential to the axis, outboard (10 mm outside
        # the surface at mid-height), centered at (0, outboard, 60).
        outboard = 50.0 if kind == "cylinder" else 42.5
        plan = doc.addObject("Part::Feature", f"{name}Plan")
        plan.Shape = Part.makePolygon(_tangential_plan_line(outboard=outboard, z=60.0))
        profile = _make_sketch(doc, f"{name}Profile", _z_profile())
        stiffener = doc.addObject("Part::FeaturePython", name)
        StiffenerFP(stiffener, support=support, plan=plan, profile=profile)
        stiffener.Direction = FreeCAD.Vector(0.0, -1.0, 0.0)
        if FreeCAD.GuiUp:
            ViewProviderStiffener(stiffener.ViewObject)
        doc.recompute()
        shape = stiffener.Shape
        if shape.isNull():
            return {"doc": doc, "ok": False, "error": "stiffener shape is null"}
        bb = shape.BoundBox
        zlen = bb.ZLength
        if zlen <= 0.0 or not (bb.XLength > 0.0 and bb.YLength > 0.0):
            return {"doc": doc, "ok": False, "error": f"degenerate shape (z-span {zlen:.1f} mm)"}
        if zlen < 50.0:
            return {"doc": doc, "ok": True, "error": ""}
        return {
            "doc": doc,
            "ok": False,
            "error": f"projection swept the full height (z-span {zlen:.1f} mm instead of ~10 mm)",
        }
    except Exception as exc:
        return {"doc": doc, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def build(doc=None, run_solver=False):
    """Build the stiffener examples, one document per stiffener.

    Parameters
    ----------
    doc
        Optional FreeCAD document; when given, the first stiffener
        (rect plate) is built into it. The Z and curved cases still use
        their own documents.
    run_solver
        Accepted for runner parity.

    Returns
    -------
    dict
        The working stiffeners (rect_plate, z_plate) and the curved
        attempts with their failure descriptions.
    """

    rect = _build_rect_plate(doc)
    zplate = _build_z_plate(None)
    zcyl = _build_z_curved(None, "cylinder")
    zcone = _build_z_curved(None, "cone")

    return {
        "rect_plate": rect,
        "z_plate": zplate,
        "z_cylinder_shell": zcyl,
        "z_cone_panel": zcone,
    }


def main():
    """Run the stiffener examples."""
    result = build()
    for key in ("rect_plate", "z_plate"):
        shape = result[key]["shape"]
        bb = shape.BoundBox
        print(f"{key}: {shape.ShapeType} | null={shape.isNull()} | bbox={round(bb.XLength,1)}x{round(bb.YLength,1)}x{round(bb.ZLength,1)}")
    for key in ("z_cylinder_shell", "z_cone_panel"):
        item = result[key]
        if item["ok"]:
            print(f"{key}: built")
        else:
            print(f"{key}: KNOWN FAILURE — {item['error']}")


if __name__ == "__main__":
    main()
