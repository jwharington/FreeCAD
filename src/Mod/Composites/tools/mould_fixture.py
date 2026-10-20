# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Fixture geometry cut into the two halves of a split mould.

A mould analysis produces two closed halves that together fill a rectangular
stock block parted along the part line. This module cuts the shop-floor
fixtures into them: alignment dowels, clamp bolt holes, clamp-ear notches and
parting wedges.

The halves are assembled by the C++ parting solver in a local frame whose +Z
is the draw direction and are mapped back to world coordinates, so the block
is *not* world-axis aligned. Every fixture position here is expressed in a
recovered block frame (``block_frame``) and converted to world coordinates
through that frame's axes, never through world XYZ.

Cutting needs solids, and the solver only *tries* to repair its sewn half
shells into solids; a half that is still a shell is refused with a reason
rather than handed to a boolean.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from FreeCAD import Vector
import Part

from .mould_analysis import _face_midpoint_normal, _normalized

# A face counts as parallel to the draw direction when its normal is this
# close to perpendicular to it. OCCT reports built planes exactly, so this is
# tight.
AXIS_ALIGNMENT_TOL = 1.0e-6

# A planar face lies on the block boundary when its plane offset is within
# this of the extreme vertex projection along its own normal. Vertices from
# the solver sit on the walls exactly; the slack only absorbs coordinate
# noise.
PLANE_OFFSET_TOL = 1.0e-4

# Two wall normals are the same block axis within this.
DIRECTION_MATCH_TOL = 1.0e-6

# Every tool runs this far past the face it breaks out of, so the boolean
# gets a clean break-out instead of a coincident-face sliver. Cutting each
# half with its own tool list makes the overshoot harmless: the material it
# reaches belongs to the other half.
TOOL_OVERSHOOT = 1.0

# How far inboard of a fixture the mating height is sampled. The parting
# surface's boundary is the block wall, so a fixture lying ON a wall (a
# parting wedge, a clamp-ear notch) would section the surface along that
# boundary edge and read no crossing at all; its height there is what the
# surface takes a fraction of a millimetre inboard.
MATING_PROBE_INSET = 0.5

# Corner pattern order. Fixed so a given count always lands on the same
# corners, whatever order OCCT enumerates the half's faces in.
_CORNER_ORDER = ((-1.0, -1.0), (1.0, 1.0), (-1.0, 1.0), (1.0, -1.0))

STATUS_READY = "Ready"
STATUS_FAIL = "Fail"
STATUS_WAITING = "Waiting for mould"

PIN_HALVES = ("Lower", "Upper")
PORT_HALVES = ("Lower", "Upper", "Both")


