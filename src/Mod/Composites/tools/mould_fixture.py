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
from FreeCAD import Placement, Rotation, Vector
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

# A port is placed where the part comes nearest its wall, so the search walks
# the wall and the heights that clear the mating plane. The part's bounding box
# touches each wall face within the stock margin, so the nearest point on a wall
# is within that margin of it: a port placed this way cannot be a long bore, and
# one that still cannot reach the part is reported rather than cut.
PORT_STATION_SAMPLES = 9
PORT_HEIGHT_STEP_MM = 5.0
PORT_TARGET_STEP_MM = 10.0
PORT_FINE_STEP_MM = 1.0
PORT_FINE_MM = 12.0
PORT_SEARCH_SPAN = 0.5

# How much longer than the stock margin a wall bore may be before it is judged
# not to be aimed at the part at all. The part's bounding box touches each wall
# face within that margin, so a bore from the wall to the part is about that
# long; one much longer has missed the near side and is running to the part's
# far end.
PORT_AIM_SLACK_MM = 10.0

# How far past a crossing to look when deciding whether it opened into the
# cavity. Small, because the cavity's surface can be nearly parallel to a bore.
PORT_CROSSING_STEP_MM = 0.5

# How far inside the block a crossing has to be to count as the cavity. A ray
# that grazes one of the block's own faces is not in the material, and reading
# that glancing crossing as the part is what put a port's target on the cap face
# and collapsed the bores to the tool overshoot.
PORT_STOCK_INSET_MM = 2.0

# Corner pattern order. Fixed so a given count always lands on the same
# corners, whatever order OCCT enumerates the half's faces in.
_CORNER_ORDER = ((-1.0, -1.0), (1.0, 1.0), (-1.0, 1.0), (1.0, -1.0))

# How finely the bolt pattern's phase is searched for one that clears the
# alignment sockets and the skirt.
BOLT_PHASE_SAMPLES = 72

# A wedge slot runs the whole wall, and the interface it straddles varies along
# that wall, so a run is lofted through a section about this far apart, each
# taken on the interface itself. Shorter samples follow the parting geometry
# more closely. The sections are facets of one slot, so the apex rides the part
# line and the seams between them are not steps.
WEDGE_SLOT_SAMPLE_MM = 10.0

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
SEAL_KIND = "the O-ring seal groove"

# The seal groove. An O-ring seals by being squeezed, so its groove is cut
# wider than the cord it holds and shallower than it: the ring compresses into
# the gap left between the groove floor and the face it seals against. The cord
# is the number the shop has, so the width and depth follow from it here.
SEAL_GROOVE_WIDTH_FACTOR = 1.25
SEAL_GROOVE_DEPTH_FACTOR = 0.75

# A corner in the groove's path is rounded, never mitred. An elastomer ring
# cannot be seated round a sharp turn, and a ruled loft between the two
# stations either side of a block corner leaves exactly that. Three cord
# diameters is a comfortable bend for a cord of that size - one is the tightest
# it is normally asked to take - so the groove is laid out at three unless the
# caller names its own radius, and taken down to the largest the strip's
# corners carry where even that does not fit.
SEAL_GROOVE_CORNER_FACTOR = 3.0

# A corner shallower than this is left in the run: rounding it would be
# invisible and would only add sections to the loft.
SEAL_GROOVE_STRAIGHT_TOL_DEG = 1.0

# A path frame is kept only where the ruled loft cannot already reach it. Within
# this deviation the dropped section lies on the loft's own interpolation, so
# dropping it leaves the cut unchanged to a tolerance far finer than the
# tessellation of the halves it is cut into. A strip walked at the part line's
# own density has hundreds of such frames - a 261 mm part gave 523 - and every
# one of them is a face in the loft and again in the boolean that cuts it.
SEAL_GROOVE_PATH_TOL_MM = 0.01

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
    # A matched round-interlock pair has the SAME outer diameter in both halves,
    # unlike a dowel-and-bush pair whose two seats differ. These are the A1-10
    # round taper interlock: D = 10 into each half, 10 mm of engagement.
    pin_diameter: float = 10.0
    bush_diameter: float = 10.0
    depth: float = 10.0
    # 3R: a seat keeps 2R of gap from the wall, so a centre any closer than that
    # breaks the skirt clearance rule. R is 5 here, so 15 mm is the minimum and
    # 24 mm keeps the seats well inboard of the block edge.
    edge_offset: float = 24.0
    pin_half: str = "Lower"
    # The seat's extra cuts, all off by default so a plain dowel socket costs
    # nothing. A commercial locating part is not a plain dowel: its flange or
    # shoulder seats on a counterbore, and its blind seat is a trapped volume
    # that has to be vented to atmosphere or it outgasses under vacuum.
    shoulder_diameter: float = 0.0
    shoulder_depth: float = 0.0
    vent_diameter: float = 0.0
    # A screw-fixed part is reached from the back of the block, which for a seat
    # opening at the mating face is the cap face. The clearance hole that lets
    # the screw through also vents the seat, so the vent above is only needed for
    # a part with no back screw. 5.5 mm clears an M5, and the head counterbore
    # clears an M5 socket head (8.5 mm across, 5.0 tall).
    screw_diameter: float = 5.5
    screw_head_diameter: float = 9.5
    screw_head_depth: float = 5.5


@dataclass(frozen=True)
class ClampingParams:
    """Through-bolts with a nut on top, plus wall notches a clamp can grip.

    A bolt enters the lower cap face - recessed into it, so the half still lands
    flat - passes up through both halves and is nutted on the upper cap face.
    The nut needs no recess, which is why the counterbore is on the lower face
    only.
    """

    bolts_enabled: bool = True
    bolt_count: int = 4
    # 11 mm clears an M10, whose socket head is 16 mm across and 10 mm tall.
    bolt_hole_diameter: float = 11.0
    bolt_head_diameter: float = 17.0
    bolt_head_depth: float = 10.5
    # 3R for the 17 mm head counterbore: a bolt keeps 2R of gap from the wall,
    # so a centre any closer to it breaks the skirt clearance rule.
    bolt_edge_offset: float = 26.0
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
class SealGrooveParams:
    """A groove for an O-ring, centred in the level strip of a levelled skirt.

    The strip is what a `fixed` levelled skirt leaves flat between the
    transition and the wall base, and it is the only land outside the cavity a
    seal can be cut into. The groove is cut into the lower half alone: the ring
    sits in it and the upper half's flat face closes over it. Its size comes
    from the cord, because that is the number the shop has - see
    ``seal_groove_width`` and ``seal_groove_depth``.
    """

    # Off by default, unlike every other kind: a groove needs the mould's level
    # strip, which only a `fixed` levelled skirt leaves flat, so a mould that
    # never asked for levelling must not start failing its build.
    enabled: bool = False
    cord_diameter: float = 3.0
    # Zero asks for the cord's own derivation. The shop normally knows the ring
    # and not the groove, so the cord stays the primary number and these are the
    # override for a table that says otherwise.
    width: float = 0.0
    depth: float = 0.0
    # Zero derives it from the cord, at one cord diameter.
    corner_radius: float = 0.0


