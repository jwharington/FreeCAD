# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Which node of a deck sits where, and which laminate owns it.

A reported hotspot has to be named by a node the input deck declares and by
the laminate whose plies are there.  Neither is in the result: a layered
composite's results come off the expanded mesh, which CalculiX numbers itself
and whose numbers name no node of any deck.  The deck is the only thing that
knows the answer, and it says it outright —

    *NODE                    node id, position
    *ELEMENT                 node id, its connectivity
    *ELSET + *SHELL SECTION  which laminate those elements belong to

so this reads those blocks (through :mod:`deckcheck`) and answers from them.
The position alone does not, in general, sit exactly on a deck node — a layered
composite reports its results off the expanded mesh, whose nodes sit through
the plies' thickness — so a hotspot is named by the *part* nearest it.

The mapping from a section's elset to the laminate it stands for is the
caller's, passed in as ``section_of``; nothing here bakes in one workbench's
naming.  The lookup caches are explicit arguments — a mutable default would
outlive a document and answer a second model from the first's geography.
"""

import os

from femtools import deckcheck


def position_key(point):
    """The deck's position in microns — how a node is looked up by place."""
    return tuple(round(c * 1000.0) for c in point[:3])


def zones_by_node(path, section_of, cache=None):
    """``({node: "Zone+Zone"}, {node: (x, y, z)})`` — both empty if no deck.

    A node on a bondline is in elements of both sides and is named by both
    laminates, because a hotspot there is in both.  A run whose deck has been
    cleaned up has numbers but no geography, and gets empty maps rather than a
    guess.
    """
    if cache is None:
        cache = {}
    key = ("zones", path)
    if key not in cache:
        zones, coords = {}, {}
        if path and os.path.isfile(path):
            with open(path, errors="replace") as handle:
                deck = deckcheck.parse_inp(handle.read())
            coords = deck["nodes"]
            by_node = {}
            for name in deck["section_elsets"]:
                zone = section_of(name)
                if not zone:
                    continue
                for element in deck["elsets"].get(name, ()):
                    for node in deck["elements"].get(element, ()):
                        by_node.setdefault(node, set()).add(zone)
            zones = {node: "+".join(sorted(found))
                     for node, found in by_node.items()}
        cache[key] = (zones, coords)
    return cache[key]


def position_index(path, section_of, cache=None):
    """``{position key: (node ids, laminate zones)}`` for every node in the deck.

    Nodes sharing a position — a mirrored airframe puts one either side of the
    centreline, and they are one point — are all returned, since a value there
    belongs to each of them, and the zones name every laminate at it.
    """
    if cache is None:
        cache = {}
    key = ("positions", path)
    if key not in cache:
        zones, coords = zones_by_node(path, section_of, cache)
        index = {}
        for node, point in coords.items():
            entry = index.setdefault(position_key(point), ([], set()))
            entry[0].append(node)
            entry[1].update(z for z in zones.get(node, "").split("+") if z)
        cache[key] = {position: (sorted(nodes), "+".join(sorted(found)))
                      for position, (nodes, found) in index.items()}
    return cache[key]


def nearest_part(point, path, section_of, cache=None):
    """``([deck node ids], laminate zones)`` of the part nearest a position.

    The deck's laminate nodes tile the airframe, so the nearest one answers for
    every position: what a hotspot location is for is the part, and the part is
    what the location sits on — a layered composite reports results off the
    expanded mesh, whose nodes sit through the plies' thickness, so the
    position is in general no deck node's position.  Only nodes a laminate owns
    are parts; a point exactly between two laminates names both.
    """
    zones, coords = zones_by_node(path, section_of, cache)
    if point is None or not zones:
        return [], ""
    px, py, pz = point[:3]
    best, nodes, found = None, [], set()
    for node, (x, y, z) in coords.items():
        zoned = zones.get(node)
        if not zoned:
            continue
        distance = (x - px) ** 2 + (y - py) ** 2 + (z - pz) ** 2
        if best is not None and distance > best:
            continue
        if best is None or distance < best:
            best, nodes, found = distance, [], set()
        nodes.append(node)
        found.update(zoned.split("+"))
    return sorted(nodes), "+".join(sorted(found))


def node_at(point, path, section_of, cache=None):
    """``([deck node ids], laminate zones)`` at a position — empty if the deck
    has no node there.

    The ids are the deck's, so they read in the deck and in the ``.frd`` alike;
    the zones name the plies, and are empty where the deck puts no laminate,
    which the caller says as "no laminate" rather than leaving blank.
    """
    if point is None:
        return [], ""
    return position_index(path, section_of, cache).get(position_key(point),
                                                       ([], ""))


def zone_of_node(node, path, section_of, cache=None):
    """What the deck says owns one of its own nodes.

    ``""`` means the deck puts that node in no laminate, which is an answer.
    ``None`` means the deck is not there to answer, and the caller must not
    print it as though it had checked.
    """
    zones, coords = zones_by_node(path, section_of, cache)
    if node not in coords:
        return None
    return zones.get(node, "")