class MouldFixtureError(Exception):
    """A mould that cannot carry fixtures, with the reason why."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class BlockFrame:
    """The stock block's own axes, and its extent along each.

    The extents are signed distances along the axes from the world origin, so
    ``point(x, y, z)`` is exactly ``x * x_axis + y * y_axis + z * z_axis`` and
    a fixture position in block coordinates is a signed distance, not an
    offset from a separate origin.
    """

    x_axis: Vector
    y_axis: Vector
    z_axis: Vector
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float

    def point(self, x, y, z):
        return self.x_axis * x + self.y_axis * y + self.z_axis * z

    @property
    def x_mid(self):
        return 0.5 * (self.x_min + self.x_max)

    @property
    def y_mid(self):
        return 0.5 * (self.y_min + self.y_max)

    @property
    def z_mid(self):
        return 0.5 * (self.z_min + self.z_max)

    @property
    def size(self):
        return (self.x_max - self.x_min,
                self.y_max - self.y_min,
                self.z_max - self.z_min)


@dataclass(frozen=True)
class PerimeterStation:
    """A point on the inset block perimeter, with its wall's directions.

    ``tangent`` and ``inward`` are unit pairs in *block-frame* coordinates,
    converted to world directions by ``_orient_tangent`` / ``_orient_inward``.
    """

    x: float
    y: float
    tangent: tuple
    inward: tuple


@dataclass(frozen=True)
class AlignmentParams:
    """Dowel pin in one half, bush socket in the other."""

    enabled: bool = True
    count: int = 2
    pin_diameter: float = 8.0
    bush_diameter: float = 16.0
    depth: float = 25.0
    edge_offset: float = 20.0
    pin_half: str = "Lower"


@dataclass(frozen=True)
class ClampingParams:
    """Through-bolts into the upper half, tapped holes into the lower, plus
    wall notches a clamp or wedge can grip."""

    bolts_enabled: bool = True
    bolt_count: int = 4
    bolt_hole_diameter: float = 11.0
    bolt_tapped_diameter: float = 8.5
    bolt_depth: float = 20.0
    bolt_edge_offset: float = 15.0
    ears_enabled: bool = False
    ear_count: int = 4
    ear_width: float = 30.0
    ear_height: float = 15.0
    ear_depth: float = 12.0


@dataclass(frozen=True)
class WedgeParams:
    """Triangular notches straddling the parting plane, one per pry point."""

    enabled: bool = True
    count: int = 4
    width: float = 20.0
    height: float = 12.0
    depth: float = 15.0


@dataclass(frozen=True)
class PortParams:
    """Bores drilled in from a block wall: vacuum, ejector, thermocouple.

    A bore is drilled perpendicular to the wall it enters, offset clear of the
    mating plane so it lies in one half. It breaks into the cavity when the
    block is thin enough at that depth and is a blind pocket when it is not -
    which is what a thermocouple pocket is.
    """

    enabled: bool = True
    count: int = 2
    diameter: float = 6.0
    depth: float = 40.0
    half: str = "Lower"
    offset_from_mating: float = 8.0


@dataclass(frozen=True)
class StockMargins:
    """The mould's declared in-plane stock, as the mould analysis reports it.

    ``explicit_footprint`` records that the mould set a stock footprint, which
    is the in-plane stock in place of these margins: the two numbers then do not
    describe the block and cannot be compared with what a fixture needs.
    """

    x: float
    y: float
    explicit_footprint: bool = False


@dataclass
class FixtureRequest:
    """Everything ``build_fixtures`` consumes, so it takes one argument."""

    lower: object
    upper: object
    draw: Vector
    parting_surface: object = None
    alignment: AlignmentParams = field(default_factory=AlignmentParams)
    clamping: ClampingParams = field(default_factory=ClampingParams)
    ports: PortParams = field(default_factory=PortParams)
    wedges: WedgeParams = field(default_factory=WedgeParams)
    stock_margins: object = None


@dataclass(eq=False)
class MouldBlock:
    """A recovered block frame plus the parting surface that sits in it.

    ``mating_fallbacks`` counts how many fixture positions had to fall back to
    the block mid-height because no parting surface crossed them, so the
    approximation is reported rather than hidden.
    """

    frame: BlockFrame
    parting_surface: object = None
    mating_fallbacks: int = 0
    breakthroughs: list = field(default_factory=list)

    def mating_height(self, x, y):
        """The z at which the two halves meet above ``(x, y)``.

        The parting surface is non-planar in general, so the local mating
        height is read by sectioning the draw-direction line through the point
        with the surface's own geometry: a position-dependent height, not one
        plane for the whole block.

        The sample is taken ``MATING_PROBE_INSET`` inboard of the position, for
        the wall-adjacent fixtures described there. A missing or non-crossing
        surface falls back to the block mid-height and is counted in
        ``mating_fallbacks``.
        """
        frame = self.frame
        fallback = frame.z_mid
        surface = self.parting_surface
        if surface is None or surface.isNull():
            self.mating_fallbacks += 1
            return fallback
        sample_x, sample_y = self._inboard(x, y)
        low = frame.z_min - TOOL_OVERSHOOT
        start = frame.point(sample_x, sample_y, low)
        span = (frame.z_max - frame.z_min) + 2.0 * TOOL_OVERSHOOT
        try:
            section = surface.section(Part.makeLine(start, start + frame.z_axis * span))
        except Exception:
            self.mating_fallbacks += 1
            return fallback
        heights = []
        for vertex in section.Vertexes:
            height = vertex.Point.dot(frame.z_axis)
            if low <= height <= frame.z_max + TOOL_OVERSHOOT:
                heights.append(height)
        if not heights:
            self.mating_fallbacks += 1
            return fallback
        return min(heights, key=lambda height: abs(height - fallback))

    def note_blind_socket(self, kind, z_mate, depth, into_lower):
        """Record a socket whose floor falls through a cap face.

        A blind socket deeper than the half is thick at its own mating height
        comes out as a through hole, and the boolean succeeds either way - so
        this arithmetic is the only place the difference is visible.
        """
        available = (z_mate - self.frame.z_min if into_lower
                     else self.frame.z_max - z_mate)
        if depth >= available:
            side = "lower" if into_lower else "upper"
            self.breakthroughs.append(
                f"{kind} socket is {depth:.3f} mm deep but the {side} half is "
                f"only {available:.3f} mm thick there: it breaks through the cap "
                f"face instead of stopping blind"
            )

    def _inboard(self, x, y):
        """``(x, y)`` moved MATING_PROBE_INSET toward the block centre."""
        span_x = self.frame.x_mid - x
        span_y = self.frame.y_mid - y
        length = math.hypot(span_x, span_y)
        if length <= MATING_PROBE_INSET:
            return x, y
        scale = MATING_PROBE_INSET / length
        return x + span_x * scale, y + span_y * scale


def _vertices(shape):
    return [vertex.Point for vertex in shape.Vertexes]


def _unit(vector):
    """Normalise, refusing a zero-length direction instead of inventing one."""
    if getattr(vector, "Length", 0.0) <= DIRECTION_MATCH_TOL:
        raise MouldFixtureError(f"direction {vector} has no length")
    return _normalized(vector)


def _is_planar(face):
    try:
        return isinstance(face.Surface, Part.Plane)
    except Exception:
        return False


def _canonical_direction(vector):
    """The unit vector, with its sign pinned by its dominant component.

    Pinning the sign makes a wall's ``+u`` face and its ``-u`` face report the
    same direction, so the four walls collapse to two axes instead of four.
    """
    unit = _unit(vector)
    components = (unit.x, unit.y, unit.z)
    dominant = max(range(3), key=lambda index: abs(components[index]))
    if components[dominant] < 0.0:
        return Vector(-unit.x, -unit.y, -unit.z)
    return unit


def _dedupe_directions(directions):
    unique = []
    for direction in directions:
        if any((direction - existing).Length <= DIRECTION_MATCH_TOL for existing in unique):
            continue
        unique.append(direction)
    return unique


def _wall_normals(shape, points, draw):
    """Normals of the faces on the block boundary that run along the draw.

    A wall plane contains the draw direction, so its normal is perpendicular
    to it. That alone also matches a prismatic cavity wall, which is why the
    plane must additionally sit at an extreme of the block - a cavity wall is
    strictly inside, so it is rejected here rather than trusted.
    """
    found = []
    for face in shape.Faces:
        if not _is_planar(face):
            continue
        normal = _face_midpoint_normal(face)
        if normal is None or abs(normal.dot(draw)) > AXIS_ALIGNMENT_TOL:
            continue
        normal = _canonical_direction(normal)
        offset = face.CenterOfMass.dot(normal)
        projections = [point.dot(normal) for point in points]
        gap = min(abs(offset - min(projections)), abs(offset - max(projections)))
        if gap <= PLANE_OFFSET_TOL:
            found.append(normal)
    return _dedupe_directions(found)


def _canonical_key(vector):
    return (round(vector.x, 6), round(vector.y, 6), round(vector.z, 6))


def block_frame(lower, upper, draw):
    """Recover the stock block's frame from the two halves.

    The in-plane axes come from the halves' own wall faces, so the layout
    follows the block the solver actually built rather than assuming the
    solver's frame convention or a world-axis-aligned box.

    Raises ``MouldFixtureError`` when the halves do not present a block.
    """
    z_axis = _unit(draw)
    points = _vertices(lower) + _vertices(upper)
    if not points:
        raise MouldFixtureError("mould halves have no vertices")
    normals = _dedupe_directions(
        _wall_normals(lower, points, z_axis) + _wall_normals(upper, points, z_axis)
    )
    if not normals:
        raise MouldFixtureError(
            "no block wall face found - the halves do not look like parted "
            "stock, or their faces are not planar"
        )
    if len(normals) > 2:
        raise MouldFixtureError(
            f"found {len(normals)} distinct wall directions, expected at most 2"
        )
    x_axis = min(normals, key=_canonical_key)
    y_axis = _unit(z_axis.cross(x_axis))

    frame = BlockFrame(
        x_axis=x_axis,
        y_axis=y_axis,
        z_axis=z_axis,
        x_min=min(point.dot(x_axis) for point in points),
        x_max=max(point.dot(x_axis) for point in points),
        y_min=min(point.dot(y_axis) for point in points),
        y_max=max(point.dot(y_axis) for point in points),
        z_min=min(point.dot(z_axis) for point in points),
        z_max=max(point.dot(z_axis) for point in points),
    )
    for axis, span in zip("xyz", frame.size):
        if span <= PLANE_OFFSET_TOL:
            raise MouldFixtureError(f"block frame is degenerate along {axis}")
    return frame


def upper_lower(half_a, half_b, draw):
    """Order the halves along the draw direction.

    Returns ``(lower, upper, order_matches_names)``. The names are the
    convention (``MouldHalfA`` is the lower half); a reversal is reported
    rather than silently accepted.
    """
    z_axis = _unit(draw)
    top_a = max(point.dot(z_axis) for point in _vertices(half_a))
    top_b = max(point.dot(z_axis) for point in _vertices(half_b))
    if abs(top_a - top_b) <= PLANE_OFFSET_TOL:
        raise MouldFixtureError("mould halves end at the same height along the draw")
    if top_b > top_a:
        return half_a, half_b, True
    return half_b, half_a, False


def corner_positions(frame, count, inset):
    """``count`` dowel positions on the block corners, inset from the walls."""
    if count < 1 or count > len(_CORNER_ORDER):
        raise MouldFixtureError(
            f"align pin count {count} is outside 1..{len(_CORNER_ORDER)}"
        )
    half_x = 0.5 * (frame.x_max - frame.x_min) - inset
    half_y = 0.5 * (frame.y_max - frame.y_min) - inset
    if half_x <= 0.0 or half_y <= 0.0:
        raise MouldFixtureError(
            f"align pin edge offset {inset:.3f} mm leaves no room inside the block"
        )
    return [
        (frame.x_mid + sign_x * half_x, frame.y_mid + sign_y * half_y)
        for sign_x, sign_y in _CORNER_ORDER[:count]
    ]


def _perimeter_spans(frame, inset):
    """The inset block rectangle as five corner-to-corner spans.

    Wound anticlockwise in the block frame from the middle of the +y edge, so
    walking them at equal arc length gives a stable, reproducible layout. Each
    entry is ``(start, end, inward)`` in block-frame coordinates and
    block-frame unit directions.
    """
    x_lo = frame.x_min + inset
    x_hi = frame.x_max - inset
    y_lo = frame.y_min + inset
    y_hi = frame.y_max - inset
    x_mid = frame.x_mid
    return [
        ((x_mid, y_hi), (x_hi, y_hi), (0.0, -1.0)),
        ((x_hi, y_hi), (x_hi, y_lo), (-1.0, 0.0)),
        ((x_hi, y_lo), (x_lo, y_lo), (0.0, 1.0)),
        ((x_lo, y_lo), (x_lo, y_hi), (1.0, 0.0)),
        ((x_lo, y_hi), (x_mid, y_hi), (0.0, -1.0)),
    ]


def _station_on_span(start, end, inward, fraction):
    x = start[0] + fraction * (end[0] - start[0])
    y = start[1] + fraction * (end[1] - start[1])
    span_x = end[0] - start[0]
    span_y = end[1] - start[1]
    scale = math.hypot(span_x, span_y)
    return PerimeterStation(
        x=x,
        y=y,
        tangent=(span_x / scale, span_y / scale),
        inward=inward,
    )


def _station_at_arc(spans, lengths, arc):
    remaining = arc
    for (start, end, inward), length in zip(spans, lengths):
        if remaining <= length:
            return _station_on_span(start, end, inward, remaining / length)
        remaining -= length
    # Floating-point overshoot at the very end of the walk: snap to the last span.
    start, end, inward = spans[-1]
    return _station_on_span(start, end, inward, 1.0)


def perimeter_stations(frame, count, inset, phase=0.0):
    """``count`` stations equally spaced around the inset block perimeter.

    ``phase`` shifts the whole layout along the perimeter as a fraction of one
    station, which is how the bolt pattern is interleaved with the wedge
    pattern instead of sharing its positions.
    """
    if count < 1:
        raise MouldFixtureError(f"perimeter station count {count} must be positive")
    spans = _perimeter_spans(frame, inset)
    lengths = [
        math.hypot(end[0] - start[0], end[1] - start[1])
        for start, end, _inward in spans
    ]
    total = sum(lengths)
    if total <= PLANE_OFFSET_TOL:
        raise MouldFixtureError(
            f"perimeter inset {inset:.3f} mm leaves no perimeter to lay out on"
        )
    return [
        _station_at_arc(spans, lengths, ((index + phase) / count) * total)
        for index in range(count)
    ]


def _orient_inward(frame, station):
    """The station's block-frame inward pair as a world direction."""
    return frame.x_axis * station.inward[0] + frame.y_axis * station.inward[1]


