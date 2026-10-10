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

import FreeCAD
import Part
from FreeCAD import Console, Vector


debug = False

PATH_SAMPLES = 72
TRAVEL_AXIS_EPSILON = 1e-12
DEGENERATE_AREA_FRACTION = 1e-9
SURFACE_TOLERANCE = 1e-9
OFFSET_DIRECTION_TOLERANCE = 1e-6
COORD_PRECISION = 6
# Ordinate below which a profile vertex counts as sitting on the base row
# (y = 0, the support surface). Keys are rounded to COORD_PRECISION.
BASE_ORDINATE_TOLERANCE = 1e-6


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
    """The one normal of a planar cut surface, or None when the surface is bent.

    A tool of several faces is fine when they are parallel planes — two offset
    planes cut several paths that all share the same profile-x direction.
    """
    faces = cut_surface.Faces
    if not faces or not all(isinstance(face.Surface, Part.Plane) for face in faces):
        return None
    normal = cut_surface_normal(cut_surface, faces[0].CenterOfMass)
    for face in faces[1:]:
        other = cut_surface_normal(cut_surface, face.CenterOfMass)
        if (normal - other).Length > 1e-7:
            return None
    return normal


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
    edges = _unique_edges(edges)
    _debug(f"_section_groups: section edges={len(edges)}")
    return Part.sortEdges(edges)


# Below which two section edges count as the same curve: measured on the
# fuselage's unsewn skin junctions, the duplicated edge (one per face) matches
# its twin to ~1e-13 in length and sampled points — seven orders above that
# noise, and far below the separation of any two distinct cut curves.
_EDGE_DUPLICATE_TOLERANCE = 1e-6


def _unique_edges(edges):
    """The section edges, with geometrically coincident duplicates dropped.

    An unsewn support's faces meet along coincident boundary edges — separate
    TShapes carrying the same curve — so a cut surface crossing the junction
    sections the curve once per face.  The duplicates chain into one path
    traversed twice (measured on the fuselage: the frame_3 station's path
    length 1897 = 2 × 948.5), which breaks every loft built against it.  Two
    edges are duplicates when they have the same length and each lies on the
    other; paths that merely touch at a point differ in length and survive.
    """
    unique = []
    for edge in edges:
        if any(_edges_coincident(edge, kept) for kept in unique):
            continue
        unique.append(edge)
    return unique


def _edges_coincident(a: Part.Edge, b: Part.Edge):
    """Whether two edges carry the same curve over the same extent."""
    if abs(a.Length - b.Length) > _EDGE_DUPLICATE_TOLERANCE * max(1.0, a.Length):
        return False
    return all(
        b.distToShape(Part.Vertex(point))[0] <= _EDGE_DUPLICATE_TOLERANCE
        for point in a.discretize(9)
    )


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


def _height_at_parameter(edge: Part.Edge, parameter: float, normal: Vector) -> Vector:
    """The height direction b = t x N on `edge` at `parameter`, in the edge's
    own direction of travel.

    The caller knows the edge and the parameter it is probing — the tangent
    comes straight from the edge, with no point-to-edge membership search:
    a boolean-produced edge's exposed basis curve evaluates up to ~1e-9 mm
    off the edge's own geometry (and microns off at the trimmed range
    endpoints), which a membership search at surface tolerance would reject.
    """
    tangent = edge.tangentAt(parameter)
    if edge.Orientation == "Reversed":
        tangent = -tangent
    return Station.at(edge.valueAt(parameter), tangent.normalize(), normal).height


