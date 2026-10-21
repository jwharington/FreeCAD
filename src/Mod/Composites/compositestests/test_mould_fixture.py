# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Tests for mould fixtures cut into split mould halves.

**The mould halves here are stand-ins, not solver output.** As of this writing
the checked-out ``src/3rdParty/nextdrape`` is mid-refactor (checked out past
the commit the parent repo pins) and its walked part line does not close:
``analyze_source_shape`` returns ``non_planar_status='march_did_not_close'``,
``MouldHalvesStatus='Fail'`` and null halves for *every* shape, including a
box. There is therefore no real mould output to cut, so the block below is
built directly from the same construction the solver performs - a rectangular
stock block parted along a plane, with a prismatic cavity for the part.

What that means for coverage:

- The block-frame recovery, the layouts and every fixture cut are tested for
  real against geometry that exercises the awkward cases (an oblique draw
  direction, so the block is not world-axis aligned, and an in-plane rotated
  cavity, whose wall planes are neither block walls nor perpendicular to the
  block axes).
- The integration with a solver-produced mould is **not** tested, because the
  solver produces nothing to integrate with. ``TestMouldFixtureFeature``
  covers the object plumbing against a real ``Composite::MouldAnalysis``
  whose two child halves hold these stand-in shapes, so the
  ``MouldHalfA`` / ``MouldHalfB`` contract and the property wiring are real.

Replace the stand-in halves with a real ``analyze_source_shape`` run once the
part-line march closes again.
"""

import math
import os
import unittest

import FreeCAD
import Part

from Composites.tools.mould_fixture import (
    ALIGN_KIND,
    BOLT_OFFSET_PROPERTY,
    CLAMP_KIND,
    INTERFERENCE_VOLUME_TOL,
    PIN_OFFSET_PROPERTY,
    SKIRT_CLEARANCE_FACTOR,
    AlignmentParams,
    BlockFrame,
    ClampingParams,
    FixtureRequest,
    MouldBlock,
    MouldFixtureError,
    PortParams,
    StockMargins,
    WedgeParams,
    _alignment_tools,
    _clamping_tools,
    _clearance_issues,
    _interference_issues,
    _pin_zones,
    _port_stations,
    _port_tools,
    _seat_radius,
    _shared_volume,
    _summary,
    _wall_normals,
    _wall_runs,
    _wedge_tools,
    block_frame,
    build_fixtures,
    corner_positions,
    margin_issues,
    perimeter_stations,
    required_in_plane_margin,
    upper_lower,
)
from .test_base import TestFreeCADFP

# Block dimensions in the block's own frame, and the cavity inside it.
# Wide enough for the default fixtures: the wedge slots leave a 50 mm corner
# standoff at either end of each wall, so the shortest wall has to exceed
# 100 mm, and the default bolt pattern wants about 43 mm of skirt - a 26 mm
# inset plus 3R for the 11 mm clearance hole against the part.  The 40 x 30
# cavity is rotated 45 degrees in plane, so its reach along the block axes is
# 35/sqrt(2) = 24.7 mm and the skirt is (BLOCK - 24.7) / 2.
BLOCK = (180.0, 140.0, 60.0)
SPLIT_Z = 30.0
CAVITY_HALF = (20.0, 15.0)
CAVITY_Z = (20.0, 40.0)

# An oblique draw direction: the block is rotated 30 degrees about world X, so
# its axes are NOT the world axes and a frame recovery that assumed world XYZ
# would be wrong in a way these tests can see.
_ROTATION_ANGLE = math.radians(30.0)
X_AXIS = FreeCAD.Vector(1.0, 0.0, 0.0)
Z_AXIS = FreeCAD.Vector(0.0, -math.sin(_ROTATION_ANGLE), math.cos(_ROTATION_ANGLE))
Y_AXIS = Z_AXIS.cross(X_AXIS)

PROBE_TOL = 1.0e-6
SIZE_TOL = 1.0e-6


def _oriented_box(x_axis, y_axis, z_axis, x_range, y_range, z_range):
    """A rectangular prism built directly in its own axes.

    Built by extruding a polygon rather than transforming a ``Part.makeBox``,
    so the result is planar by construction and no transform can quietly
    convert its faces to BSpline surfaces.
    """
    x_min, x_max = x_range
    y_min, y_max = y_range
    z_min, z_max = z_range
    corners = [
        x_axis * x + y_axis * y + z_axis * z_min
        for x, y in ((x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max))
    ]
    return Part.Face(Part.makePolygon(corners, True)).extrude(
        z_axis * (z_max - z_min)
    )


def _parting_face(point, normal, in_plane):
    """A large face on the parting plane, plus its normal."""
    unit = normal.normalize()
    across = unit.cross(in_plane).normalize()
    corners = [
        point + in_plane * 200.0 + across * 200.0,
        point - in_plane * 200.0 + across * 200.0,
        point - in_plane * 200.0 - across * 200.0,
        point + in_plane * 200.0 - across * 200.0,
    ]
    return Part.Face(Part.makePolygon(corners, True)), unit


def make_block_halves():
    """``(lower, upper, parting_surface, draw)`` - the stand-in mould.

    A 100 x 80 x 60 stock block with a 40 x 30 x 20 cavity, parted by a plane
    tilted about the block's y axis so the mating height varies with x. The
    cavity is rotated 45 degrees in-plane, so its walls are planar and run
    along the draw direction without being parallel to the block walls.
    """
    stock = _oriented_box(X_AXIS, Y_AXIS, Z_AXIS, (0.0, BLOCK[0]),
                          (0.0, BLOCK[1]), (0.0, BLOCK[2]))

    centre = X_AXIS * (BLOCK[0] / 2.0) + Y_AXIS * (BLOCK[1] / 2.0)
    across_x = (X_AXIS + Y_AXIS).normalize()
    across_y = (Y_AXIS - X_AXIS).normalize()
    cavity = _oriented_box(
        across_x, across_y, Z_AXIS,
        (centre.dot(across_x) - CAVITY_HALF[0], centre.dot(across_x) + CAVITY_HALF[0]),
        (centre.dot(across_y) - CAVITY_HALF[1], centre.dot(across_y) + CAVITY_HALF[1]),
        CAVITY_Z,
    )
    body = stock.cut(cavity)

    local_normal = FreeCAD.Vector(0.08, 0.0, 1.0)
    normal = X_AXIS * local_normal.x + Z_AXIS * local_normal.z
    point = X_AXIS * (BLOCK[0] / 2.0) + Y_AXIS * (BLOCK[1] / 2.0) + Z_AXIS * SPLIT_Z
    parting, unit = _parting_face(point, normal, Y_AXIS)
    lower = body.common(parting.extrude(unit * -400.0))
    upper = body.common(parting.extrude(unit * 400.0))
    return lower, upper, parting, Z_AXIS


def _probe(frame, x, y, z_from, z_to, radius):
    start = frame.point(x, y, min(z_from, z_to))
    return Part.makeCylinder(radius, abs(z_to - z_from), start, frame.z_axis)


def _material(shape, probe):
    return shape.common(probe).Volume


def _bore_probe(frame, station, z, from_depth, to_depth, radius):
    """A cylinder along the wall normal, ``from_depth``..``to_depth`` into the block."""
    inward = frame.x_axis * station.inward[0] + frame.y_axis * station.inward[1]
    near = min(from_depth, to_depth)
    wall_point = frame.point(station.x, station.y, z)
    return Part.makeCylinder(radius, abs(to_depth - from_depth),
                             wall_point + inward * near, inward)


def _boundary_length(frame, inset):
    return 2.0 * ((frame.x_max - frame.x_min - 2.0 * inset)
                  + (frame.y_max - frame.y_min - 2.0 * inset))


def _boundary_position(frame, inset, station):
    """Where a station sits along the inset rectangle, in walk order.

    The walk starts at the middle of the +y side and runs +x. Each side is
    identified from the station's own coordinates rather than from the
    layout's own segment table, so this is an independent check on the
    spacing rather than a restatement of it.
    """
    x_lo = frame.x_min + inset
    x_hi = frame.x_max - inset
    y_lo = frame.y_min + inset
    y_hi = frame.y_max - inset
    width = x_hi - x_lo
    height = y_hi - y_lo
    after_top = width / 2.0
    after_right = after_top + height
    after_bottom = after_right + width
    if (abs(station.y - y_hi) <= SIZE_TOL
            and station.x >= frame.x_mid - SIZE_TOL):
        return station.x - frame.x_mid
    if abs(station.x - x_hi) <= SIZE_TOL:
        return after_top + (y_hi - station.y)
    if abs(station.y - y_lo) <= SIZE_TOL:
        return after_right + (x_hi - station.x)
    if abs(station.x - x_lo) <= SIZE_TOL:
        return after_bottom + (station.y - y_lo)
    # Remaining case: the +y side left of its middle, on the closing span.
    return after_bottom + height + (station.x - x_lo)


def _only(**flags):
    """A request with only the named fixture kinds enabled."""
    return FixtureRequest(
        lower=None,
        upper=None,
        draw=None,
        alignment=AlignmentParams(enabled=flags.get("alignment", False)),
        clamping=ClampingParams(bolts_enabled=flags.get("bolts", False),
                                ears_enabled=flags.get("ears", False)),
        ports=PortParams(enabled=flags.get("ports", False)),
        wedges=WedgeParams(enabled=flags.get("wedges", False)),
    )


class TestBlockFrame(unittest.TestCase):
    """Recovering the stock block's own frame from the two halves."""

    def setUp(self):
        self.lower, self.upper, self.parting, self.draw = make_block_halves()

    def test_frame_is_the_block_not_the_world_axes(self):
        frame = block_frame(self.lower, self.upper, self.draw)
        # The draw axis is recovered exactly.
        self.assertAlmostEqual(frame.z_axis.dot(Z_AXIS), 1.0, delta=SIZE_TOL)
        # The block spans its full height along the draw, and its two in-plane
        # extents are the block's own sides - never the world axes' extents.
        self.assertAlmostEqual(frame.size[2], BLOCK[2], delta=SIZE_TOL)
        self.assertEqual(sorted(round(value, 6) for value in frame.size[:2]),
                         [BLOCK[1], BLOCK[0]])
        # Both in-plane axes lie along the block's own in-plane axes.
        for axis in (frame.x_axis, frame.y_axis):
            best = max(abs(axis.dot(candidate)) for candidate in (X_AXIS, Y_AXIS))
            self.assertAlmostEqual(best, 1.0, delta=SIZE_TOL)

    def test_frame_axes_are_orthonormal_and_right_handed(self):
        frame = block_frame(self.lower, self.upper, self.draw)
        for axis in (frame.x_axis, frame.y_axis, frame.z_axis):
            self.assertAlmostEqual(axis.Length, 1.0, delta=SIZE_TOL)
        self.assertAlmostEqual(frame.x_axis.dot(frame.y_axis), 0.0, delta=SIZE_TOL)
        self.assertAlmostEqual(frame.x_axis.dot(frame.z_axis), 0.0, delta=SIZE_TOL)
        self.assertAlmostEqual(frame.y_axis.dot(frame.z_axis), 0.0, delta=SIZE_TOL)

    def test_cavity_walls_are_not_taken_for_block_walls(self):
        # The cavity is rotated in-plane, so its four wall planes carry
        # directions that are neither block axes nor world axes. Only the
        # block's own two directions may survive the extreme-offset filter;
        # four directions here means a cavity wall was trusted.
        points = [vertex.Point for vertex in self.lower.Vertexes]
        points += [vertex.Point for vertex in self.upper.Vertexes]
        normals = _wall_normals(self.lower, points, self.draw)
        self.assertEqual(len(normals), 2)

    def test_frame_is_reproducible(self):
        first = block_frame(self.lower, self.upper, self.draw)
        second = block_frame(self.lower, self.upper, self.draw)
        self.assertEqual(first, second)

    def test_halves_tile_the_block(self):
        total = self.lower.Volume + self.upper.Volume
        cavity = 4.0 * CAVITY_HALF[0] * CAVITY_HALF[1] * (CAVITY_Z[1] - CAVITY_Z[0])
        expected = BLOCK[0] * BLOCK[1] * BLOCK[2] - cavity
        self.assertAlmostEqual(total, expected, delta=1e-3)

    def test_non_block_input_is_refused(self):
        ball = Part.makeSphere(10.0)
        with self.assertRaises(MouldFixtureError):
            block_frame(ball, ball, FreeCAD.Vector(0, 0, 1))