def _orient_tangent(frame, station):
    """The station's block-frame tangent pair as a world direction."""
    return frame.x_axis * station.tangent[0] + frame.y_axis * station.tangent[1]


def _drill_down(frame, x, y, z_top, diameter, depth):
    """A hole from ``z_top`` running down into the lower half."""
    start = frame.point(x, y, z_top - depth)
    return Part.makeCylinder(diameter / 2.0, depth + TOOL_OVERSHOOT, start,
                             frame.z_axis)


def _drill_up(frame, x, y, z_bottom, diameter, depth):
    """A hole from ``z_bottom`` running up into the upper half."""
    start = frame.point(x, y, z_bottom - TOOL_OVERSHOOT)
    return Part.makeCylinder(diameter / 2.0, depth + TOOL_OVERSHOOT, start,
                             frame.z_axis)


def _drill_through_upper(frame, x, y, z_mate, diameter):
    """A hole from the upper cap face down to the mating surface."""
    start = frame.point(x, y, z_mate - TOOL_OVERSHOOT)
    height = (frame.z_max - z_mate) + 2.0 * TOOL_OVERSHOOT
    return Part.makeCylinder(diameter / 2.0, height, start, frame.z_axis)


def _prism(points, direction):
    return Part.Face(Part.makePolygon(list(points), True)).extrude(direction)


