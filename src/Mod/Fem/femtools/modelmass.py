# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""What a built article weighs, member by member, from the deck it solves on.

Mass is not in the results: a static solve says nothing about it, and no card
in the deck adds it up.  It follows from two things that are stated elsewhere,
and it is computed here from those and nothing else —

    *SHELL SECTION   the ply thicknesses of each laminate, per element elset
    *DENSITY         what each ply's material card weighs per unit volume
    member area      the area of each part the mesh was cut from

so the number is the one ccx would use for its own mass properties, in the
units the deck is written in: mm, Mg.  A member's mass is its area times
``Σ(ρ_ply · t_ply)`` over the plies of the laminate that owns it.

The caller supplies the areas and the member-to-section mapping: which parts
exist and how the model names a section are the article's properties, not the
deck's.  Nothing here reads a document or an object name.
"""

import re

from femtools import deckcheck

GRAMS_PER_MG = 1.0e6

_MATERIAL_NAME = re.compile(r"^\*MATERIAL\b.*?NAME=(.*)$", re.IGNORECASE)
_DENSITY = re.compile(r"^\*DENSITY\b", re.IGNORECASE)


def densities_by_card(text):
    """``{material card name: ρ in Mg/mm³}``, as the deck's own cards say.

    A card name is the whole rest of the ``NAME=`` line, spaces included: a
    laminate card is written ``SKINFWDLAMINATE:00: ORTHOTROPICGLASS-EPOXY``,
    and cutting the name at the first space names a material that does not
    exist.
    """
    lines = text.splitlines()
    densities, card = {}, None
    for index, line in enumerate(lines):
        named = _MATERIAL_NAME.match(line)
        if named:
            card = named.group(1).strip()
            continue
        if _DENSITY.match(line):
            if card is None:
                raise RuntimeError(
                    "*DENSITY on line %d comes before any *MATERIAL — no card "
                    "owns this density, so no ply can be weighed"
                    % (index + 1))
            try:
                densities[card] = float(lines[index + 1].split(",")[0])
            except (IndexError, ValueError):
                raise RuntimeError("*DENSITY on line %d is not followed by a "
                                   "number" % (index + 1))
            continue
    return densities


def _stack_of(block, densities):
    """``[(ρ, t)]`` for one section block, in ply order."""
    thicknesses = block["plies"]
    if block["layered"]:
        cards = block["cards"]
        if len(cards) != len(thicknesses):
            raise RuntimeError(
                "%s states %d thicknesses but %d material cards — a ply "
                "without a card has no density"
                % (block["elset"], len(thicknesses), len(cards)))
        pairs = list(zip(thicknesses, cards))
    else:
        # A plain layer: one thickness, one material, both named once.
        pairs = [(t, block["material"]) for t in thicknesses]
    return [(_density(card, block["elset"], densities), t)
            for t, card in pairs]


def _density(card, elset, densities):
    try:
        return densities[card]
    except KeyError:
        raise RuntimeError(
            "%s cites material %r, which has no *DENSITY card — a ply with no "
            "density weighs nothing, which is not the same as being light"
            % (elset, card))


def stacks_by_section(text, section_of):
    """``{section name: [(ρ, thickness) per ply]}`` for every laminate in the deck.

    ``section_of`` maps the elset a ``*SHELL SECTION`` is written for to the
    section it belongs to, or ``None`` for a block that is not a laminate —
    that naming is the caller's, so the deck reader stays application-neutral.

    One laminate is written as many per-element sections, and they must say the
    same thing; if they do not, the laminate has no one thickness and a mass
    computed from whichever block was read last would be a guess.
    """
    densities = densities_by_card(text)
    stacks = {}
    for block in deckcheck.parse_inp(text)["sections"]:
        section = section_of(block["elset"])
        if section is None:
            continue
        stack = _stack_of(block, densities)
        known = stacks.setdefault(section, stack)
        if known != stack:
            raise RuntimeError(
                "%s is written with two different ply stacks (%s and %s) — a "
                "laminate that is not one laminate cannot be weighed"
                % (section, known, stack))
    return stacks


def masses(areas, owners, stacks):
    """``{member: {area, section, thickness, mass_g}}`` for one built article.

    ``areas`` is ``{member: area}``, ``owners`` is ``{member: section}`` and
    ``stacks`` is :func:`stacks_by_section`'s output.  Every member must be
    referenced by a section and every section must be in the deck: an unweighed
    member is a hole in the article's mass, and the total would read as a
    measurement rather than as a partial one.
    """
    by_member = {}
    for name, area in sorted(areas.items()):
        section = owners.get(name)
        if section is None:
            raise RuntimeError("%s is meshed but no section references it — "
                               "it carries plies that nothing can weigh" % name)
        stack = stacks.get(section)
        if stack is None:
            raise RuntimeError("%s belongs to %s, which the deck does not "
                               "write" % (name, section))
        areal = sum(rho * t for rho, t in stack)
        by_member[name] = {"area": area,
                           "section": section,
                           "thickness": sum(t for _, t in stack),
                           "mass_g": area * areal * GRAMS_PER_MG}
    return by_member


def layups(owners, blocks_by_section, path):
    """``{member: {section, kind, plies: [[t, material], ...], total_mm}}``.

    The layup plan a report should not make you look up: every member's plies
    as the deck writes them — thickness, the material card the ply names, and
    the stack total — read from the same deck the solve ran on, so a run's
    artifact says what its numbers were computed on.  Refuses what the mass
    path refuses: an ownerless member, an unstacked section.
    """
    by_member = {}
    for member, section in sorted(owners.items()):
        block = blocks_by_section.get(section)
        if block is None:
            raise RuntimeError(
                "%s is owned by %s, which wrote no *SHELL SECTION in %s — no "
                "layup to report" % (member, section, path))
        stacked = block["layered"]
        plies = (list(zip(block["plies"], block["cards"])) if stacked
                 else [(block["plies"][0], block["material"])])
        by_member[member] = {
            "section": section,
            "kind": "layered" if stacked else "SMEAR",
            "plies": [[t, card] for t, card in plies],
            "total_mm": sum(t for t, _ in plies),
        }
    return by_member


def summarize(by_member, layup_table):
    """The article's mass: total, per laminate, and per member, in grams.

    Per laminate is what a layup iteration changes; per member is where a
    cut-vs-uncut difference actually sits, which is the question two articles
    are built to ask.
    """
    by_laminate = {}
    for member in by_member.values():
        key = member["section"][:-len("_Section")]
        by_laminate[key] = by_laminate.get(key, 0.0) + member["mass_g"]
    return {"total_g": sum(m["mass_g"] for m in by_member.values()),
            "by_laminate": by_laminate,
            "by_member": by_member,
            "layups": layup_table}
