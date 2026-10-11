# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Document tree and visibility passes for a finished composite build.

A build runs headless, where nothing hides the scaffolding, so every ply,
laminate, datum, section and tool would otherwise load visible and the GUI
would open hundreds of objects at once.  These passes state the finished
structure, and file what is left into named groups.  Which objects are which
is the caller's knowledge, so a name list arrives as ARGUMENTS here - a
second part's names are its own.
"""

import json


def apply_visibility(doc, structure):
    """Show only the parts of ``structure``; hide everything else.

    ``structure`` is a compound that links exactly the finished pieces, so the
    keep-set is read from it - one definition of the finished structure, no
    duplicated name lists.  Everything else is hidden, because FreeCAD leaves
    every created object visible.
    """
    finished = set(getattr(structure, "Links", []) or [])
    for obj in doc.Objects:
        obj.Visibility = obj in finished


def apply_review_visibility(doc, article):
    """Show the article, hide the build scaffold.

    ``article`` is the explicit set of objects the reviewer wants to see.  A
    name rule cannot stand in for it: the finished shells are their own
    objects in every article, and an uncut article's drape sources look like
    finished sources.
    """
    visible = set(article)
    for obj in doc.Objects:
        obj.Visibility = obj.Name in visible


def group_top_level(doc, container, rules):
    """File the construction-only top-level objects into groups.

    ``rules`` is an ordered list of ``(group_name, match)`` pairs; ``match``
    takes an object's ``(Name, TypeId)`` and answers whether it belongs in
    that group.  A model then shows a few curated groups instead of hundreds
    of loose objects - the bulk is rosette LCS machinery and per-stiffener
    support/remainder features nobody selects in the 3D view.  Membership
    does not change 3D visibility, and links (sections, DrapeSource) survive
    regrouping.  Objects already in the container are left where they are.
    """
    def members_of(container_obj):
        # By NAME, never by wrapper identity: the same underlying object
        # reached through a fresh doc.Objects access is a different Python
        # wrapper, and an object-set `taken` would silently fail to
        # recognise it - filing one object into a second group and dying on
        # "Object can only be in a single Group".
        try:
            return set(o.Name for o in container_obj.Group)
        except Exception:
            return set()

    taken = members_of(container)
    for group_name, match in rules:
        group = doc.getObject(group_name)
        if group is None:
            group = doc.addObject("App::DocumentObjectGroup", group_name)
        picked = [
            obj for obj in doc.Objects
            if obj.Name not in taken and match(obj.Name, obj.TypeId)
        ]
        if picked:
            group.Group = picked
            taken.update(o.Name for o in picked)


def log_drape_coverage(doc, log):
    """One line per draped shell: coverage, worst shear, quality verdict.

    ``log`` is the caller's progress callable, so a build's lines share one
    timeline and one prefix.
    """
    for obj in doc.Objects:
        raw = getattr(obj, "DrapeDiagnostics", None)
        if not raw:
            continue
        try:
            diag = json.loads(raw)
        except Exception:
            continue
        if diag.get("status") != "valid":
            log(
                "drape %s: status=%s (%s)"
                % (obj.Name, diag.get("status"), diag.get("failure_reason"))
            )
            continue
        log(
            "drape %s: coverage %s, max shear %.1f deg, %s"
            % (
                obj.Name,
                ("%.1f%%" % (100.0 * float(diag["coverage_ratio"]))
                 if diag.get("coverage_ratio") is not None else "not measured"),
                float(diag.get("max_shear_deg", 0.0)),
                "quality PASS" if getattr(obj, "QualityPass", False) else "quality FAIL",
            )
        )
