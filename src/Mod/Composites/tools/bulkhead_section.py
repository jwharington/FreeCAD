# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""The filled section a bulkhead is built from, and how it sits on its support.

A bulkhead is a *plate with flanges*: a wall of constant depth `d` standing off
the support, joined to the support along a contact line and gusseted into it.
This module settles that section's shape before any shell is sewn, and it
answers the question in *faces*, because a chain's length does not reveal
whether it crossed the band seam or merely ran along one face's own boundary —
and only the first of those means the member's boundary fails to close on
material, which is what §2 of docs/fem-shell-mesh-continuity.md is about.

**The flange and the plate come out of one boolean, not two.**  `band_of` asks
`support` for the material inside a prism whose section is the whole bulkhead
cross-section, `p x [0, d]`, and the same prism's wall faces are what the
panel's faces are cut by.  That is deliberate: the band's boundary and the
plate's boundary share the section path, and a member assembled from
independently produced pieces carries *two* copies of that shared curve, which
is known-issue #14 seen from the other side — equal point sets produced by
different paths do not match the seam's exact shared-edge check, so the mesh
cracks there.

**Depth is measured along b = t x N, which lies *in* the cutting plane (F2).**
`t` is the path's tangent and `N` the cutting surface's normal, so b is in the
plane and perpendicular to the path — *not* normal to the support, which is
what a first reading of "stand-off" suggests.  Measured along the support
normal instead, a constant `depth` would put the plate *in* the cutting plane,
where it has no thickness, and the boolean would answer "nothing to take out
of" for a support that plainly has a band to give.

**One member per chain (F1).**  Measured on the fixture, every cut yields one
closed chain and none of them self-crosses, so the hole-test machinery an
earlier draft carried has been deleted rather than kept as insurance against a
case that does not arise.  What remains of that concern is the de-duplication,
which *does* arise constantly: an open multi-face support is full of duplicated
section edges, `section()` reports every copy, and a chain traversed twice
breaks every loft built against it.

