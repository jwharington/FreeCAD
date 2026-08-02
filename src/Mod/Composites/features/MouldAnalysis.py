# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

import FreeCAD

from FreeCAD import Vector

from .. import MOULD_TOOL_ICON, is_comp_type
from ..tools.mould_analysis import (
    analyze_source_shape,
    default_mould_analysis_draw_direction,
)
from .Command import BaseCommand
from .VPCompositePart import CompositePartFP, VPCompositePart


def is_mould_analysis(obj):
    return is_comp_type(obj, "Part::FeaturePython", "Composite::MouldAnalysis")


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
            "PartingModel",
            "MouldAnalysis",
            "Parting-surface model: Planar (midpoint plane) or NonPlanar (marching equator)",
        ).PartingModel = ["Planar", "NonPlanar"]
        obj.PartingModel = "Planar"

        obj.addProperty(
            "App::PropertyFloat",
            "PartLineSampleSpacing",
            "MouldAnalysis",
            "Target spacing (mm) between samples along the part line",
        ).PartLineSampleSpacing = 2.0

        obj.addProperty(
            "App::PropertyFloat",
            "PartingStockMarginXY",
            "MouldAnalysis",
            "Lateral stock-block margin (mm) in the draw-perpendicular plane",
        ).PartingStockMarginXY = 5.0

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

    def execute(self, fp):
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
            parting_model=fp.PartingModel,
            parting_stock_margin_xy=fp.PartingStockMarginXY,
            parting_stock_margin_z=fp.PartingStockMarginZ,
            parting_sample_spacing=fp.PartLineSampleSpacing,
            parting_stock_footprint=stock_footprint,
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
        fp.ValidationStatus = result["validation_status"]
        fp.ValidationSummary = result["validation_summary"]
        fp.ValidationChecks = result["validation_checks"]
        fp.AnalysisSummary = result["summary"]
        fp.Shape = result["shape"]

    def onChanged(self, fp, prop):
        if prop in (
            "Source",
            "PreferredDrawDirection",
            "PartingModel",
            "PartLineSampleSpacing",
            "PartingStockMarginXY",
            "PartingStockMarginZ",
            "PartingStockFootprint",
        ):
            fp.recompute()


class ViewProviderMouldAnalysis(VPCompositePart):
    def claimChildren(self):
        children = []
        for name in ("PartingSurface", "MouldHalfA", "MouldHalfB"):
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