def _sideways(row: Part.Wire, ordinate: float, normal: Vector) -> Part.Wire:
    """The row moved `ordinate` sideways along b = t x N, staying in its plane."""
    if abs(ordinate) <= SURFACE_TOLERANCE:
        return row
    if len(row.Edges) == 1 and isinstance(row.Edges[0].Curve, Part.Line):
        return _translated_sideways(row, ordinate, normal)
    if len(row.Edges) == 1:
        try:
            return _occt_sideways(row, ordinate, normal)
        except Part.OCCError:
            # The exact offset refuses some basis curves outright — a section
            # of a lofted surface is a C0 B-spline at its seam, and
            # ``Geom_OffsetCurve`` raises "Offset on C0 curve" on it.  The row
            # is then rebuilt by sampling: its own points moved along the
            # local height direction.  That is the web's definition of record
            # (each point `ordinate` off the surface along b), only
            # approximated between samples.
            return _sampled_sideways(row, ordinate, normal)
    return _creased_sideways(row, ordinate, normal)


def _sampled_sideways(row: Part.Wire, ordinate: float, normal: Vector, per_edge: int = 12):
    """The row rebuilt from sampled points, each moved along local b.

    The escape for rows the exact offset refuses (a lofted surface's C0
    section, see :func:`_sideways`).  Each edge is sampled at strictly
    interior parameters — a boolean-produced edge's trimmed range endpoints
    evaluate up to microns off the curve, which _edge_holding rightly
    refuses — each sample is lifted by `ordinate` along the height direction
    b = t x N measured on its own edge, and the lifted points are
    interpolated; a closed row interpolates periodically.
    """
    points = []
    for edge in row.Edges:
        low = min(edge.FirstParameter, edge.LastParameter)
        high = max(edge.FirstParameter, edge.LastParameter)
        span = high - low
        # Sample in the edge's own direction of travel: a reversed edge's
        # parametrisation runs backward along the wire.
        fractions = [(i + 0.5) / per_edge for i in range(per_edge)]
        if edge.Orientation == "Reversed":
            fractions = list(reversed(fractions))
        for fraction in fractions:
            parameter = low + span * fraction
            point = edge.valueAt(parameter)
            points.append(
                point + _height_at_parameter(edge, parameter, normal) * ordinate
            )
    closed = row.isClosed()
    curve = Part.BSplineCurve()
    curve.interpolate(points, PeriodicFlag=closed)
    return _oriented_by_travel(Part.Wire([curve.toShape()]), normal)


def _translated_sideways(row: Part.Wire, ordinate: float, normal: Vector) -> Part.Wire:
    """A straight row lifted sideways: b is constant, so this is a rigid move."""
    lifted = row.copy()
    lifted.translate(
        _height_at(row, row.Edges[0].valueAt(row.Edges[0].FirstParameter), normal)
        * ordinate
    )
    return lifted


def _occt_sideways(row: Part.Wire, ordinate: float, normal: Vector) -> Part.Wire:
    """The row moved `ordinate` sideways along b = t x N, exactly.

    ``Part.OffsetCurve`` wraps OCCT's ``Geom_OffsetCurve``: the exact offset
    curve, one curve per basis curve, taking its parametrisation from the
    basis — so the parallel of an ellipse stays a single curve.  The
    approximating wire offset (``makeOffset2D``, i.e.
    ``BRepOffsetAPI_MakeOffset``) splits that same parallel into four
    pieces, and ``Part.makeLoft`` then refuses to rule between a row and its
    own offset: that is the ring sweep's coin flip, measured on the
    fuselage's frames and reproduced by
    ``test_ring_sweeps_on_a_fuselage_scale_sleeve``.  It also made every
    swept row approximate; this keeps it exact.

    The sign of the displacement depends on how the row is wound, so it is
    determined rather than assumed — the same reason the previous
    implementation probed it, but here with an exact point comparison at the
    probe parameter instead of a distance-to-shape solve.
    """
    probe_edge = row.Edges[0]
    # Probe at an interior parameter: a boolean-produced edge's trimmed range
    # endpoints are imprecise (measured 4.8e-6 mm off the true endpoint on a
    # fuselage skin section), and _edge_holding rightly refuses a point that
    # far off the row.  Interior parameters evaluate exactly on the curve.
    low = min(probe_edge.FirstParameter, probe_edge.LastParameter)
    high = max(probe_edge.FirstParameter, probe_edge.LastParameter)
    probe_parameter = (low + high) / 2.0
    probe = probe_edge.valueAt(probe_parameter)
    expected = probe + _height_at_parameter(probe_edge, probe_parameter, normal) * ordinate
    for sign in (1.0, -1.0):
        pieces = _offset_pieces(row, sign * ordinate, normal)
        # An exact point comparison at the probe parameter, not a
        # distance-to-shape solve: the offset curve keeps its basis
        # parametrisation, so the piece's value at that parameter is either
        # the point asked for or the one on the other side.
        if (
            pieces[0].valueAt(probe_parameter).distanceToPoint(expected)
            <= OFFSET_DIRECTION_TOLERANCE
        ):
            return _oriented_by_travel(Part.Wire(pieces), normal)
    raise ValueError(
        "neither offset direction moved the profile row along the height "
        "direction"
    )


