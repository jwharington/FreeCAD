# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

from typing import NamedTuple

import FreeCAD
import Part

from FreeCAD import Vector

from .. import MOULD_TOOL_ICON, is_comp_type
from ..tools.mould_analysis import (
    DEFAULT_TESSELLATION_BAND_TOL_DEG,
    analyze_source_shape,
    default_mould_analysis_draw_direction,
    split_faces,
)
from .Command import BaseCommand
from .VPCompositePart import CompositePartFP, VPCompositePart


def is_mould_analysis(obj):
    return is_comp_type(obj, "Part::FeaturePython", "Composite::MouldAnalysis")


class DefectKind(NamedTuple):
    """One kind of defect: its child link, its summary, and its colour.

    ``shape_key`` / ``summary_key`` are the analysis-result fields holding its
    faces and its description, so the two kinds cannot drift apart.
    """

    link: str
    summary: str
    shape_key: str
    summary_key: str
    description: str
    color: tuple


# The two defect kinds are shown in different colours, and each has its own
# child so the split between them is structural, not only pigmentation.
WRONG_SIDE_COLOR = (1.0, 0.0, 0.0)      # draft opposes the piece's own half
STRADDLING_COLOR = (1.0, 0.5, 0.0)      # part line did not cut it at its equator

DEFECT_KINDS = (
    DefectKind(
        "DraftDefects", "DraftDefectSummary",
        "draft_defect_wrong_side_shape", "draft_defect_summary",
        "Wrong-side draft faces: the piece's draft opposes its own mould half",
        WRONG_SIDE_COLOR),
    DefectKind(
        "StraddlingFaces", "StraddlingSummary",
        "draft_defect_straddling_shape", "draft_defect_straddling_summary",
        "Straddling faces: the part line did not cut the source face at its "
        "equator, leaving normals on both halves of the draw",
        STRADDLING_COLOR),
)

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
        obj.setPropertyStatus(f"{label}SplitFaces", "ReadOnly")

        obj.addProperty(
            "App::PropertyIntegerList",
            f"{label}SourceFaces",
            "MouldAnalysis",
            f"Source face each {half} piece was cut from (1-based Face numbering)",
        )
        obj.setPropertyStatus(f"{label}SourceFaces", "ReadOnly")

        obj.addProperty(
            "App::PropertyBoolList",
            f"{label}StraddlingFaces",
            "MouldAnalysis",
            f"{half} pieces whose source face the part line did not cut at its "
            f"equator",
        )
        obj.setPropertyStatus(f"{label}StraddlingFaces", "ReadOnly")


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


def _add_defect_child(obj, kind):
    """One defect kind: a summary string plus its faces, in its own colour."""
    obj.addProperty("App::PropertyString", kind.summary, "MouldAnalysis",
                    kind.description)
    setattr(obj, kind.summary, "No source shape available.")
    obj.setPropertyStatus(kind.summary, "ReadOnly")

    obj.addProperty("App::PropertyLink", kind.link, "MouldAnalysis",
                    f"{kind.description} (shown in {kind.color})", hidden=True)
    child = obj.Document.addObject("Part::Feature", f"{obj.Name}_{kind.link}")
    if FreeCAD.GuiUp:
        child.ViewObject.ShapeColor = kind.color
        child.ViewObject.LineColor = kind.color
    setattr(obj, kind.link, child)
    obj.setPropertyStatus(kind.link, "ReadOnly")