Design record: docs/bulkhead-design.md.
"""

import Part

from FreeCAD import Console, Vector

from .stiffener import _section_groups

debug = False

# Sample points per curve, for the queries that have to ask where a curve lies
# relative to a surface: too few to miss a fold, too many to matter.
_SAMPLES = 24

# Distance from a surface within which a curve still counts as lying on it, and
# the area below which a subtracted footprint has nothing left of it.  A
# boolean-produced edge's exposed basis curve evaluates up to ~1e-9 mm off the
# edge's own geometry, so the first of these separates stitching noise from a
# real gap by three orders of magnitude.
_PROXIMITY = 1e-6
_MIN_AREA = 1e-9


def _debug(message):
    """Emit a debug trace when :data:`debug` is enabled."""
    if debug:
        Console.PrintLog(message + "\n")


# ── the section path ─────────────────────────────────────────────────


def section_chains(support: Part.Shape, cut_surface: Part.Shape):
    """Every continuous chain where `cut_surface` cuts `support`, deduplicated.

    :func:`Composites.tools.stiffener._section_groups` is reused rather than
    reimplemented, for two reasons that both bite on real geometry.  It sections
    a solid or a single face in one shape-level `section()` call, so a cut
    running along a cap plane yields one chain rather than two wires meeting
    head-on; and it drops coincident duplicate edges, which an open multi-face
    support is full of, and which otherwise sew into double rows of elements.

    A chain that duplicates a support edge *is* the place where the cut and the
    support agree, so a copy rebuilt by a different boolean carries different
    defining data and reads as a crack (known-issue #14), and a chain traversed
    twice breaks every loft built against it.
    """
    chains = [Part.Wire(group) for group in _section_groups(support, cut_surface)]
    _debug(f"section_chains: {len(chains)} chains {[c.isClosed() for c in chains]}")
    return chains


def chain_regions(support: Part.Shape, chain: Part.Wire):
    """The support faces `chain` runs along, as (face, boundary, interior).

    A chain that crosses the band seam yields one region per face it crossed,
    with the seam recorded as a boundary of *both* — which is the only answer
    that survives the two ways a support can be joined along a seam.  A sewn
    shell holds the seam once and `ancestorsOfType` reports both faces for it;
    an unsewn one — which is what a lofted skin is, because `Part.makeShell`
    does not stitch — holds one coincident copy per face, under two different
    TShapes, and each copy belongs to only one face.

    A chain that runs *along* a face's own boundary without entering it is
    reported as boundary only: it does not cut that face, and cutting a face
    along its own edge is not a cut.
    """
    return [(face,
             [edge for edge in chain.Edges
              if not _runs_on(face, edge) and _bounds(face, edge)],
             [edge for edge in chain.Edges if _runs_on(face, edge)])
            for face in support.Faces
            if any(_runs_on(face, edge) or _bounds(face, edge)
                   for edge in chain.Edges)]


def _runs_on(face: Part.Shape, curve) -> bool:
    """Whether `curve` runs along the inside of `face`, rather than beside it.

    Sampled at a strictly interior parameter, and against the surface's own
    parametric domain: a boolean-produced edge's exposed basis curve evaluates up
    to ~1e-9 mm off the edge's own geometry, and its end vertices sit on the
    *support's* boundary edge rather than inside any one face, so a test written
    against trimmed endpoints or against `OuterWire` answers "off the surface"
    to a question nothing ever asks.
    """
    return all(face.distToShape(Part.Vertex(point))[0] <= _PROXIMITY
               for point in curve.discretize(_SAMPLES))


def _bounds(face: Part.Shape, edge: Part.Edge) -> bool:
    """Whether `edge` bounds `face` — the curve two of its faces would share."""
    return any(_same_curve(edge, own) for own in face.OuterWire.Edges)


def _same_curve(a: Part.Edge, b: Part.Edge) -> bool:
    """Whether two edges carry the same curve over the same extent.

    Compared geometrically rather than topologically: `isSame` is exactly true
    only when one edge references the other's underlying curve, and that holds
    between two coincident copies in a compound sewn in passing, so `isSame`
    alone answers "distinct" for curves a mesh would treat as one.
    """
    if a.isSame(b):
        return True
    if abs(a.Length - b.Length) > _PROXIMITY * max(1.0, a.Length):
        return False
    return all(b.distToShape(Part.Vertex(point))[0] <= _PROXIMITY
               for point in a.discretize(5))


def plate_of(support: Part.Shape, cut_surface: Part.Shape):
    """The bulkhead's plate cores: one filled face per closed section chain.

    Every point of a plane/surface intersection lies in the cutting plane, so
    each closed chain bounds a planar region and ``Part.Face`` of the wire *is*
    the filled section (R1) — no re-parametrisation, and the face's boundary
    curves are the chain's own, so a flange band taken out of the support by
    boolean shares them exactly rather than being matched to them by tolerance.

    An open chain — one that runs off the support's free edge — bounds nothing
    and is skipped rather than chorded shut: closing it in space would invent a
    plate edge where the support has none, and the caller decides whether a
    member that fails to close is an error or a bulkhead bridging an opening.
    """
    return [Part.Face(chain) for chain in section_chains(support, cut_surface)
            if chain.isClosed()]


# ── the section region ───────────────────────────────────────────────


def _plane_normal(surface: Part.Shape):
    """The cutting surface's normal, or None when it is not one plane.

    Asked of the surface at its own centre rather than assumed to be the cut's
    own axis, and refused outright for a cutter that is not planar: `depth` is
    measured along this direction, so a bent cutter has no *one* depth to
    measure, and guessing one would tilt the section silently rather than fail.
    """
    try:
        face = surface.Faces[0]
        return Vector(face.normalAt(*face.Surface.parameter(face.CenterOfMass)))
    except (AttributeError, IndexError, Part.OCCError, ValueError):
        return None


def member_slab(support: Part.Shape, cut_surface: Part.Shape,
                width: float, depth: float):
    """The prism the flange band and the plate are together taken out of.

    The cutting surface, widened `width` back along its own normal and then stood
    off `depth` along the same normal.  One solid, not a compound of two,
    because **the common of a shell with a solid is a curve**: handing the
    boolean two overlapping slabs produces no faces at all, which reads as "this
    support has no band to give" and silently drops the flanges.

    Returns None when the cutter is bent, or when it produces nothing at all,
    which is how "the cut surface misses the support" is told apart from "there
    is no band to take out of" — the first is an error, the second is a plate
    with no flanges.
    """
    normal = _plane_normal(cut_surface)
    if normal is None or width <= _PROXIMITY or depth <= _PROXIMITY:
        return None
    widened = cut_surface.copy()
    widened.translate(normal * -width)
    slab = widened.extrude(normal * (width + depth))
    return slab if slab.Faces and slab.Faces[0].Area > _MIN_AREA else None


def band_of(support: Part.Shape, cut_surface: Part.Shape, width: float, depth: float):
    """The bulkhead's flange band, taken out of `support`, as faces.

    These do double duty, which is the reason they are computed once: they are
    the faces the member is sewn from, *and* the faces subtracted from the
    support's own faces so that panel and member cannot both claim one patch of
    material (F4).  Taken from the support rather than offset off it, so the
    band's boundary curves *are* the support's section edges and the seam's
    exact shared-edge check matches by construction.

    An empty result means the plate never met the support, which is reported to
    the caller rather than absorbed here: it is a failure for a member that must
    sit on the panel, and the right answer for one that bridges an opening, and
    only the feature knows which of the two was asked for.
    """
    slab = member_slab(support, cut_surface, width, depth)
    if slab is None:
        return ()
    return tuple(face for face in support.common(slab).Faces if face.Area > _MIN_AREA)


def drape_cuts_of(support: Part.Shape, cut_surface: Part.Shape,
                  width: float, depth: float):
    """The plate's footprint on `support`, one face per connected region.

    The same prism `band_of` is taken from, subtracted *from* the support's
    faces instead of intersected with them, so the two answers stay exclusive by
    construction: whatever the band occupies, the panel's own faces give up.
    """
    slab = member_slab(support, cut_surface, width, depth)
    if slab is None:
        return ()
    return tuple(cut for face in support.Faces
                 for cut in face.cut(slab).Faces if cut.Area > _MIN_AREA)


def make_bulkhead(support: Part.Shape, cut_surface: Part.Shape,
                  flange_width: float, flange_depth: float):
    """The bulkhead's material, as faces: plate cores first, then the flange.

    The plate is the filled section (R1) and the flange is the band taken out
    of the support around it, so the member's two parts meet along the section
    chain and nowhere else, and both come from the same cutter (see
    :func:`band_of` for why the boolean is one prism rather than two).

    Returns ``(plates, bands)`` — kept separate because the plate lies in the
    cutting plane and the flange lies on the support, so the drape that covers
    them runs across a fold and each needs its own stack model.  An empty
    `plates` means the cut never closed on the support; the feature layer turns
    that into an error, because a bulkhead that closes across nothing is not a
    bulkhead.
    """
    plates = plate_of(support, cut_surface)
    bands = band_of(support, cut_surface, flange_width, flange_depth)
    _debug(f"make_bulkhead: {len(plates)} plates {len(bands)} bands")
    return plates, list(bands)
