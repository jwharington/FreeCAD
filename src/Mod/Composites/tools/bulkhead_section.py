# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""The filled section a bulkhead is built from, and how it sits on its support.

A bulkhead is a *plate with flanges*: the plate is a wall of constant depth
standing off the support, and the flanges are bands of the support's own
surface folded flat beside it.  This module settles the section's shape rather
than leaving it to emerge mid-build, and it answers those questions in *faces*,
not in chain lengths, because a chain's length does not reveal whether it
crossed the band seam or merely ran along one face's own boundary edge.

Three decisions live here, each taken on evidence from
``compositestests/inspect_bulkhead_section.py`` — which runs against the same
fixture the tests use — rather than assumed:

**Depth is measured along b = t x N, which lies *in* the cutting plane (F2).**
`t` is the path's tangent and `N` the cutting surface's normal, so b is in the
plane and perpendicular to the path — *not* normal to the support, which is
what a first reading of "stand-off" suggests.  A plate of constant `depth`
therefore spans from the path, where it meets the support, out to a copy of the
path displaced `depth` along b; `depth` and `flange_width` are orthogonal
displacements of one polygon, which is what keeps the two knobs independent.

**One member per chain, one face per connected region (F1, F3).**  Every cut
probed on the doubly curved fixture produced *one* chain, not several — but
self-crossing ones, whose boundary bounds more than one region.  A
self-crossing outer wire is what defeats nextdrape's hole test, so each
connected region becomes its own face and each region's holes are subtracted
from its own face, which leaves the hole test with nothing to decide.

**The flange is taken *out of* the support (F5), and the plate's boundary
passes *through* the support (F3).**  Both go through one boolean over the
section polygon, because a band whose boundary lies on the surface and a plate
whose boundary closes in void are one problem, not two: a chain that runs off
an open end of the support *closes in space without closing on the surface*,
and a member bounded by it sews from geometry that is not in the mesh, which
§2 of docs/fem-shell-mesh-continuity.md refuses to allow.

Design record: docs/bulkhead-design.md.
"""

import Part

from FreeCAD import Console, Vector

from .stiffener import SURFACE_TOLERANCE, _section_groups

debug = False

# Sample points per chain edge, for the queries that have to ask whether a
# curve lies on a surface: too few to miss a fold, too many to matter.
_CHAIN_SAMPLES = 24

# Distance from the support within which a chain still counts as lying on it.
# A section of a lofted surface is piecewise and its pieces join to within
# microns of one another, so this separates a real gap from stitching noise by
# seven orders of magnitude.
_PROXIMITY = 1e-6


def _debug(message):
    """Emit a debug trace when :data:`debug` is enabled."""
    if debug:
        Console.PrintLog(message + "\n")


# ── the section path ─────────────────────────────────────────────────


def section_chains(support: Part.Shape, cut_surface: Part.Shape):
    """Every continuous chain where `cut_surface` cuts `support`, deduplicated.

    :func:`Composites.tools.stiffener._section_groups` is reused rather than
    reimplemented, because getting this list right is not a detail.  It
    sections a solid or a single face in one go — sectioning a solid face by
    face would duplicate the curve wherever the cut runs along a cap plane —
    and it drops coincident duplicate edges, which an open multi-face support
    is full of.

    A chain that duplicates a support edge *is* the place where the cut and the
    support agree, so a copy rebuilt by a different boolean carries different
    defining data and reads as a crack (known-issue #14), and a chain traversed
    twice breaks every loft built against it.  A bulkhead's flange band is
    bounded on one side by exactly such a curve, so the dedupe that
    `make_stiffener` needs is the dedupe this feature needs.
    """
    chains = [Part.Wire(group) for group in _section_groups(support, cut_surface)]
    _debug(f"section_chains: {len(chains)} chains {[c.isClosed() for c in chains]}")
    return chains


def chain_regions(support: Part.Shape, chain: Part.Wire):
    """The connected surface regions `chain` runs along, as (face, boundary).

    A chain that stays inside one face yields one region; one that crosses the
    band seam yields one region per face it crossed, with the seam recorded as
    a boundary of each.  Splitting them here — rather than letting one shell
    carry both faces — is what keeps nextdrape's hole test meaningful, and it
    is also what §2 of docs/fem-shell-mesh-continuity.md asks for: a section
    referenced to faces that are not in the mesh matches nothing.

    Region membership is decided by the face's *own boundary*, not by a
    proximity search.  A chain crossing the seam of a sewn shell contains that
    seam edge once; the same cut on an unsewn shell contains it twice, once per
    face, and a test built on "is this point near the surface" cannot tell
    those apart and answers "nowhere" for both — which is how a chain that
    plainly crosses the seam gets reported as crossing nothing.
    """
    return [
        (face, [edge for edge in chain.Edges if _bounds(face, edge)])
        for face in support.Faces
        if _runs_on(face, chain)
    ]


def _runs_on(face: Part.Face, chain: Part.Wire) -> bool:
    """Whether `chain` has a part of itself inside `face`, rather than beside it."""
    return any(_in_face(face, edge) for edge in chain.Edges)


def _in_face(face: Part.Face, edge: Part.Edge) -> bool:
    """Whether the middle of `edge` lies inside `face`, not merely on it.

    Probed at a strictly interior parameter: a boolean-produced edge's trimmed
    range endpoints evaluate up to microns off the edge's own geometry, which
    a membership test at surface tolerance rightly rejects.
    """
    return face.isInside(_middle_of(edge), _PROXIMITY, False)


def _bounds(face: Part.Face, edge: Part.Edge) -> bool:
    """Whether `edge` is part of `face`'s boundary — its band seam, if it has one."""
    return any(_same_curve(edge, own) for own in face.OuterWire.Edges)


def _middle_of(edge: Part.Edge) -> Vector:
    return edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))