def _wall_notch(frame, station, z_mate, width, height, depth):
    """A rectangular notch cut into the block wall, centred on the mating plane."""
    tangent = _orient_tangent(frame, station)
    inward = _orient_inward(frame, station)
    base = frame.point(station.x, station.y, z_mate) - inward * TOOL_OVERSHOOT
    half_width = tangent * (width / 2.0)
    half_height = frame.z_axis * (height / 2.0)
    corners = [
        base - half_width - half_height,
        base + half_width - half_height,
        base + half_width + half_height,
        base - half_width + half_height,
    ]
    return _prism(corners, inward * (depth + TOOL_OVERSHOOT))


def _parting_wedge(frame, station, z_mate, width, height, depth):
    """A triangular notch in the wall, apex on the mating plane.

    Driven in, a wedge separates the halves. The apex sits *on* the mating
    plane so each half receives a mirror-image half of the notch.
    """
    inward = _orient_inward(frame, station)
    base = frame.point(station.x, station.y, z_mate) - inward * TOOL_OVERSHOOT
    wall_bottom = base - frame.z_axis * (height / 2.0)
    wall_top = base + frame.z_axis * (height / 2.0)
    apex = base + inward * (depth + TOOL_OVERSHOOT)
    shift = _orient_tangent(frame, station) * (width / 2.0)
    triangle = [wall_bottom - shift, wall_top - shift, apex - shift]
    return _prism(triangle, _orient_tangent(frame, station) * width)


