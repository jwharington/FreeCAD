# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

import FreeCAD
import Part

from FreeCAD import Vector

from .. import MOULD_TOOL_ICON, is_comp_type
from ..tools.mould_analysis import (
    DEFAULT_PART_LINE_RADIUS_MM,
    DEFAULT_PART_LINE_SOURCE,
    DEFAULT_SKIRT_LEVELLING,
    DEFAULT_SKIRT_LEVELLING_EXTENT,
    DEFAULT_SKIRT_LEVELLING_TRANSITION_MM,
    DEFAULT_TESSELLATION_BAND_TOL_DEG,
    PART_LINE_SOURCES,
    SKIRT_LEVELLING_EXTENTS,
    SKIRT_LEVELLING_MODES,
    analyze_source_shape,
    default_mould_analysis_draw_direction,
    split_faces,
)
from .Command import BaseCommand
from .VPCompositePart import CompositePartFP, VPCompositePart


def is_mould_analysis(obj):
    return is_comp_type(obj, "Part::FeaturePython", "Composite::MouldAnalysis")


DRAFT_DEFECT_COLOR = (1.0, 0.0, 0.0)      # draft opposes the piece's own half
STRADDLING_COLOR = (1.0, 0.5, 0.0)        # the part line left it straddling its equator

SPLIT_FACE_HALVES = ("upper", "lower")


def _add_tessellation_band_property(obj):
    obj.addProperty(
        "App::PropertyFloat",
        "TessellationBandTolDeg",
        "MouldAnalysis",
        "Equator-band half-width (degrees) the part-line solver treats as the "
        "veil: faces whose draft is within it carry no draft opinion and the "
        "part line may cross them anywhere. It has to cover the shallowest "
        "face the part line crosses and stay below the smallest usable draft "
        "(blade-article: 0.8 - its hub has a 0.71 deg and a 1 deg cone).",
    ).TessellationBandTolDeg = DEFAULT_TESSELLATION_BAND_TOL_DEG


def _add_tessellation_deflection_property(obj):
    obj.addProperty(
        "App::PropertyLength",
        "TessellationDeflection",
        "MouldAnalysis",
        "Absolute deflection (mm) of the tessellation the part-line scan is "
        "run on. Smaller is finer; nextdrape's own default is 0.05, and an "
        "article that needs a finer scan sets it lower.",
    ).TessellationDeflection = 0.05


def _add_part_line_source_property(obj):
    obj.addProperty(
        "App::PropertyEnumeration",
        "PartLineSource",
        "MouldAnalysis",
        "Part-line solver. 'tessellation' marches the draft/equator scan and is "
        "the drafted path; 'hlr' projects the outline instead, and still closes "
        "on shapes the march does not (a box, cone_side, a sphere). The choice "
        "changes the part line, so it changes both halves.",
    ).PartLineSource = list(PART_LINE_SOURCES)
    obj.PartLineSource = DEFAULT_PART_LINE_SOURCE


def _add_part_line_radius_property(obj):
    obj.addProperty(
        "App::PropertyLength",
        "PartLineRadius",
        "MouldAnalysis",
        "Round the skirt creases: the part line's s-z profile is filleted at "
        "exactly this radius (mm) before the split, so a crease is machined as "
        "a fillet rather than left as a sharp step (ridge plan 12.11/12.12). "
        "0 (default) leaves the profile alone.",
    ).PartLineRadius = DEFAULT_PART_LINE_RADIUS_MM


def _add_skirt_levelling_properties(obj):
    """How the skirt's outer wall is shaped, on their own so a restore can add
    them.

    Levelling is what makes the mould manufacturable - a skirt that meets the
    block wall at a slope cannot be machined - and only a `fixed` extent leaves
    the flat strip the O-ring groove is cut into. It is off by default so a
    mould that does not ask for it casts exactly what it did before (A12).
    """
    obj.addProperty(
        "App::PropertyEnumeration",
        "SkirtLevelling",
        "MouldAnalysis",
        "Shape the skirt's outer wall so it lands level on the block wall: "
        "'off' (default), 'direct' or 's-curve'. 's-curve' is a Bezier whose "
        "z has zero gradient at both rails, so the land runs out smoothly.",
    ).SkirtLevelling = list(SKIRT_LEVELLING_MODES)
    obj.SkirtLevelling = DEFAULT_SKIRT_LEVELLING

    obj.addProperty(
        "App::PropertyEnumeration",
        "SkirtLevellingExtent",
        "MouldAnalysis",
        "How much of each skirt ray the levelling transition occupies: "
        "'whole' spans the cutline-to-wall run, 'fixed' takes the whole fall "
        "in the first SkirtLevellingTransition mm outboard of the cutline and "
        "holds the rest flat. Only 'fixed' leaves a level strip.",
    ).SkirtLevellingExtent = list(SKIRT_LEVELLING_EXTENTS)
    obj.SkirtLevellingExtent = DEFAULT_SKIRT_LEVELLING_EXTENT

    obj.addProperty(
        "App::PropertyLength",
        "SkirtLevellingTransition",
        "MouldAnalysis",
        "Length of the levelling transition, measured from the cutline "
        "outward. The spec's absolute minimum is 10 mm - below it an S-curve "
        "reads as a crease - and the mould's in-plane stock margin grows to "
        "hold it.",
    ).SkirtLevellingTransition = DEFAULT_SKIRT_LEVELLING_TRANSITION_MM