class TestUpperLowerOrdering(unittest.TestCase):
    def setUp(self):
        self.lower, self.upper, self.parting, self.draw = make_block_halves()

    def test_named_order_is_reported_as_matching(self):
        _, _, matches = upper_lower(self.lower, self.upper, self.draw)
        self.assertTrue(matches)

    def test_reversed_order_is_reported(self):
        lower, upper, matches = upper_lower(self.upper, self.lower, self.draw)
        self.assertFalse(matches)
        self.assertAlmostEqual(lower.Volume, self.lower.Volume, delta=1e-6)
        self.assertAlmostEqual(upper.Volume, self.upper.Volume, delta=1e-6)


class TestFixtureLayouts(unittest.TestCase):
    def setUp(self):
        self.lower, self.upper, self.parting, self.draw = make_block_halves()
        self.frame = block_frame(self.lower, self.upper, self.draw)

    def test_corner_positions_are_inside_the_inset_block(self):
        inset = 20.0
        positions = corner_positions(self.frame, 4, inset)
        self.assertEqual(len(positions), 4)
        for x, y in positions:
            self.assertGreaterEqual(x, self.frame.x_min + inset - SIZE_TOL)
            self.assertLessEqual(x, self.frame.x_max - inset + SIZE_TOL)
            self.assertGreaterEqual(y, self.frame.y_min + inset - SIZE_TOL)
            self.assertLessEqual(y, self.frame.y_max - inset + SIZE_TOL)

    def test_corner_positions_reject_an_impossible_count(self):
        with self.assertRaises(MouldFixtureError):
            corner_positions(self.frame, 5, 20.0)

    def test_corner_positions_reject_an_impossible_inset(self):
        with self.assertRaises(MouldFixtureError):
            corner_positions(self.frame, 2, 1.0e6)

    def test_perimeter_stations_are_evenly_spaced_and_inward(self):
        inset = 5.0
        stations = perimeter_stations(self.frame, 6, inset)
        self.assertEqual(len(stations), 6)
        centre = self.frame.point(self.frame.x_mid, self.frame.y_mid, 0.0)
        positions = []
        for station in stations:
            self.assertAlmostEqual(math.hypot(*station.inward), 1.0, delta=SIZE_TOL)
            self.assertAlmostEqual(math.hypot(*station.tangent), 1.0, delta=SIZE_TOL)
            # The station lies on the inset rectangle: inside it, and tight
            # against at least one of its four sides.
            gaps = (
                abs(station.x - (self.frame.x_min + inset)),
                abs(station.x - (self.frame.x_max - inset)),
                abs(station.y - (self.frame.y_min + inset)),
                abs(station.y - (self.frame.y_max - inset)),
            )
            self.assertGreaterEqual(station.x, self.frame.x_min + inset - SIZE_TOL)
            self.assertLessEqual(station.x, self.frame.x_max - inset + SIZE_TOL)
            self.assertGreaterEqual(station.y, self.frame.y_min + inset - SIZE_TOL)
            self.assertLessEqual(station.y, self.frame.y_max - inset + SIZE_TOL)
            self.assertLess(min(gaps), SIZE_TOL)
            # Its inward direction points at the block centre rather than away.
            point = self.frame.point(station.x, station.y, 0.0)
            inward = (self.frame.x_axis * station.inward[0]
                      + self.frame.y_axis * station.inward[1])
            self.assertGreater((centre - point).dot(inward), 0.0)
            positions.append(_boundary_position(self.frame, inset, station))
        # Even spacing is along the perimeter, not straight-line between
        # stations: a step that straddles a corner is shorter as a chord than
        # as a walk, so the chords are not equal even when the walk is.
        perimeter = _boundary_length(self.frame, inset)
        for index, position in enumerate(positions):
            following = positions[(index + 1) % len(positions)]
            step = (following - position) % perimeter
            self.assertAlmostEqual(step, perimeter / len(positions), delta=1e-6)

    def test_perimeter_layout_is_reproducible(self):
        first = perimeter_stations(self.frame, 4, 0.0, phase=0.25)
        second = perimeter_stations(self.frame, 4, 0.0, phase=0.25)
        self.assertEqual(first, second)

    def test_wedge_slots_stop_short_of_every_corner(self):
        """Each wall carries one slot, trimmed back from both of its corners.

        A parting wedge is driven in along a wall, so the slot runs the wall
        rather than sitting at a point: what it leaves is the corner standoff,
        which keeps the alignment sockets clear and gives a wedge somewhere to
        bite without running out of the block edge.
        """
        standoff = 50.0
        runs = _wall_runs(self.frame, standoff)
        self.assertEqual(len(runs), 4)
        spans = [self.frame.x_max - self.frame.x_min,
                 self.frame.y_max - self.frame.y_min]
        for station, length in runs:
            # The run is the wall's full span less the standoff at either end.
            full = spans[0] if abs(station.tangent[0]) > 0.5 else spans[1]
            self.assertAlmostEqual(length, full - 2.0 * standoff, delta=1e-9)
            self.assertAlmostEqual(math.hypot(*station.tangent), 1.0, delta=SIZE_TOL)
            self.assertAlmostEqual(math.hypot(*station.inward), 1.0, delta=SIZE_TOL)
            # Centred on the wall, and on it rather than inside the block.
            if abs(station.tangent[0]) > 0.5:
                self.assertAlmostEqual(station.x, self.frame.x_mid, delta=1e-9)
                self.assertIn(round(station.y, 6),
                              (round(self.frame.y_min, 6), round(self.frame.y_max, 6)))
            else:
                self.assertAlmostEqual(station.y, self.frame.y_mid, delta=1e-9)
                self.assertIn(round(station.x, 6),
                              (round(self.frame.x_min, 6), round(self.frame.x_max, 6)))

    def test_wedge_standoff_that_consumes_the_wall_is_refused(self):
        with self.assertRaises(MouldFixtureError):
            _wall_runs(self.frame, 1.0e6)
        with self.assertRaises(MouldFixtureError):
            _wall_runs(self.frame, -1.0)