def _alignment_tools(mould, params):
    """``(lower_tools, upper_tools, hole_count)`` for the dowel/bush pairs."""
    if not params.enabled:
        return [], [], 0
    if params.pin_half not in PIN_HALVES:
        raise MouldFixtureError(
            f"align pin half must be one of {PIN_HALVES}, not {params.pin_half!r}"
        )
    frame = mould.frame
    pin_tools, bush_tools = [], []
    for x, y in corner_positions(frame, params.count, params.edge_offset):
        z_mate = mould.mating_height(x, y)
        mould.note_blind_socket("align pin", z_mate, params.depth,
                                params.pin_half == "Lower")
        mould.note_blind_socket("align bush", z_mate, params.depth,
                                params.pin_half != "Lower")
        if params.pin_half == "Lower":
            pin_tools.append(_drill_down(frame, x, y, z_mate,
                                         params.pin_diameter, params.depth))
            bush_tools.append(_drill_up(frame, x, y, z_mate,
                                        params.bush_diameter, params.depth))
        else:
            pin_tools.append(_drill_up(frame, x, y, z_mate,
                                       params.pin_diameter, params.depth))
            bush_tools.append(_drill_down(frame, x, y, z_mate,
                                          params.bush_diameter, params.depth))
    holes = len(pin_tools) + len(bush_tools)
    if params.pin_half == "Lower":
        return pin_tools, bush_tools, holes
    return bush_tools, pin_tools, holes


