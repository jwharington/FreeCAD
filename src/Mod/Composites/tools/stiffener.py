# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Sweep geometry for the Stiffener feature.

The path is where the intersecting surface cuts the support — never a
projection of separate plan geometry. The profile rides a moving frame along
that path: tangent t, cut-surface normal N, and height b = t x N. Profile
abscissa x runs along N, ordinate y along b, so the y = 0 row lies on the
support surface. See docs/stiffener-design.md.
"""

from dataclasses import dataclass

import Part
from FreeCAD import Console, Vector


debug = False

PATH_SAMPLES = 72
TRAVEL_AXIS_EPSILON = 1e-12
DEGENERATE_AREA_FRACTION = 1e-9
SURFACE_TOLERANCE = 1e-9
OFFSET_DIRECTION_TOLERANCE = 1e-6
COORD_PRECISION = 6
DIRECTION_PROBE_SAMPLES = 3


def _debug(message):
    """Emit a debug trace when :data:`debug` is enabled."""
    if debug:
        Console.PrintLog(message + "\n")


@dataclass
class ProfileMirror:
    """Which profile axes the user has flipped."""

    flip_x: bool = False
    flip_y: bool = False

    def apply(self, coord: Vector) -> Vector:
        return Vector(
            -coord.x if self.flip_x else coord.x,
            -coord.y if self.flip_y else coord.y,
            0.0,
        )


@dataclass
class Station:
    """The frame at one point of the path."""

    point: Vector
    tangent: Vector
    normal: Vector
    height: Vector

    @classmethod
    def at(cls, point, tangent, normal):
        return cls(point, tangent, normal, tangent.cross(normal))


def _area_vector(points):
    """Newell normal of the polygon the points trace (chord-closed when open)."""
    ordered = list(points) + points[:1]
    total = Vector()
    for point, following in zip(ordered, ordered[1:]):
        total += Vector(
            point.y * following.z - following.y * point.z,
            point.z * following.x - following.z * point.x,
            point.x * following.y - following.x * point.y,
        )
    return total


def _first_axis_delta_is_positive(delta: Vector) -> bool:
    """True when the first non-zero component of delta, in x/y/z order, is positive."""
    for component in (delta.x, delta.y, delta.z):
        if abs(component) > TRAVEL_AXIS_EPSILON:
            return component > 0.0
    return True


def _travels_counter_clockwise(path: Part.Wire, normal: Vector) -> bool:
    """Whether travel along `path` winds counter-clockwise about `normal`.

    A path enclosing no area — a straight run across a plate — has no winding
    sense, so it travels in positive axis order instead.
    """
    points = path.discretize(PATH_SAMPLES)
    area = _area_vector(points)
    if area.Length > DEGENERATE_AREA_FRACTION * path.Length**2:
        return area.dot(normal) > 0.0
    return _first_axis_delta_is_positive(points[1] - points[0])


def plane_normal(cut_surface: Part.Shape):
    """The one normal of a planar cut surface, or None when the surface is bent."""
    faces = cut_surface.Faces
    if len(faces) != 1 or not isinstance(faces[0].Surface, Part.Plane):
        return None
    return cut_surface_normal(cut_surface, faces[0].CenterOfMass)


def cut_surface_normal(cut_surface: Part.Shape, point: Vector) -> Vector:
    """The normal of the cut surface at `point`, in its own orientation."""
    faces = cut_surface.Faces
    if not faces:
        raise ValueError("the intersecting surface has no faces to intersect with")
    return faces[0].normalAt(*faces[0].Surface.parameter(point)).normalize()


def intersection_paths(support: Part.Shape, cut_surface: Part.Shape):
    """Every continuous curve where `cut_surface` cuts `support`, oriented.

    Curves that meet are joined into one path — that is how a path bends over a
    fold between two faces. Curves that do not meet are separate paths, each
    swept in its own right, which is what a support of several disjoint faces
    asks for.

    Travel is oriented counter-clockwise about the cut surface's normal, which
    fixes the sign of the tangent t and so of the frame's height direction
    b = t x N.
    """
    paths = []
    for group in _section_groups(support, cut_surface):
        path = Part.Wire(group)
        start = min(path.discretize(PATH_SAMPLES), key=_coordinate_order)
        paths.append(_oriented_by_travel(path, cut_surface_normal(cut_surface, start)))
    _debug(f"intersection_paths: {len(paths)} paths")
    return paths


def _section_groups(support: Part.Shape, cut_surface: Part.Shape):
    """The edge groups where `cut_surface` cuts `support`, joined into chains.

    A solid or a single face is sectioned in one go — sectioning a solid face by
    face would duplicate the curve wherever the cut runs along a cap plane. An
    open support built of several faces cannot be sectioned in one go, so its
    faces are cut one at a time and the pieces joined at their shared edges,
    which is where the path bends.
    """
    if support.ShapeType in ("Solid", "Face"):
        edges = support.section(cut_surface).Edges
    else:
        edges = [edge for face in support.Faces for edge in face.section(cut_surface).Edges]
    _debug(f"_section_groups: section edges={len(edges)}")
    return Part.sortEdges(edges)


def generate_intersection_path(support: Part.Shape, cut_surface: Part.Shape) -> Part.Wire:
    """The sweep path when the cut surface yields one curve, else an empty wire.

    Raises when the cut yields several, because one of them would be chosen
    silently — call `intersection_paths` to sweep them all.
    """
    paths = intersection_paths(support, cut_surface)
    if len(paths) > 1:
        raise ValueError(
            f"the cut surface meets the support in {len(paths)} paths; they are swept"
            " separately by make_stiffener"
        )
    return paths[0] if paths else Part.Wire()


def _oriented_by_travel(curve: Part.Wire, normal: Vector) -> Part.Wire:
    """`curve`, oriented so travel winds counter-clockwise about `normal`."""
    if not _travels_counter_clockwise(curve, normal):
        curve.reverse()
    return curve


def _coordinate_order(point: Vector):
    return (point.x, point.y, point.z)


def _edge_holding(path: Part.Wire, point: Vector) -> Part.Edge:
    vertex = Part.Vertex(point)
    for edge in path.Edges:
        if edge.distToShape(vertex)[0] < SURFACE_TOLERANCE:
            return edge
    raise ValueError(f"no path edge passes through {point}")


def frames_along(path: Part.Wire, cut_surface: Part.Shape, samples: int = PATH_SAMPLES):
    """The frame at each station of `path`, in the direction of travel."""
    frames = []
    for point in path.discretize(samples):
        edge = _edge_holding(path, point)
        tangent = edge.tangentAt(edge.Curve.parameter(point))
        if edge.Orientation == "Reversed":
            tangent = -tangent
        frames.append(
            Station.at(point, tangent.normalize(), cut_surface_normal(cut_surface, point))
        )
    return frames


def _coordinate_key(coord: Vector):
    return (round(coord.x, COORD_PRECISION), round(coord.y, COORD_PRECISION))


def _profile_coords(xsect, mirror: ProfileMirror):
    """The distinct profile vertices, mirrored into the frame's axes."""
    coords = {}
    for edge in xsect:
        for vertex in (edge.firstVertex(), edge.lastVertex()):
            coord = mirror.apply(vertex.Point)
            coords[_coordinate_key(coord)] = coord
    return coords


