# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Create boundary conditions idempotently, and read them back before writing.

Two disciplines a study script has to keep, both of which a solver will not
report on:

* **Idempotent creation.**  A constraint is looked up by name and re-pointed,
  never re-created, so re-running a script does not leave ``.001`` copies whose
  only difference is which one the writer happened to walk.
* **Read-back.**  A load's Force and Torque are read *from the object* before
  the deck is written and compared against the intent, failing loudly on a sign
  flip or a dropped term.  A sign-flipped load writes a valid-looking deck and
  solves to nonsense — the same silent-direction failure class as a force whose
  axis comes from the wrong place.

The force and torque a reaction carries are arguments here, not module state:
what a load case means belongs to the study.
"""

import FreeCAD
import ObjectsFem

# The writer applies the negative of the desired load (reaction convention), so
# the object stores it negated.  Named rather than spelled ``-1`` at each use so
# the read-back compares against the same sign it wrote.
REACTION_SIGN = -1.0


def set_references(constraint, references):
    """Point a constraint at geometry, if it has a ``References`` property."""
    if constraint is None:
        return
    if hasattr(constraint, "References"):
        constraint.References = references


def add_to_analysis(analysis, obj):
    """Put an object into an analysis once, if the analysis takes objects."""
    if analysis is None or obj is None:
        return
    add_object = getattr(analysis, "addObject", None)
    if callable(add_object):
        add_object(obj)


def add_fixed(doc, analysis, tag, references):
    """The fixed constraint named ``tag``, created or re-pointed, never doubled."""
    fixed = doc.getObject(tag)
    if fixed is None:
        fixed = ObjectsFem.makeConstraintFixed(doc, tag)
    set_references(fixed, references)
    add_to_analysis(analysis, fixed)
    return fixed


def add_reaction(doc, analysis, tag, references, force, torque, origin,
                 sign=REACTION_SIGN):
    """The reaction load named ``tag``, created or updated, never doubled.

    ``force`` and ``torque`` are the desired load as three components each; the
    object stores ``sign`` times them, because that is the reaction convention
    the writer applies.  ``origin`` is the point the torque is referred to.
    """
    reaction = doc.getObject(tag)
    if reaction is None:
        reaction = ObjectsFem.makeConstraintReaction(doc, tag)
    set_references(reaction, references)
    reaction.ModelType = "Uniform"  # pure area weighting: exact resultant
    reaction.Force = FreeCAD.Vector(*(sign * component for component in force))
    reaction.Torque = FreeCAD.Vector(*(sign * component for component in torque))
    reaction.Origin = FreeCAD.Placement(origin, FreeCAD.Rotation())
    add_to_analysis(analysis, reaction)
    return reaction


def verify_reaction(reaction, force, torque, sign=REACTION_SIGN, tolerance=1e-9):
    """Read Force and Torque back from the object and compare with the intent.

    Raises on a sign flip or a dropped term; returns nothing otherwise, because
    silence is the pass.
    """
    expected_f = FreeCAD.Vector(*(sign * component for component in force))
    expected_t = FreeCAD.Vector(*(sign * component for component in torque))
    for label, got, expected in (("Force", reaction.Force, expected_f),
                                 ("Torque", reaction.Torque, expected_t)):
        if (got - expected).Length > tolerance:
            raise RuntimeError(
                "%s: %s is (%g, %g, %g) — expected (%g, %g, %g)"
                % (reaction.Name, label, got.x, got.y, got.z,
                   expected.x, expected.y, expected.z))