def _clamping_tools(mould, params):
    """``(lower_tools, upper_tools, bolt_holes, notches)``."""
    frame = mould.frame
    lower_tools, upper_tools = [], []
    if params.bolts_enabled:
        for station in perimeter_stations(frame, params.bolt_count,
                                          params.bolt_edge_offset, phase=0.5):
            z_mate = mould.mating_height(station.x, station.y)
            upper_tools.append(_drill_through_upper(
                frame, station.x, station.y, z_mate, params.bolt_hole_diameter))
            mould.note_blind_socket("tapped bolt", z_mate, params.bolt_depth, True)
            lower_tools.append(_drill_down(
                frame, station.x, station.y, z_mate,
                params.bolt_tapped_diameter, params.bolt_depth))
    bolt_holes = len(lower_tools)
    notches = 0
    if params.ears_enabled:
        for station in perimeter_stations(frame, params.ear_count, 0.0, phase=0.25):
            z_mate = mould.mating_height(station.x, station.y)
            notch = _wall_notch(frame, station, z_mate, params.ear_width,
                                params.ear_height, params.ear_depth)
            lower_tools.append(notch)
            upper_tools.append(notch.copy())
            notches += 1
    return lower_tools, upper_tools, bolt_holes, notches


def _port_tools(mould, params):
    """``(lower_tools, upper_tools, bore_count)`` for the wall bores.

    Stations sit on the block walls (no inset) so a bore starts at the wall,
    at a phase that interleaves with the bolts, clamp-ear notches and wedges
    instead of sharing their positions.
    """
    if not params.enabled:
        return [], [], 0
    if params.half not in PORT_HALVES:
        raise MouldFixtureError(
            f"process port half must be one of {PORT_HALVES}, not {params.half!r}"
        )
    frame = mould.frame
    lower_tools, upper_tools = [], []
    for station in perimeter_stations(frame, params.count, 0.0, phase=0.75):
        z_mate = mould.mating_height(station.x, station.y)
        inward = _orient_inward(frame, station)
        for half, sign in (("Lower", -1.0), ("Upper", 1.0)):
            if params.half not in (half, "Both"):
                continue
            centre = frame.point(station.x, station.y,
                                 z_mate + sign * params.offset_from_mating)
            start = centre - inward * TOOL_OVERSHOOT
            bore = Part.makeCylinder(params.diameter / 2.0,
                                     params.depth + TOOL_OVERSHOOT, start, inward)
            (lower_tools if half == "Lower" else upper_tools).append(bore)
    return lower_tools, upper_tools, len(lower_tools) + len(upper_tools)


