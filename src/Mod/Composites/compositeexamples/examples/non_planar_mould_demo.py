"""Non-planar mould analysis demos — part line + mould halves, one shape per doc.

Implementation module for the three registered single-document examples
(``non_planar_mould_demo_box``, ``non_planar_mould_demo_loft``,
``non_planar_mould_demo_blade``). Each runs the non-planar parting solver on
one source shape and adds the part line + mould halves to its own document.
The freeform shapes use shape-specific draw directions.
"""
import FreeCAD
import Part

from Composites.tools.mould_analysis import analyze_source_shape
from Composites.tools.profile_mould_analysis import (
    _make_blade_shape,
    _make_loft_shape,
)


def _add_shape(doc, name, shape):
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = shape
    return obj


def _set_view_style(obj, color=None, line_width=None, transparency=None):
    view = getattr(obj, "ViewObject", None)
    if view is None:
        return
    if color is not None:
        view.ShapeColor = color
    if line_width is not None:
        view.LineWidth = line_width
    if transparency is not None:
        view.Transparency = transparency


def _add_part_line(doc, name, parting_surface):
    if parting_surface is None or parting_surface.isNull():
        return None
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = parting_surface
    _set_view_style(obj, color=(1.0, 0.0, 0.0, 1.0), line_width=3)
    return obj


def _add_mould_half(doc, name, shape, color):
    if shape is None or shape.isNull():
        return None
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = shape
    _set_view_style(obj, color=color, transparency=50)
    return obj


def _run_analysis(doc, label, shape, draw_dir):
    source = _add_shape(doc, f"{label}_source", shape)

    result = analyze_source_shape(
        source.Shape,
        draw_direction=FreeCAD.Vector(*draw_dir),
        source_obj=source,
    )

    status = result.get("non_planar_status", "n/a")
    summary = result.get("non_planar_summary", "")
    wc = result.get("withdrawal_clearance_status", "n/a")
    val = result.get("validation_status", "n/a")

    print(f"[{label}] non_planar_status={status} WC={wc} validation={val}")
    if val == "Fail":
        print(f"[{label}] validation_checks={result.get('validation_checks', [])}")
    print(f"[{label}] summary={summary}")

    parting_surface = result.get("parting_surface_shape")
    lower = result.get("mould_half_a_shape")
    upper = result.get("mould_half_b_shape")

    _add_part_line(doc, f"{label}_part_line", parting_surface)
    _add_mould_half(doc, f"{label}_mould_lower", lower, (0.2, 0.6, 1.0, 1.0))
    _add_mould_half(doc, f"{label}_mould_upper", upper, (1.0, 0.6, 0.2, 1.0))

    return result


def _new_document(doc, name):
    """Return ``doc`` or open a fresh document with the given name."""
    if doc is not None:
        return doc
    existing = FreeCAD.listDocuments().get(name)
    if existing is not None:
        FreeCAD.closeDocument(existing.Name)
    return FreeCAD.newDocument(name)


def _build_shape(doc, document_name, label, shape, draw_dir):
    """Build one mould-analysis demo document for a single source shape."""
    doc = _new_document(doc, document_name)
    _run_analysis(doc, label, shape, draw_dir)
    doc.recompute()
    FreeCAD.setActiveDocument(doc.Name)
    gui = getattr(FreeCAD, "Gui", None)
    if gui is not None:
        gui.SendMsgToActiveView("ViewFit")
    return doc


def build_box(doc=None, run_solver=False):
    """Box: simple degenerate parting (planar at z_mid), in its own document."""
    return {
        "doc": _build_shape(
            doc, "Composites_MouldDemo_Box", "box", Part.makeBox(20.0, 20.0, 20.0), (0, 0, 1)
        )
    }


def build_loft(doc=None, run_solver=False):
    """Cambered, slightly twisted loft, in its own document.

    Draw along Y (the thin direction) so the parting ring closes cleanly; a
    diagonal (0,1,1) draw leaves the outer-ring skirt corner unplaceable.
    """
    return {
        "doc": _build_shape(
            doc, "Composites_MouldDemo_Loft", "loft", _make_loft_shape(), (0, 1, 0)
        )
    }


def build_blade(doc=None, run_solver=False):
    """Tapered, twisted blade profile, in its own document (thin-direction draw)."""
    return {
        "doc": _build_shape(
            doc, "Composites_MouldDemo_Blade", "blade", _make_blade_shape(), (0, 1, 0)
        )
    }