def _row_groups(support: Part.Shape, cut_surface: Part.Shape, normal: Vector, abscissa: float):
    """The base rows `abscissa` along the cut normal.

    Rows are cut the same way the path is: by moving the cut surface along its
    own normal and intersecting again. That keeps a point travelling along the
    normal on the surface curve rather than on a chord.
    """
    moved = cut_surface.copy()
    moved.translate(normal * abscissa)
    return _section_groups(support, moved)


def _row_for(path: Part.Wire, groups, normal: Vector, abscissa: float) -> Part.Wire:
    """The row belonging to `path` — of the rows cut at this abscissa, the one
    nearest the path, since each path has its own."""
    if not groups:
        raise ValueError(f"the profile leaves the support {abscissa:g} mm along the cut normal")
    rows = [_oriented_by_travel(Part.Wire(group), normal) for group in groups]
    if len(rows) == 1:
        return rows[0]
    return min(rows, key=lambda row: path.distToShape(row)[0])


def _height_at(curve: Part.Wire, point: Vector, normal: Vector) -> Vector:
    """The height direction b = t x N at `point`, in `curve`'s direction of travel."""
    edge = _edge_holding(curve, point)
    tangent = edge.tangentAt(edge.Curve.parameter(point))
    if edge.Orientation == "Reversed":
        tangent = -tangent
    return Station.at(point, tangent.normalize(), normal).height


def _sideways(row: Part.Wire, ordinate: float, normal: Vector) -> Part.Wire:
    """The row moved `ordinate` sideways along b = t x N, staying in its plane."""
    if abs(ordinate) <= SURFACE_TOLERANCE:
        return row
    if len(row.Edges) == 1 and isinstance(row.Edges[0].Curve, Part.Line):
        return _translated_sideways(row, ordinate, normal)
    return _offset_sideways(row, ordinate, normal)


def _translated_sideways(row: Part.Wire, ordinate: float, normal: Vector) -> Part.Wire:
    """A straight row lifted sideways: b is constant, so this is a rigid move."""
    lifted = row.copy()
    lifted.translate(_height_at(row, row.discretize(2)[0], normal) * ordinate)
    return lifted


def _offset_sideways(row: Part.Wire, ordinate: float, normal: Vector) -> Part.Wire:
    """Offset by ordinate in the row's plane, taking the sign that runs along b.

    OCCT offsets by expanding or shrinking the enclosed area, which agrees with
    b = t x N for a closed curve but not necessarily for an open one, so the
    direction is read back rather than assumed.
    """
    probe = row.discretize(DIRECTION_PROBE_SAMPLES)[0]
    expected = probe + _height_at(row, probe, normal) * ordinate
    for sign in (1.0, -1.0):
        lifted = row.makeOffset2D(sign * ordinate, openResult=True)
        if lifted.distToShape(Part.Vertex(expected))[0] < OFFSET_DIRECTION_TOLERANCE:
            return _oriented_by_travel(lifted, normal)
    raise ValueError("offsetting the profile row did not move it along the height direction")