def _add_split_face_outputs(obj):
    """The cut pieces of both halves, with the source face each came from."""
    for half in SPLIT_FACE_HALVES:
        label = half.capitalize()
        obj.addProperty(
            "App::PropertyLink",
            f"{label}SplitFaces",
            "MouldAnalysis",
            f"The {half} half's cut pieces, one face per source face region",
            hidden=True,
        )
        pieces = obj.Document.addObject(
            "Part::Feature",
            f"{obj.Name}_{label}SplitFaces",
        )
        setattr(obj, f"{label}SplitFaces", pieces)
        obj.setPropertyStatus(f"{label}SplitFaces", "Output")
        # The pieces are an output of this feature; declared as one, writing
        # them stays out of the document's recompute bookkeeping.
        pieces.setPropertyStatus("Shape", "Output")

        obj.addProperty(
            "App::PropertyIntegerList",
            f"{label}SourceFaces",
            "MouldAnalysis",
            f"Source face each {half} piece was cut from (1-based Face numbering)",
        )
        obj.setPropertyStatus(f"{label}SourceFaces", "Output")

        obj.addProperty(
            "App::PropertyBoolList",
            f"{label}StraddlingFaces",
            "MouldAnalysis",
            f"{half} pieces whose source face the part line did not cut at its "
            f"equator",
        )
        obj.setPropertyStatus(f"{label}StraddlingFaces", "Output")


def analysis_split_faces(analysis, half):
    """The cut pieces of ``half`` of ``analysis``, with their provenance.

    Returns one dict per piece: ``face`` (a Part.Face), ``source_face_index``
    (1-based into the source shape's own face numbering - FreeCAD's FaceN) and
    ``straddles``. The pieces of both halves tile the source exactly once.
    """
    if half not in SPLIT_FACE_HALVES:
        raise ValueError(f"half must be one of {SPLIT_FACE_HALVES}, not {half!r}")
    label = half.capitalize()
    target = getattr(analysis, f"{label}SplitFaces", None)
    source_faces = list(getattr(analysis, f"{label}SourceFaces", []) or [])
    straddling = list(getattr(analysis, f"{label}StraddlingFaces", []) or [])
    if target is None or target.Shape.isNull():
        return []
    return [
        {
            "face": face,
            "source_face_index": (source_faces[index]
                                  if index < len(source_faces) else None),
            "straddles": (straddling[index]
                          if index < len(straddling) else False),
        }
        for index, face in enumerate(target.Shape.Faces)
    ]


def upper_split_faces(analysis):
    """The upper half's cut pieces, with provenance (see ``analysis_split_faces``)."""
    return analysis_split_faces(analysis, "upper")


def lower_split_faces(analysis):
    """The lower half's cut pieces, with provenance (see ``analysis_split_faces``)."""
    return analysis_split_faces(analysis, "lower")


def _add_draft_defect_outputs(obj):
    obj.addProperty(
        "App::PropertyString",
        "DraftDefectSummary",
        "MouldAnalysis",
        "Split-shell faces whose draft opposes their own mould half",
    ).DraftDefectSummary = "No source shape available."
    obj.setPropertyStatus("DraftDefectSummary", "Output")

    obj.addProperty(
        "App::PropertyLink",
        "DraftDefects",
        "MouldAnalysis",
        "Wrong-side draft faces, shown in red on the source",
        hidden=True,
    )
    draft_defects = obj.Document.addObject(
        "Part::Feature",
        f"{obj.Name}_DraftDefects",
    )
    draft_defects.setPropertyStatus("Shape", "Output")
    if FreeCAD.GuiUp:
        draft_defects.ViewObject.ShapeColor = DRAFT_DEFECT_COLOR
        draft_defects.ViewObject.LineColor = DRAFT_DEFECT_COLOR
    obj.DraftDefects = draft_defects
    obj.setPropertyStatus("DraftDefects", "Output")


