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
from itertools import combinations
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

# How finely the bolt pattern's phase is searched for one that clears the
# alignment sockets and the skirt.
BOLT_PHASE_SAMPLES = 72

# A wedge slot runs the whole wall, and the interface it straddles varies along
# that wall, so a run is cut as segments about this long, each measured at its
# own midpoint. Shorter segments follow the parting geometry more closely; every
# seam between them is a step the shop floor dresses.
WEDGE_SLOT_SEGMENT_MM = 25.0

# Every hole keeps this multiple of its radius of gap from every other hole and
# from both edges of the skirt: the part outline inboard, the block wall
# outboard. A clear diameter of web is what keeps a socket from breaking into
# the cavity or the wall, and what leaves the material between two holes
# machinable.
SKIRT_CLEARANCE_FACTOR = 2.0

PIN_OFFSET_PROPERTY = "PinEdgeOffset"
BOLT_OFFSET_PROPERTY = "BoltEdgeOffset"

# Two fixtures cut into the same half count as interfering when they share this
# much material. Above the noise of two solids that merely touch.
INTERFERENCE_VOLUME_TOL = 1.0e-3

ALIGN_KIND = "the align pin and bush sockets"
CLAMP_KIND = "the clamp bolt holes and clamp-ear notches"
PORT_KIND = "the process ports"
WEDGE_KIND = "the parting wedges"

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

    def local(self, world):
        """The block coordinates of a world point.

        The axes are unit and mutually perpendicular and the extents are signed
        distances from the world origin, so ``point`` is a projection and this is
        its inverse: a dot with each axis.
        """
        return (world.dot(self.x_axis), world.dot(self.y_axis),
                world.dot(self.z_axis))

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
    # 3R for the default bush: the socket keeps 2R of gap from the wall, so a
    # centre any closer to it breaks the skirt clearance rule.
    edge_offset: float = 24.0
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
    # 3R for the 11 mm clearance hole: the socket keeps 2R of gap from the wall,
    # so a centre any closer to it breaks the skirt clearance rule.
    bolt_edge_offset: float = 18.0
    ears_enabled: bool = False
    ear_count: int = 4
    ear_width: float = 30.0
    ear_height: float = 15.0
    ear_depth: float = 12.0


@dataclass(frozen=True)
class WedgeParams:
    """A triangular slot along each wall, straddling the parting plane.

    A driven wedge separates the halves, so every wall carries one slot running
    its full length less ``corner_standoff`` at each end. The corners are left
    intact: they hold the alignment sockets and take the blow if a wedge is
    driven too hard.
    """

    enabled: bool = True
    corner_standoff: float = 50.0
    height: float = 12.0
    # 11 mm keeps the slot's reach (plus the tool overshoot) clear of the clamp
    # bolt holes at their default edge offset: 11 + 1 against 18 - 5.5.
    depth: float = 11.0


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
    """A recovered block frame, the parting surface in it, and its lower half.

    ``mating_fallbacks`` counts how many fixture positions had to fall back to
    the block mid-height because neither the parting surface nor the half gave a
    crossing, so the approximation is reported rather than hidden.
    """

    frame: BlockFrame
    parting_surface: object = None
    lower: object = None
    mating_fallbacks: int = 0
    breakthroughs: list = field(default_factory=list)
    _mating_cache: dict = field(default_factory=dict, repr=False)

    def mating_height(self, x, y):
        """The z at which the two halves meet above ``(x, y)``.

        The interface is not one plane: it varies with position, so the height
        is measured per position, never assumed flat.

        Two sources, in order. The parting surface, when the probe line crosses
        it, gives the height directly. Otherwise the lower half does: its top
        face *is* the interface, so sectioning it carries the same variation
        and needs no assumption about how the solver reports its parting
        geometry - a part line carried as a bare edge loop cannot be crossed by
        a probe at all, because a line through the loop's interior meets the
        surface the loop bounds, never one of the edges. A position where
        neither gives a crossing falls back to the block mid-height and is
        counted in ``mating_fallbacks``.

        The sample is taken ``MATING_PROBE_INSET`` inboard of the position, for
        the wall-adjacent fixtures described there.
        """
        key = (round(x, 6), round(y, 6))
        if key in self._mating_cache:
            return self._mating_cache[key]
        height = self._measure_mating_height(x, y)
        self._mating_cache[key] = height
        return height

    def _measure_mating_height(self, x, y):
        """One measurement of the interface above ``(x, y)``."""
        frame = self.frame
        fallback = frame.z_mid
        sample_x, sample_y = self._inboard(x, y)
        low = frame.z_min - TOOL_OVERSHOOT
        high = frame.z_max + TOOL_OVERSHOOT
        start = frame.point(sample_x, sample_y, low)
        line = Part.makeLine(start, start + frame.z_axis * (high - low))

        crossed = self._crossings(self.parting_surface, line, low, high)
        if crossed:
            return min(crossed, key=lambda height: abs(height - fallback))
        crossed = self._crossings(self.lower, line, low, high)
        if crossed:
            # The lower half's top face, which is the interface itself.
            return max(crossed)
        self.mating_fallbacks += 1
        return fallback

    def _crossings(self, shape, line, low, high):
        """The draw-axis heights where ``line`` meets ``shape`` inside the block."""
        if shape is None or shape.isNull():
            return []
        try:
            section = shape.section(line)
        except Exception:
            return []
        return [vertex.Point.dot(self.frame.z_axis)
                for vertex in section.Vertexes
                if low <= vertex.Point.dot(self.frame.z_axis) <= high]

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