def _wedge_tools(mould, params):
    """``(tools, count)`` for the parting wedges.

    The notch straddles the mating plane, so the same tool applies to both
    halves and each receives its own half of the triangular void.
    """
    if not params.enabled:
        return [], 0
    tools = [
        _parting_wedge(mould.frame, station, mould.mating_height(station.x, station.y),
                       params.width, params.height, params.depth)
        for station in perimeter_stations(mould.frame, params.count, 0.0, phase=0.0)
    ]
    return tools, len(tools)


def _cut_half(shape, tools):
    return shape.cut(tuple(tools)) if tools else shape


def _cut_is_sound(original, cut):
    if cut.isNull():
        return False, "the boolean cut returned a null shape"
    if len(cut.Solids) < 1:
        return False, f"the boolean cut left {len(cut.Solids)} solids"
    if not cut.isValid():
        return False, "the boolean cut left an invalid shape"
    if cut.Volume > original.Volume + PLANE_OFFSET_TOL:
        return False, (
            f"the boolean cut grew the half from {original.Volume:.6g} to "
            f"{cut.Volume:.6g} mm^3"
        )
    return True, ""


def _base_result():
    return {
        "status": STATUS_WAITING,
        "summary": "Waiting for mould halves.",
        "lower_shape": Part.Shape(),
        "upper_shape": Part.Shape(),
        "alignment_holes": 0,
        "bolt_holes": 0,
        "clamp_notches": 0,
        "port_bores": 0,
        "wedge_count": 0,
        "mating_fallbacks": 0,
        "issues": [],
    }


def _fail(result, reason):
    result["status"] = STATUS_FAIL
    result["summary"] = f"Fixture build failed: {reason}"
    result["issues"].append(reason)
    return result


def _require_solid(name, half, result):
    if half is None or half.isNull():
        _fail(result, f"{name} mould half is null")
        return False
    if len(half.Solids) < 1:
        _fail(result,
              f"{name} mould half is a {half.ShapeType} with no solid to cut "
              f"- the solver left the sewn shell unrepaired")
        return False
    return True


MARGIN_PROPERTY_NAMES = "PartingStockMarginX/Y"

FOOTPRINT_NOTE = (
    "the mould sets an explicit PartingStockFootprint, which is the in-plane "
    f"stock in place of {MARGIN_PROPERTY_NAMES}: the fixtures are not checked "
    "against the margins"
)


def _in_plane_requirements(alignment, clamping, wedges):
    """``(what, needed)`` for each enabled fixture cut in from a block wall.

    Each need is a distance from the wall the fixture is measured from. The
    socket or notch reaches that far into the block, so that much material has
    to stand between the wall and the part for the cut to stay in the stock.
    """
    required = []
    if alignment.enabled:
        radius = 0.5 * max(alignment.pin_diameter, alignment.bush_diameter)
        required.append(("the align pin and bush sockets",
                         alignment.edge_offset + radius))
    if clamping.bolts_enabled:
        radius = 0.5 * max(clamping.bolt_hole_diameter,
                           clamping.bolt_tapped_diameter)
        required.append(("the clamp bolt holes",
                         clamping.bolt_edge_offset + radius))
    if clamping.ears_enabled:
        required.append(("the clamp-ear notches", clamping.ear_depth))
    if wedges.enabled:
        required.append(("the parting wedges", wedges.depth))
    return required


def required_in_plane_margin(alignment, clamping, wedges):
    """The stock the enabled in-plane fixtures need, or 0.0 when none are."""
    needs = [needed for _what, needed
             in _in_plane_requirements(alignment, clamping, wedges)]
    return max(needs, default=0.0)