class TestFixtureCuts(unittest.TestCase):
    """Every cut is checked against the material that must be there and gone."""

    def setUp(self):
        self.lower, self.upper, self.parting, self.draw = make_block_halves()
        self.frame = block_frame(self.lower, self.upper, self.draw)

    def _request(self, **flags):
        request = _only(**flags)
        request.lower = self.lower
        request.upper = self.upper
        request.draw = self.draw
        request.parting_surface = self.parting
        return request

    def _build(self, **flags):
        return build_fixtures(self._request(**flags))

    def _alignment(self, **overrides):
        """Alignment params with a depth that leaves each seat a floor.

        The stand-in block is 60 mm tall with the pins sitting where the mating
        height is about 32 mm, so 15 mm leaves material below the pin and above
        the bush. Pinned here so these tests do not shift when the production
        default does.
        """
        settings = {"enabled": True, "count": 2, "depth": 15.0}
        settings.update(overrides)
        return AlignmentParams(**settings)

    def _mating_height(self, x, y, frame):
        from Composites.tools.mould_fixture import MouldBlock

        return MouldBlock(frame, self.parting).mating_height(x, y)

    def test_alignment_cuts_a_socket_in_each_half(self):
        request = self._request()
        request.alignment = self._alignment()
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Ready", result["summary"])
        self.assertEqual(result["alignment_holes"], 4)
        # The parting surface is a tilted plane, so the mating height varies
        # across the block and every lookup must have crossed it.
        self.assertEqual(result["mating_fallbacks"], 0)
        geometry = block_frame(result["lower_shape"], result["upper_shape"], self.draw)
        for x, y in corner_positions(geometry, 2, self._alignment().edge_offset):
            z_mate = self._mating_height(x, y, geometry)
            # A dowel socket in the pin (lower) half.
            probe = _probe(geometry, x, y, z_mate - 12.0, z_mate - 3.0, 2.0)
            self.assertLess(_material(result["lower_shape"], probe), PROBE_TOL)
            self.assertGreater(_material(self.lower, probe), 100.0)
            # A wider bush socket in the upper half.
            probe = _probe(geometry, x, y, z_mate + 3.0, z_mate + 12.0, 5.0)
            self.assertLess(_material(result["upper_shape"], probe), PROBE_TOL)
            self.assertGreater(_material(self.upper, probe), 100.0)

    def test_alignment_height_follows_the_tilted_parting_surface(self):
        # The pin half's depth is measured from its own local mating height, so
        # two pins at different x get different socket floors. A single plane
        # for the whole block would make these equal.
        request = self._request()
        request.alignment = self._alignment()
        result = build_fixtures(request)
        geometry = block_frame(result["lower_shape"], result["upper_shape"], self.draw)
        heights = [self._mating_height(x, y, geometry)
                   for x, y in corner_positions(geometry, 2,
                                                self._alignment().edge_offset)]
        self.assertGreater(abs(heights[0] - heights[1]), 1.0)

    def test_over_deep_socket_is_reported(self):
        # Deeper than the material available below and above the pins' own
        # mating heights. The sockets come out as through holes, which the
        # boolean cannot distinguish from a blind socket, so the arithmetic
        # has to be what says so.
        request = self._request()
        request.alignment = self._alignment(depth=60.0)
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Ready", result["summary"])
        self.assertTrue(result["issues"])
        for issue in result["issues"]:
            self.assertIn("breaks through", issue)
        self.assertIn("breaks through", result["summary"])

    def test_sockets_that_stop_blind_are_not_reported(self):
        request = self._request()
        request.alignment = self._alignment(depth=10.0)
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Ready", result["summary"])
        self.assertEqual(result["issues"], [])

    def test_pins_and_bushes_are_different_diameters(self):
        # The two seats are sized independently, which a dowel-and-bush pair
        # needs even though the default round interlock pair does not.
        request = self._request()
        request.alignment = self._alignment(pin_diameter=8.0, bush_diameter=16.0)
        result = build_fixtures(request)
        geometry = block_frame(result["lower_shape"], result["upper_shape"], self.draw)
        x, y = corner_positions(geometry, 2, self._alignment().edge_offset)[0]
        z_mate = self._mating_height(x, y, geometry)
        # Just outside the pin diameter (8 mm) but inside the bush diameter
        # (16 mm): material must be gone from the patch above the mating plane.
        probe = _probe(geometry, x, y, z_mate + 3.0, z_mate + 12.0, 6.0)
        self.assertLess(_material(result["upper_shape"], probe), PROBE_TOL)
        # And below the socket floor: material must remain, i.e. the bush is
        # blind rather than drilled through the cap.
        deeper = _probe(geometry, x, y, z_mate + 18.0, z_mate + 23.0, 6.0)
        self.assertGreater(_material(result["upper_shape"], deeper), 300.0)

    def _seat_ring_material(self, shape, geometry, offset):
        """Material on a ring around each pin seat, just below the mating face.

        Sampled off the seat's axis rather than on it, so it reads the annulus
        between the bore wall and the counterbore wall and nothing else.
        """
        total = 0.0
        for x, y in corner_positions(geometry, 2, self._alignment().edge_offset):
            z_mate = self._mating_height(x, y, geometry)
            probe = _probe(geometry, x + offset, y, z_mate - 3.0, z_mate - 1.0, 1.0)
            total += _material(shape, probe)
        return total

    def test_seat_shoulder_cuts_a_counterbore(self):
        """A locating part's flange seats on a counterbore, cut from the face."""
        request = self._request()
        request.alignment = self._alignment(pin_diameter=8.0,
                                           shoulder_diameter=20.0,
                                           shoulder_depth=5.0)
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Ready", result["summary"])
        geometry = block_frame(result["lower_shape"], result["upper_shape"], self.draw)
        # Between the 4 mm bore wall and the 10 mm counterbore wall, just under
        # the face: the counterbore has taken it.
        self.assertLess(self._seat_ring_material(
            result["lower_shape"], geometry, 5.0), PROBE_TOL)
        # And it was material before the cut.
        self.assertGreater(self._seat_ring_material(self.lower, geometry, 5.0), 1.0)

    def test_no_counterbore_is_cut_unless_one_is_asked_for(self):
        request = self._request()
        request.alignment = self._alignment(pin_diameter=8.0)
        result = build_fixtures(request)
        geometry = block_frame(result["lower_shape"], result["upper_shape"], self.draw)
        self.assertGreater(self._seat_ring_material(
            result["lower_shape"], geometry, 5.0), 1.0)

    def test_seat_vent_opens_the_floor_to_the_cap(self):
        """A blind seat is a trapped volume, which reads as a leak under vacuum."""
        request = self._request()
        # The screw hole would also open the floor, so it is off here and the
        # vent is the only cut that could reach below it. The head counterbore
        # goes with it: there is nothing for it to sink a screw into.
        request.alignment = self._alignment(depth=10.0, vent_diameter=2.0,
                                           screw_diameter=0.0,
                                           screw_head_diameter=0.0,
                                           screw_head_depth=0.0)
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Ready", result["summary"])
        geometry = block_frame(result["lower_shape"], result["upper_shape"], self.draw)
        for x, y in corner_positions(geometry, 2, self._alignment().edge_offset):
            z_mate = self._mating_height(x, y, geometry)
            # Below the seat floor, on the seat's own axis: the vent is the only
            # cut that reaches there.
            probe = _probe(geometry, x, y, z_mate - 12.0, z_mate - 11.0, 0.5)
            self.assertLess(_material(result["lower_shape"], probe), PROBE_TOL)
            self.assertGreater(_material(self.lower, probe), 0.5)

    def test_no_vent_is_cut_unless_one_is_asked_for(self):
        request = self._request()
        request.alignment = self._alignment(depth=10.0, screw_diameter=0.0,
                                           screw_head_diameter=0.0,
                                           screw_head_depth=0.0)
        result = build_fixtures(request)
        geometry = block_frame(result["lower_shape"], result["upper_shape"], self.draw)
        for x, y in corner_positions(geometry, 2, self._alignment().edge_offset):
            z_mate = self._mating_height(x, y, geometry)
            probe = _probe(geometry, x, y, z_mate - 12.0, z_mate - 11.0, 0.5)
            self.assertGreater(_material(result["lower_shape"], probe), 0.5)

    def test_the_default_part_is_screw_fixed(self):
        """The defaults are a matched A1-10 interlock pair, held by an M5."""
        params = AlignmentParams()
        self.assertAlmostEqual(params.pin_diameter, 10.0, delta=1e-9)
        self.assertAlmostEqual(params.bush_diameter, 10.0, delta=1e-9)
        self.assertAlmostEqual(params.depth, 10.0, delta=1e-9)
        self.assertAlmostEqual(params.screw_diameter, 5.5, delta=1e-9)
        self.assertAlmostEqual(params.screw_head_diameter, 9.5, delta=1e-9)
        self.assertAlmostEqual(params.screw_head_depth, 5.5, delta=1e-9)

    def test_screw_head_counterbore_is_cut_at_the_cap_face(self):
        """The head sinks into the face behind the seat, not the mating face."""
        request = self._request()
        request.alignment = self._alignment(depth=10.0, screw_diameter=5.5,
                                           screw_head_diameter=9.5,
                                           screw_head_depth=5.5)
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Ready", result["summary"])
        geometry = block_frame(result["lower_shape"], result["upper_shape"], self.draw)
        for x, y in corner_positions(geometry, 2, self._alignment().edge_offset):
            # Off the screw's axis but inside the 9.5 mm counterbore, at the cap
            # face: material gone.
            under_head = _probe(geometry, x + 4.0, y, geometry.z_min + 1.0,
                                geometry.z_min + 3.0, 0.5)
            self.assertLess(_material(result["lower_shape"], under_head), PROBE_TOL)
            # Outside it: the cap face is intact.
            beside_head = _probe(geometry, x + 6.0, y, geometry.z_min + 1.0,
                                 geometry.z_min + 3.0, 0.5)
            self.assertGreater(_material(result["lower_shape"], beside_head), 0.5)

    def test_a_head_counterbore_that_swallows_the_screw_hole_is_refused(self):
        # The block behind the seat is only about 17 mm at the test depth, so a
        # 100 mm counterbore meets the seat floor and leaves the screw nowhere
        # to pass. Nothing else could report that: the seat itself is sound.
        request = self._request()
        request.alignment = self._alignment(screw_head_depth=100.0)
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Fail")
        self.assertIn("leaves nothing", result["summary"])

    def test_a_head_narrower_than_the_screw_is_refused(self):
        request = self._request()
        request.alignment = self._alignment(screw_diameter=5.5,
                                           screw_head_diameter=5.0,
                                           screw_head_depth=3.0)
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Fail")
        self.assertIn("does not counterbore", result["summary"])

    def test_a_head_counterbore_without_a_screw_hole_is_refused(self):
        request = self._request()
        request.alignment = self._alignment(screw_diameter=0.0,
                                           screw_head_diameter=9.5,
                                           screw_head_depth=5.5)
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Fail")
        self.assertIn("needs a screw clearance hole", result["summary"])

    def test_seat_screw_hole_opens_the_floor_to_the_back(self):
        """A screw-fixed part is reached from the cap face behind its seat."""
        request = self._request()
        request.alignment = self._alignment(depth=10.0, screw_diameter=5.5)
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Ready", result["summary"])
        geometry = block_frame(result["lower_shape"], result["upper_shape"], self.draw)
        for x, y in corner_positions(geometry, 2, self._alignment().edge_offset):
            z_mate = self._mating_height(x, y, geometry)
            # On the seat's axis, below its floor: the clearance hole is there.
            through = _probe(geometry, x, y, z_mate - 13.0, z_mate - 12.0, 2.0)
            self.assertLess(_material(result["lower_shape"], through), PROBE_TOL)
            # Off the axis but inside the seat's own footprint, below the floor:
            # untouched, so the hole did not widen the seat.
            beside = _probe(geometry, x + 4.0, y, z_mate - 13.0, z_mate - 12.0, 0.5)
            self.assertGreater(_material(result["lower_shape"], beside), 0.5)

    def test_a_screw_clearance_as_wide_as_the_seat_is_refused(self):
        request = self._request()
        request.alignment = self._alignment(pin_diameter=10.0, bush_diameter=10.0,
                                           screw_diameter=10.0)
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Fail")
        self.assertIn("seat screw clearance", result["summary"])

    def test_a_shoulder_narrower_than_the_seat_is_refused(self):
        request = self._request()
        request.alignment = self._alignment(pin_diameter=10.0, bush_diameter=10.0,
                                           shoulder_diameter=8.0,
                                           shoulder_depth=3.0)
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Fail")
        self.assertIn("does not countersink", result["summary"])

    def test_a_shoulder_deeper_than_the_seat_is_refused(self):
        request = self._request()
        request.alignment = self._alignment(depth=15.0, shoulder_diameter=20.0,
                                           shoulder_depth=15.0)
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Fail")
        self.assertIn("reaches past", result["summary"])

    def test_a_vent_as_wide_as_the_seat_is_refused(self):
        request = self._request()
        request.alignment = self._alignment(pin_diameter=8.0, vent_diameter=8.0)
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Fail")
        self.assertIn("seat vent diameter", result["summary"])

    def test_the_clearance_rule_uses_the_shoulder_radius(self):
        """The counterbore removes more than the bore, so it sets the clearance.

        Holding the bore clear while the counterbore reaches the wall would
        report nothing and cut into it.
        """
        params = AlignmentParams(enabled=True, pin_diameter=8.0,
                                 bush_diameter=16.0, shoulder_diameter=30.0,
                                 shoulder_depth=4.0)
        self.assertAlmostEqual(_seat_radius(params), 15.0, delta=1e-9)
        zones = _pin_zones(self.frame, params)
        self.assertTrue(zones)
        for _x, _y, radius in zones:
            self.assertAlmostEqual(radius, 15.0, delta=1e-9)

    def test_a_bolt_goes_right_through_both_halves(self):
        """A through-bolt, nutted on top, with its head sunk in the lower face."""
        result = self._build(bolts=True)
        self.assertEqual(result["status"], "Ready", result["summary"])
        self.assertEqual(result["bolt_holes"], 4)
        geometry = block_frame(result["lower_shape"], result["upper_shape"], self.draw)
        # The pattern's phase is chosen by the build, so the stations are read
        # from the result rather than recomputed at a guessed phase.
        for x, y in result["bolt_stations"]:
            z_mate = self._mating_height(x, y, geometry)
            # Clearance right through the upper half, out at its cap face.
            upper_probe = _probe(geometry, x, y, z_mate + 0.5,
                                 geometry.z_max - 0.5, 3.0)
            self.assertLess(_material(result["upper_shape"], upper_probe),
                            PROBE_TOL)
            self.assertGreater(_material(self.upper, upper_probe), 100.0)
            # And right through the lower half, out at its cap face.
            lower_probe = _probe(geometry, x, y, geometry.z_min + 0.5,
                                 z_mate - 0.5, 3.0)
            self.assertLess(_material(result["lower_shape"], lower_probe),
                            PROBE_TOL)
            # The head counterbore is in that lower cap face, where the head
            # would otherwise stand proud of it.
            under_head = _probe(geometry, x + 6.0, y, geometry.z_min + 1.0,
                                geometry.z_min + 3.0, 0.5)
            self.assertLess(_material(result["lower_shape"], under_head), PROBE_TOL)
            self.assertGreater(_material(self.lower, under_head), 0.5)

    def test_clamp_ear_notches_cut_both_halves(self):
        result = self._build(ears=True)
        self.assertEqual(result["status"], "Ready", result["summary"])
        self.assertEqual(result["clamp_notches"], 4)
        self.assertLess(result["lower_shape"].Volume, self.lower.Volume)
        self.assertLess(result["upper_shape"].Volume, self.upper.Volume)

    def test_process_ports_bore_in_from_the_wall(self):
        request = self._request()
        request.ports = PortParams(enabled=True, count=2, half="Lower")
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Ready", result["summary"])
        self.assertEqual(result["port_bores"], 2)
        geometry = block_frame(result["lower_shape"], result["upper_shape"], self.draw)
        for station in _port_stations(self.frame, 2):
            z_bore = self._mating_height(station.x, station.y, geometry) - 8.0
            # The bore opens at the wall...
            mouth = _bore_probe(geometry, station, z_bore, 0.5, 2.0, 2.0)
            self.assertLess(_material(result["lower_shape"], mouth), PROBE_TOL)
            self.assertGreater(_material(self.lower, mouth), 10.0)
            # ...and runs on into the block.
            shaft = _bore_probe(geometry, station, z_bore, 4.0, 30.0, 2.0)
            self.assertGreater(_material(self.lower, shaft), 10.0)
            self.assertLess(_material(result["lower_shape"], shaft),
                            _material(self.lower, shaft))
        # A lower-half port leaves the other half alone.
        self.assertAlmostEqual(result["upper_shape"].Volume, self.upper.Volume,
                               delta=1e-6)

    def test_process_ports_can_serve_both_halves(self):
        request = self._request()
        request.ports = PortParams(enabled=True, count=2, half="Both")
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Ready", result["summary"])
        self.assertEqual(result["port_bores"], 4)
        self.assertLess(result["lower_shape"].Volume, self.lower.Volume)
        self.assertLess(result["upper_shape"].Volume, self.upper.Volume)

    def test_unknown_port_half_is_refused(self):
        request = self._request()
        request.ports = PortParams(enabled=True, half="Middle")
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Fail")
        self.assertIn("port half", result["summary"])

    def test_parting_wedges_are_a_mirror_image_in_both_halves(self):
        result = self._build(wedges=True)
        self.assertEqual(result["status"], "Ready", result["summary"])
        self.assertEqual(result["wedge_count"], 4)
        removed_lower = self.lower.Volume - result["lower_shape"].Volume
        removed_upper = self.upper.Volume - result["upper_shape"].Volume
        self.assertGreater(removed_lower, 100.0)
        self.assertAlmostEqual(removed_lower, removed_upper, delta=1e-3)

    def test_wedge_slots_run_each_wall_and_stop_at_the_corner_standoff(self):
        """The slot reaches the run's ends and leaves the standoff uncut.

        Probed either side of the run's end, because that is what the standoff
        means: a wedge has to be able to bite anywhere along the wall, and the
        corners have to survive one driven too hard.
        """
        params = WedgeParams()
        request = self._request(wedges=True)
        request.wedges = params
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Ready", result["summary"])
        frame = block_frame(result["lower_shape"], result["upper_shape"], self.draw)
        for station, length in _wall_runs(frame, params.corner_standoff):
            tangent = (frame.x_axis * station.tangent[0]
                       + frame.y_axis * station.tangent[1])
            centre = frame.point(station.x, station.y, 0.0)
            for end in (-1.0, 1.0):
                for offset, cut in ((length / 2.0 - 2.0, True),
                                    (length / 2.0 + 2.0, False)):
                    local = frame.local(centre + tangent * (end * offset))
                    x, y = local[0], local[1]
                    z_mate = self._mating_height(x, y, frame)
                    probe = _probe(frame, x, y, z_mate - 3.0, z_mate - 1.0, 1.0)
                    whole = _material(self.lower, probe)
                    self.assertGreater(whole, 1.0)
                    left = _material(result["lower_shape"], probe)
                    if cut:
                        self.assertLess(
                            left, PROBE_TOL,
                            "no slot %.3f mm along the wall" % offset)
                    else:
                        self.assertAlmostEqual(
                            left, whole, delta=1e-6,
                            msg="standoff cut %.3f mm along the wall" % offset)

    def test_wedge_slots_are_interrupted_where_a_port_enters(self):
        """A bore in the same wall must not break into the slot.

        Shown by contrast: the same slot built without the keep-out does share
        material with the bore, so it is the interruption that stops it rather
        than the two happening to miss.
        """
        result = self._build(ports=True, wedges=True)
        self.assertEqual(result["status"], "Ready", result["summary"])
        self.assertEqual([issue for issue in result["issues"] if "share" in issue], [])

        frame = block_frame(self.lower, self.upper, self.draw)
        mould = MouldBlock(frame=frame, parting_surface=self.parting,
                           lower=self.lower, upper=self.upper)
        for half, index in (("Lower", 0), ("Upper", 1)):
            port_lower, port_upper, bores, specs = _port_tools(
                mould, PortParams(enabled=True, count=2, half=half))
            ports = port_lower if half == "Lower" else port_upper
            # The bores land in the half they are bored into, not the other.
            self.assertEqual(len(ports), bores)
            self.assertTrue(ports)
            uninterrupted = _wedge_tools(mould, WedgeParams())[index]
            interrupted = _wedge_tools(mould, WedgeParams(), specs)[index]
            self.assertTrue(interrupted)
            for port in ports:
                for wedge in interrupted:
                    self.assertLessEqual(
                        _shared_volume(port, wedge), INTERFERENCE_VOLUME_TOL,
                        "the %s slot was not interrupted" % half)
                self.assertTrue(
                    any(_shared_volume(port, wedge) > INTERFERENCE_VOLUME_TOL
                        for wedge in uninterrupted),
                    "the %s bore does not reach the slot anyway" % half)

    def test_every_fixture_kind_together(self):
        result = self._build(alignment=True, bolts=True, ears=True, ports=True,
                             wedges=True)
        self.assertEqual(result["status"], "Ready", result["summary"])
        self.assertEqual(result["alignment_holes"], 4)
        self.assertEqual(result["bolt_holes"], 4)
        self.assertEqual(result["clamp_notches"], 4)
        self.assertEqual(result["port_bores"], 2)
        self.assertEqual(result["wedge_count"], 4)
        for original, cut in ((self.lower, result["lower_shape"]),
                              (self.upper, result["upper_shape"])):
            self.assertTrue(cut.isValid())
            self.assertEqual(len(cut.Solids), 1)
            self.assertLess(cut.Volume, original.Volume)

    def test_frame_information_survives_the_rebuilt_halves(self):
        result = self._build(alignment=True, wedges=True)
        rebuilt = block_frame(result["lower_shape"], result["upper_shape"], self.draw)
        for recovered, original in zip(rebuilt.size, self.frame.size):
            self.assertAlmostEqual(recovered, original, delta=1e-9)

    def test_nothing_to_measure_from_falls_back_and_says_so(self):
        """With neither a parting surface nor a half, the mid-height is used.

        The fallback is the last resort rather than the first: a missing parting
        surface no longer degrades anything, because the lower half's own top
        face carries the interface and varies with position. It is reached only
        when there is nothing at all to section, so this pins it there - on the
        block - and the summary wording that carries the count.
        """
        frame = block_frame(self.lower, self.upper, self.draw)
        block = MouldBlock(frame=frame, parting_surface=None, lower=None)
        self.assertAlmostEqual(block.mating_height(0.0, 0.0), frame.z_mid)
        self.assertEqual(block.mating_fallbacks, 1)
        self.assertIn("mid-height", _summary(
            {"alignment_holes": 0, "bolt_holes": 0, "clamp_notches": 0,
             "port_bores": 0, "wedge_count": 0, "mating_fallbacks": 1,
             "issues": []}, frame))

    def test_bolts_are_placed_clear_of_the_corner_pin_sockets(self):
        """The bolt pattern shifts so it does not cut into the sockets.

        Default pins sit on the block corners and default bolts on the block
        perimeter, which met on the corner stations: 2.66 mm of interference on
        two of the four bolts, worse in the upper half where the bush socket is
        the larger of the pair. The pattern stays equally spaced; only where it
        starts moves.
        """
        request = _only(alignment=True, bolts=True)
        request.lower = self.lower
        request.upper = self.upper
        request.draw = self.draw
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Ready", result["summary"])
        self.assertEqual([issue for issue in result["issues"] if "share" in issue], [])

        # Asserted from the tools themselves, not from the report above.
        frame = block_frame(self.lower, self.upper, self.draw)
        mould = MouldBlock(frame=frame, parting_surface=None, lower=self.lower)
        pins, _pins_upper, _holes = _alignment_tools(mould, AlignmentParams())
        bolts, _bolts_upper, _bolt_holes, _notches, _stations = _clamping_tools(
            mould, ClampingParams(), _pin_zones(frame, AlignmentParams()))
        for pin in pins:
            for bolt in bolts:
                self.assertLessEqual(pin.common(bolt).Volume,
                                     INTERFERENCE_VOLUME_TOL)

    def test_reversed_half_arguments_still_cut_the_right_half(self):
        straight = self._build(alignment=True)
        request = _only(alignment=True)
        request.lower = self.upper
        request.upper = self.lower
        request.draw = self.draw
        request.parting_surface = self.parting
        reversed_result = build_fixtures(request)
        self.assertEqual(reversed_result["status"], "Ready", reversed_result["summary"])
        self.assertTrue(any("reversed" in issue
                            for issue in reversed_result["issues"]))
        self.assertAlmostEqual(reversed_result["lower_shape"].Volume,
                               straight["lower_shape"].Volume, delta=1e-6)
        self.assertAlmostEqual(reversed_result["upper_shape"].Volume,
                               straight["upper_shape"].Volume, delta=1e-6)

    def test_shell_halves_are_refused_with_a_reason(self):
        request = _only(alignment=True)
        request.lower = self.lower.Shells[0]
        request.upper = self.upper
        request.draw = self.draw
        request.parting_surface = self.parting
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Fail")
        self.assertIn("no solid to cut", result["summary"])

    def test_null_halves_are_refused(self):
        request = _only(alignment=True)
        request.lower = Part.Shape()
        request.upper = self.upper
        request.draw = self.draw
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Fail")
        self.assertIn("null", result["summary"])

    def test_impossible_pin_count_is_refused(self):
        request = _only(alignment=True)
        request.lower = self.lower
        request.upper = self.upper
        request.draw = self.draw
        request.parting_surface = self.parting
        request.alignment = AlignmentParams(enabled=True, count=9)
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Fail")
        self.assertIn("outside 1..4", result["summary"])

    def test_unknown_pin_half_is_refused(self):
        request = _only(alignment=True)
        request.lower = self.lower
        request.upper = self.upper
        request.draw = self.draw
        request.parting_surface = self.parting
        request.alignment = AlignmentParams(enabled=True, pin_half="Middle")
        result = build_fixtures(request)
        self.assertEqual(result["status"], "Fail")
        self.assertIn("pin half", result["summary"])

    def test_nothing_enabled_is_a_no_op(self):
        result = self._build()
        self.assertEqual(result["status"], "Ready", result["summary"])
        self.assertAlmostEqual(result["lower_shape"].Volume, self.lower.Volume,
                               delta=1e-6)
        self.assertAlmostEqual(result["upper_shape"].Volume, self.upper.Volume,
                               delta=1e-6)