def _creased_sideways(row: Part.Wire, ordinate: float, normal: Vector) -> Part.Wire:
    """The row moved sideways where it has a crease, joined at the crease.

    A parallel curve is defined only for a smooth curve.  At a crease — a row
    crossing a fold in the support — the two exact offsets do not meet, and
    connecting them is a separate decision (OCCT's ``GeomAbs_Arc`` or
    ``GeomAbs_Intersection`` join), which ``Geom_OffsetCurve`` does not make.
    ``makeOffset2D`` does make it and returns one continuous wire, which is
    what such a row needs; it also approximates each piece, which is why it is
    used *only* here, the smooth row having the exact offset instead.

    The direction comes from the exact offset of the row's first edge, which
    is a smooth curve even when the whole row is not: an exact evaluation at
    the probe parameter, not a distance-to-shape solve.
    """
    probe_edge = row.Edges[0]
    low = min(probe_edge.FirstParameter, probe_edge.LastParameter)
    high = max(probe_edge.FirstParameter, probe_edge.LastParameter)
    # Interior probe parameter — see _occt_sideways.
    probe_parameter = (low + high) / 2.0
    probe = probe_edge.valueAt(probe_parameter)
    for sign in (1.0, -1.0):
        exact = Part.Edge(
            Part.OffsetCurve(probe_edge.Curve, sign * ordinate, normal), low, high
        )
        if (
            exact.valueAt(probe_parameter).distanceToPoint(
                probe + _height_at_parameter(probe_edge, probe_parameter, normal) * ordinate
            )
            > OFFSET_DIRECTION_TOLERANCE
        ):
            continue
        lifted = row.makeOffset2D(sign * ordinate, openResult=True)
        if lifted.isNull():
            continue
        return _oriented_by_travel(lifted, normal)
    raise ValueError(
        "neither offset direction moved the profile row along the height "
        "direction"
    )


def _offset_pieces(row: Part.Wire, distance: float, normal: Vector):
    """Each edge of the row offset by *distance*, as exact offset curves.

    ``Part.OffsetCurve`` keeps the basis parametrisation, so the piece is
    trimmed with the edge's own parameters and reversed to match the edge's
    direction of travel.
    """
    pieces = []
    for edge in row.Edges:
        curve = Part.OffsetCurve(edge.Curve, distance, normal)
        low = min(edge.FirstParameter, edge.LastParameter)
        high = max(edge.FirstParameter, edge.LastParameter)
        piece = Part.Edge(curve, low, high)
        if edge.Orientation == "Reversed":
            piece.reverse()
        pieces.append(piece)
    return pieces