def _same_curve(a: Part.Edge, b: Part.Edge) -> bool:
    """Whether two edges carry the same curve over the same extent."""
    if a.isSame(b):
        return True
    if abs(a.Length - b.Length) > _PROXIMITY * max(1.0, a.Length):
        return False
    return all(b.distToShape(Part.Vertex(p))[0] <= _PROXIMITY for p in a.discretize(5))


# ── the section polygon ──────────────────────────────────────────────


def section_polygon(support: Part.Shape, cut_surface: Part.Shape, path: Part.Wire,
                    depth: float, flange_width: float, normal: Vector):
    """The bulkhead's section polygon, as the planar region it bounds.

    `path` is the section path — the curve where the cutting surface meets the
    support — and `depth` is measured from it along b = t x N, *within* the
    cutting plane, toward whichever side of the plane the plate stands off.
    A closed `path` therefore bounds an annular region whose inner edge is
    `path` itself, and an open `path` bounds a strip closed across the gap
    where it ran off the surface.

    Returns one region per connected area, or None when the cutter produces
    nothing at all — which is how "the cut surface misses the support" is
    told apart from "the plate stands off nothing".
    """
    if normal is None:
        return None
    region = support.common(_member_slab(cut_surface, normal, flange_width, depth))
    return region if region.Faces else None


def _member_slab(cut_surface: Part.Shape, normal: Vector, width: float, depth: float):
    """The prism the flange band and the plate are together taken out of.

    The cutting surface widened `width` back along its own normal — so the band
    lies in the cut plane *and* on the support's surface — and that widened
    face then stood off `depth` along the same normal.  One solid, not a
    compound of two, because the common of a *shell* with a solid is a curve:
    handing the boolean two overlapping slabs produces no faces at all and
    reads as a support that has no band to give.
    """
    if width <= _PROXIMITY or depth <= _PROXIMITY:
        return Part.makeCompound([])
    widened = cut_surface.copy()
    widened.translate(normal * -width)
    return widened.extrude(normal * (width + depth))


def drape_cuts_of(support: Part.Shape, region):
    """The plate's footprint on `support`, one face per connected region.

    These are subtracted from the support's own faces before those become
    shells, which is the only way the member's boundary keeps *material* on
    both sides.  Subtracting whole faces instead would leave the member's edge
    in void wherever the plate bridged an opening or ran off the surface's
    free edge, and a member sewn to geometry that is not in the mesh matches
    no section at all.
    """
    return [cut for face in support.Faces for cut in face.cut(region).Faces]
