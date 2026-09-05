# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Stiffener examples — sweep profiles along the path an intersecting surface
cuts from a support.

Each stiffener lives in its own document, one example per document. The result
still names a single ``doc`` — the first case's — because that is what the
example runner and its smoke test read.

Builds:

1. ``Composites_Stiffener_RectPlate`` — rectangular section on a planar plate,
   path cut by a surface standing on the plate.
2. ``Composites_Stiffener_ZPlate`` — Z-section on a planar plate. The Z is an
   OPEN polyline (base flange, web, top flange), so the stiffener is the web +
   top flange (an L), distinct from the closed rect box.
3. ``Composites_Stiffener_ZCylRing`` / ``Composites_Stiffener_ZConeRing`` —
   Z-section as an annular frame, swept around a cylinder / cone. The path is
   the ring the cut surface intersects from the curved surface, and the
   profile's base row stays on that surface.
4. ``Composites_Stiffener_TConePanel`` — thin T on a 270-degree conical
   panel, swept along the open ellipse a tilted cut plane traces on it.
"""

import FreeCAD
import Part

from ...features.Stiffener import StiffenerFP, ViewProviderStiffener, add_stiffener_filters


PLATE_LENGTH = 120.0
PLATE_WIDTH = 60.0
CYLINDER_RADIUS = 40.0
CONE_BASE_RADIUS = 45.0
CONE_TOP_RADIUS = 20.0
SHELL_HEIGHT = 120.0
PANEL_ANGLE = 270.0
TILT_NORMAL = FreeCAD.Vector(0.0, 0.6, 0.8)
CUT_Z = 60.0
CUT_SIDE = 120.0


def _new_document(doc, name):
    """Return ``doc`` or open a fresh document with the given name."""
    if doc is not None:
        return doc
    if name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(name)
    return FreeCAD.newDocument(name)


def _make_sketch(doc, name, points):
    """Create a sketch from polyline points, or explicit (start, end) strokes."""
    sketch = doc.addObject("Sketcher::SketchObject", name)
    if points and isinstance(points[0], (tuple, list)):
        strokes = points
    else:
        strokes = list(zip(points, points[1:]))
    for start, end in strokes:
        sketch.addGeometry(Part.LineSegment(start, end), False)
    return sketch


def _make_shape_object(doc, name, shape):
    object_with_shape = doc.addObject("Part::Feature", name)
    object_with_shape.Shape = shape
    return object_with_shape


def _rect_profile():
    """A rectangular section: base row at y=0, rising to y=10."""
    return [
        FreeCAD.Vector(0.0, 0.0, 0.0),
        FreeCAD.Vector(0.0, 10.0, 0.0),
        FreeCAD.Vector(20.0, 10.0, 0.0),
        FreeCAD.Vector(20.0, 0.0, 0.0),
        FreeCAD.Vector(0.0, 0.0, 0.0),
    ]


def _t_profile():
    """A thin T as three strokes: stem plus two flange arms (branched)."""
    return [
        (FreeCAD.Vector(0.0, 0.0, 0.0), FreeCAD.Vector(0.0, 15.0, 0.0)),
        (FreeCAD.Vector(-10.0, 15.0, 0.0), FreeCAD.Vector(0.0, 15.0, 0.0)),
        (FreeCAD.Vector(0.0, 15.0, 0.0), FreeCAD.Vector(10.0, 15.0, 0.0)),
    ]


def _z_profile():
    """A Z-section as an OPEN polyline: base flange, web, top flange.

    The base flange (y=0) rides the support surface; the web and top flange are
    free edges. No closing edge — one would create a spurious wall and collapse
    the Z into a box.
    """
    return [
        FreeCAD.Vector(0.0, 0.0, 0.0),
        FreeCAD.Vector(20.0, 0.0, 0.0),
        FreeCAD.Vector(20.0, 10.0, 0.0),
        FreeCAD.Vector(0.0, 10.0, 0.0),
    ]


def plate_cut_surface():
    """A surface standing on the plate, cutting a straight path across it."""
    corners = [
        FreeCAD.Vector(-10.0, PLATE_WIDTH / 2.0, -20.0),
        FreeCAD.Vector(PLATE_LENGTH + 10.0, PLATE_WIDTH / 2.0, -20.0),
        FreeCAD.Vector(PLATE_LENGTH + 10.0, PLATE_WIDTH / 2.0, 80.0),
        FreeCAD.Vector(-10.0, PLATE_WIDTH / 2.0, 80.0),
    ]
    return Part.Face(Part.makePolygon(corners + corners[:1]))


def ring_cut_surface():
    """A surface square enough to cut a complete ring from the shell."""
    return Part.makePlane(
        CUT_SIDE,
        CUT_SIDE,
        FreeCAD.Vector(-CUT_SIDE / 2.0, -CUT_SIDE / 2.0, CUT_Z),
        FreeCAD.Vector(0, 0, 1),
    )


def _add_stiffener(doc, name, support, cut_surface, profile_points):
    """Create a StiffenerFP feature in ``doc`` with support/cut-surface/profile.

    The stiffener's parts and the remainder of the cut support are exposed as
    CompoundFilters on the feature; the remainder replaces the pristine support
    on screen, which it otherwise coincides with.
    """
    surface = _make_shape_object(doc, f"{name}CutSurface", cut_surface)
    profile = _make_sketch(doc, f"{name}Profile", profile_points)
    stiffener = doc.addObject("Part::FeaturePython", name)
    StiffenerFP(stiffener, support=support, cut_surface=surface, profile=profile)
    if FreeCAD.GuiUp:
        ViewProviderStiffener(stiffener.ViewObject)
    doc.recompute()

    filters = add_stiffener_filters(doc, stiffener)
    support.Visibility = False
    doc.recompute()
    return {
        "doc": doc,
        "stiffener": stiffener,
        "parts": filters["parts"],
        "remainder": filters["remainder"],
        "shape": stiffener.Shape,
        "remainders": stiffener.Proxy.remainders,
    }


def _build_on_plate(doc, name, document_name, profile_points):
    """A stiffener on a planar plate, in its own document."""
    doc = _new_document(doc, document_name)
    support = _make_shape_object(doc, "PlateSupport", Part.makePlane(PLATE_LENGTH, PLATE_WIDTH))
    return _add_stiffener(doc, name, support, plate_cut_surface(), profile_points)


def _build_ring(doc, name, document_name, kind, profile_points):
    """An annular frame swept around a cylinder or cone, in its own document.

    The support is the lateral face alone — an open shell without end caps,
    as a real panel would be.
    """
    doc = _new_document(doc, document_name)
    solid = (
        Part.makeCylinder(CYLINDER_RADIUS, SHELL_HEIGHT)
        if kind == "cylinder"
        else Part.makeCone(CONE_BASE_RADIUS, CONE_TOP_RADIUS, SHELL_HEIGHT)
    )
    surface = Part.Cylinder if kind == "cylinder" else Part.Cone
    shell = next(face for face in solid.Faces if isinstance(face.Surface, surface))
    support = _make_shape_object(doc, f"{name}Support", shell)
    return _add_stiffener(doc, name, support, ring_cut_surface(), profile_points)


def _build_tilted_t_on_conical_panel(doc, name, document_name):
    """A thin T on a conical panel, swept along a tilted cut plane's ellipse."""
    doc = _new_document(doc, document_name)
    solid = Part.makeCone(
        CONE_BASE_RADIUS,
        CONE_TOP_RADIUS,
        SHELL_HEIGHT,
        FreeCAD.Vector(0, 0, 0),
        FreeCAD.Vector(0, 0, 1),
        PANEL_ANGLE,
    )
    panel = next(face for face in solid.Faces if isinstance(face.Surface, Part.Cone))
    support = _make_shape_object(doc, f"{name}Support", panel)
    cut = Part.makePlane(
        CUT_SIDE, CUT_SIDE, FreeCAD.Vector(-CUT_SIDE / 2, -CUT_SIDE / 2, 0), FreeCAD.Vector(0, 0, 1)
    )
    cut.Placement = FreeCAD.Placement(
        FreeCAD.Vector(0, 0, CUT_Z), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), TILT_NORMAL)
    )
    return _add_stiffener(doc, name, support, cut, _t_profile())


