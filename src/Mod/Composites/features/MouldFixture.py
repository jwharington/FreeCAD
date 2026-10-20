# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Mould fixtures: cut the shop-floor fittings into a mould's two halves.

Consumes the upper and lower moulds a Mould analysis produced - as
``MouldHalfA`` / ``MouldHalfB`` on the linked ``Composite::MouldAnalysis``
object - and cuts alignment dowels, clamp bolt holes, clamp-ear notches,
process ports and parting wedges into them. The geometry and the
block-frame recovery live in
``tools/mould_fixture.py``; this module owns the object, its properties and
its outputs.
"""

import FreeCAD
import Part

from .. import MOULD_FIXTURE_TOOL_ICON, is_comp_type
from ..tools.mould_fixture import (
    AlignmentParams,
    ClampingParams,
    FixtureRequest,
    PortParams,
    WedgeParams,
    build_fixtures,
)
from ..tools.mould_fixture import PORT_HALVES as PORT_HALF_OPTIONS
from .Command import BaseCommand
from .VPCompositePart import CompositePartFP, VPCompositePart

PROPERTY_GROUP = "MouldFixture"
PIN_HALVES = ("Lower", "Upper")


def is_mould_fixture(obj):
    return is_comp_type(obj, "Part::FeaturePython", "Composite::MouldFixture")


def is_mould_analysis(obj):
    return is_comp_type(obj, "Part::FeaturePython", "Composite::MouldAnalysis")


def _add_property(obj, type_id, name, description, default):
    obj.addProperty(type_id, name, PROPERTY_GROUP, description)
    setattr(obj, name, default)


def _add_enumeration(obj, name, description, options, default):
    obj.addProperty("App::PropertyEnumeration", name, PROPERTY_GROUP, description)
    setattr(obj, name, list(options))
    setattr(obj, name, default)


def _shape_key(shape):
    """A comparable summary of a shape, for the recompute guard."""
    if shape is None or shape.isNull():
        return None
    box = shape.BoundBox
    return (round(shape.Volume, 6),
            round(box.XMin, 6), round(box.XMax, 6),
            round(box.YMin, 6), round(box.YMax, 6),
            round(box.ZMin, 6), round(box.ZMax, 6))


def mould_halves(source):
    """The ``(lower, upper)`` child objects of a mould analysis, or ``(None, None)``."""
    if source is None:
        return None, None
    return getattr(source, "MouldHalfA", None), getattr(source, "MouldHalfB", None)


class MouldFixtureFP(CompositePartFP):
    Type = "Composite::MouldFixture"

    def __init__(self, obj, source):
        obj.addProperty(
            "App::PropertyLink",
            "Source",
            PROPERTY_GROUP,
            "The mould whose halves are fixtured",
            locked=True,
        ).Source = source

        _add_property(obj, "App::PropertyBool", "AlignmentPins",
                      "Cut alignment dowel and bush sockets into the halves.", True)
        _add_property(obj, "App::PropertyInteger", "PinCount",
                      "Number of dowel/bush pairs, 1-4, placed on the block corners.", 2)
        _add_property(obj, "App::PropertyLength", "PinDiameter",
                      "Dowel pin socket diameter, cut in the pin half.", 8.0)
        _add_property(obj, "App::PropertyLength", "BushDiameter",
                      "Bush socket diameter, cut in the bush half.", 16.0)
        _add_property(obj, "App::PropertyLength", "PinDepth",
                      "Depth of each socket, measured from the mating surface.", 25.0)
        _add_property(obj, "App::PropertyLength", "PinEdgeOffset",
                      "Inset of each pin from the two block walls at its corner.", 20.0)
        _add_enumeration(obj, "PinHalf",
                         "Half that carries the dowel pin; the other carries the bush.",
                         PIN_HALVES, "Lower")

        _add_property(obj, "App::PropertyBool", "ClampBolts",
                      "Cut clamp bolt holes: clearance through the upper half into "
                      "a tapped hole in the lower.", True)
        _add_property(obj, "App::PropertyInteger", "BoltCount",
                      "Number of clamp bolts, equally spaced around the block perimeter.", 4)
        _add_property(obj, "App::PropertyLength", "BoltHoleDiameter",
                      "Bolt clearance hole diameter, cut through the upper half.", 11.0)
        _add_property(obj, "App::PropertyLength", "BoltTappedDiameter",
                      "Tapped core hole diameter, cut into the lower half.", 8.5)
        _add_property(obj, "App::PropertyLength", "BoltDepth",
                      "Depth of each tapped hole from the mating surface.", 20.0)
        _add_property(obj, "App::PropertyLength", "BoltEdgeOffset",
                      "Inset of the bolt pattern from the block walls.", 15.0)
        _add_property(obj, "App::PropertyBool", "ClampEars",
                      "Cut clamp-ear notches into the block walls at the mating plane, "
                      "so a clamp or wedge can grip the halves.", False)
        _add_property(obj, "App::PropertyInteger", "ClampEarCount",
                      "Number of clamp-ear notches around the block perimeter.", 4)
        _add_property(obj, "App::PropertyLength", "ClampEarWidth",
                      "Clamp-ear notch width, along the block wall.", 30.0)
        _add_property(obj, "App::PropertyLength", "ClampEarHeight",
                      "Clamp-ear notch height, across the mating plane.", 15.0)
        _add_property(obj, "App::PropertyLength", "ClampEarDepth",
                      "Clamp-ear notch depth, into the block from the wall.", 12.0)

        _add_property(obj, "App::PropertyBool", "ProcessPorts",
                      "Bore vacuum, ejector and thermocouple ports in from the block "
                      "walls.", True)
        _add_property(obj, "App::PropertyInteger", "PortCount",
                      "Number of process ports around the block perimeter.", 2)
        _add_property(obj, "App::PropertyLength", "PortDiameter",
                      "Process port bore diameter.", 6.0)
        _add_property(obj, "App::PropertyLength", "PortDepth",
                      "Process port bore depth into the block from the wall. A bore "
                      "that reaches the cavity breaks into it; one that does not stays "
                      "a blind pocket.", 40.0)
        _add_property(obj, "App::PropertyLength", "PortMatingOffset",
                      "Offset of a bore from the mating plane, so it lies in one half "
                      "rather than being split by the parting surface.", 8.0)
        _add_enumeration(obj, "PortHalf",
                         "Half, or halves, each process port is bored into.",
                         PORT_HALF_OPTIONS, "Lower")

        _add_property(obj, "App::PropertyBool", "PartingWedges",
                      "Cut triangular parting wedges into the block walls, apex on the "
                      "mating plane, so a driven wedge separates the halves.", True)
        _add_property(obj, "App::PropertyInteger", "WedgeCount",
                      "Number of parting wedges around the block perimeter.", 4)
        _add_property(obj, "App::PropertyLength", "WedgeWidth",
                      "Parting wedge width, along the block wall.", 20.0)
        _add_property(obj, "App::PropertyLength", "WedgeHeight",
                      "Parting wedge height, across the mating plane.", 12.0)
        _add_property(obj, "App::PropertyLength", "WedgeDepth",
                      "Parting wedge depth, into the block from the wall.", 15.0)

        for label in ("Lower", "Upper"):
            obj.addProperty(
                "App::PropertyLink",
                f"Fixture{label}",
                PROPERTY_GROUP,
                f"The fixtured {label.lower()} mould half",
                hidden=True,
            )
            child = obj.Document.addObject(
                "Part::Feature", f"{obj.Name}_Fixture{label}"
            )
            setattr(obj, f"Fixture{label}", child)
            obj.setPropertyStatus(f"Fixture{label}", "ReadOnly")

        for name, description in (
            ("FixtureStatus", "Current fixture state"),
            ("FixtureSummary", "Human-readable fixture summary"),
        ):
            obj.addProperty("App::PropertyString", name, PROPERTY_GROUP, description)
            setattr(obj, name, "Waiting for mould halves")
            obj.setPropertyStatus(name, "ReadOnly")

        obj.addProperty(
            "App::PropertyStringList",
            "FixtureIssues",
            PROPERTY_GROUP,
            "Fixture warnings and failures",
        ).FixtureIssues = ["Waiting for mould halves"]
        obj.setPropertyStatus("FixtureIssues", "ReadOnly")

        super().__init__(obj)

    def _params(self, fp):
        return (
            AlignmentParams(
                enabled=bool(fp.AlignmentPins),
                count=int(fp.PinCount),
                pin_diameter=float(fp.PinDiameter),
                bush_diameter=float(fp.BushDiameter),
                depth=float(fp.PinDepth),
                edge_offset=float(fp.PinEdgeOffset),
                pin_half=fp.PinHalf,
            ),
            ClampingParams(
                bolts_enabled=bool(fp.ClampBolts),
                bolt_count=int(fp.BoltCount),
                bolt_hole_diameter=float(fp.BoltHoleDiameter),
                bolt_tapped_diameter=float(fp.BoltTappedDiameter),
                bolt_depth=float(fp.BoltDepth),
                bolt_edge_offset=float(fp.BoltEdgeOffset),
                ears_enabled=bool(fp.ClampEars),
                ear_count=int(fp.ClampEarCount),
                ear_width=float(fp.ClampEarWidth),
                ear_height=float(fp.ClampEarHeight),
                ear_depth=float(fp.ClampEarDepth),
            ),
            PortParams(
                enabled=bool(fp.ProcessPorts),
                count=int(fp.PortCount),
                diameter=float(fp.PortDiameter),
                depth=float(fp.PortDepth),
                half=fp.PortHalf,
                offset_from_mating=float(fp.PortMatingOffset),
            ),
            WedgeParams(
                enabled=bool(fp.PartingWedges),
                count=int(fp.WedgeCount),
                width=float(fp.WedgeWidth),
                height=float(fp.WedgeHeight),
                depth=float(fp.WedgeDepth),
            ),
        )

    def _input_signature(self, fp):
        """Everything that defines the fixtures, as one comparable tuple.

        A mould whose halves changed touches this object through the ``Source``
        link, so the halves' own geometry distinguishes a real change from a
        repeat recompute.
        """
        source = fp.Source
        if source is None:
            return None
        lower, upper = mould_halves(source)
        half_keys = tuple(
            _shape_key(getattr(half, "Shape", None)) if half is not None else None
            for half in (lower, upper)
        )
        if any(key is None for key in half_keys):
            return None
        parting = getattr(source, "PartingSurface", None)
        parting_key = _shape_key(parting.Shape) if parting is not None else None
        draw = getattr(source, "BestDrawDirection", None)
        draw_key = None if draw is None else (round(draw.x, 6), round(draw.y, 6),
                                             round(draw.z, 6))
        return (half_keys, parting_key, draw_key, self._params(fp))

    def execute(self, fp):
        signature = self._input_signature(fp)
        if signature is None:
            fp.FixtureStatus = "Fail"
            fp.FixtureSummary = "Fixture build failed: the source mould has no halves."
            fp.FixtureIssues = [
                "Source has no usable MouldHalfA/MouldHalfB; run the mould "
                "analysis to completion first."
            ]
            self._fixtured_inputs = None
            self._write_shapes(fp, Part.Shape(), Part.Shape())
            return
        if signature == getattr(self, "_fixtured_inputs", None):
            # Writing the outputs below leaves this object touched, so without
            # this guard every document recompute re-runs every boolean cut.
            return

        source = fp.Source
        lower, upper = mould_halves(source)
        draw = getattr(source, "BestDrawDirection", None)
        if draw is None:
            draw = FreeCAD.Vector(0, 0, 1)
        parting = getattr(source, "PartingSurface", None)
        alignment, clamping, ports, wedges = self._params(fp)
        result = build_fixtures(
            FixtureRequest(
                lower=lower.Shape,
                upper=upper.Shape,
                draw=draw,
                parting_surface=parting.Shape if parting is not None else None,
                alignment=alignment,
                clamping=clamping,
                ports=ports,
                wedges=wedges,
            )
        )
        fp.FixtureStatus = result["status"]
        fp.FixtureSummary = result["summary"]
        fp.FixtureIssues = result["issues"]
        self._write_shapes(fp, result["lower_shape"], result["upper_shape"])
        if result["status"] != "Fail":
            self._fixtured_inputs = signature

    def _write_shapes(self, fp, lower_shape, upper_shape):
        if fp.FixtureLower:
            fp.FixtureLower.Shape = lower_shape
        if fp.FixtureUpper:
            fp.FixtureUpper.Shape = upper_shape


class ViewProviderMouldFixture(VPCompositePart):
    def claimChildren(self):
        if not hasattr(self, "Object"):
            return []
        children = []
        for name in ("FixtureLower", "FixtureUpper"):
            child = getattr(self.Object, name, None)
            if child:
                children.append(child)
        return children

    def getIcon(self):
        return MOULD_FIXTURE_TOOL_ICON


class CompositeMouldFixtureCommand(BaseCommand):
    icon = MOULD_FIXTURE_TOOL_ICON
    menu_text = "Mould fixtures"
    tool_tip = """Create a mould fixture object.
        Select the mould analysis object whose halves are fixtured.
        WORK-IN-PROGRESS"""
    sel_args = [
        {
            "key": "source",
            "type": "Part::Feature",
            "test": is_mould_analysis,
        },
    ]
    type_id = "Part::FeaturePython"
    instance_name = "MouldFixture"
    cls_fp = MouldFixtureFP
    cls_vp = ViewProviderMouldFixture

    def validate_selection(self, sel):
        lower, upper = mould_halves(sel.get("source"))
        for label, half in (("MouldHalfA", lower), ("MouldHalfB", upper)):
            if half is None or half.Shape.isNull():
                return (
                    f"The mould has no {label}: its analysis did not produce "
                    f"mould halves, so there is nothing to fixture."
                )
            if not half.Shape.Solids:
                return (
                    f"The mould's {label} is a {half.Shape.ShapeType} with no "
                    f"solid to cut. Fixtures need the mould halves as solids."
                )
        return None


# The ViewProvider class that repairs this feature's serialised VP proxy on
# document restore (see CompositeBaseFP.onDocumentRestored).
MouldFixtureFP.view_provider_class = ViewProviderMouldFixture


# Command registration moved to InitGui.py to avoid FreeCADGui dependency