def margin_issues(margins, alignment, clamping, wedges):
    """Fixtures that need more in-plane stock than the mould declares.

    The margin is measured from the part's bounding box and a cavity does not
    fill its box, so it is a lower bound on the material standing between a
    block wall and the part: a fixture that fits within the margin may still
    reach the part, and only one that does not fit is certainly short of stock.

    Process ports are left out. A port is bored in from the wall in order to
    reach the part, so the margin does not bound it.
    """
    if margins.explicit_footprint:
        return [FOOTPRINT_NOTE]
    available = min(margins.x, margins.y)
    issues = []
    for what, needed in _in_plane_requirements(alignment, clamping, wedges):
        if needed > available:
            issues.append(
                f"{what} need {needed:.3f} mm of stock between the block wall "
                f"and the part, but {MARGIN_PROPERTY_NAMES} are "
                f"{margins.x:.3f}/{margins.y:.3f} mm: raise the margins on the "
                f"mould, or reduce the offsets and sizes on this fixture"
            )
    return issues


def build_fixtures(request):
    """Cut every enabled fixture into both halves.

    Returns a result dict: the two cut shapes, the counts, and a status. A
    mould that cannot carry fixtures at all - a half still a shell, no block
    wall to anchor to - fails with the reason, never a partially cut mould.
    """
    result = _base_result()
    for name, half in (("lower", request.lower), ("upper", request.upper)):
        if not _require_solid(name, half, result):
            return result

    try:
        lower, upper, order_matches = upper_lower(request.lower, request.upper,
                                                  request.draw)
        frame = block_frame(lower, upper, request.draw)
    except MouldFixtureError as exc:
        return _fail(result, exc.reason)
    if not order_matches:
        result["issues"].append(
            "mould half names are reversed against the draw direction; "
            "ordered by geometry"
        )

    mould = MouldBlock(frame=frame, parting_surface=request.parting_surface)
    try:
        pin_lower, pin_upper, align_holes = _alignment_tools(mould, request.alignment)
        clamp_lower, clamp_upper, bolt_holes, notches = _clamping_tools(
            mould, request.clamping)
        port_lower, port_upper, bores = _port_tools(mould, request.ports)
        wedges, wedge_count = _wedge_tools(mould, request.wedges)
    except MouldFixtureError as exc:
        return _fail(result, exc.reason)

    lower_tools = pin_lower + clamp_lower + port_lower + wedges
    upper_tools = pin_upper + clamp_upper + port_upper + [tool.copy() for tool in wedges]
    cut_lower = _cut_half(lower, lower_tools)
    cut_upper = _cut_half(upper, upper_tools)
    for name, original, cut in (("lower", lower, cut_lower),
                                ("upper", upper, cut_upper)):
        sound, why = _cut_is_sound(original, cut)
        if not sound:
            return _fail(result, f"{name} mould half: {why}")

    result.update(
        lower_shape=cut_lower,
        upper_shape=cut_upper,
        alignment_holes=align_holes,
        bolt_holes=bolt_holes,
        clamp_notches=notches,
        port_bores=bores,
        wedge_count=wedge_count,
        mating_fallbacks=mould.mating_fallbacks,
    )
    result["issues"].extend(mould.breakthroughs)
    if request.stock_margins is not None:
        result["issues"].extend(
            margin_issues(request.stock_margins, request.alignment,
                          request.clamping, request.wedges)
        )
    result["status"] = STATUS_READY
    result["summary"] = _summary(result, frame)
    return result


def _summary(result, frame):
    width, depth, height = frame.size
    parts = [
        f"block {width:.3f} x {depth:.3f} x {height:.3f} mm",
        f"alignment holes {result['alignment_holes']}",
        f"bolt holes {result['bolt_holes']}",
        f"clamp notches {result['clamp_notches']}",
        f"process bores {result['port_bores']}",
        f"parting wedges {result['wedge_count']}",
    ]
    if result["mating_fallbacks"]:
        parts.append(
            f"{result['mating_fallbacks']} position(s) measured from the block "
            f"mid-height: no parting surface there"
        )
    for issue in result["issues"]:
        parts.append(issue)
    return "Fixtures ready: " + ", ".join(parts)
