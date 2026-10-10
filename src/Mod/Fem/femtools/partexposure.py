# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Which part of a structure every result node sits on, and each part's worst.

A run reports one global hotspot, and a hotspot has a part because
:func:`femtools.decknodes.nearest_part` names the laminate whose deck nodes
tile the structure around it.  Per-part accounting asks that question of every
node the result carries, not one of them, so it is answered from the same
source the deck gives it and vectorized:

    *NODE / *ELEMENT / *ELSET  ->  deck node -> section
    section references         ->  section -> member, split per member by its
                                   bounding box where one section spans two
                                   (mirrored halves share a section; their
                                   boxes meet only at the seam)
    cKDTree per member         ->  result node -> nearest deck node(s)

A result node of a layered composite sits through the plies' thickness, so it
is named by the deck node(s) it is nearest: exactly one normally, and every
node within the tie window of the best is named too, because a node on a
bondline is in both laminates and a high value there counts against both.  A
node no member claims is counted and reported rather than silently dropped.

The section-to-member mapping and the bounding boxes are passed in: which parts
exist and how the model names a section are the article's properties, not the
deck's.  The tie and reach windows are arguments, never module constants a
caller cannot move.
"""

import numpy as np
from scipy.spatial import cKDTree

# A node whose distance to the best member's deck node is within this of the
# best is claimed by every member that close.  Ply mid-planes sit up to ~2.4 mm
# off the surface (a 4.8 mm laminate); neighbouring members' surfaces are a mesh
# size apart except across a bondline, so 0.5 mm catches the bonded pairs
# without reaching across open space.
TIE_MM = 0.5

BBOX_MARGIN = 0.01

# A node further than this from every member's deck node is off the structure
# the members tile — counted, never attributed.
UNREACHED_MM = 50.0


def section_members(section_references, members):
    """``{section name: [member names]}`` — who each section's references name.

    ``section_references`` is ``{section name: [referenced names]}``; only
    references to members of the meshed structure count.  A section that names
    none of them owns no deck geography and is reported by the caller through
    the unclaimed-node count, not silently.
    """
    found = {}
    for name, references in section_references.items():
        named = [reference for reference in references if reference in members]
        if named:
            found[name] = named
    return found


def clouds(zones, coords, claimed, boxes, margin=BBOX_MARGIN):
    """``({member name: (k, 3) deck node positions}, note)``.

    ``zones``/``coords`` come from :func:`femtools.decknodes.zones_by_node`,
    ``claimed`` from :func:`section_members`, and ``boxes`` is
    ``{member: bounding box}``.  A deck node is a member's when an element
    carrying that member's section contains it and the node lies inside the
    member's bounding box — the split that separates the mirrored halves a
    shared section spans.  A node on the seam belongs to both, and so does a
    node in two sections across a bondline.
    """
    if not zones or not coords:
        return {}, "no deck geography"
    buckets = {name: [] for name in boxes}
    orphans = 0
    for node, zone_text in zones.items():
        point = coords[node]
        owners = set()
        for section in zone_text.split("+"):
            for name in claimed.get(section, ()):
                if _inside(boxes[name], point, margin):
                    owners.add(name)
        if not owners:
            orphans += 1
            continue
        for name in owners:
            buckets[name].append(point)
    found = {name: np.array(points) for name, points in buckets.items()
             if points}
    note = ("%d of %d deck nodes name no member" % (orphans, len(zones))
            if orphans else "")
    return found, note


def assign(positions, clouds, tie=TIE_MM, unreached=UNREACHED_MM):
    """``({member: row indices}, unclaimed count)`` for result node positions.

    Every member whose deck node is within ``tie`` of the best distance claims
    the node — a bondline node lands in both of its members.  A node no cloud
    reaches within ``unreached`` is unclaimed, and the count says so rather
    than dropping it silently.
    """
    if not clouds or not len(positions):
        return {}, len(positions)
    distance = np.empty((len(positions), len(clouds)))
    names = sorted(clouds)
    for column, name in enumerate(names):
        distance[:, column] = cKDTree(clouds[name]).query(positions)[0]
    best = distance.min(axis=1)
    # The tie window widens the claim only among nodes the structure reaches at
    # all; otherwise a lone member claims everything within tie of its own best,
    # however far that best is.
    reached = best <= unreached
    best_reached = np.where(reached, best, np.inf)
    assignment = {}
    for column, name in enumerate(names):
        rows = np.where(reached & (distance[:, column] <= best_reached + tie))[0]
        if len(rows):
            assignment[name] = rows
    unclaimed = int(np.sum(~reached))
    return assignment, unclaimed


def maxima(utilization, assignment):
    """``{member: worst exposure factor over the nodes it was given}``."""
    worst = {}
    for name, rows in assignment.items():
        worst[name] = float(utilization[rows].max())
    return worst


def _inside(bbox, point, margin=BBOX_MARGIN):
    return (bbox.XMin - margin <= point[0] <= bbox.XMax + margin
            and bbox.YMin - margin <= point[1] <= bbox.YMax + margin
            and bbox.ZMin - margin <= point[2] <= bbox.ZMax + margin)