@dataclass(frozen=True)
class PortParams:
    """Bores drilled in from a block wall: vacuum, ejector, thermocouple.

    A bore is drilled perpendicular to the wall it enters, offset clear of the
    mating plane so it lies in one half. Its depth is not asked for: the bore is
    sized to reach the part, which is the whole point of it. A port that stopped
    inside the stock would be a blind pocket, and the depth that reaches the
    part is a property of the mould being fixtured, not of the fixture.
    """

    enabled: bool = True
    count: int = 2
    diameter: float = 6.0
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
    seal_groove: SealGrooveParams = field(default_factory=SealGrooveParams)
    # The mould's levelling transition, in mm: the inboard part of the skirt that
    # the level strip does not cover, so stock a groove centred in the strip
    # cannot be laid out in.
    seal_transition_mm: float = 0.0
    # The two rings bounding the mould's level strip, as shapes: the inboard
    # edge of the flat strip and the wall base. They carry the same stations in
    # the same order, so the groove is centred on them station for station.
    level_strip_in: object = None
    level_strip_out: object = None
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
    upper: object = None
    mating_fallbacks: int = 0
    breakthroughs: list = field(default_factory=list)
    unreached_ports: list = field(default_factory=list)
    port_warnings: list = field(default_factory=list)
    port_notes: list = field(default_factory=list)
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