def _all_walls(frame):
    """The four block walls, wound anticlockwise in the block frame.

    Each entry is ``((mid_x, mid_y), (inward_x, inward_y), length)``: the wall's
    midpoint, the direction into the block, and how far the wall runs along its
    own span. A wall's length is the span it runs along, so the pair with the
    shorter span is the pair whose own run is shortest.
    """
    span_x = frame.x_max - frame.x_min
    span_y = frame.y_max - frame.y_min
    return [((frame.x_mid, frame.y_max), (0.0, -1.0), span_x),
            ((frame.x_max, frame.y_mid), (-1.0, 0.0), span_y),
            ((frame.x_mid, frame.y_min), (0.0, 1.0), span_x),
            ((frame.x_min, frame.y_mid), (1.0, 0.0), span_y)]


def _shortest_walls(frame):
    """The opposite pair of block walls that runs the shorter way."""
    walls = _all_walls(frame)
    return walls[0::2] if walls[0][2] <= walls[1][2] else walls[1::2]


def _wall_runs(frame, standoff):
    """The four walls as runs trimmed ``standoff`` back from each corner.

    As ``(station, length)`` with the station at the middle of the run, so a
    slot cut about it runs the wall's full length less the standoff at either
    end. A standoff that would consume the wall is refused rather than cut to
    nothing.
    """
    if standoff < 0.0:
        raise MouldFixtureError(
            f"wedge corner standoff {standoff:.3f} mm is negative")
    runs = []
    for (mid_x, mid_y), inward, span in _all_walls(frame):
        length = span - 2.0 * standoff
        if length <= PLANE_OFFSET_TOL:
            raise MouldFixtureError(
                f"wedge corner standoff {standoff:.3f} mm leaves none of a "
                f"{span:.3f} mm wall left to cut")
        tangent = (1.0, 0.0) if inward[0] == 0.0 else (0.0, 1.0)
        runs.append((PerimeterStation(x=mid_x, y=mid_y, tangent=tangent,
                                      inward=inward), length))
    return runs