class TestFixtureInterference(unittest.TestCase):
    """Fixtures cut into one half must not share material."""

    def _cylinder(self, radius, x):
        return Part.makeCylinder(radius, 20.0, FreeCAD.Vector(x, 0.0, 0.0))

    def test_overlapping_fixtures_are_reported(self):
        issues = _interference_issues([(ALIGN_KIND, self._cylinder(4.0, 0.0)),
                                       (CLAMP_KIND, self._cylinder(4.0, 2.0))])
        self.assertEqual(len(issues), 1)
        self.assertIn(ALIGN_KIND, issues[0])
        self.assertIn(CLAMP_KIND, issues[0])

    def test_fixtures_that_miss_are_not_reported(self):
        self.assertEqual(
            _interference_issues([(ALIGN_KIND, self._cylinder(4.0, 0.0)),
                                  (CLAMP_KIND, self._cylinder(4.0, 50.0))]),
            [])

    def test_fixtures_that_merely_touch_are_not_reported(self):
        # Tangent cylinders share no material; only real overlap counts.
        self.assertEqual(
            _interference_issues([(ALIGN_KIND, self._cylinder(4.0, 0.0)),
                                  (CLAMP_KIND, self._cylinder(4.0, 8.0))]),
            [])


class TestSkirtClearance(unittest.TestCase):
    """A diameter of web between every hole and both edges of the skirt.

    The skirt is the material between the part outline (its inner edge) and the
    block wall (its outer edge); a pin or bolt socket keeps
    ``SKIRT_CLEARANCE_FACTOR`` of its own radius of gap from every one of those,
    and from every other socket. Reported rather than cut thinner, because the
    fix is a wider offset or a smaller hole.
    """

    def _frame(self):
        return BlockFrame(x_axis=X_AXIS, y_axis=Y_AXIS, z_axis=Z_AXIS,
                          x_min=0.0, x_max=100.0, y_min=0.0, y_max=100.0,
                          z_min=0.0, z_max=50.0)

    def _square_outline(self, low=40.0, high=60.0):
        corners = [(low, low), (high, low), (high, high), (low, high)]
        return [(ax, ay, bx, by)
                for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1])]

    def test_a_socket_too_close_to_the_wall_is_reported(self):
        issues = _clearance_issues(
            self._frame(), [],
            [(ALIGN_KIND, PIN_OFFSET_PROPERTY, 5.0, 50.0, 4.0, 4.0)])
        self.assertEqual(len(issues), 1)
        self.assertIn("block wall", issues[0])
        self.assertIn(PIN_OFFSET_PROPERTY, issues[0])

    def test_a_socket_too_close_to_the_part_outline_is_reported(self):
        issues = _clearance_issues(
            self._frame(), self._square_outline(),
            [(CLAMP_KIND, BOLT_OFFSET_PROPERTY, 50.0, 70.0, 4.0, 4.0)])
        self.assertEqual(len(issues), 1)
        self.assertIn("part outline", issues[0])
        self.assertIn(BOLT_OFFSET_PROPERTY, issues[0])

    def test_sockets_too_close_to_each_other_are_reported(self):
        issues = _clearance_issues(
            self._frame(), [],
            [(ALIGN_KIND, PIN_OFFSET_PROPERTY, 30.0, 50.0, 4.0, 4.0),
             (CLAMP_KIND, BOLT_OFFSET_PROPERTY, 40.0, 50.0, 4.0, 4.0)])
        self.assertEqual(len(issues), 1)
        self.assertIn(ALIGN_KIND, issues[0])
        self.assertIn(CLAMP_KIND, issues[0])

    def test_sockets_with_a_diameter_of_web_are_not_reported(self):
        self.assertEqual(_clearance_issues(
            self._frame(), self._square_outline(),
            [(ALIGN_KIND, PIN_OFFSET_PROPERTY, 20.0, 50.0, 4.0, 4.0),
             (CLAMP_KIND, BOLT_OFFSET_PROPERTY, 80.0, 50.0, 4.0, 4.0)]), [])

    def test_the_rule_is_a_diameter_of_web(self):
        # A radius-4 socket needs 8 mm of gap, so its centre needs x >= 12.
        self.assertEqual(SKIRT_CLEARANCE_FACTOR, 2.0)
        frame = self._frame()
        issues = _clearance_issues(
            frame, [],
            [(ALIGN_KIND, PIN_OFFSET_PROPERTY, 11.9, 50.0, 4.0, 4.0)])
        self.assertEqual(len(issues), 1)
        self.assertEqual(_clearance_issues(
            frame, [],
            [(ALIGN_KIND, PIN_OFFSET_PROPERTY, 12.1, 50.0, 4.0, 4.0)]), [])

    def test_a_cap_face_counterbore_counts_against_the_wall_only(self):
        """Which radius applies depends on the edge, and the face it is on.

        A bolt head counterbore widens the hole at the cap face, so it reaches
        the wall. The cavity is at the mating face, so it is the hole - not the
        counterbore - that has to stand clear of the part. Measuring the
        counterbore against the part too would report a second violation here.
        """
        issues = _clearance_issues(
            self._frame(), self._square_outline(),
            [(CLAMP_KIND, BOLT_OFFSET_PROPERTY, 20.0, 50.0, 9.0, 5.5)])
        self.assertEqual(len(issues), 1)
        self.assertIn("block wall", issues[0])