def _loci_over_plane(
    support: Part.Shape, cut_surface: Part.Shape, path: Part.Wire, coords,
    normal: Vector, band_rows: dict | None = None
):
    """One locus curve per distinct profile vertex, for one path and a planar cut surface.

    ``band_rows`` supplies the foot band's boolean wall edges, keyed by
    abscissa: for those abscissas the row IS the band's edge, so the web
    loft preserves it as its bottom edge and the web/band pair shares that
    curve by construction (known-issue #14: equal point sets produced by
    different paths carry different defining data, and only a shared
    construction matches the exact shared-edge check)."""
    rows = {}
    for abscissa in sorted({key[0] for key in coords}):
        band_row = (band_rows or {}).get(abscissa)
        rows[abscissa] = band_row if band_row is not None else _row_for(
            path, _row_groups(support, cut_surface, normal, abscissa), normal, abscissa
        )
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


def _profile_edges(profile):
    """The profile's edges: a sketch's Geometry, or a shape's own edges.

    A profile does not have to be a Sketcher object.  This build's GUI
    cannot restore a sketch ("Extension: Extension type not set", raised
    from App/Extension.cpp when the Sketcher object's extension type is not
    registered in the restoring process), so a document whose profiles are
    plain wires is a document that reopens — and nothing in a sweep needs
    the sketch, only its edges.
    """
    geometry = getattr(profile, "Geometry", None)
    if geometry is not None:
        return [geo.toShape() for geo in geometry]
    shape = getattr(profile, "Shape", None)
    if shape is not None:
        return list(shape.Edges)
    return list(getattr(profile, "Edges", []) or [])


def get_xsect(profile):
    """The profile's edges, with repeated vertices merged."""
    profile_edges = _profile_edges(profile)
    if not profile_edges:
        # A profile this cannot read used to sweep into an empty shell that
        # only failed much later, as "the ring produced no web faces".  Say
        # what was passed instead.
        raise ValueError(
            "the profile has no edges to sweep - pass a sketch, a shape or a "
            "wire, not a %s" % type(profile).__name__
        )
    points = {}
    links = []
    for edge in profile_edges:

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

        links.append(
            [add_vertex(edge.firstVertex()), add_vertex(edge.lastVertex())]
        )

    return [
        Part.LineSegment(points[start], points[end]).toShape() for start, end in links
    ]


# How far apart the two curves' start points may be before a ruled loft
# between them is twisting rather than merely seam-misaligned.
_LOFT_TWIST_WARNING = 1.0


def _loft_failure_detail(coords, curves) -> str:
    """Describe the curves a ruled loft was given, for the raised message.

    A ruled loft between two closed curves (every profile vertex of a ring
    traces one) fails as ``StdFail_NotDone`` with no other clue, and the
    useful question is whether a curve is degenerate, unclosed, or a seam
    that has drifted round to the opposite side of the ring — so report
    each curve's extent and closure, and how far its start point sits from
    its partner's.
    """
    parts = []
    for coord, curve in zip(coords, curves):
        try:
            box = curve.BoundBox
            parts.append(
                f"[{coord.x:.3f},{coord.y:.3f}]"
                f"(edges={len(curve.Edges)},closed={curve.isClosed()},"
                f"valid={curve.isValid()},"
                f"parts={len(curve.Wires)},"
                f"x[{box.XMin:.1f},{box.XMax:.1f}],"
                f"y[{box.YMin:.1f},{box.YMax:.1f}],"
                f"z[{box.ZMin:.1f},{box.ZMax:.1f}])"
            )
        except Exception as exc:
            parts.append(f"[{coord.x:.3f},{coord.y:.3f}](unreadable: {exc})")
    if len(curves) == 2:
        try:
            gap = curves[0].Vertexes[0].Point.distanceToPoint(
                curves[1].Vertexes[0].Point
            )
            parts.append(f"seam gap={gap:.3f}")
        except Exception as exc:
            parts.append(f"seam gap unreadable: {exc}")
    return ", ".join(parts)

