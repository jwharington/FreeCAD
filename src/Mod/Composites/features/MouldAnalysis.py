# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

import FreeCAD

from FreeCAD import Vector

from .. import MOULD_TOOL_ICON, is_comp_type
from ..tools.mould_analysis import (
    DEFAULT_TESSELLATION_BAND_TOL_DEG,
    analyze_source_shape,
    default_mould_analysis_draw_direction,
)
from .Command import BaseCommand
from .VPCompositePart import CompositePartFP, VPCompositePart


def is_mould_analysis(obj):
    return is_comp_type(obj, "Part::FeaturePython", "Composite::MouldAnalysis")


DRAFT_DEFECT_COLOR = (1.0, 0.0, 0.0)


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


def _add_draft_defect_outputs(obj):
    obj.addProperty(
        "App::PropertyString",
        "DraftDefectSummary",
        "MouldAnalysis",
        "Split-shell faces whose draft opposes their own mould half",
    ).DraftDefectSummary = "No source shape available."
    obj.setPropertyStatus("DraftDefectSummary", "ReadOnly")

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
    if FreeCAD.GuiUp:
        draft_defects.ViewObject.ShapeColor = DRAFT_DEFECT_COLOR
        draft_defects.ViewObject.LineColor = DRAFT_DEFECT_COLOR
    obj.DraftDefects = draft_defects
    obj.setPropertyStatus("DraftDefects", "ReadOnly")


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
        if not hasattr(fp, "DraftDefects"):
            _add_draft_defect_outputs(fp)

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
        fp.DraftDefectSummary = result["draft_defect_summary"]
        if fp.DraftDefects:
            fp.DraftDefects.Shape = result["draft_defect_shape"]
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


class ViewProviderMouldAnalysis(VPCompositePart):
    def claimChildren(self):
        if not hasattr(self, "Object"):
            return []
        children = []
        for name in ("PartingSurface", "MouldHalfA", "MouldHalfB", "DraftDefects"):
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