def _add_draft_defect_outputs(obj):
    for kind in DEFECT_KINDS:
        _add_defect_child(obj, kind)


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
        obj.setPropertyStatus("AnalysisStatus", "ReadOnly")

        obj.addProperty(
            "App::PropertyFloat",
            "DrawDirectionScore",
            "MouldAnalysis",
            "Normalized score for the preferred draw direction",
        ).DrawDirectionScore = 0.0
        obj.setPropertyStatus("DrawDirectionScore", "ReadOnly")

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
        obj.setPropertyStatus("BestDrawDirection", "ReadOnly")

        obj.addProperty(
            "App::PropertyString",
            "PartingSurfaceStatus",
            "MouldAnalysis",
            "Current parting surface state",
        ).PartingSurfaceStatus = "Waiting for source"
        obj.setPropertyStatus("PartingSurfaceStatus", "ReadOnly")

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
        obj.setPropertyStatus("PartingSurfaceNormal", "ReadOnly")

        obj.addProperty(
            "App::PropertyFloat",
            "PartingSurfaceOffset",
            "MouldAnalysis",
            "Offset of the proposed parting surface",
        ).PartingSurfaceOffset = 0.0
        obj.setPropertyStatus("PartingSurfaceOffset", "ReadOnly")

        obj.addProperty(
            "App::PropertyFloat",
            "PartingSurfaceArea",
            "MouldAnalysis",
            "Area of the proposed parting surface",
        ).PartingSurfaceArea = 0.0
        obj.setPropertyStatus("PartingSurfaceArea", "ReadOnly")

        obj.addProperty(
            "App::PropertyString",
            "PartingSurfaceSummary",
            "MouldAnalysis",
            "Human-readable parting surface summary",
        ).PartingSurfaceSummary = "No source shape available."
        obj.setPropertyStatus("PartingSurfaceSummary", "ReadOnly")

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
        obj.PartingSurface = parting_surface
        obj.setPropertyStatus("PartingSurface", "ReadOnly")

        obj.addProperty(
            "App::PropertyString",
            "MouldHalvesStatus",
            "MouldAnalysis",
            "Current mould halves state",
        ).MouldHalvesStatus = "Waiting for source"
        obj.setPropertyStatus("MouldHalvesStatus", "ReadOnly")

        obj.addProperty(
            "App::PropertyString",
            "MouldHalvesSummary",
            "MouldAnalysis",
            "Human-readable mould halves summary",
        ).MouldHalvesSummary = "No source shape available."
        obj.setPropertyStatus("MouldHalvesSummary", "ReadOnly")

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
        obj.MouldHalfA = mould_half_a
        obj.setPropertyStatus("MouldHalfA", "ReadOnly")

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
        obj.MouldHalfB = mould_half_b
        obj.setPropertyStatus("MouldHalfB", "ReadOnly")

        _add_draft_defect_outputs(obj)
        _add_split_face_outputs(obj)

        obj.addProperty(
            "App::PropertyString",
            "ValidationStatus",
            "MouldAnalysis",
            "Current validation state",
        ).ValidationStatus = "Waiting for source"
        obj.setPropertyStatus("ValidationStatus", "ReadOnly")

        obj.addProperty(
            "App::PropertyString",
            "ValidationSummary",
            "MouldAnalysis",
            "Human-readable validation summary",
        ).ValidationSummary = "No source shape available."
        obj.setPropertyStatus("ValidationSummary", "ReadOnly")

        obj.addProperty(
            "App::PropertyStringList",
            "ValidationChecks",
            "MouldAnalysis",
            "Validation check results",
        ).ValidationChecks = ["No source shape available."]
        obj.setPropertyStatus("ValidationChecks", "ReadOnly")

        obj.addProperty(
            "App::PropertyString",
            "AnalysisSummary",
            "MouldAnalysis",
            "Human-readable analysis summary",
        ).AnalysisSummary = "Select a solid to begin mould analysis."
        obj.setPropertyStatus("AnalysisSummary", "ReadOnly")

        super().__init__(obj)

    def _input_signature(self, fp):
        """Everything that defines the mould, as one comparable tuple.

        A source whose geometry changed touches this object through the
        ``Source`` link, so the configured properties plus the source's own
        geometry distinguish a real change from a repeat recompute.
        """
        source = fp.Source
        shape = getattr(source, "Shape", None) if source is not None else None
        if shape is None or shape.isNull():
            return None
        box = shape.BoundBox
        geometry = (source.Name, round(shape.Volume, 6),
                    round(box.XMin, 6), round(box.XMax, 6),
                    round(box.YMin, 6), round(box.YMax, 6),
                    round(box.ZMin, 6), round(box.ZMax, 6))
        draw = fp.PreferredDrawDirection
        footprint = fp.PartingStockFootprint
        return (geometry,
                (draw.x, draw.y, draw.z),
                fp.OutputMode,
                fp.PartLineTolerance,
                fp.PartingStockMarginX,
                fp.PartingStockMarginY,
                fp.PartingStockMarginZ,
                (footprint.x, footprint.y, footprint.z),
                bool(fp.WithdrawalClearance),
                fp.TessellationBandTolDeg)

    def onDocumentRestored(self, fp):
        super().onDocumentRestored(fp)
        # Documents saved before the band was configurable get the default.
        if not hasattr(fp, "TessellationBandTolDeg"):
            _add_tessellation_band_property(fp)
        # Documents saved before the defect display get its outputs.
        if not hasattr(fp, "StraddlingFaces"):
            _add_draft_defect_outputs(fp)
        if not hasattr(fp, "UpperSplitFaces"):
            _add_split_face_outputs(fp)

    def execute(self, fp):
        signature = self._input_signature(fp)
        if signature is not None and signature == getattr(self, "_analysed_inputs", None):
            # Nothing that defines the mould has changed. Writing the outputs
            # below (Shape, the status strings, the child halves) leaves this
            # object touched, so without this guard every document recompute
            # runs the whole find-seed/split/skirt/close pipeline again - one
            # build paid for three solves, each dominated by closeHalves.
            return
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
        for kind in DEFECT_KINDS:
            setattr(fp, kind.summary, result[kind.summary_key])
            child = getattr(fp, kind.link, None)
            if child:
                child.Shape = result[kind.shape_key]
        for half in SPLIT_FACE_HALVES:
            _write_split_faces(fp, half.capitalize(),
                               split_faces(result, half))
        fp.ValidationStatus = result["validation_status"]
        fp.ValidationSummary = result["validation_summary"]
        fp.ValidationChecks = result["validation_checks"]
        fp.AnalysisSummary = result["summary"]
        fp.Shape = result["shape"]
        self._analysed_inputs = signature

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


class ViewProviderMouldAnalysis(VPCompositePart):
    def claimChildren(self):
        if not hasattr(self, "Object"):
            return []
        children = []
        for name in ("PartingSurface", "MouldHalfA", "MouldHalfB", "DraftDefects",
                     "UpperSplitFaces", "LowerSplitFaces", "StraddlingFaces"):
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


# Command registration moved to InitGui.py to avoid FreeCADGui dependency