class TestStockMargins(unittest.TestCase):
    """The stock a mould declares, against the stock its fixtures need."""

    def test_required_margin_is_the_widest_enabled_fixture(self):
        # Defaults: pins 24 + 5, bolts 26 + 8.5, wedges 11; the ears are off.
        self.assertAlmostEqual(
            required_in_plane_margin(AlignmentParams(), ClampingParams(),
                                     WedgeParams()),
            34.5, delta=1e-9)

    def test_short_margins_name_the_fixture_and_the_properties(self):
        issues = margin_issues(StockMargins(x=5.0, y=5.0), AlignmentParams(),
                               ClampingParams(bolts_enabled=False),
                               WedgeParams(enabled=False))
        self.assertEqual(len(issues), 1)
        self.assertIn("the align pin and bush sockets", issues[0])
        self.assertIn("29.000", issues[0])
        self.assertIn("PartingStockMarginX/Y", issues[0])

    def test_ample_margins_report_nothing(self):
        self.assertEqual(margin_issues(StockMargins(x=40.0, y=40.0),
                                       AlignmentParams(), ClampingParams(),
                                       WedgeParams()),
                         [])

    def test_the_smaller_margin_is_what_bounds_the_fixtures(self):
        # A fixture can sit against either wall, so the smaller of the two
        # margins is the one that has to be enough.
        issues = margin_issues(StockMargins(x=30.0, y=5.0), AlignmentParams(),
                               ClampingParams(bolts_enabled=False),
                               WedgeParams(enabled=False))
        self.assertEqual(len(issues), 1)

    def test_no_in_plane_fixture_needs_margin(self):
        # Process ports are not asked for any: a port is bored in to reach the
        # part, so the margin cannot bound it.
        self.assertEqual(
            required_in_plane_margin(AlignmentParams(enabled=False),
                                     ClampingParams(bolts_enabled=False),
                                     WedgeParams(enabled=False)),
            0.0)

    def test_an_explicit_footprint_replaces_the_comparison(self):
        issues = margin_issues(
            StockMargins(x=5.0, y=5.0, explicit_footprint=True),
            AlignmentParams(), ClampingParams(), WedgeParams())
        self.assertEqual(len(issues), 1)
        self.assertIn("PartingStockFootprint", issues[0])