def _loft_profile(xsect, loci, mirror: ProfileMirror, normal=None, skip_base=False):
    """One lofted face per profile edge, ruled between its two vertex loci.

    Returns the faces with their provenance: the foot faces are the lofts
    whose generating profile edge lies at y = 0 (both vertex ordinates on
    the base row) — the part of the stiffener that runs along the support;
    every other face is a web face.  With `skip_base` the base edges are not
    lofted at all: on a planar cut the foot comes from the support's own
    band (:func:`_foot_bands`), and ruling between two independently
    booleaned section rows can fail outright (measured: OCCT cannot unify
    the two arcs' knot structures — the lofted foot would be discarded
    anyway).
    """
    faces, foot_faces, web_faces = [], [], []
    for index, edge in enumerate(xsect):
        coords = [mirror.apply(vertex.Point) for vertex in edge.Vertexes]
        if skip_base and all(abs(coord.y) <= BASE_ORDINATE_TOLERANCE for coord in coords):
            continue
        curves = [loci[_coordinate_key(coord)] for coord in coords]
        try:
            face = Part.makeLoft(curves, solid=False, ruled=True)
        except Exception as error:
            raise ValueError(
                f"lofting profile edge {index} of {len(xsect)} failed "
                f"({_loft_failure_detail(coords, curves)})"
            ) from error
        faces.append(face)
        if all(abs(coord.y) <= BASE_ORDINATE_TOLERANCE for coord in coords):
            foot_faces.append(face)
        else:
            web_faces.append(face)
    return faces, foot_faces, web_faces


@dataclass
class StiffenerSweep:
    """The geometry one `make_stiffener` run produces, with face provenance.

    `foot_width` is the narrowest base-edge extent (None when the profile
    has no base edge); `web_height` is the tallest profile ordinate.  Both
    scale the child shells' drape pitch — a default pitch can exceed a
    15 mm flange and fail to drape it.
    """

    shell: Part.Shape
    remainders: list
    foot_faces: list
    web_faces: list
    foot_width: float | None = None
    web_height: float = 0.0


