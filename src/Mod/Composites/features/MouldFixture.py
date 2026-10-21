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
from FreeCAD import Console

from .. import MOULD_FIXTURE_TOOL_ICON, is_comp_type
from ..tools.mould_fixture import (
    AlignmentParams,
    ClampingParams,
    FixtureRequest,
    PortParams,
    StockMargins,
    WedgeParams,
    build_fixtures,
    required_in_plane_margin,
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


def _add_bolt_properties(obj):
    """The clamp bolts' shape, on its own so a restore can add it.

    The bolts go right through both halves with a nut on top, so the lower half
    needs a clearance hole rather than the tapped one an earlier version cut,
    and the head is recessed into the face it enters by.
    """
    _add_property(obj, "App::PropertyBool", "ClampBolts",
                  "Cut clamp bolt holes right through both halves, the head "
                  "recessed into the lower cap face and a nut on the upper.",
                  True)
    _add_property(obj, "App::PropertyInteger", "BoltCount",
                  "Number of clamp bolts, equally spaced around the block "
                  "perimeter.", 4)
    _add_property(obj, "App::PropertyLength", "BoltHoleDiameter",
                  "Bolt clearance hole diameter, cut through both halves. 11 mm "
                  "clears an M10.", 11.0)
    _add_property(obj, "App::PropertyLength", "BoltHeadDiameter",
                  "Counterbore diameter that sinks the bolt head into the lower "
                  "cap face. 17 mm clears an M10 socket head; the nut on the "
                  "upper face needs no recess, so there is none there.", 17.0)
    _add_property(obj, "App::PropertyLength", "BoltHeadDepth",
                  "Depth of the bolt head counterbore, into the lower cap face. "
                  "Has to stop short of the mating surface.", 10.5)
    _add_property(obj, "App::PropertyLength", "BoltEdgeOffset",
                  "Inset of the bolt pattern from the block walls. A bolt keeps "
                  "2R of gap from the wall, so the pattern stands 3R in: 26 mm "
                  "for the 17 mm head counterbore. Less than that is reported "
                  "rather than cut.", 26.0)


def _add_seat_properties(obj):
    """The alignment seat's extra cuts, on their own so a restore can add them.

    A commercial locating part is not a plain dowel: its flange or shoulder
    seats on a counterbore, it is held by a screw from the back of the block,
    and its blind seat holds an air pocket that has to be vented or it
    outgasses into a vacuum tool. Only the screw hole is on by default, because
    it is what the default part needs and it vents the seat as well.
    """
    _add_property(obj, "App::PropertyLength", "SeatShoulderDiameter",
                  "Counterbore diameter for a locating part's flange or "
                  "shoulder. Zero cuts no counterbore.", 0.0)
    _add_property(obj, "App::PropertyLength", "SeatShoulderDepth",
                  "Depth of the shoulder counterbore, from the mating face. "
                  "Has to stop short of the seat floor.", 0.0)
    _add_property(obj, "App::PropertyLength", "SeatVentDiameter",
                  "Diameter of a vent from each seat floor out through the cap "
                  "face, so a blind seat is not a trapped volume under vacuum. "
                  "Zero cuts no vent; a screw clearance hole already vents the "
                  "seat, so this is only needed for a part with no back screw.",
                  0.0)
    _add_property(obj, "App::PropertyLength", "SeatScrewDiameter",
                  "Clearance diameter for the screw that holds a screw-fixed "
                  "locating part, cut from the cap face behind the seat to its "
                  "floor. 5.5 mm clears an M5. Zero cuts no screw hole.", 5.5)
    _add_property(obj, "App::PropertyLength", "SeatScrewHeadDiameter",
                  "Counterbore diameter that sinks the screw head into the cap "
                  "face. 9.5 mm clears an M5 socket head. Zero leaves the head "
                  "standing proud.", 9.5)
    _add_property(obj, "App::PropertyLength", "SeatScrewHeadDepth",
                  "Depth of the screw head counterbore, into the cap face. Has "
                  "to stop short of the seat floor.", 5.5)


def _add_wedge_properties(obj):
    """The parting-wedge slot's shape, on its own so a restore can add it."""
    _add_property(obj, "App::PropertyBool", "PartingWedges",
                  "Cut a triangular parting slot along each block wall, apex "
                  "on the mating plane, so a driven wedge separates the "
                  "halves.", True)
    _add_property(obj, "App::PropertyLength", "WedgeCornerStandoff",
                  "Length of wall left uncut at each corner. The corners keep "
                  "the alignment sockets and survive a wedge driven too hard; "
                  "the slot runs the rest of the wall, interrupted where a "
                  "process port is bored through it.", 50.0)
    _add_property(obj, "App::PropertyLength", "WedgeHeight",
                  "Parting wedge height, across the mating plane.", 12.0)
    _add_property(obj, "App::PropertyLength", "WedgeDepth",
                  "Parting wedge depth, into the block from the wall. It has "
                  "to stay clear of the clamp bolt holes and the process "
                  "bores: at the 11 mm default the slot reaches 12 mm in, "
                  "against a bolt edge 12.5 mm out.", 11.0)


def mould_halves(source):
    """The ``(lower, upper)`` child objects of a mould analysis, or ``(None, None)``."""
    if source is None:
        return None, None
    return getattr(source, "MouldHalfA", None), getattr(source, "MouldHalfB", None)


def stock_margins(source):
    """The mould's declared in-plane stock, or ``None`` when it declares none."""
    margin_x = getattr(source, "PartingStockMarginX", None)
    margin_y = getattr(source, "PartingStockMarginY", None)
    if margin_x is None or margin_y is None:
        return None
    footprint = getattr(source, "PartingStockFootprint", None)
    explicit = footprint is not None and (footprint.x != 0.0 or footprint.y != 0.0)
    return StockMargins(x=float(margin_x), y=float(margin_y),
                        explicit_footprint=explicit)


def fixture_params(fp):
    """The fixture properties as the tool's parameter objects."""
    return (
        AlignmentParams(
            enabled=bool(fp.AlignmentPins),
            count=int(fp.PinCount),
            pin_diameter=float(fp.PinDiameter),
            bush_diameter=float(fp.BushDiameter),
            depth=float(fp.PinDepth),
            edge_offset=float(fp.PinEdgeOffset),
            pin_half=fp.PinHalf,
            shoulder_diameter=float(fp.SeatShoulderDiameter),
            shoulder_depth=float(fp.SeatShoulderDepth),
            vent_diameter=float(fp.SeatVentDiameter),
            screw_diameter=float(fp.SeatScrewDiameter),
            screw_head_diameter=float(fp.SeatScrewHeadDiameter),
            screw_head_depth=float(fp.SeatScrewHeadDepth),
        ),
        ClampingParams(
            bolts_enabled=bool(fp.ClampBolts),
            bolt_count=int(fp.BoltCount),
            bolt_hole_diameter=float(fp.BoltHoleDiameter),
            bolt_head_diameter=float(fp.BoltHeadDiameter),
            bolt_head_depth=float(fp.BoltHeadDepth),
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
            half=fp.PortHalf,
            offset_from_mating=float(fp.PortMatingOffset),
        ),
        WedgeParams(
            enabled=bool(fp.PartingWedges),
            corner_standoff=float(fp.WedgeCornerStandoff),
            height=float(fp.WedgeHeight),
            depth=float(fp.WedgeDepth),
        ),
    )


def reserve_stock_margins(source, fixture):
    """Raise the mould's in-plane margins to fit this fixture's own sizes.

    Returns ``[(property, before, after)]`` for the margins raised, empty when
    the mould already declares enough stock or its margins do not apply.

    For the command to run once, when the fixture is created: the margins are
    part of the mould's recompute guard, so raising them re-runs its whole
    parting analysis, and a user's later size edits are reported rather than
    resizing the mould under them.
    """
    margins = stock_margins(source)
    if margins is None or margins.explicit_footprint:
        return []
    alignment, clamping, _ports, wedges = fixture_params(fixture)
    needed = required_in_plane_margin(alignment, clamping, wedges)
    raised = []
    for name, before in (("PartingStockMarginX", margins.x),
                         ("PartingStockMarginY", margins.y)):
        if needed > before:
            setattr(source, name, needed)
            raised.append((name, before, needed))
    return raised


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
                      "Diameter of the seat in the pin half. A matched round "
                      "interlock pair has the same outer diameter in both "
                      "halves, so this normally equals BushDiameter - 10 mm for "
                      "the default A1-10 part.", 10.0)
        _add_property(obj, "App::PropertyLength", "BushDiameter",
                      "Diameter of the seat in the bush half. Equal to "
                      "PinDiameter for a round interlock pair; a dowel-and-bush "
                      "pair sets them differently.", 10.0)
        _add_property(obj, "App::PropertyLength", "PinDepth",
                      "Depth of each seat, measured from the mating surface. The "
                      "part must not bottom, so leave the assembled gap clear: "
                      "10 mm matches the default A1-10 part's engagement.", 10.0)
        _add_property(obj, "App::PropertyLength", "PinEdgeOffset",
                      "Inset of each pin from the two block walls at its corner. "
                      "The socket keeps 2R of gap from the wall, so the centre "
                      "stands 3R in: 24 mm for the default 8 mm pin and 16 mm "
                      "bush. Less than that is reported rather than cut.", 24.0)
        _add_enumeration(obj, "PinHalf",
                         "Half that carries the dowel pin; the other carries the bush.",
                         PIN_HALVES, "Lower")
        _add_seat_properties(obj)

        _add_bolt_properties(obj)
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
                      "Bore vacuum, ejector and thermocouple ports in from the "
                      "block walls. Each bore is cut to reach the part and open "
                      "into the cavity; there is no depth to set, because the "
                      "depth that reaches the part belongs to the mould.", True)
        _add_property(obj, "App::PropertyInteger", "PortCount",
                      "Number of process ports around the block perimeter.", 2)
        _add_property(obj, "App::PropertyLength", "PortDiameter",
                      "Process port bore diameter.", 6.0)
        _add_property(obj, "App::PropertyLength", "PortMatingOffset",
                      "Offset of a bore from the mating plane, so it lies in one half "
                      "rather than being split by the parting surface.", 8.0)
        _add_enumeration(obj, "PortHalf",
                         "Half, or halves, each process port is bored into.",
                         PORT_HALF_OPTIONS, "Lower")

        _add_wedge_properties(obj)

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

    def onDocumentRestored(self, fp):
        super().onDocumentRestored(fp)
        # A wedge used to be a notch at each of `WedgeCount` stations, `WedgeWidth`
        # long. Documents saved then carry neither of the properties that
        # replaced them, so the slot's shape is added back here rather than
        # leaving the fixture unbuildable. The stale pair is left alone: nothing
        # reads it, and removing a user's property is worse than leaving one.
        if not hasattr(fp, "WedgeCornerStandoff"):
            _add_wedge_properties(fp)
        # Documents saved before the seat's extra cuts existed carry none of
        # them, and fixture_params reads all three directly.
        if not hasattr(fp, "SeatShoulderDiameter"):
            _add_seat_properties(fp)
        # A bolt used to thread into the lower half, so documents saved then
        # carry a tapped diameter and a tapped depth in place of the head
        # counterbore, and fixture_params reads the counterbore directly.
        if not hasattr(fp, "BoltHeadDiameter"):
            _add_bolt_properties(fp)

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
        return (half_keys, parting_key, draw_key, fixture_params(fp))

    def execute(self, fp):
        signature = self._input_signature(fp)
        if signature is None:
            self._write_failure(
                fp,
                "Fixture build failed: the source mould has no halves.",
                ["Source has no usable MouldHalfA/MouldHalfB; run the mould "
                 "analysis to completion first."],
            )
            return
        if signature == getattr(self, "_fixtured_inputs", None):
            # Writing the outputs below leaves this object touched, so without
            # this guard every document recompute re-runs every boolean cut.
            return
        if signature == getattr(self, "_failed_inputs", None):
            # A build that failed for this same input is not worth repeating
            # either, and re-writing its report would touch the object again.
            return

        source = fp.Source
        lower, upper = mould_halves(source)
        draw = getattr(source, "BestDrawDirection", None)
        if draw is None:
            draw = FreeCAD.Vector(0, 0, 1)
        parting = getattr(source, "PartingSurface", None)
        alignment, clamping, ports, wedges = fixture_params(fp)
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
                stock_margins=stock_margins(source),
            )
        )
        if result["status"] == "Fail":
            self._write_failure(fp, result["summary"], result["issues"])
            return
        fp.FixtureStatus = result["status"]
        fp.FixtureSummary = result["summary"]
        fp.FixtureIssues = result["issues"]
        self._write_shapes(fp, result["lower_shape"], result["upper_shape"])
        self._fixtured_inputs = signature
        self._failed_inputs = None

    def _write_failure(self, fp, summary, issues):
        """Report a failure once, then stop.

        Writing the outputs touches this object and its children, which
        re-schedules the recompute that produced them - so a failure that
        re-wrote its report on every recompute looped instead of reporting.
        Only changed text writes anything, and a half that is already empty is
        left alone for the same reason. The failed input is remembered so a
        failing build is not run again either, which matters when the build is
        expensive.
        """
        if (fp.FixtureStatus != "Fail" or fp.FixtureSummary != summary
                or list(fp.FixtureIssues) != list(issues)):
            fp.FixtureStatus = "Fail"
            fp.FixtureSummary = summary
            fp.FixtureIssues = list(issues)
            self._fixtured_inputs = None
            for child in (fp.FixtureLower, fp.FixtureUpper):
                if child is not None and not child.Shape.isNull():
                    child.Shape = Part.Shape()
        self._failed_inputs = self._input_signature(fp)

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

    def post_create(self, fixture):
        """Size the mould to receive the fixtures, before the first build."""
        raised = reserve_stock_margins(fixture.Source, fixture)
        if not raised:
            return
        changes = ", ".join(
            f"{name} {before:.3f} -> {after:.3f} mm" for name, before, after in raised
        )
        Console.PrintWarning(
            f"Mould fixtures: raised {changes} on {fixture.Source.Label} so the "
            f"mould has the stock these fixtures need\n"
        )

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