def build(doc=None, run_solver=False):
    """Build the stiffener examples, one document per example.

    Parameters
    ----------
    doc
        Optional FreeCAD document; when given, the first stiffener
        (rect plate) is built into it. The others use their own documents.
    run_solver
        Accepted for runner parity.

    Returns
    -------
    dict
        ``doc`` names the document the first case went into, and ``cases``
        holds one entry per stiffener with its own ``doc``, ``stiffener``
        feature and swept ``shape``.
    """
    cases = {
        "rect_plate": _build_on_plate(
            doc, "RectOnPlate", "Composites_Stiffener_RectPlate", _rect_profile()
        ),
        "z_plate": _build_on_plate(None, "ZOnPlate", "Composites_Stiffener_ZPlate", _z_profile()),
        "z_cylinder_ring": _build_ring(
            None, "ZCylRing", "Composites_Stiffener_ZCylRing", "cylinder", _z_profile()
        ),
        "z_cone_ring": _build_ring(
            None, "ZConeRing", "Composites_Stiffener_ZConeRing", "cone", _z_profile()
        ),
        "t_cone_panel": _build_tilted_t_on_conical_panel(
            None, "TConePanel", "Composites_Stiffener_TConePanel"
        ),
    }
    return {"doc": cases["rect_plate"]["doc"], "cases": cases}


def main():
    """Run the stiffener examples."""
    for key, case in build()["cases"].items():
        shape = case["shape"]
        box = shape.BoundBox
        print(
            f"{key}: {shape.ShapeType} | null={shape.isNull()} | "
            f"bbox={round(box.XLength, 1)}x{round(box.YLength, 1)}x{round(box.ZLength, 1)} | "
            f"remainders={len(case['remainders'])}"
        )


if __name__ == "__main__":
    main()