def _port_stations(frame, count):
    """``count`` port positions along the block's two shortest walls.

    A port is bored in from a wall face towards the work, so it belongs on a
    wall: its stations are spread along the shortest pair of sides and centred
    there. Equal spacing around the whole perimeter is wrong for this, because
    the fractions it lands on are span boundaries - the corners - which is
    where the two-port default used to put them.

    ``count`` ports are shared between the pair, the first wall taking the odd
    one, and each wall's own ports are centred on it.
    """
    if count < 1:
        raise MouldFixtureError(f"port count {count} must be positive")
    walls = _shortest_walls(frame)
    share = [count // len(walls)] * len(walls)
    for index in range(count % len(walls)):
        share[index] += 1
    stations = []
    for ((mid_x, mid_y), inward, length), per_wall in zip(walls, share):
        tangent = (1.0, 0.0) if inward[0] == 0.0 else (0.0, 1.0)
        for slot in range(per_wall):
            along = ((slot + 0.5) / per_wall - 0.5) * length
            stations.append(PerimeterStation(
                x=mid_x + tangent[0] * along,
                y=mid_y + tangent[1] * along,
                tangent=tangent,
                inward=inward,
            ))
    return stations


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


def _parting_wedge(frame, station, z_mate, length, height, depth):
    """A triangular slot along the wall, apex on the mating plane.

    Driven in, a wedge separates the halves. The apex sits *on* the mating
    plane so each half receives a mirror-image half of the notch, and the slot
    runs ``length`` along the wall, centred on the station.
    """
    inward = _orient_inward(frame, station)
    tangent = _orient_tangent(frame, station)
    base = frame.point(station.x, station.y, z_mate) - inward * TOOL_OVERSHOOT
    wall_bottom = base - frame.z_axis * (height / 2.0)
    wall_top = base + frame.z_axis * (height / 2.0)
    apex = base + inward * (depth + TOOL_OVERSHOOT)
    shift = tangent * (length / 2.0)
    triangle = [wall_bottom - shift, wall_top - shift, apex - shift]
    return _prism(triangle, tangent * length)


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


def _bolt_tools(mould, params, phase):
    """``(lower, upper, stations)`` for the bolt pattern at one phase.

    Building a candidate pattern is cheap because the mating height is cached,
    which is what lets the phase search try patterns against each other. The
    blind-socket notes are left to the caller, so a candidate that is rejected
    leaves nothing behind.
    """
    frame = mould.frame
    lower, upper, stations = [], [], []
    for station in perimeter_stations(frame, params.bolt_count,
                                      params.bolt_edge_offset, phase=phase):
        stations.append(station)
        z_mate = mould.mating_height(station.x, station.y)
        upper.append(_drill_through_upper(frame, station.x, station.y, z_mate,
                                          params.bolt_hole_diameter))
        lower.append(_drill_down(frame, station.x, station.y, z_mate,
                                 params.bolt_tapped_diameter, params.bolt_depth))
    return lower, upper, stations


def _clashes(tools, obstacles):
    """Whether any of ``tools`` shares material with any of ``obstacles``."""
    for tool in tools:
        for obstacle in obstacles:
            if _shared_volume(tool, obstacle) > INTERFERENCE_VOLUME_TOL:
                return True
    return False


def _bolt_station_phase(mould, params, pin_zones, segments, obstacles=()):
    """The equally-spaced perimeter phase the bolt pattern can be laid out at.

    The bolt pattern is one phase around the block, so a single shift moves
    every bolt and the stations stay equally spaced; only where the pattern
    starts is chosen. Candidates are tried nearest the intended 0.5 first, and
    the first that both obeys the skirt clearance rule and cuts into no fixture
    already placed - a wedge, a bore, an ear - wins. Shifting the pattern to
    clear the pins is exactly what pushed it into the wedges before this.

    When no phase is clear, the one with the most room is taken and the
    shortfall is reported rather than hidden.

    ``pin_zones`` is ``(x, y, radius)`` per socket and ``segments`` the part
    outline, both in frame coordinates. ``obstacles`` are the tools already
    placed.
    """
    if params.bolt_count < 1:
        return 0.5
    frame = mould.frame
    bolt_radius = 0.5 * max(params.bolt_hole_diameter, params.bolt_tapped_diameter)
    candidates = sorted((step / float(BOLT_PHASE_SAMPLES)
                         for step in range(BOLT_PHASE_SAMPLES)),
                        key=lambda phase: abs(phase - 0.5))
    widest = None
    ruled = None
    for phase in candidates:
        lower, upper, stations = _bolt_tools(mould, params, phase)
        surplus = min(_surplus(frame, segments, station.x, station.y, bolt_radius,
                               pin_zones)
                      for station in stations)
        if surplus < 0.0:
            if widest is None or surplus > widest[0]:
                widest = (surplus, phase)
            continue
        if _clashes(lower + upper, obstacles):
            # A parting wedge slot runs the whole wall, so some phases obey the
            # clearance rule and still touch it, and no phase can miss it. Keep
            # the best of those rather than dropping to one that breaks the
            # rule outright; the clash itself is reported as interference.
            if ruled is None or surplus > ruled[0]:
                ruled = (surplus, phase)
            continue
        return phase
    if ruled is not None:
        return ruled[1]
    return widest[1] if widest is not None else 0.5


def _required_gap(radius):
    """The gap a hole of ``radius`` keeps from the skirt and from any other hole."""
    return SKIRT_CLEARANCE_FACTOR * radius


def _point_segment_distance(px, py, ax, ay, bx, by):
    """Distance from ``(px, py)`` to the segment AB, in the block plane."""
    span_x, span_y = bx - ax, by - ay
    length_squared = span_x * span_x + span_y * span_y
    if length_squared <= 0.0:
        return math.hypot(px - ax, py - ay)
    along = ((px - ax) * span_x + (py - ay) * span_y) / length_squared
    along = max(0.0, min(1.0, along))
    return math.hypot(px - (ax + along * span_x), py - (ay + along * span_y))


def _outline_segments(frame, part_line):
    """The skirt's inner edge, as ``(ax, ay, bx, by)`` in the block plane.

    That edge is the part line: it bounds the cavity, so its projection into the
    block plane is where the part begins. The block walls are the outer edge.
    """
    if part_line is None or part_line.isNull():
        return []
    segments = []
    for edge in part_line.Edges:
        vertices = edge.Vertexes
        if not vertices:
            continue
        first, last = vertices[0].Point, vertices[-1].Point
        ax, ay = frame.local(first)[:2]
        bx, by = frame.local(last)[:2]
        segments.append((ax, ay, bx, by))
    return segments


def _skirt_gaps(frame, segments, x, y, radius):
    """``(wall, outline)`` gaps for a hole of ``radius`` at ``(x, y)``.

    Edge to edge: from the hole's own edge out to the block wall, and in to the
    part outline. ``outline`` is ``None`` when the part line is not known, which
    is not the same as a clear one.
    """
    wall = min(x - frame.x_min, frame.x_max - x,
               y - frame.y_min, frame.y_max - y) - radius
    gaps = [_point_segment_distance(x, y, *segment) - radius
            for segment in segments]
    return wall, (min(gaps) if gaps else None)


def _surplus(frame, segments, x, y, radius, neighbours=()):
    """How much more gap a hole at ``(x, y)`` keeps than the rule demands.

    Negative means it breaks the rule. ``neighbours`` is ``(x, y, radius)`` of
    the other holes it has to clear as well.
    """
    needed = _required_gap(radius)
    wall, outline = _skirt_gaps(frame, segments, x, y, radius)
    surplus = wall - needed
    if outline is not None:
        surplus = min(surplus, outline - needed)
    for other_x, other_y, other_radius in neighbours:
        pair_gap = (math.hypot(x - other_x, y - other_y)
                    - (radius + other_radius))
        surplus = min(surplus,
                      pair_gap - _required_gap(max(radius, other_radius)))
    return surplus


def _clearance_issues(frame, segments, holes):
    """Holes keeping less than a diameter of gap from the skirt or each other.

    ``holes`` is ``(label, offset_property, x, y, radius)``. A violation names
    the property to raise, because the fix is a wider offset or a smaller hole,
    never a thinner web.
    """
    issues = []
    for label, offset_property, x, y, radius in holes:
        needed = _required_gap(radius)
        wall, outline = _skirt_gaps(frame, segments, x, y, radius)
        if wall < needed:
            issues.append(
                f"{label} keep {wall:.3f} mm to the block wall but need "
                f"{needed:.3f} mm (2 x the {radius:.3f} mm radius): raise "
                f"{offset_property}, or reduce the socket diameter"
            )
        if outline is not None and outline < needed:
            issues.append(
                f"{label} keep {outline:.3f} mm to the part outline but need "
                f"{needed:.3f} mm (2 x the {radius:.3f} mm radius): raise "
                f"{offset_property}, or reduce the socket diameter"
            )
    for (label_a, _property_a, xa, ya, ra), (label_b, _property_b, xb, yb, rb) \
            in combinations(holes, 2):
        gap = math.hypot(xa - xb, ya - yb) - (ra + rb)
        needed = _required_gap(max(ra, rb))
        if gap < needed:
            issues.append(
                f"{label_a} and {label_b} are {gap:.3f} mm apart at their "
                f"edges but need {needed:.3f} mm: move the offsets further "
                f"apart, or reduce the counts"
            )
    return issues


def _boxes_overlap(first, second):
    """Whether two bounding boxes meet, as a cheap pre-filter."""
    return (first.XMin <= second.XMax and second.XMin <= first.XMax
            and first.YMin <= second.YMax and second.YMin <= first.YMax
            and first.ZMin <= second.ZMax and second.ZMin <= first.ZMax)


def _shared_volume(first, second):
    """How much material two tool solids share, ``0.0`` when they miss."""
    if not _boxes_overlap(first.BoundBox, second.BoundBox):
        return 0.0
    try:
        return first.common(second).Volume
    except Exception:
        return 0.0


def _interference_issues(labeled_tools):
    """Overlapping pairs of fixtures cut into the same half.

    Two fixtures sharing material weaken the block and can break into each
    other's sockets, so a clash is reported rather than cut silently. Fixtures
    are compared only within one half: the clearance hole and the tapped hole
    of a bolt are meant to line up across the mating plane, not to avoid each
    other.
    """
    issues = []
    for (label_a, tool_a), (label_b, tool_b) in combinations(labeled_tools, 2):
        overlap = _shared_volume(tool_a, tool_b)
        if overlap > INTERFERENCE_VOLUME_TOL:
            issues.append(
                f"{label_a} and {label_b} share {overlap:.3f} mm^3: move the "
                f"offsets further apart, or reduce the counts"
            )
    return issues


def _pin_zones(frame, params):
    """``(x, y, radius)`` per alignment socket, in frame coordinates.

    Read from the positions rather than the built sockets: the corner pattern is
    what a fixture has to clear, and a socket's own solid would only repeat it
    in a frame that has to be mapped back.
    """
    if not params.enabled:
        return []
    radius = 0.5 * max(params.pin_diameter, params.bush_diameter)
    return [(x, y, radius)
            for x, y in corner_positions(frame, params.count, params.edge_offset)]


def _labeled(tools, label):
    """``[(label, tool)]``, so an interference report can name the fixtures."""
    return [(label, tool) for tool in tools]


def _hole_audit(request, pin_zones, bolt_stations):
    """``(label, offset_property, x, y, radius)`` for every hole in the layout.

    The sockets at a station are a pin in one half and a bush in the other, so
    the larger of the two radii is what the site has to clear with.
    """
    holes = [(ALIGN_KIND, PIN_OFFSET_PROPERTY, x, y, radius)
             for x, y, radius in pin_zones]
    if request.clamping.bolts_enabled:
        radius = 0.5 * max(request.clamping.bolt_hole_diameter,
                           request.clamping.bolt_tapped_diameter)
        holes.extend((CLAMP_KIND, BOLT_OFFSET_PROPERTY, station.x, station.y,
                      radius) for station in bolt_stations)
    return holes


def _clamping_tools(mould, params, pin_zones=(), segments=(), obstacles=()):
    """``(lower_tools, upper_tools, bolt_holes, notches, bolt_stations)``.

    The ears are placed first so the bolt pattern can be laid out around them
    rather than the other way round: only the bolt phase is free to move.
    """
    frame = mould.frame
    lower_tools, upper_tools, bolt_stations = [], [], []
    notches = 0
    if params.ears_enabled:
        for station in perimeter_stations(frame, params.ear_count, 0.0, phase=0.25):
            z_mate = mould.mating_height(station.x, station.y)
            notch = _wall_notch(frame, station, z_mate, params.ear_width,
                                params.ear_height, params.ear_depth)
            lower_tools.append(notch)
            upper_tools.append(notch.copy())
            notches += 1
    bolt_holes = 0
    if params.bolts_enabled:
        phase = _bolt_station_phase(
            mould, params, pin_zones, segments,
            tuple(obstacles) + tuple(lower_tools) + tuple(upper_tools))
        bolt_lower, bolt_upper, bolt_stations = _bolt_tools(mould, params, phase)
        for station in bolt_stations:
            mould.note_blind_socket("tapped bolt",
                                    mould.mating_height(station.x, station.y),
                                    params.bolt_depth, True)
        lower_tools.extend(bolt_lower)
        upper_tools.extend(bolt_upper)
        bolt_holes = len(bolt_lower)
    return lower_tools, upper_tools, bolt_holes, notches, bolt_stations


def _port_tools(mould, params):
    """``(lower_tools, upper_tools, bore_count, specs)`` for the wall bores.

    Stations sit on the middle of the block's two shortest walls, so a bore
    starts at a wall face and runs in towards the work. ``specs`` is
    ``(station, radius, half)`` for each, which is what a parting wedge slot
    needs to keep out of its way.
    """
    if not params.enabled:
        return [], [], 0, []
    if params.half not in PORT_HALVES:
        raise MouldFixtureError(
            f"process port half must be one of {PORT_HALVES}, not {params.half!r}"
        )
    frame = mould.frame
    lower_tools, upper_tools = [], []
    specs = []
    for station in _port_stations(frame, params.count):
        specs.append((station, params.diameter / 2.0, params.half))
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
    return lower_tools, upper_tools, len(lower_tools) + len(upper_tools), specs


def _slot_keepouts(station, ports):
    """Along-wall spans a slot must leave uncut, as distances from its centre.

    A bore entering the same wall would break into the slot, so the slot is
    interrupted over it. The bore keeps ``SKIRT_CLEARANCE_FACTOR`` of its own
    radius of gap from the slot's end - the same web the hole rule asks for
    between two holes - so the keep-out reaches ``radius`` to the bore's edge
    and a further ``2 * radius`` of web beyond it.
    """
    keepouts = []
    for port_station, radius, _half in ports:
        if any(abs(port_station.inward[index] - station.inward[index]) > 1e-9
               for index in (0, 1)):
            continue
        along = ((port_station.x - station.x) * station.tangent[0]
                 + (port_station.y - station.y) * station.tangent[1])
        reach = radius + _required_gap(radius)
        keepouts.append((along - reach, along + reach))
    return keepouts


def _subtract_keepouts(span, keepouts):
    """``span`` less every keep-out, as the remaining sub-spans."""
    spans = [span]
    for low, high in keepouts:
        remaining = []
        for start, end in spans:
            if high <= start or low >= end:
                remaining.append((start, end))
                continue
            if low > start:
                remaining.append((start, min(low, end)))
            if high < end:
                remaining.append((max(high, start), end))
        spans = remaining
    return [(start, end) for start, end in spans
            if end - start > PLANE_OFFSET_TOL]


def _slot_segments(mould, station, start, end, params):
    """The tools covering ``start``..``end`` of one wall, measured per piece.

    Each piece is measured at its own midpoint, so the slot follows the parting
    geometry rather than one plane across the wall.
    """
    length = end - start
    if length <= PLANE_OFFSET_TOL:
        return []
    segments = max(1, int(math.ceil(length / WEDGE_SLOT_SEGMENT_MM)))
    piece = length / segments
    tools = []
    for index in range(segments):
        along = start + (index + 0.5) * piece
        segment = PerimeterStation(
            x=station.x + station.tangent[0] * along,
            y=station.y + station.tangent[1] * along,
            tangent=station.tangent,
            inward=station.inward,
        )
        tools.append(_parting_wedge(
            mould.frame, segment,
            mould.mating_height(segment.x, segment.y),
            piece, params.height, params.depth))
    return tools


def _wedge_tools(mould, params, ports=()):
    """``(lower_tools, upper_tools, slot_count)`` for the parting wedge slots.

    One slot per wall, running the wall's full length less the corner standoff,
    and interrupted over any process port bored into that same wall - in the
    half that port serves, because a bore entering there would otherwise break
    into the slot. The notch straddles the mating plane, so each half receives
    its own share of the triangular void.
    """
    if not params.enabled:
        return [], [], 0
    runs = _wall_runs(mould.frame, params.corner_standoff)
    lower_tools, upper_tools = [], []
    for station, length in runs:
        full = (-length / 2.0, length / 2.0)
        for half, tools in (("Lower", lower_tools), ("Upper", upper_tools)):
            keepouts = _slot_keepouts(
                station, [port for port in ports if port[2] in (half, "Both")])
            for start, end in _subtract_keepouts(full, keepouts):
                tools.extend(_slot_segments(mould, station, start, end, params))
    return lower_tools, upper_tools, len(runs)


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
        "bolt_stations": [],
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

    mould = MouldBlock(frame=frame, parting_surface=request.parting_surface,
                       lower=lower)
    try:
        pin_zones = _pin_zones(frame, request.alignment)
        segments = _outline_segments(frame, request.parting_surface)
        pin_lower, pin_upper, align_holes = _alignment_tools(mould, request.alignment)
        port_lower, port_upper, bores, port_specs = _port_tools(mould, request.ports)
        wedge_lower, wedge_upper, wedge_count = _wedge_tools(
            mould, request.wedges, port_specs)
        # The bolts are placed last, around everything already in the block.
        clamp_lower, clamp_upper, bolt_holes, notches, bolt_stations = _clamping_tools(
            mould, request.clamping, pin_zones, segments,
            tuple(pin_lower) + tuple(pin_upper) + tuple(port_lower)
            + tuple(port_upper) + tuple(wedge_lower) + tuple(wedge_upper))
    except MouldFixtureError as exc:
        return _fail(result, exc.reason)

    lower_tools = pin_lower + clamp_lower + port_lower + wedge_lower
    upper_tools = pin_upper + clamp_upper + port_upper + wedge_upper
    # Each half is checked on its own: a bolt's clearance hole and its tapped
    # hole are meant to line up across the mating plane, and a wedge slot is
    # interrupted in the half a port serves but not in the other.
    result["issues"].extend(_clearance_issues(
        frame, segments, _hole_audit(request, pin_zones, bolt_stations)))

    for half_tools in ((_labeled(pin_lower, ALIGN_KIND)
                        + _labeled(clamp_lower, CLAMP_KIND)
                        + _labeled(port_lower, PORT_KIND)
                        + _labeled(wedge_lower, WEDGE_KIND)),
                       (_labeled(pin_upper, ALIGN_KIND)
                        + _labeled(clamp_upper, CLAMP_KIND)
                        + _labeled(port_upper, PORT_KIND)
                        + _labeled(wedge_upper, WEDGE_KIND))):
        result["issues"].extend(_interference_issues(half_tools))
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
        bolt_stations=[(station.x, station.y) for station in bolt_stations],
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