def make_stiffener(
    support: Part.Shape,
    cut_surface: Part.Shape,
    profile,
    mirror: ProfileMirror = ProfileMirror(),
) -> StiffenerSweep:
    """The stiffener shell, the cut support, and the foot/web provenance.

    The support must be a shell or a face — the stiffener is a shell laid on a
    shell, and a solid is rejected outright.

    Every profile edge is lofted along the whole path into a face, whatever the
    profile's topology, so the stiffener is an open shell rather than a solid.
    Each profile vertex traces a locus: the row at its abscissa, moved sideways
    by its ordinate.

    Returns a :class:`StiffenerSweep`: the stiffener as one compound; the
    remainders of the support with the stiffener cut away, one shape per
    piece; and the lofted faces split into foot faces and web faces.  On a
    planar cut surface the foot is *not* lofted: the foot is the band of the
    support's own surface between the base rows (see :func:`_foot_bands`),
    exact at edge and interior alike.  A profile with no base edge yields no
    foot faces.
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
    intervals = _base_edge_intervals(xsect, mirror)
    # The band's boolean wall edges, keyed by abscissa: the loci's base
    # rows for those abscissas are built from them (see _band_wall_rows).
    band_row_groups = _band_wall_rows(
        support, cut_surface, normal, intervals) if (
        normal is not None and intervals) else {}
    faces, foot_faces, web_faces = [], [], []
    for path_index, path in enumerate(paths):
        if normal is None:
            loci = _loci_over_surface(support, cut_surface, path, coords)
            path_faces, path_foot, path_web = _loft_profile(xsect, loci, mirror)
            faces.extend(path_faces)
            foot_faces.extend(path_foot)
            web_faces.extend(path_web)
        else:
            # The wall-edge groups come out of _section_groups in the same
            # deterministic order as the paths (both sort the same section
            # geometry), so the path's row is picked by INDEX - a
            # distToShape between two long curved wires measured 155 s per
            # stiffener.
            band_rows = {
                a: wires[path_index] if path_index < len(wires) else wires[0]
                for a, wires in band_row_groups.items()
            } if band_row_groups else {}
            loci = _loci_over_plane(
                support, cut_surface, path, coords, normal, band_rows)
            _, _, path_web = _loft_profile(xsect, loci, mirror, skip_base=True)
            faces.extend(path_web)
            web_faces.extend(path_web)
    if normal is not None and intervals:
        bands = _foot_bands(support, cut_surface, normal, intervals)
        faces.extend(bands)
        foot_faces.extend(bands)

    shell = Part.makeCompound(faces)
    remainders = (
        _remainder_outside_bands(support, cut_surface, normal, intervals)
        if normal is not None and intervals
        else _support_remainders(support, shell)
    )
    return StiffenerSweep(
        shell=shell,
        remainders=remainders,
        foot_faces=foot_faces,
        web_faces=web_faces,
        foot_width=_base_edge_width(xsect, mirror),
        web_height=max((abs(coord.y) for coord in coords.values()), default=0.0),
    )


def _base_edge_intervals(xsect, mirror: ProfileMirror):
    """The abscissa span of each base edge — the profile edges lying at y = 0.

    The foot runs along the support between those abscissas; the band of
    support surface between the planes at the interval's ends is the foot's
    geometry of record.  Degenerate spans (no extent along the support) are
    skipped — they carry no foot.
    """
    intervals = []
    for edge in xsect:
        coords = [mirror.apply(vertex.Point) for vertex in edge.Vertexes]
        if all(abs(coord.y) <= BASE_ORDINATE_TOLERANCE for coord in coords):
            low, high = sorted(coord.x for coord in coords)
            if high - low > SURFACE_TOLERANCE:
                intervals.append((low, high))
    return intervals


def _band_slab(cut_surface: Part.Shape, normal: Vector, low: float, high: float):
    """The prism between the cut surface and the parallel plane `high` along
    the normal, starting from the plane at `low`."""
    moved = cut_surface.copy()
    moved.translate(normal * low)
    return moved.extrude(normal * (high - low))


def _band_wall_rows(support: Part.Shape, cut_surface: Part.Shape,
                    normal: Vector, intervals):
    """The boolean wall-edge wires of the foot bands, keyed by abscissa.

    For each interval the band's boundary in the low and high wall planes is
    the boolean edge where the slab's wall meets the support — the curve the
    seam's shared-edge check can match the remainder's seat against (the cut
    and the common of the same slab produce identical curve data).  The
    loci's base rows are built from THESE instead of from a fresh section,
    so the web loft preserves the band's own edges and the web/foot pair
    shares by construction (known-issue #14: equal point sets from different
    production paths carry different defining data, and only a shared
    construction matches).
    """
    com = cut_surface.CenterOfMass
    rows = {}
    for low, high in intervals:
        faces = support.common(_band_slab(cut_surface, normal, low, high)).Faces
        for a in (low, high):
            # Per GROUP (a split support's band wall crosses several paths,
            # one group each): a merged wire of disjoint groups is garbage,
            # and each path must borrow its own group's edge.
            groups = []
            for face in faces:
                for wire in face.Wires:
                    edges = []
                    for e in wire.OrderedEdges:
                        mid = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
                        if abs(normal.dot(mid.sub(com)) - a) <= 1e-6:
                            edges.append(e)
                    if edges:
                        groups.append(Part.Wire(edges) if len(edges) > 1 else edges[0])
            kept = []
            for wire in groups:
                # Only OPEN rows substitute: a closed row's loft pairings
                # depend on the boolean edge's seam position, which is not
                # consistent between the wall planes, and the cross-lofts
                # twist (measured on the cylinder ring: the flange's vertices
                # wandered from radius 50 down to 30).  The fuselage's L/R
                # halves - the case the shared-edge failure is about - are
                # open arcs, where the pairing is seam-free.
                if not wire.isClosed():
                    kept.append(_oriented_by_travel(wire, normal))
            if kept:
                rows[a] = kept
    # The boolean edges' orientations are independent per face, and the
    # travel law cannot normalize degenerate (straight) rows into mutual
    # agreement - measured on the plate: one wall row Forward, the other
    # Reversed, and their sideways offsets pointed in opposite b directions
    # (the web went down while the flange went up).  The rows of ONE band
    # bound the same strip, so their tangents must agree: compare at the
    # rows' midpoints and reverse the odd one out.
    for low, high in intervals:
        w0s, w1s = rows.get(low), rows.get(high)
        if not w0s or not w1s:
            continue
        # Pair the rows by vertex bounding boxes (a split support keeps one
        # row per path, and the rows of one band are near-neighbours): a
        # distToShape between two long curved wires is an exact extrema
        # solve and measured 155 s per stiffener.
        for w0 in w0s:
            box0 = w0.BoundBox
            near = min(
                w1s,
                key=lambda w: max(0.0,
                                  max(box0.XMin - w.BoundBox.XMax, w.BoundBox.XMin - box0.XMax)
                                  + max(box0.YMin - w.BoundBox.YMax, w.BoundBox.YMin - box0.YMax)
                                  + max(box0.ZMin - w.BoundBox.ZMax, w.BoundBox.ZMin - box0.ZMax)),
            )
            e0, e1 = w0.Edges[0], near.Edges[0]
            t0 = e0.tangentAt(0.5 * (e0.FirstParameter + e0.LastParameter))
            if e0.Orientation == "Reversed":
                t0 = -t0
            t1 = e1.tangentAt(0.5 * (e1.FirstParameter + e1.LastParameter))
            if e1.Orientation == "Reversed":
                t1 = -t1
            if t0.dot(t1) < 0.0:
                near.reverse()
    return rows


def _foot_bands(support: Part.Shape, cut_surface: Part.Shape, normal: Vector,
                intervals):
    """The support's own surface between each base edge's abscissa planes.

    The foot is cut from the support, not lofted: a ruled loft between two
    section rows leaves the surface wherever it curves, which lifts the foot
    off the support, silently breaks the seat's weave exclusivity (a boolean
    cannot split a support by a tool that only rides it) and leaves the foot
    mesh disconnected from the panel's.  The band is the surface's own patch
    - exact at edge and interior alike - and the remainder is what the same
    cut leaves behind.
    """
    faces = []
    for low, high in intervals:
        faces.extend(support.common(_band_slab(cut_surface, normal, low, high)).Faces)
    return faces


def _remainder_outside_bands(support: Part.Shape, cut_surface: Part.Shape, normal: Vector, intervals):
    """The support with every foot band cut away, one face per piece.

    The complement of :func:`_foot_bands` on the same cut - so the weave
    exclusivity is exact by construction, not a boolean approximation of it.
    """
    rest = support
    for low, high in intervals:
        rest = rest.cut(_band_slab(cut_surface, normal, low, high))
    return list(rest.Faces)


def _base_edge_width(xsect, mirror: ProfileMirror) -> float | None:
    """The narrowest base-edge extent, or None when no base edge exists.

    A base edge is a profile edge whose two vertex ordinates both sit on
    the base row (y = 0); its extent is the abscissa span between them.
    """
    widths = []
    for edge in xsect:
        coords = [mirror.apply(vertex.Point) for vertex in edge.Vertexes]
        if all(abs(coord.y) <= BASE_ORDINATE_TOLERANCE for coord in coords):
            widths.append(abs(coords[0].x - coords[1].x))
    return min(widths) if widths else None


def _support_remainders(support: Part.Shape, stiffener: Part.Shape):
    """The support with the stiffener cut away, one shape per piece.

    The cut removes the strip the stiffener sits on and splits what is left:
    a plate falls into the regions beside the stiffener, a cylinder into the
    bands above and below a ring. Each face is cut on its own, which is also
    what an open support of several faces needs; the cut faces are returned
    individually.

    The stiffener's seat — the profile's base row, swept along the path —
    lies *on* the support, so subtracting it as it stands is a coplanar-face
    Boolean: measured on a lofted sleeve that returns an EMPTY shape (no
    pieces at all, ~1 s), silently removing the panel's weave exclusivity,
    while the same cut on a planar plate returns the expected pieces.  The
    face is therefore split with the general fuse (the algorithm FreeCAD's
    own Part Slice uses), and the pieces are separated by their *provenance*
    rather than by any geometric guess: the seat region is shared with the
    tool, the regions beside it are not.  Nothing is extruded and nothing is
    converted to a solid.
    """
    pieces = []
    for face in support.Faces:
        pieces.extend(_pieces_around(face, stiffener))
    return pieces


# Separation below which a stiffener face is taken to meet the support face:
# a seat lies *on* the support, so its faces are at zero distance, and a tool
# further than this cannot split the face at all.
_MEETING_TOLERANCE = 1e-3


def _tools_meeting(face, stiffener: Part.Shape):
    """The stiffener's faces that meet the support face.

    A cheap prefilter in front of the general fuse: a tool that does not
    reach the face cannot split it, and passing it anyway is what shortened
    the fuse's provenance map and lost the untouched piece (see
    ``_pieces_around``).  A face whose distance cannot be measured is kept —
    the fuse decides its fate rather than the prefilter dropping it.
    """
    meeting = []
    for candidate in stiffener.Faces:
        try:
            if face.distToShape(candidate)[0] <= _MEETING_TOLERANCE:
                meeting.append(candidate)
        except Exception:
            meeting.append(candidate)
    return meeting


def _pieces_around(face, stiffener: Part.Shape):
    """The parts of *face* that belong to the support, not to the seat.

    The general fuse records which of its inputs each resulting piece came
    from, and that record is the only thing used here:

    * a piece generated by the support **and** a tool is the region they
      share — the seat — and is not part of the remainder;
    * a piece generated by the support alone is a region beside the seat and
      is.  Where the seat covers the whole support — a ring whose sleeve is
      the frame section — there are simply no such pieces, and the empty
      remainder is the geometry's own answer.

    Taking every piece the fuse returns would list the *stiffener's* own
    faces as support remainder; an earlier version did exactly that and then
    tried to repair it by filtering on centre of mass, which is arbitrary
    and unnecessary when the fuse already records each piece's owner.

    Only the tools that *meet* the face are passed.  The fuse can split a
    face only where a tool reaches it, and asking it to split with a
    disjoint tool leaves the provenance map short — OCCT reports "Map entry
    0 is empty.  Source-to-piece correspondence information is probably
    incomplete." and ``piecesFromSource`` then returns nothing for the
    support, so the whole untouched piece was lost (measured on the chained
    fixture: a face 20 mm from the seat disappeared from the remainder, and
    with it half of the plate).  A face no tool meets is therefore returned
    whole, without a fuse.

    Tools are wrapped in compounds, as FreeCAD's own Part Slice does, so
    their pieces cannot contaminate the result.  Falls back to the bare
    subtraction if the fuse or the provenance lookup raises, so a support
    this path cannot handle behaves as it did before.
    """
    meeting = _tools_meeting(face, stiffener)
    if not meeting:
        return list(face.Faces)
    tools = [Part.makeCompound([candidate]) for candidate in meeting]
    shapes = [face] + tools
    try:
        from BOPTools.GeneralFuseResult import GeneralFuseResult

        fused, mapping = face.generalFuse(tools)
        result = GeneralFuseResult(shapes, (fused, mapping))
        own = result.piecesFromSource(shapes[0])
    except Exception:
        return list(face.cut(stiffener).Faces)
    remainder = []
    for piece in own:
        try:
            sources = result.sourcesOfPiece(piece)
        except Exception:
            sources = [shapes[0]]
        if len(sources) > 1:
            continue  # shared with the stiffener: the seat
        remainder.extend(piece.Faces)
    return remainder