def _add_level_strip_outputs(obj):
    """The two rings bounding the level strip, and what the solver said of it.

    The rings are the boundary of the flat strip a `fixed` levelled skirt
    leaves between the transition and the block wall, and they are what the
    O-ring groove is cut between. Each is a closed wire of the same stations in
    the same ring order, so a consumer pairs them station for station.
    """
    obj.addProperty(
        "App::PropertyString",
        "LevelStripSummary",
        "MouldAnalysis",
        "Whether the skirt left a level strip for the O-ring groove, and why "
        "not when it did not",
    ).LevelStripSummary = "No level strip."
    obj.setPropertyStatus("LevelStripSummary", "Output")

    for name, label in (("LevelStripIn", "inboard"),
                        ("LevelStripOut", "outboard")):
        obj.addProperty(
            "App::PropertyLink",
            name,
            "MouldAnalysis",
            f"The {label} ring bounding the level strip",
            hidden=True,
        )
        ring = obj.Document.addObject("Part::Feature", f"{obj.Name}_{name}")
        ring.setPropertyStatus("Shape", "Output")
        setattr(obj, name, ring)
        obj.setPropertyStatus(name, "Output")


class MouldAnalysisFP(CompositePartFP):
    Type = "Composite::MouldAnalysis"

    def __init__(self, obj, source):
        obj.addProperty(
            "App::PropertyLink",
            "Source",
            "MouldAnalysis",
            "Link to the source solid",
            locked=True,
        ).Source = source

        obj.addProperty(
            "App::PropertyVector",
            "PreferredDrawDirection",
            "MouldAnalysis",
            "Preferred draw direction",
        ).PreferredDrawDirection = Vector(
            default_mould_analysis_draw_direction.x,
            default_mould_analysis_draw_direction.y,
            default_mould_analysis_draw_direction.z,
        )

        obj.addProperty(
            "App::PropertyEnumeration",
            "OutputMode",
            "MouldAnalysis",
            "What to produce: Full mould (part line + split + skirt + halves) or part line only",
        ).OutputMode = ["Full mould", "Part-line only"]
        obj.OutputMode = "Full mould"

        obj.addProperty(
            "App::PropertyBool",
            "WithdrawalClearance",
            "MouldAnalysis",
            "Run the incremental-withdrawal clearance check. It is the most "
            "expensive stage of the full pipeline and verdicts the mould halves, "
            "but does not generate them. Off by default; opt in to verdict the "
            "halves.",
        ).WithdrawalClearance = False

        obj.addProperty(
            "App::PropertyFloat",
            "PartLineTolerance",
            "MouldAnalysis",
            "Target spacing (mm) between samples along the part line",
        ).PartLineTolerance = 0.1

        _add_tessellation_band_property(obj)
        _add_tessellation_deflection_property(obj)
        _add_part_line_source_property(obj)
        _add_part_line_radius_property(obj)
        _add_skirt_levelling_properties(obj)

        obj.addProperty(
            "App::PropertyFloat",
            "PartingStockMarginX",
            "MouldAnalysis",
            "+X/-X mould block margin (mm)",
        ).PartingStockMarginX = 5.0

        obj.addProperty(
            "App::PropertyFloat",
            "PartingStockMarginY",
            "MouldAnalysis",
            "+Y/-Y mould block margin (mm)",
        ).PartingStockMarginY = 5.0

        obj.addProperty(
            "App::PropertyFloat",
            "PartingStockMarginZ",
            "MouldAnalysis",
            "Draw-direction clearance (mm) between the part bbox and the mould cap",
        ).PartingStockMarginZ = 5.0

        obj.addProperty(
            "App::PropertyVector",
            "PartingStockFootprint",
            "MouldAnalysis",
            "Explicit rectangular stock footprint (dx, dy, 0) in the draw-perpendicular plane; (0,0,0) auto-derives from bbox + margin",
        ).PartingStockFootprint = Vector(0.0, 0.0, 0.0)

        obj.addProperty(
            "App::PropertyString",
            "AnalysisStatus",
            "MouldAnalysis",
            "Current analysis state",
        ).AnalysisStatus = "Waiting for source"
        obj.setPropertyStatus("AnalysisStatus", "Output")

        obj.addProperty(
            "App::PropertyFloat",
            "DrawDirectionScore",
            "MouldAnalysis",
            "Normalized score for the preferred draw direction",
        ).DrawDirectionScore = 0.0
        obj.setPropertyStatus("DrawDirectionScore", "Output")

        obj.addProperty(
            "App::PropertyVector",
            "BestDrawDirection",
            "MouldAnalysis",
            "Best candidate draw direction",
        ).BestDrawDirection = Vector(
            default_mould_analysis_draw_direction.x,
            default_mould_analysis_draw_direction.y,
            default_mould_analysis_draw_direction.z,
        )
        obj.setPropertyStatus("BestDrawDirection", "Output")

        obj.addProperty(
            "App::PropertyString",
            "PartingSurfaceStatus",
            "MouldAnalysis",
            "Current parting surface state",
        ).PartingSurfaceStatus = "Waiting for source"
        obj.setPropertyStatus("PartingSurfaceStatus", "Output")

        obj.addProperty(
            "App::PropertyVector",
            "PartingSurfaceNormal",
            "MouldAnalysis",
            "Normal of the proposed parting surface",
        ).PartingSurfaceNormal = Vector(
            default_mould_analysis_draw_direction.x,
            default_mould_analysis_draw_direction.y,
            default_mould_analysis_draw_direction.z,
        )
        obj.setPropertyStatus("PartingSurfaceNormal", "Output")

        obj.addProperty(
            "App::PropertyFloat",
            "PartingSurfaceOffset",
            "MouldAnalysis",
            "Offset of the proposed parting surface",
        ).PartingSurfaceOffset = 0.0
        obj.setPropertyStatus("PartingSurfaceOffset", "Output")

        obj.addProperty(
            "App::PropertyFloat",
            "PartingSurfaceArea",
            "MouldAnalysis",
            "Area of the proposed parting surface",
        ).PartingSurfaceArea = 0.0
        obj.setPropertyStatus("PartingSurfaceArea", "Output")

        obj.addProperty(
            "App::PropertyString",
            "PartingSurfaceSummary",
            "MouldAnalysis",
            "Human-readable parting surface summary",
        ).PartingSurfaceSummary = "No source shape available."
        obj.setPropertyStatus("PartingSurfaceSummary", "Output")

        obj.addProperty(
            "App::PropertyLink",
            "PartingSurface",
            "MouldAnalysis",
            "Preview parting surface",
            hidden=True,
        )
        parting_surface = obj.Document.addObject(
            "Part::Feature",
            f"{obj.Name}_PartingSurface",
        )
        parting_surface.setPropertyStatus("Shape", "Output")
        obj.PartingSurface = parting_surface
        obj.setPropertyStatus("PartingSurface", "Output")

        obj.addProperty(
            "App::PropertyString",
            "MouldHalvesStatus",
            "MouldAnalysis",
            "Current mould halves state",
        ).MouldHalvesStatus = "Waiting for source"
        obj.setPropertyStatus("MouldHalvesStatus", "Output")

        obj.addProperty(
            "App::PropertyString",
            "MouldHalvesSummary",
            "MouldAnalysis",
            "Human-readable mould halves summary",
        ).MouldHalvesSummary = "No source shape available."
        obj.setPropertyStatus("MouldHalvesSummary", "Output")

        obj.addProperty(
            "App::PropertyLink",
            "MouldHalfA",
            "MouldAnalysis",
            "First mould half preview",
            hidden=True,
        )
        mould_half_a = obj.Document.addObject(
            "Part::Feature",
            f"{obj.Name}_MouldHalfA",
        )
        mould_half_a.setPropertyStatus("Shape", "Output")
        obj.MouldHalfA = mould_half_a
        obj.setPropertyStatus("MouldHalfA", "Output")

        obj.addProperty(
            "App::PropertyLink",
            "MouldHalfB",
            "MouldAnalysis",
            "Second mould half preview",
            hidden=True,
        )
        mould_half_b = obj.Document.addObject(
            "Part::Feature",
            f"{obj.Name}_MouldHalfB",
        )
        mould_half_b.setPropertyStatus("Shape", "Output")
        obj.MouldHalfB = mould_half_b
        obj.setPropertyStatus("MouldHalfB", "Output")

        _add_draft_defect_outputs(obj)
        _add_split_face_outputs(obj)
        _add_level_strip_outputs(obj)

        obj.addProperty(
            "App::PropertyString",
            "ValidationStatus",
            "MouldAnalysis",
            "Current validation state",
        ).ValidationStatus = "Waiting for source"
        obj.setPropertyStatus("ValidationStatus", "Output")

        obj.addProperty(
            "App::PropertyString",
            "ValidationSummary",
            "MouldAnalysis",
            "Human-readable validation summary",
        ).ValidationSummary = "No source shape available."
        obj.setPropertyStatus("ValidationSummary", "Output")

        obj.addProperty(
            "App::PropertyStringList",
            "ValidationChecks",
            "MouldAnalysis",
            "Validation check results",
        ).ValidationChecks = ["No source shape available."]
        obj.setPropertyStatus("ValidationChecks", "Output")

        obj.addProperty(
            "App::PropertyString",
            "AnalysisSummary",
            "MouldAnalysis",
            "Human-readable analysis summary",
        ).AnalysisSummary = "Select a solid to begin mould analysis."
        obj.setPropertyStatus("AnalysisSummary", "Output")

        super().__init__(obj)

    def onDocumentRestored(self, fp):
        super().onDocumentRestored(fp)
        # Documents saved before the band was configurable get the default.
        if not hasattr(fp, "TessellationBandTolDeg"):
            _add_tessellation_band_property(fp)
        if not hasattr(fp, "TessellationDeflection"):
            _add_tessellation_deflection_property(fp)
        if not hasattr(fp, "PartLineSource"):
            _add_part_line_source_property(fp)
        if not hasattr(fp, "PartLineRadius"):
            _add_part_line_radius_property(fp)
        # Documents saved before the defect display get its outputs.
        if not hasattr(fp, "DraftDefects"):
            _add_draft_defect_outputs(fp)
        if not hasattr(fp, "UpperSplitFaces"):
            _add_split_face_outputs(fp)
        # Documents saved before the skirt could be levelled carry none of its
        # inputs, and the rings the groove is cut between are new outputs.
        if not hasattr(fp, "SkirtLevelling"):
            _add_skirt_levelling_properties(fp)
        if not hasattr(fp, "LevelStripIn"):
            _add_level_strip_outputs(fp)

    def execute(self, fp):
        """Analyse the source, once per change of input.

        Nothing here remembers its inputs. The outputs are declared as outputs,
        so writing them leaves this object's recompute state alone, and FreeCAD
        runs this again only when something that defines the mould changed. A
        remembered signature could only skip a solve FreeCAD had already decided
        was due - and it did not survive the reload it was most needed for.
        """
        source_shape = fp.Source.Shape if fp.Source else None
        footprint = fp.PartingStockFootprint
        stock_footprint = (
            None
            if (footprint.x == 0.0 and footprint.y == 0.0 and footprint.z == 0.0)
            else (footprint.x, footprint.y)
        )
        result = analyze_source_shape(
            source_shape,
            fp.PreferredDrawDirection,
            source_obj=fp.Source,
            parting_stock_margin_x=fp.PartingStockMarginX,
            parting_stock_margin_y=fp.PartingStockMarginY,
            parting_stock_margin_z=fp.PartingStockMarginZ,
            parting_line_tolerance=fp.PartLineTolerance,
            parting_stock_footprint=stock_footprint,
            part_line_only=(fp.OutputMode == "Part-line only"),
            run_withdrawal_clearance=fp.WithdrawalClearance,
            parting_tessellation_band_tol_deg=fp.TessellationBandTolDeg,
            parting_tessellation_deflection_mm=float(fp.TessellationDeflection),
            part_line_source=fp.PartLineSource,
            part_line_radius_mm=float(fp.PartLineRadius),
            skirt_levelling=fp.SkirtLevelling,
            skirt_levelling_extent=fp.SkirtLevellingExtent,
            skirt_levelling_transition_mm=float(fp.SkirtLevellingTransition),
        )
        fp.AnalysisStatus = result["status"]
        fp.DrawDirectionScore = result["draw_direction_score"]
        fp.BestDrawDirection = result["best_draw_direction"]
        fp.PartingSurfaceStatus = result["parting_surface_status"]
        fp.PartingSurfaceNormal = result["parting_surface_normal"]
        fp.PartingSurfaceOffset = result["parting_surface_offset"]
        fp.PartingSurfaceArea = result["parting_surface_area"]
        fp.PartingSurfaceSummary = result["parting_surface_summary"]
        if fp.PartingSurface:
            fp.PartingSurface.Shape = result["parting_surface_shape"]
        fp.MouldHalvesStatus = result["mould_halves_status"]
        fp.MouldHalvesSummary = result["mould_halves_summary"]
        if fp.MouldHalfA:
            fp.MouldHalfA.Shape = result["mould_half_a_shape"]
        if fp.MouldHalfB:
            fp.MouldHalfB.Shape = result["mould_half_b_shape"]
        fp.DraftDefectSummary = result["draft_defect_summary"]
        if fp.DraftDefects:
            fp.DraftDefects.Shape = result["draft_defect_shape"]
            _paint_defects(fp.DraftDefects, result.get("draft_defect_faces", []))
        for half in SPLIT_FACE_HALVES:
            _write_split_faces(fp, half.capitalize(),
                               split_faces(result, half))
        fp.LevelStripSummary = result["level_strip_summary"]
        if fp.LevelStripIn:
            fp.LevelStripIn.Shape = result["level_strip_in_shape"]
        if fp.LevelStripOut:
            fp.LevelStripOut.Shape = result["level_strip_out_shape"]
        fp.ValidationStatus = result["validation_status"]
        fp.ValidationSummary = result["validation_summary"]
        fp.ValidationChecks = result["validation_checks"]
        fp.AnalysisSummary = result["summary"]
        fp.Shape = result["shape"]

    # There is deliberately no onChanged -> recompute hook here. Analysing on
    # the first property write makes the result depend on the order the caller
    # sets them in: the draw direction, the output mode and the withdrawal
    # flag all have to be in place *before* the first analysis, and a caller
    # setting them one by one cannot win. A property write touches the object
    # (the Source link is locked), so the document's own recompute runs the
    # analysis once, with everything configured - and MouldAnalysisFP.execute
    # skips it when nothing that defines the mould has changed.