class TestMouldFixtureFeature(TestFreeCADFP):
    """The feature object, against a real MouldAnalysis holding stand-in halves.

    The mould analysis cannot produce halves in this tree (see the module
    docstring), so the real feature is built and its own ``MouldHalfA`` /
    ``MouldHalfB`` children are then given the stand-in block. The property
    plumbing, the child-object contract and the recompute guard are therefore
    exercised for real; only the geometry is synthetic.
    """

    def _mould_with_stand_in_halves(self, margin=40.0):
        from Composites.features.MouldAnalysis import MouldAnalysisFP

        source = self.doc.addObject("Part::Feature", "Source")
        source.Shape = Part.makeBox(20.0, 20.0, 20.0)
        mould = self.doc.addObject("Part::FeaturePython", "Mould")
        MouldAnalysisFP(mould, source)
        # The default fixtures need 28 mm at their widest - a corner pin at a
        # 24 mm edge offset plus the 8 mm radius of the bush socket - so 40 mm
        # is a mould that needs no fixture-driven resize. Set before the first
        # recompute, because these margins are part of the analysis's guard.
        mould.PartingStockMarginX = margin
        mould.PartingStockMarginY = margin
        # Let the real analysis run to its current (failing) conclusion first,
        # so its recompute guard is armed and a later recompute cannot clobber
        # the stand-in halves.
        self.doc.recompute()
        lower, upper, parting, _draw = make_block_halves()
        mould.MouldHalfA.Shape = lower
        mould.MouldHalfB.Shape = upper
        mould.PartingSurface.Shape = parting
        mould.BestDrawDirection = Z_AXIS
        return mould, lower, upper

    def _make_fixture(self, mould, name="Fixture"):
        from Composites.features.MouldFixture import MouldFixtureFP

        fixture = self.doc.addObject("Part::FeaturePython", name)
        MouldFixtureFP(fixture, mould)
        self.doc.recompute()
        return fixture

    def _add_fixture_without_recompute(self, mould, name="Fixture"):
        """Create the fixture object without building it.

        The post-create resize is asserted on the mould's own properties, and a
        recompute would run the analysis again over the stand-in halves.
        """
        from Composites.features.MouldFixture import MouldFixtureFP

        fixture = self.doc.addObject("Part::FeaturePython", name)
        MouldFixtureFP(fixture, mould)
        return fixture

    def test_feature_cuts_both_halves(self):
        mould, lower, upper = self._mould_with_stand_in_halves()
        fixture = self._make_fixture(mould)
        self.assertEqual(fixture.FixtureStatus, "Ready", fixture.FixtureSummary)
        self.assertLess(fixture.FixtureLower.Shape.Volume, lower.Volume)
        self.assertLess(fixture.FixtureUpper.Shape.Volume, upper.Volume)
        # A clean build reports no issues; the readable account is the summary.
        self.assertEqual(fixture.FixtureIssues, [])
        self.assertIn("alignment holes", fixture.FixtureSummary)

    def test_build_reports_short_margins_without_writing_them(self):
        mould, _lower, _upper = self._mould_with_stand_in_halves(margin=5.0)
        fixture = self._make_fixture(mould)
        self.assertEqual(fixture.FixtureStatus, "Ready", fixture.FixtureSummary)
        self.assertTrue(
            any("PartingStockMarginX/Y" in issue for issue in fixture.FixtureIssues),
            fixture.FixtureIssues,
        )
        # Reported, not applied: once the fixture exists it does not resize the
        # mould behind the user's back.
        self.assertAlmostEqual(mould.PartingStockMarginX, 5.0, delta=1e-9)
        self.assertAlmostEqual(mould.PartingStockMarginY, 5.0, delta=1e-9)

    def test_post_create_raises_the_margins_for_the_fixtures(self):
        from Composites.features.MouldFixture import CompositeMouldFixtureCommand

        mould, _lower, _upper = self._mould_with_stand_in_halves(margin=5.0)
        fixture = self._add_fixture_without_recompute(mould)
        CompositeMouldFixtureCommand().post_create(fixture)
        # The widest fixture is the clamp bolt now: a 26 mm edge offset plus the
        # 8.5 mm radius of its 17 mm head counterbore.
        self.assertAlmostEqual(mould.PartingStockMarginX, 34.5, delta=1e-9)
        self.assertAlmostEqual(mould.PartingStockMarginY, 34.5, delta=1e-9)

    def test_post_create_leaves_ample_margins_alone(self):
        from Composites.features.MouldFixture import CompositeMouldFixtureCommand

        mould, _lower, _upper = self._mould_with_stand_in_halves(margin=40.0)
        fixture = self._add_fixture_without_recompute(mould)
        CompositeMouldFixtureCommand().post_create(fixture)
        self.assertAlmostEqual(mould.PartingStockMarginX, 40.0, delta=1e-9)
        self.assertAlmostEqual(mould.PartingStockMarginY, 40.0, delta=1e-9)

    def test_feature_reports_a_mould_without_halves(self):
        mould, _lower, _upper = self._mould_with_stand_in_halves()
        mould.MouldHalfA.Shape = Part.Shape()
        fixture = self._make_fixture(mould)
        self.assertEqual(fixture.FixtureStatus, "Fail")
        self.assertIn("no halves", fixture.FixtureSummary)
        self.assertTrue(fixture.FixtureIssues)

    def test_recompute_guard_skips_a_second_build(self):
        mould, _lower, _upper = self._mould_with_stand_in_halves()
        fixture = self._make_fixture(mould)
        first = fixture.FixtureLower.Shape.Volume
        self.assertIsNotNone(fixture.Proxy._fixtured_inputs)
        fixture.Proxy.execute(fixture)
        self.assertAlmostEqual(fixture.FixtureLower.Shape.Volume, first, delta=1e-9)

    def test_selection_validation_accepts_a_mould_with_solids(self):
        from Composites.features.MouldFixture import CompositeMouldFixtureCommand

        mould, _lower, _upper = self._mould_with_stand_in_halves()
        command = CompositeMouldFixtureCommand()
        self.assertIsNone(command.validate_selection({"source": mould}))

    def test_selection_validation_refuses_a_mould_without_halves(self):
        from Composites.features.MouldFixture import CompositeMouldFixtureCommand

        mould, _lower, _upper = self._mould_with_stand_in_halves()
        mould.MouldHalfB.Shape = Part.Shape()
        command = CompositeMouldFixtureCommand()
        reason = command.validate_selection({"source": mould})
        self.assertIsNotNone(reason)
        self.assertIn("MouldHalfB", reason)

    def test_command_only_accepts_a_mould_analysis(self):
        from Composites.features.MouldFixture import is_mould_analysis

        mould, _lower, _upper = self._mould_with_stand_in_halves()
        plain = self.doc.addObject("Part::Feature", "Plain")
        plain.Shape = Part.makeBox(1.0, 1.0, 1.0)
        self.assertTrue(is_mould_analysis(mould))
        self.assertFalse(is_mould_analysis(plain))


class TestMouldFixtureRegistration(unittest.TestCase):
    """The toolbar and menu wiring the workbench needs at activation."""

    def test_icon_file_exists(self):
        # The command's icon is resolved at workbench activation; a missing
        # file leaves a blank toolbar button rather than an error.
        from Composites import MOULD_FIXTURE_TOOL_ICON

        self.assertTrue(os.path.isfile(MOULD_FIXTURE_TOOL_ICON))

    def test_mould_tool_group_lists_the_fixture_command(self):
        from Composites.features.ToolbarGroup import get_command_groups

        groups = dict(get_command_groups())
        self.assertIn("Composites_MouldTools", groups)
        commands = groups["Composites_MouldTools"].GetCommands()
        self.assertIn("Composites_MouldFixture", commands)
        self.assertIn("Composites_MouldAnalysis", commands)

    def test_command_declares_the_mould_as_its_source(self):
        from Composites.features.MouldFixture import (
            CompositeMouldFixtureCommand,
            is_mould_analysis,
        )

        command = CompositeMouldFixtureCommand()
        self.assertEqual(command.sel_args[0]["key"], "source")
        self.assertIs(command.sel_args[0]["test"], is_mould_analysis)


if __name__ == "__main__":
    unittest.main()