def _loci_over_plane(
    support: Part.Shape, cut_surface: Part.Shape, path: Part.Wire, coords, normal: Vector
):
    """One locus curve per distinct profile vertex, for one path and a planar cut surface."""
    rows = {
        abscissa: _row_for(
            path, _row_groups(support, cut_surface, normal, abscissa), normal, abscissa
        )
        for abscissa in sorted({key[0] for key in coords})
    }
    return {key: _sideways(rows[key[0]], key[1], normal) for key in coords}


def _loci_over_surface(support: Part.Shape, cut_surface: Part.Shape, path, coords):
    """One locus curve per distinct profile vertex, for a bent cut surface.

    Without a single cut-plane normal the rows are not plane curves, so they
    are sampled along the path and snapped back onto the support.
    """
    frames = frames_along(path, cut_surface)
    loci = {}
    for coord in coords.values():
        points = []
        for station in frames:
            offset = station.point + station.normal * coord.x
            if support.distToShape(Part.Vertex(offset))[0] > SURFACE_TOLERANCE:
                offset = _nearest_surface_point(support, offset)
            points.append(offset + station.height * coord.y)
        loci[_coordinate_key(coord)] = Part.Wire([_curve_through(points)])
    return loci


def _nearest_surface_point(support: Part.Shape, point: Vector) -> Vector:
    return support.distToShape(Part.Vertex(point))[1][0][0]


def _curve_through(points):
    curve = Part.BSplineCurve()
    curve.interpolate(points)
    return curve.toShape()


def get_xsect(sketch):
    """The profile's edges, with repeated vertices merged."""
    points = {}
    links = []
    for geo in sketch.Geometry:

        def add_vertex(v):
            p = v.Point
            for key, existing in points.items():
                if p.distanceToPoint(existing) < 1.0e-3:
                    return key
            # Key by coordinates, not hashCode(): OCCT vertex hashes are not
            # stable per point (the same point can hash differently across
            # edges, and distinct points can collide), which corrupted the
            # profile for Z-sections.
            key = (round(p.x, 6), round(p.y, 6), round(p.z, 6))
            points[key] = p
            return key

        edge = geo.toShape()
        links.append([add_vertex(edge.firstVertex()), add_vertex(edge.lastVertex())])

    return [
        Part.LineSegment(points[start], points[end]).toShape() for start, end in links
    ]


def _loft_profile(xsect, loci, mirror: ProfileMirror):
    """One lofted face per profile edge, ruled between its two vertex loci."""
    return [
        Part.makeLoft(
            [loci[_coordinate_key(mirror.apply(vertex.Point))] for vertex in edge.Vertexes],
            solid=False,
            ruled=True,
        )
        for edge in xsect
    ]


def make_stiffener(
    support: Part.Shape,
    cut_surface: Part.Shape,
    profile,
    mirror: ProfileMirror = ProfileMirror(),
):
    """The stiffener shell, the cut support, and the tool curves.

    The support must be a shell or a face — the stiffener is a shell laid on a
    shell, and a solid is rejected outright.

    Every profile edge is lofted along the whole path into a face, whatever the
    profile's topology, so the stiffener is an open shell rather than a solid.
    Each profile vertex traces a locus: the row at its abscissa, moved sideways
    by its ordinate.

    Returns the stiffener as one compound, then the remainders of the support
    with the stiffener cut away — one shape per piece — then the surface rows.
    """
    if support.ShapeType == "Solid":
        raise ValueError(
            "the support must be a shell or a face, not a solid — the stiffener is laid on a shell"
        )
    paths = intersection_paths(support, cut_surface)
    if not paths:
        raise ValueError("the cut surface does not meet the support — no path to sweep along")

    xsect = get_xsect(profile)
    _debug(f"make_stiffener: paths={len(paths)} profile edges={len(xsect)}")

    coords = _profile_coords(xsect, mirror)
    normal = plane_normal(cut_surface)
    faces, surface_rows = [], []
    for path in paths:
        if normal is None:
            loci = _loci_over_surface(support, cut_surface, path, coords)
        else:
            loci = _loci_over_plane(support, cut_surface, path, coords, normal)
        faces.extend(_loft_profile(xsect, loci, mirror))
        surface_rows.extend(locus for key, locus in loci.items() if key[1] == 0.0)

    stiffener = Part.makeCompound(faces)
    return stiffener, _support_remainders(support, stiffener), surface_rows


def _support_remainders(support: Part.Shape, stiffener: Part.Shape):
    """The support with the stiffener cut away, one shape per piece.

    The cut removes the strip the stiffener sits on and splits what is left:
    a plate falls into the regions beside the stiffener, a cylinder into the
    bands above and below a ring. Each face is cut on its own, which is also
    what an open support of several faces needs; the cut faces are returned
    individually.
    """
    pieces = []
    for face in support.Faces:
        pieces.extend(face.cut(stiffener).Faces)
    return pieces