def _write_split_faces(fp, label, pieces):
    """Persist one half's cut pieces: the faces as a compound, the rest as lists."""
    pieces = [piece for piece in pieces if piece["face"] is not None]
    setattr(fp, f"{label}SourceFaces",
            [int(piece["source_face_index"] or 0) for piece in pieces])
    setattr(fp, f"{label}StraddlingFaces",
            [bool(piece["straddles"]) for piece in pieces])
    target = getattr(fp, f"{label}SplitFaces", None)
    if target:
        target.Shape = (Part.makeCompound([piece["face"] for piece in pieces])
                        if pieces else Part.Shape())


def _paint_defects(child, details):
    """Colour each defect face by kind: wrong-side, or straddling its equator.

    The child's shape is built from this same defect list in the same order,
    so entry ``i`` is face ``i`` of the compound, which is the order
    DiffuseColor is applied in.
    """
    if not FreeCAD.GuiUp or not details:
        return
    if len(child.Shape.Faces) != len(details):
        return
    child.ViewObject.DiffuseColor = [
        STRADDLING_COLOR if detail.get("straddles") else DRAFT_DEFECT_COLOR
        for detail in details
    ]


class ViewProviderMouldAnalysis(VPCompositePart):
    def claimChildren(self):
        if not hasattr(self, "Object"):
            return []
        children = []
        for name in ("PartingSurface", "MouldHalfA", "MouldHalfB", "DraftDefects",
                     "UpperSplitFaces", "LowerSplitFaces",
                     "LevelStripIn", "LevelStripOut"):
            child = getattr(self.Object, name, None)
            if child:
                children.append(child)
        return children

    def getIcon(self):
        return MOULD_TOOL_ICON


class CompositeMouldAnalysisCommand(BaseCommand):
    icon = MOULD_TOOL_ICON
    menu_text = "Mould analysis"
    tool_tip = """Create a mould analysis object.
        Select source feature.
        WORK-IN-PROGRESS"""
    sel_args = [
        {
            "key": "source",
            "type": "Part::Feature",
        },
    ]
    type_id = "Part::FeaturePython"
    instance_name = "MouldAnalysis"
    cls_fp = MouldAnalysisFP
    cls_vp = ViewProviderMouldAnalysis


# The ViewProvider class that repairs this feature's serialised VP proxy on
# document restore (see CompositeBaseFP.onDocumentRestored). Without it a
# saved mould reopens with an int proxy, so its icon, its claimed children and
# its children's visibility all fail.
MouldAnalysisFP.view_provider_class = ViewProviderMouldAnalysis


# Command registration moved to InitGui.py to avoid FreeCADGui dependency