def _port_walls(frame, count):
    """``((wall, per_wall), ...)``: the two shortest walls and their ports' share.

    A port is bored in from a wall face towards the work, so it belongs on a
    wall, and the pair that faces the work is the shortest pair of sides.
    ``count`` is shared between the pair, the first wall taking the odd one.
    """
    if count < 1:
        raise MouldFixtureError(f"port count {count} must be positive")
    walls = _shortest_walls(frame)
    share = [count // len(walls)] * len(walls)
    for index in range(count % len(walls)):
        share[index] += 1
    return list(zip(walls, share))


def _port_stations(frame, count):
    """``count`` nominal port positions, one per port, on the shortest walls.

    Each wall's own ports are centred on it. Equal spacing around the whole
    perimeter is wrong for this, because the fractions it lands on are span
    boundaries - the corners - which is where the two-port default used to put
    them. These are what the placement search starts from, not necessarily
    where a port ends up.
    """
    stations = []
    for ((mid_x, mid_y), inward, length), per_wall in _port_walls(frame, count):
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


def _drill_through_lower(frame, x, y, z_mate, diameter):
    """A hole from the mating surface down through the lower cap face."""
    start = frame.point(x, y, frame.z_min - TOOL_OVERSHOOT)
    height = (z_mate - frame.z_min) + 2.0 * TOOL_OVERSHOOT
    return Part.makeCylinder(diameter / 2.0, height, start, frame.z_axis)


def _seat_radius(params):
    """The widest radius an alignment seat presents, shoulder included.

    The clearance rule is about the material a seat removes, and a counterbore
    removes more of it than the bore does, so the shoulder is what has to be
    held clear of the wall, the part outline and the other fixtures.
    """
    radius = 0.5 * max(params.pin_diameter, params.bush_diameter)
    if params.shoulder_diameter > 0.0:
        radius = max(radius, 0.5 * params.shoulder_diameter)
    return radius


def _bolt_radius(params):
    """The widest radius a clamp bolt presents, head counterbore included."""
    radius = 0.5 * params.bolt_hole_diameter
    if params.bolt_head_diameter > 0.0:
        radius = max(radius, 0.5 * params.bolt_head_diameter)
    return radius


def _drill_between(frame, x, y, start_z, end_z, diameter):
    """A cylinder along the draw from ``start_z`` to ``end_z``.

    Overshoots at both ends, which is what a cut wants: the face it breaks out
    of and the floor it bottoms on are clean either way.
    """
    low = min(start_z, end_z) - TOOL_OVERSHOOT
    return Part.makeCylinder(diameter / 2.0,
                             abs(end_z - start_z) + 2.0 * TOOL_OVERSHOOT,
                             frame.point(x, y, low), frame.z_axis)


def _seat_tool(mould, x, y, z_mate, diameter, params, into_lower):
    """One whole seat, as a single tool.

    The bore the locating part sits in, the counterbore its flange seats on when
    it has one, the bore that lets a screw in from the back, and the screw's own
    counterbore in the cap face. Combined into one tool because they are coaxial
    parts of a single feature - a screw's counterbore and its clearance hole
    overlap along the axis by design - and the interference check would
    otherwise read them as two fixtures fighting for the same material.

    A screw reaches a screw-fixed part from the back of the block, which for a
    seat opening at the mating face is the cap face. That bore also vents the
    seat: a blind one holds an air pocket which outgasses into the tool and
    reads as a leak under vacuum. Both run along the seat's own axis, and the
    clearance rule already holds every seat clear of the cavity, so neither can
    reach the part.
    """
    frame = mould.frame
    drill = _drill_down if into_lower else _drill_up
    socket = drill(frame, x, y, z_mate, diameter, params.depth)
    floor = z_mate - params.depth if into_lower else z_mate + params.depth
    cap = frame.z_min if into_lower else frame.z_max
    # How much half is left between the seat's floor and the face behind it.
    span = (floor - cap) if into_lower else (cap - floor)
    if span <= PLANE_OFFSET_TOL:
        # The seat has already broken through. note_blind_socket reports that,
        # and there is nothing left behind it for a bore or a counterbore to do.
        return socket
    cuts = [socket]
    if params.shoulder_diameter > 0.0:
        cuts.append(drill(frame, x, y, z_mate, params.shoulder_diameter,
                          params.shoulder_depth))
    # Inward from the cap face is the opposite direction to the seat itself.
    inward = 1.0 if into_lower else -1.0
    open_z = cap
    if params.screw_head_diameter > 0.0:
        if params.screw_head_depth >= span:
            raise MouldFixtureError(
                f"screw head counterbore {params.screw_head_depth:.3f} mm deep "
                f"leaves nothing of the {span:.3f} mm between the cap face and "
                f"the seat floor"
            )
        cuts.append(_drill_between(frame, x, y, cap,
                                   cap + inward * params.screw_head_depth,
                                   params.screw_head_diameter))
        open_z = cap + inward * params.screw_head_depth
    for bore in (params.vent_diameter, params.screw_diameter):
        if bore > 0.0:
            cuts.append(_drill_between(frame, x, y, open_z, floor, bore))
    return Part.makeCompound(cuts)


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


def _slot_section(frame, station, z_mate, height, depth):
    """The slot's cross-section at one station, as a closed wire.

    A triangle whose apex sits *on* the mating plane, so each half receives a
    mirror-image share of the notch, and whose wall-side edge spans the plane so
    the slot opens through the block face. A slot is a loft through one of these
    per station, which is what makes its apex ride the part line.
    """
    inward = _orient_inward(frame, station)
    base = frame.point(station.x, station.y, z_mate) - inward * TOOL_OVERSHOOT
    wall_bottom = base - frame.z_axis * (height / 2.0)
    wall_top = base + frame.z_axis * (height / 2.0)
    apex = base + inward * (depth + TOOL_OVERSHOOT)
    return Part.Wire(Part.makePolygon([wall_bottom, wall_top, apex], True))


def _alignment_tools(mould, params):
    """``(lower_tools, upper_tools, hole_count)`` for the dowel/bush pairs."""
    if not params.enabled:
        return [], [], 0
    if params.pin_half not in PIN_HALVES:
        raise MouldFixtureError(
            f"align pin half must be one of {PIN_HALVES}, not {params.pin_half!r}"
        )
    # The extras apply to both seats, so each has to suit the narrower of them.
    narrowest = min(params.pin_diameter, params.bush_diameter)
    if params.shoulder_diameter > 0.0:
        if params.shoulder_diameter <= narrowest:
            raise MouldFixtureError(
                f"seat shoulder diameter {params.shoulder_diameter:.3f} mm does "
                f"not countersink a {narrowest:.3f} mm seat"
            )
        if params.shoulder_depth >= params.depth:
            raise MouldFixtureError(
                f"seat shoulder depth {params.shoulder_depth:.3f} mm reaches "
                f"past the {params.depth:.3f} mm seat it countersinks"
            )
    if params.vent_diameter > 0.0 and params.vent_diameter >= narrowest:
        raise MouldFixtureError(
            f"seat vent diameter {params.vent_diameter:.3f} mm is no smaller "
            f"than the {narrowest:.3f} mm seat it drains"
        )
    if params.screw_diameter > 0.0 and params.screw_diameter >= narrowest:
        raise MouldFixtureError(
            f"seat screw clearance {params.screw_diameter:.3f} mm is no smaller "
            f"than the {narrowest:.3f} mm seat it opens into"
        )
    if params.screw_head_diameter > 0.0:
        if params.screw_diameter <= 0.0:
            raise MouldFixtureError(
                "a screw head counterbore needs a screw clearance hole to sit "
                "around"
            )
        if params.screw_head_diameter <= params.screw_diameter:
            raise MouldFixtureError(
                f"seat screw head diameter {params.screw_head_diameter:.3f} mm "
                f"does not counterbore the {params.screw_diameter:.3f} mm screw "
                f"clearance"
            )
    frame = mould.frame
    pin_tools, bush_tools = [], []
    for x, y in corner_positions(frame, params.count, params.edge_offset):
        z_mate = mould.mating_height(x, y)
        mould.note_blind_socket("align pin", z_mate, params.depth,
                                params.pin_half == "Lower")
        mould.note_blind_socket("align bush", z_mate, params.depth,
                                params.pin_half != "Lower")
        pin_tools.append(_seat_tool(mould, x, y, z_mate, params.pin_diameter,
                                    params, into_lower=params.pin_half == "Lower"))
        bush_tools.append(_seat_tool(mould, x, y, z_mate, params.bush_diameter,
                                     params, into_lower=params.pin_half != "Lower"))
    # One seat is one hole, however many cuts it takes to make it.
    holes = len(pin_tools) + len(bush_tools)
    if params.pin_half == "Lower":
        return pin_tools, bush_tools, holes
    return bush_tools, pin_tools, holes


def _bolt_tools(mould, params, phase):
    """``(lower, upper, stations)`` for the bolt pattern at one phase.

    Each bolt is one tool: the clearance hole through the half plus, in the
    lower half, the counterbore its head sinks into. Combined because they
    overlap along the axis by design, and the interference check reads two
    overlapping tools as two fixtures fighting for the same material.

    Building a candidate pattern is cheap because the mating height is cached,
    which is what lets the phase search try patterns against each other.
    """
    frame = mould.frame
    lower, upper, stations = [], [], []
    for station in perimeter_stations(frame, params.bolt_count,
                                      params.bolt_edge_offset, phase=phase):
        stations.append(station)
        z_mate = mould.mating_height(station.x, station.y)
        upper.append(_drill_through_upper(frame, station.x, station.y, z_mate,
                                          params.bolt_hole_diameter))
        cuts = [_drill_through_lower(frame, station.x, station.y, z_mate,
                                     params.bolt_hole_diameter)]
        if params.bolt_head_diameter > 0.0:
            # The head sinks into the face the bolt enters by, so the half still
            # lands flat on whatever it is bolted down to.
            available = z_mate - frame.z_min
            if params.bolt_head_depth >= available:
                raise MouldFixtureError(
                    f"bolt head counterbore {params.bolt_head_depth:.3f} mm deep "
                    f"reaches the mating surface, only {available:.3f} mm from "
                    f"the lower cap face"
                )
            cuts.append(_drill_between(frame, station.x, station.y,
                                       frame.z_min,
                                       frame.z_min + params.bolt_head_depth,
                                       params.bolt_head_diameter))
        lower.append(Part.makeCompound(cuts))
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
    bolt_radius = _bolt_radius(params)
    bolt_bore = 0.5 * params.bolt_hole_diameter
    candidates = sorted((step / float(BOLT_PHASE_SAMPLES)
                         for step in range(BOLT_PHASE_SAMPLES)),
                        key=lambda phase: abs(phase - 0.5))
    widest = None
    ruled = None
    for phase in candidates:
        lower, upper, stations = _bolt_tools(mould, params, phase)
        surplus = min(_surplus(frame, segments, station.x, station.y, bolt_radius,
                               bolt_bore, pin_zones)
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


def _skirt_gaps(frame, segments, x, y, wall_radius, cavity_radius):
    """``(wall, outline)`` gaps for a hole at ``(x, y)``.

    Edge to edge, each against the radius that actually applies there: the widest
    cut at the station for the wall, and the cut that reaches the cavity for the
    part outline. ``outline`` is ``None`` when the part line is not known, which
    is not the same as a clear one.
    """
    wall = min(x - frame.x_min, frame.x_max - x,
               y - frame.y_min, frame.y_max - y) - wall_radius
    gaps = [_point_segment_distance(x, y, *segment) - cavity_radius
            for segment in segments]
    return wall, (min(gaps) if gaps else None)


def _surplus(frame, segments, x, y, wall_radius, cavity_radius, neighbours=()):
    """How much more gap a hole at ``(x, y)`` keeps than the rule demands.

    Negative means it breaks the rule. ``neighbours`` is ``(x, y, radius)`` of
    the other holes it has to clear as well, and those are measured against the
    part, so the cavity radius is what counts between them.
    """
    wall, outline = _skirt_gaps(frame, segments, x, y, wall_radius,
                                cavity_radius)
    surplus = wall - _required_gap(wall_radius)
    if outline is not None:
        surplus = min(surplus, outline - _required_gap(cavity_radius))
    for other_x, other_y, other_radius in neighbours:
        pair_gap = (math.hypot(x - other_x, y - other_y)
                    - (cavity_radius + other_radius))
        surplus = min(surplus,
                      pair_gap - _required_gap(max(cavity_radius, other_radius)))
    return surplus


def _clearance_issues(frame, segments, holes):
    """Holes keeping less than a diameter of gap from the skirt or each other.

    ``holes`` is ``(label, offset_property, x, y, wall_radius, cavity_radius)``.
    A violation names the property to raise, because the fix is a wider offset
    or a smaller hole, never a thinner web.
    """
    issues = []
    for label, offset_property, x, y, wall_radius, cavity_radius in holes:
        wall, outline = _skirt_gaps(frame, segments, x, y, wall_radius,
                                    cavity_radius)
        if wall < _required_gap(wall_radius):
            issues.append(
                f"{label} keep {wall:.3f} mm to the block wall but need "
                f"{_required_gap(wall_radius):.3f} mm (2 x the "
                f"{wall_radius:.3f} mm radius): raise {offset_property}, or "
                f"reduce the size"
            )
        if outline is not None and outline < _required_gap(cavity_radius):
            issues.append(
                f"{label} keep {outline:.3f} mm to the part outline but need "
                f"{_required_gap(cavity_radius):.3f} mm (2 x the "
                f"{cavity_radius:.3f} mm radius): raise {offset_property}, or "
                f"reduce the size"
            )
    for (label_a, _property_a, xa, ya, _wa, ca), \
            (label_b, _property_b, xb, yb, _wb, cb) in combinations(holes, 2):
        gap = math.hypot(xa - xb, ya - yb) - (ca + cb)
        needed = _required_gap(max(ca, cb))
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
    radius = _seat_radius(params)
    return [(x, y, radius)
            for x, y in corner_positions(frame, params.count, params.edge_offset)]


def _labeled(tools, label):
    """``[(label, tool)]``, so an interference report can name the fixtures."""
    return [(label, tool) for tool in tools]


def _hole_audit(request, pin_zones, bolt_stations):
    """``(label, offset_property, x, y, wall_radius, cavity_radius)`` per hole.

    Two radii, because a feature does not present the same size to both edges it
    has to clear. A seat's shoulder is on the mating face, where the cavity is,
    so it counts against both. A bolt's head counterbore is in the cap face, far
    from the cavity in the draw direction, so it counts against the wall only -
    the hole itself is what has to stand clear of the part.
    """
    holes = [(ALIGN_KIND, PIN_OFFSET_PROPERTY, x, y, radius, radius)
             for x, y, radius in pin_zones]
    if request.clamping.bolts_enabled:
        wall = _bolt_radius(request.clamping)
        cavity = 0.5 * request.clamping.bolt_hole_diameter
        holes.extend((CLAMP_KIND, BOLT_OFFSET_PROPERTY, station.x, station.y,
                      wall, cavity) for station in bolt_stations)
    return holes


def _clamping_tools(mould, params, pin_zones=(), segments=(), obstacles=()):
    """``(lower_tools, upper_tools, bolt_holes, notches, bolt_stations)``.

    The ears are placed first so the bolt pattern can be laid out around them
    rather than the other way round: only the bolt phase is free to move.
    """
    frame = mould.frame
    lower_tools, upper_tools, bolt_stations = [], [], []
    if params.bolt_head_diameter > 0.0 and params.bolt_head_diameter <= params.bolt_hole_diameter:
        raise MouldFixtureError(
            f"bolt head diameter {params.bolt_head_diameter:.3f} mm does not "
            f"counterbore the {params.bolt_hole_diameter:.3f} mm clearance hole"
        )
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
        lower_tools.extend(bolt_lower)
        upper_tools.extend(bolt_upper)
        bolt_holes = len(bolt_lower)
    return lower_tools, upper_tools, bolt_holes, notches, bolt_stations


def _inside_stock(frame, point):
    """Whether a world point is properly inside the stock block.

    Properly, by ``PORT_STOCK_INSET_MM``: a point on one of the block's own
    faces is not inside it, so a ray grazing a face cannot have met the part.
    """
    x, y, z = frame.local(point)
    inset = PORT_STOCK_INSET_MM
    return (frame.x_min + inset <= x <= frame.x_max - inset
            and frame.y_min + inset <= y <= frame.y_max - inset
            and frame.z_min + inset <= z <= frame.z_max - inset)


def _part_crossing(frame, half, station, z, span):
    """``(distance, point)`` where the ray meets the part, or ``None``.

    Measured by sectioning the half the bore is cut into, because the half ends
    where the part begins. The first crossing past the wall is NOT necessarily
    the part: a bore passing under a cambered part runs the whole block in stock
    and crosses the far wall instead, and taking that crossing drilled a bore
    the length of the block. A crossing is the cavity only when the material
    just beyond it is still inside the stock - the cavity is, the far wall is
    not - so a crossing that leaves the block is refused.
    """
    if half is None or half.isNull():
        return None
    inward = _orient_inward(frame, station)
    start = frame.point(station.x, station.y, z) - inward * TOOL_OVERSHOOT
    try:
        section = half.section(Part.makeLine(start, start + inward * span))
    except Exception:
        return None
    crossings = sorted((vertex.Point - start).dot(inward)
                       for vertex in section.Vertexes)
    for along in crossings:
        if along <= 2.0 * TOOL_OVERSHOOT:
            continue
        beyond = start + inward * (along + PORT_CROSSING_STEP_MM)
        if _inside_stock(frame, beyond) and not half.isInside(
                beyond, PLANE_OFFSET_TOL, False):
            return along, start + inward * along
    return None


def _along_wall(station, along):
    """A station ``along`` the wall from this one, with the same directions."""
    return PerimeterStation(
        x=station.x + station.tangent[0] * along,
        y=station.y + station.tangent[1] * along,
        tangent=station.tangent,
        inward=station.inward,
    )


def _port_limit(margins, station):
    """How long a bore from this wall may run and still be aimed at the part.

    The part's bounding box touches each wall face within the mould's stock
    margin, so a bore from that wall to the part is about that margin long. A
    declared footprint replaces the margins, and then there is no per-axis
    figure to compare with, so no absolute bound is applied - the shortest aim
    the wall offers is taken instead, and ``_summary`` reports every bore's kind
    and length so a poor one is visible rather than hidden.
    """
    if margins is None or getattr(margins, "explicit_footprint", False):
        return None
    along = (margins.x if abs(station.inward[0]) > abs(station.inward[1])
             else margins.y)
    return along + PORT_AIM_SLACK_MM


def _aim_port(mould, params, station, half, span, limit):
    """The shortest bore from this station that meets the part, or ``None``.

    Only heights clearing the mating plane are tried, so the bore stays in its
    own half, and only a crossing within ``limit`` counts: a bore that has to
    run further than that to meet the part has missed the part's near side. The
    shallowest such height wins among equals, since it is the one closest to the
    mating plane.
    """
    frame = mould.frame
    side = mould.lower if half == "Lower" else mould.upper
    sign = -1.0 if half == "Lower" else 1.0
    mate = mould.mating_height(station.x, station.y)
    face = frame.z_min if half == "Lower" else frame.z_max
    depth = abs(mate - face)
    steps = max(1, int((depth - params.offset_from_mating) / PORT_HEIGHT_STEP_MM))
    best = None
    for step in range(steps + 1):
        z = mate + sign * (params.offset_from_mating + step * PORT_HEIGHT_STEP_MM)
        crossing = _part_crossing(frame, side, station, z, span)
        if crossing is None:
            continue
        reach, point = crossing
        if limit is not None and reach > limit:
            continue
        if best is None or reach < best[1]:
            best = (z, reach, point)
    return best


def _wall_target(mould, params, stations, half, span):
    """The part's nearest point to this wall, as ``(reach, point, z)``.

    Scanned finely just inside the mating plane and coarsely below it. A part
    that is thin in this half - which is the case that reaches the cap fallback
    - is met within a millimetre or two of the interface, and a coarse scan
    steps straight over it. The interface plane and the cap face are never
    sampled: a ray along either grazes the half's own boundary rather than
    crossing the part, and reading that graze as the part is what put a target
    on the cap face.
    """
    frame = mould.frame
    side = mould.lower if half == "Lower" else mould.upper
    sign = -1.0 if half == "Lower" else 1.0
    face = frame.z_min if half == "Lower" else frame.z_max
    best = None
    for station in stations:
        mate = mould.mating_height(station.x, station.y)
        depth = abs(mate - face)
        offsets = [PORT_FINE_STEP_MM * (step + 1)
                   for step in range(int(PORT_FINE_MM / PORT_FINE_STEP_MM))]
        offsets += [PORT_FINE_MM + PORT_TARGET_STEP_MM * (step + 1)
                    for step in range(int(max(0.0, depth - PORT_FINE_MM)
                                          / PORT_TARGET_STEP_MM))]
        for offset in offsets:
            if offset >= depth:
                break
            z = mate + sign * offset
            crossing = _part_crossing(frame, side, station, z, span)
            if crossing is None:
                continue
            reach, point = crossing
            if best is None or reach < best[0]:
                best = (reach, point, z)
    return best


def _cap_depth(frame, half, target):
    """How deep a bore from the half's cap face goes to reach ``target``."""
    _x, _y, z = frame.local(target)
    face = frame.z_min if half == "Lower" else frame.z_max
    return abs(z - face) + 2.0 * TOOL_OVERSHOOT


def _cap_bore(frame, params, half, target):
    """A bore from the half's cap face to ``target``, along the draw.

    The fallback for a port no wall bore can reach: aimed at the same point on
    the part, but entered through the face away from the mating plane instead of
    through a wall.
    """
    x, y, _z = frame.local(target)
    if half == "Lower":
        start = frame.point(x, y, frame.z_min - TOOL_OVERSHOOT)
        direction = frame.z_axis
    else:
        start = frame.point(x, y, frame.z_max + TOOL_OVERSHOOT)
        direction = frame.z_axis * -1.0
    return Part.makeCylinder(params.diameter / 2.0,
                             _cap_depth(frame, half, target),
                             start, direction)


def _port_placement(mould, params, margins=None):
    """``(half, (station, z, reach) or None, target or None)`` per port.

    A port bores from a wall to the part, so the shortest bore that meets the
    part wins: every station the wall offers is tried, at every height that
    clears the mating plane, and only a crossing within the stock margin counts
    (``_port_limit``). Where nothing qualifies - the part is thin in this half,
    or away from that wall - the port keeps the point nearest the wall
    (``target``) and is bored from the cap to it, and where the wall offers no
    point at all there is no port to place and the caller says so.
    """
    frame = mould.frame
    span = 2.0 * max(frame.size)
    placements = []
    for station, (wall, per_wall) in zip(_port_stations(frame, params.count),
                                         _port_walls(frame, params.count)):
        window = PORT_SEARCH_SPAN * wall[2] / per_wall
        offsets = [(index / (PORT_STATION_SAMPLES - 1.0) - 0.5) * window
                   for index in range(PORT_STATION_SAMPLES)]
        stations = [_along_wall(station, along) for along in offsets]
        for half in ("Lower", "Upper"):
            if params.half not in (half, "Both"):
                continue
            limit = _port_limit(margins, station)
            best = None
            for probe in stations:
                aimed = _aim_port(mould, params, probe, half, span, limit)
                if aimed is None:
                    continue
                z, reach, _point = aimed
                if best is None or reach < best[2]:
                    best = (probe, z, reach)
            target = None
            if best is None:
                target = _wall_target(mould, params, stations, half, span)
            placements.append((half, best, target))
    return placements


def _port_tools(mould, params, margins=None):
    """``(lower_tools, upper_tools, bore_count, specs)`` for the wall bores.

    Each bore is aimed at the part's nearest point on its wall (see
    ``_port_placement``), so it is as short as the stock allows and opens into
    the cavity instead of running past it. A port no wall bore can reach keeps
    its point and is bored from the cap instead, with a warning, and one that
    cannot be placed at all is reported rather than drilled to whatever it
    happens to hit.

    ``specs`` is ``(station, radius, half)`` for each wall bore, which is what a
    parting wedge slot needs to keep out of its way.
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
    for half, placement, target in _port_placement(mould, params, margins):
        tools = lower_tools if half == "Lower" else upper_tools
        if placement is not None:
            station, z, reach = placement
            specs.append((station, params.diameter / 2.0, half))
            inward = _orient_inward(frame, station)
            start = frame.point(station.x, station.y, z) - inward * TOOL_OVERSHOOT
            tools.append(Part.makeCylinder(
                params.diameter / 2.0, reach + 2.0 * TOOL_OVERSHOOT,
                start, inward))
            mould.port_notes.append(
                f"{half.lower()} wall {reach + 2.0 * TOOL_OVERSHOOT:.1f} mm")
            continue
        if target is None:
            mould.unreached_ports.append(
                f"the process ports cannot reach the part from the "
                f"{half.lower()} wall: no position along that wall meets it, "
                f"so no bore was cut there"
            )
            continue
        _reach, point, _z = target
        x, y, _ = frame.local(point)
        tools.append(_cap_bore(frame, params, half, point))
        mould.port_notes.append(
            f"{half.lower()} cap {_cap_depth(frame, half, point):.1f} mm")
        mould.port_warnings.append(
            f"the process port on the {half.lower()} wall cannot clear the "
            f"mating plane and still reach the part, so it is bored from the "
            f"cap at ({x:.3f}, {y:.3f}) to the same point"
        )
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


def _slot_sections(mould, station, start, end, params):
    """The sections covering ``start``..``end`` of one wall, on the interface.

    One section every ``WEDGE_SLOT_SAMPLE_MM``, each measured at its own
    position, so the slot follows the parting geometry rather than one plane
    across the wall - and, being sections of a single loft, follows it with no
    step at any station.
    """
    length = end - start
    if length <= PLANE_OFFSET_TOL:
        return []
    count = max(2, int(math.ceil(length / WEDGE_SLOT_SAMPLE_MM)) + 1)
    sections = []
    for index in range(count):
        along = start + length * index / (count - 1)
        point = PerimeterStation(
            x=station.x + station.tangent[0] * along,
            y=station.y + station.tangent[1] * along,
            tangent=station.tangent,
            inward=station.inward,
        )
        sections.append(_slot_section(
            mould.frame, point, mould.mating_height(point.x, point.y),
            params.height, params.depth))
    return sections


def _slot_tool(mould, station, start, end, params):
    """One continuous slot covering ``start``..``end`` of one wall."""
    sections = _slot_sections(mould, station, start, end, params)
    if len(sections) < 2:
        return []
    tool = Part.makeLoft(sections, solid=True, ruled=True)
    if tool.isNull() or not tool.Solids:
        return []
    return [tool]


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
                tools.extend(_slot_tool(mould, station, start, end, params))
    return lower_tools, upper_tools, len(runs)


def seal_groove_width(params):
    """The groove's width across the strip: the caller's, or the cord's own."""
    if params.width > 0.0:
        return params.width
    return SEAL_GROOVE_WIDTH_FACTOR * params.cord_diameter


def seal_groove_depth(params):
    """The groove's depth into the strip: the caller's, or the cord's own."""
    if params.depth > 0.0:
        return params.depth
    return SEAL_GROOVE_DEPTH_FACTOR * params.cord_diameter


def seal_groove_corner_radius(params):
    """The radius the groove's path turns a corner at."""
    if params.corner_radius > 0.0:
        return params.corner_radius
    return SEAL_GROOVE_CORNER_FACTOR * params.cord_diameter


def _ring_stations(shape, name):
    """One level-strip ring's stations in ring order, without the repeated first.

    The ring is a closed polyline, so its last vertex repeats its first: the
    duplicate goes, and the two rings' entries then line up station for
    station.
    """
    if shape is None or shape.isNull():
        return []
    wires = shape.Wires
    if len(wires) != 1:
        raise MouldFixtureError(
            f"the level strip's {name} ring is {len(wires)} wires, not one")
    points = [vertex.Point for vertex in wires[0].OrderedVertexes]
    if len(points) > 1 and points[0].distanceToPoint(points[-1]) <= AXIS_ALIGNMENT_TOL:
        points.pop()
    return points


def level_strip_stations(level_strip_in, level_strip_out):
    """The level strip's stations as ``[(inboard, outboard)]`` pairs in ring order.

    The two rings bound the strip and carry the same stations in the same
    order, so station ``i`` of one pairs with station ``i`` of the other. That
    pairing is the strip's own, taken from the same construction as the band,
    never re-derived from the geometry.
    """
    in_points = _ring_stations(level_strip_in, "inboard")
    out_points = _ring_stations(level_strip_out, "outboard")
    if not in_points and not out_points:
        return []
    if len(in_points) != len(out_points):
        raise MouldFixtureError(
            f"the level strip's rings disagree: {len(in_points)} inboard "
            f"stations against {len(out_points)} outboard")
    return list(zip(in_points, out_points))


def _station_frames(stations):
    """Each strip station as a path frame: ``(midpoint, across, strip width)``.

    ``across`` runs from the inboard point to the outboard one - the ray the
    strip was built from - so a section drawn on it follows the strip's own
    direction rather than assuming the walls are parallel.
    """
    frames = []
    for point_in, point_out in stations:
        across = Vector(point_out.x - point_in.x, point_out.y - point_in.y, 0.0)
        if across.Length <= PLANE_OFFSET_TOL:
            raise MouldFixtureError(
                "a level strip station is zero width across: the two rings "
                "coincide there, so there is no strip for a groove to sit in")
        width = across.Length
        across.normalize()
        frames.append((0.5 * (point_in + point_out), across, width))
    return frames


def _round_corner(previous, vertex, following, radius, samples=8):
    """``[(point, tangent)]`` along the arc that replaces one sharp vertex.

    Tangent to both segments, so the path leaves the incoming direction, turns
    through the corner at a constant radius and picks up the outgoing one - the
    mitre a ruled loft would otherwise leave is exactly what this removes. An
    empty list means the corner is too shallow to be worth rounding.
    """
    incoming = vertex - previous
    incoming.z = 0.0
    outgoing = following - vertex
    outgoing.z = 0.0
    if incoming.Length <= PLANE_OFFSET_TOL or outgoing.Length <= PLANE_OFFSET_TOL:
        return []
    incoming.normalize()
    outgoing.normalize()
    turn = incoming.getAngle(outgoing)
    if turn <= math.radians(SEAL_GROOVE_STRAIGHT_TOL_DEG):
        return []
    cutback = radius * math.tan(turn / 2.0)
    if (cutback > 0.5 * (vertex - previous).Length
            or cutback > 0.5 * (following - vertex).Length):
        raise MouldFixtureError(
            f"the strip turns a corner with less than {2.0 * cutback:.3f} mm "
            f"of straight either side of it, too short to round at "
            f"{radius:.3f} mm: cut a smaller corner radius, or fit a smaller "
            f"cord")

    start = vertex - incoming * cutback
    end = vertex + outgoing * cutback
    # The centre lies on the side the path turns towards, one radius from both
    # segments; the cross product says which side that is.
    left = Vector(-incoming.y, incoming.x, 0.0)
    correction = 1.0 if incoming.cross(outgoing).z > 0.0 else -1.0
    centre = start + left * (radius * correction)
    start_angle = math.atan2(start.y - centre.y, start.x - centre.x)
    sweep = turn * correction
    points = []
    for index in range(samples + 1):
        angle = start_angle + sweep * index / samples
        points.append((
            Vector(centre.x + radius * math.cos(angle),
                   centre.y + radius * math.sin(angle), 0.0),
            Vector(-math.sin(angle) * correction,
                   math.cos(angle) * correction, 0.0),
        ))
    return points


def _largest_fitting_corner_radius(stations, radius):
    """The largest corner radius this strip can carry.

    ``_round_corner`` needs ``radius * tan(turn/2)`` of straight either side of
    a corner.  A strip whose stations crowd a shallow turn has less than the
    cord's derived radius asks for, and no single radius satisfies both the cord
    and the geometry - the geometry wins, at the largest value that fits,
    because a groove that cannot be rounded cannot be cut at all.  Returns
    `radius` unchanged when every corner carries it.
    """
    base = _station_frames(stations)
    count = len(base)
    limit = radius
    for index, (point, _across, _width) in enumerate(base):
        previous = base[(index - 1) % count][0]
        following = base[(index + 1) % count][0]
        incoming = point - previous
        incoming.z = 0.0
        outgoing = following - point
        outgoing.z = 0.0
        if (incoming.Length <= PLANE_OFFSET_TOL
                or outgoing.Length <= PLANE_OFFSET_TOL):
            continue
        incoming.normalize()
        outgoing.normalize()
        turn = incoming.getAngle(outgoing)
        if turn <= math.radians(SEAL_GROOVE_STRAIGHT_TOL_DEG):
            continue
        straight = 0.5 * min((point - previous).Length,
                             (following - point).Length)
        limit = min(limit, straight / math.tan(turn / 2.0))
    return limit


def _seal_groove_frames(stations, radius):
    """The groove path's frames: the strip's stations, with corners rounded.

    Each station is rounded into a tangent arc, and the arc is sampled into
    frames of its own, so the loft through them turns the corner at `radius`
    instead of jumping the across-direction in one step. The arc carries its
    corner station's own surface z and the narrowest of the three stations'
    widths: it replaces that station and stays within the strip that bounds it.
    """
    base = _station_frames(stations)
    count = len(base)
    frames = []
    for index, (point, across, width) in enumerate(base):
        previous_frame = base[(index - 1) % count]
        following_frame = base[(index + 1) % count]
        arc = _round_corner(previous_frame[0], point, following_frame[0], radius)
        if not arc:
            frames.append((point, across, width))
            continue
        corner_width = min(width, previous_frame[2], following_frame[2])
        for arc_point, tangent in arc:
            arc_across = Vector(tangent.y, -tangent.x, 0.0)
            if arc_across.dot(across) < 0.0:
                arc_across = -arc_across
            frames.append((Vector(arc_point.x, arc_point.y, point.z),
                           arc_across, corner_width))
    return frames


def _seal_groove_corners(point, across, width, depth):
    """The four corners of the groove's profile at one path frame.

    Sunk from just above the strip's surface down to the groove's floor; the
    overshoot above the surface keeps a coincident face out of the cut.
    """
    half_width = 0.5 * width
    top = point.z + TOOL_OVERSHOOT
    floor = point.z - depth

    def corner(side, z):
        return Vector(point.x + across.x * half_width * side,
                      point.y + across.y * half_width * side, z)

    return (corner(1.0, top), corner(-1.0, top),
            corner(-1.0, floor), corner(1.0, floor))


def _seal_groove_section(point, across, width, depth):
    """The groove's cross-section at one path frame, as a closed wire."""
    return Part.Wire(Part.makePolygon(
        list(_seal_groove_corners(point, across, width, depth)), True))


def _frame_matters(frames, corners, before, candidate, after,
                   width, depth, tolerance):
    """Does the loft need the candidate frame's own section?

    The loft is ruled, so between two frames it is the straight interpolation
    of their profile corners. A frame earns its faces only if its own corners
    lie further than ``tolerance`` from that interpolation, read at the
    parameter the frame's centre projects to between its neighbours - which is
    where the loft would meet it. ``before``, ``candidate`` and ``after`` are
    indices into ``frames``; ``corners`` holds each frame's profile corners.
    """
    point, across, _strip = frames[candidate]
    span = frames[after][0] - frames[before][0]
    span.z = 0.0
    if span.Length <= PLANE_OFFSET_TOL:
        return True
    reach = point - frames[before][0]
    reach.z = 0.0
    where = min(1.0, max(0.0, reach.dot(span) / span.dot(span)))
    for index, corner in enumerate(_seal_groove_corners(point, across,
                                                        width, depth)):
        interpolated = (corners[before][index] * (1.0 - where)
                        + corners[after][index] * where)
        if corner.distanceToPoint(interpolated) > tolerance:
            return True
    return False


def _decimate_frames(frames, width, depth, tolerance):
    """Drop the path frames a ruled loft already passes through.

    Only the frames the loft cannot reach are worth a section. The frame the
    scan starts at is always kept, and each frame is tested against the
    neighbours that have survived so far, so dropping one never widens the
    deviation past ``tolerance``: the path is thinned, not approximated.
    """
    if len(frames) <= 3:
        return frames
    corners = [_seal_groove_corners(point, across, width, depth)
               for point, across, _strip in frames]
    order = list(range(len(frames)))
    index = 1
    while index < len(order) - 1 and len(order) > 3:
        previous, frame, following = order[index - 1], order[index], order[index + 1]
        if _frame_matters(frames, corners, previous, frame, following,
                          width, depth, tolerance):
            index += 1
            continue
        del order[index]
        # The frame before it now has a different neighbour, so test it again.
        index = max(1, index - 1)
    if len(order) > 3 and not _frame_matters(
            frames, corners, order[-2], order[-1], order[0],
            width, depth, tolerance):
        del order[-1]
    return [frames[index] for index in order]


def _seal_groove_tool(frames, width, depth):
    """One continuous groove round the whole strip.

    A ruled loft through a section per path frame, with the first repeated at
    the end so the ring closes. The frames sit on the solver's own strip - its
    stations, with every corner rounded into an arc - so the groove follows the
    construction the band does and carries no step and no mitre.
    """
    sections = [_seal_groove_section(point, across, width, depth)
                for point, across, _width in frames]
    tool = Part.makeLoft(sections + [sections[0]], solid=True, ruled=True)
    if tool.isNull() or not tool.Solids:
        raise MouldFixtureError(
            "the O-ring seal groove's loft did not produce a solid")
    return tool


def _draw_frame_rotation(draw):
    """The rotation taking the draw onto +Z, or None when it is +Z already.

    A between-vectors rotation is degenerate for parallel vectors, and world Z is
    the common case - the box - so that one is no rotation rather than an empty
    one, and every caller here treats None as already there.
    """
    if draw is None:
        return None
    normal = Vector(draw.x, draw.y, draw.z).normalize()
    up = Vector(0.0, 0.0, 1.0)
    if normal.dot(up) > 1.0 - AXIS_ALIGNMENT_TOL:
        return None
    return Rotation(normal, up)


def _seal_groove_tools(params, level_strip_in, level_strip_out, draw):
    """``(lower_tools, note)`` for the O-ring seal groove, cut in the lower half.

    The groove's geometry is written for a draw of world Z - `across` the strip in
    plan, the corner arcs in plan, the section sunk down from the strip's surface -
    so the strip is rotated into that frame first and the cut rotated back out of
    it. On a mould drawn along world Z that rotation is the identity and the
    geometry is exactly what it always was; on one drawn along anything else it is
    what stops `across` collapsing to nothing.

    Fails loudly rather than cut a groove that is not there to cut. A mould
    with no level strip has no flat land for the ring to seat on, and one whose
    strip is narrower than the groove would have the groove cut through the
    land's edge and out of the level surface - the face the ring seals against,
    which is therefore never cut smaller than the groove fits.
    """
    if not params.enabled:
        return [], ""
    stations = level_strip_stations(level_strip_in, level_strip_out)
    to_draw_frame = _draw_frame_rotation(draw)
    if to_draw_frame is not None:
        stations = [(to_draw_frame.multVec(point_in),
                     to_draw_frame.multVec(point_out))
                    for point_in, point_out in stations]
    if not stations:
        raise MouldFixtureError(
            "the mould has no level strip to cut the O-ring groove into: a "
            "level strip needs the skirt levelling switched on with a 'fixed' "
            "extent, and a transition shorter than every ray's plan run")
    if len(stations) < 3:
        raise MouldFixtureError(
            f"the level strip has {len(stations)} stations; a closed groove "
            f"needs at least 3")
    width = seal_groove_width(params)
    depth = seal_groove_depth(params)
    radius = seal_groove_corner_radius(params)
    cord_radius = radius
    if params.corner_radius <= 0.0:
        radius = _largest_fitting_corner_radius(stations, radius)
    frames = _seal_groove_frames(stations, radius)
    # The fit check reads every frame the strip produced, not the thinned path:
    # the groove has to fit the strip where the strip is narrowest.
    narrowest = min(strip for _point, _across, strip in frames)
    if narrowest < width - PLANE_OFFSET_TOL:
        raise MouldFixtureError(
            f"the level strip is {narrowest:.3f} mm across at its narrowest "
            f"station, but the seal groove is {width:.3f} mm wide: raise the "
            f"mould's in-plane stock margin (PartingStockMarginX/Y) until the "
            f"strip is wider than the groove, or cut a narrower groove")
    path = _decimate_frames(frames, width, depth, SEAL_GROOVE_PATH_TOL_MM)
    note = (f"{width:.3f} mm wide x {depth:.3f} mm deep in the level strip, "
            f"centred on it, corners rounded at {radius:.3f} mm, "
            f"{len(path)} path sections from {len(frames)} frames")
    if radius < cord_radius:
        note += (f"; reduced from the cord's {cord_radius:.3f} mm, the strip's "
                 f"corners cannot carry more")
    if params.width <= 0.0 or params.depth <= 0.0:
        note += f", for a {params.cord_diameter:.3f} mm cord"
    tool = _seal_groove_tool(path, width, depth)
    if to_draw_frame is not None:
        tool = tool.transformGeometry(
            Placement(Vector(), to_draw_frame.inverted()).toMatrix())
    return [tool], note


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
        "seal_grooves": 0,
        "seal_groove_note": "",
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


def _groove_stock_need(hardware, groove, transition_mm):
    """The stock a centred seal groove needs between the block wall and the part.

    The groove is centred in the level strip, so its distance from the wall is
    half the strip's width: widening the strip carries the groove inboard, away
    from hardware that sits at a fixed offset from the wall whatever the strip
    does. The widest enabled fixture sets the reach the groove has to clear, the
    groove's own two-radius gap sets how far clear of it the groove has to be,
    and the transition in front of the strip is stock the groove cannot use.
    """
    half = 0.5 * seal_groove_width(groove)
    reach = max((needed for _what, needed in hardware), default=0.0)
    return 2.0 * (reach + _required_gap(half) + half) + transition_mm


def _in_plane_requirements(alignment, clamping, wedges, groove=None,
                           transition_mm=0.0):
    """``(what, needed)`` for each enabled fixture cut in from a block wall.

    Each need is a distance from the wall the fixture is measured from. The
    socket or notch reaches that far into the block, so that much material has
    to stand between the wall and the part for the cut to stay in the stock.

    A seal groove is a different kind of need: it is not a hole cut in from the
    wall but a ring centred in the level strip, and it is the *strip* that has
    to be wide enough to carry it clear of the rest. Its need is therefore read
    from the widest of the others rather than from its own size alone, and a
    groove over a fixture that already reaches past it widens the strip until
    the two are clear instead of cutting through each other.
    """
    required = []
    if alignment.enabled:
        required.append(("the align pin and bush sockets",
                         alignment.edge_offset + _seat_radius(alignment)))
    if clamping.bolts_enabled:
        required.append(("the clamp bolt holes",
                         clamping.bolt_edge_offset + _bolt_radius(clamping)))
    if clamping.ears_enabled:
        required.append(("the clamp-ear notches", clamping.ear_depth))
    if wedges.enabled:
        required.append(("the parting wedges", wedges.depth))
    if groove is not None and groove.enabled:
        required.append((SEAL_KIND,
                         _groove_stock_need(required, groove, transition_mm)))
    return required


def required_in_plane_margin(alignment, clamping, wedges, groove=None,
                             transition_mm=0.0):
    """The stock the enabled in-plane fixtures need, or 0.0 when none are."""
    needs = [needed for _what, needed
             in _in_plane_requirements(alignment, clamping, wedges, groove,
                                       transition_mm)]
    return max(needs, default=0.0)


def margin_issues(margins, alignment, clamping, wedges, groove=None,
                  transition_mm=0.0):
    """Fixtures that need more in-plane stock than the mould declares.

    The margin is measured from the part's bounding box and a cavity does not
    fill its box, so it is a lower bound on the material standing between a
    block wall and the part: a fixture that fits within the margin may still
    reach the part, and only one that does not fit is certainly short of stock.

    Process ports are left out. A port is bored in from the wall in order to
    reach the part, and its depth is measured from the part rather than set, so
    the margin does not bound it either way.
    """
    if margins.explicit_footprint:
        return [FOOTPRINT_NOTE]
    available = min(margins.x, margins.y)
    issues = []
    for what, needed in _in_plane_requirements(alignment, clamping, wedges,
                                               groove, transition_mm):
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
                       lower=lower, upper=upper)
    try:
        pin_zones = _pin_zones(frame, request.alignment)
        segments = _outline_segments(frame, request.parting_surface)
        pin_lower, pin_upper, align_holes = _alignment_tools(mould, request.alignment)
        port_lower, port_upper, bores, port_specs = _port_tools(
            mould, request.ports, request.stock_margins)
        wedge_lower, wedge_upper, wedge_count = _wedge_tools(
            mould, request.wedges, port_specs)
        seal_lower, seal_note = _seal_groove_tools(
            request.seal_groove, request.level_strip_in, request.level_strip_out,
            request.draw)
        # The bolts are placed last, around everything already in the block.
        clamp_lower, clamp_upper, bolt_holes, notches, bolt_stations = _clamping_tools(
            mould, request.clamping, pin_zones, segments,
            tuple(pin_lower) + tuple(pin_upper) + tuple(port_lower)
            + tuple(port_upper) + tuple(wedge_lower) + tuple(wedge_upper)
            + tuple(seal_lower))
    except MouldFixtureError as exc:
        return _fail(result, exc.reason)

    lower_tools = pin_lower + clamp_lower + port_lower + wedge_lower + seal_lower
    upper_tools = pin_upper + clamp_upper + port_upper + wedge_upper
    # Each half is checked on its own: a bolt's clearance hole and its tapped
    # hole are meant to line up across the mating plane, and a wedge slot is
    # interrupted in the half a port serves but not in the other.
    result["issues"].extend(_clearance_issues(
        frame, segments, _hole_audit(request, pin_zones, bolt_stations)))

    for half_tools in ((_labeled(pin_lower, ALIGN_KIND)
                        + _labeled(clamp_lower, CLAMP_KIND)
                        + _labeled(port_lower, PORT_KIND)
                        + _labeled(wedge_lower, WEDGE_KIND)
                        + _labeled(seal_lower, SEAL_KIND)),
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
        seal_grooves=len(seal_lower),
        seal_groove_note=seal_note,
        mating_fallbacks=mould.mating_fallbacks,
        bolt_stations=[(station.x, station.y) for station in bolt_stations],
        port_notes=mould.port_notes,
    )
    result["issues"].extend(mould.breakthroughs)
    result["issues"].extend(mould.unreached_ports)
    result["issues"].extend(mould.port_warnings)
    if request.stock_margins is not None:
        result["issues"].extend(
            margin_issues(request.stock_margins, request.alignment,
                          request.clamping, request.wedges, request.seal_groove,
                          request.seal_transition_mm)
        )
    result["status"] = STATUS_READY
    result["summary"] = _summary(result, frame)
    return result


def _summary(result, frame):
    width, depth, height = frame.size
    bores = f"process bores {result['port_bores']}"
    if result.get("port_notes"):
        bores += " (%s)" % ", ".join(result["port_notes"])
    groove = f"seal groove {result.get('seal_grooves', 0)}"
    if result.get("seal_groove_note"):
        groove += " (%s)" % result["seal_groove_note"]
    parts = [
        f"block {width:.3f} x {depth:.3f} x {height:.3f} mm",
        f"alignment holes {result['alignment_holes']}",
        f"bolt holes {result['bolt_holes']}",
        f"clamp notches {result['clamp_notches']}",
        bores,
        f"parting wedges {result['wedge_count']}",
        groove,
    ]
    if result["mating_fallbacks"]:
        parts.append(
            f"{result['mating_fallbacks']} position(s) measured from the block "
            f"mid-height: no parting surface there"
        )
    for issue in result["issues"]:
        parts.append(issue)
    return "Fixtures ready: " + ", ".join(parts)
