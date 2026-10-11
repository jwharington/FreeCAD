# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Applying one stack model to every laminate in a document."""

from ..mechanics import StackModelType


def apply_stack_model(doc, laminate_groups, stack_model_type):
    """Set the stack model of every laminate, and prove it took.

    Whether the deck gets one layer per ply or a merged homogenised stack is
    a modelling choice that has to be the same everywhere in the model for a
    comparison run to mean anything.  It is applied here rather than in the
    builders because combined laminates are created deep inside the stiffener
    code, out of reach of a laminate builder.

    ``laminate_groups`` maps each laminate to the members carrying it; every
    laminate named there must be found in the document, or its stack model is
    unknown and the comparison is meaningless.  Reads the value back from
    each object: a property that silently fails to stick is the failure mode
    worth catching, not the assignment.
    """
    if stack_model_type not in StackModelType.__members__:
        raise RuntimeError(
            "stack model %r is not one of %s"
            % (stack_model_type, ", ".join(StackModelType.__members__))
        )
    applied, refused = set(), []
    for obj in doc.Objects:
        if not hasattr(obj, "StackModelType"):
            continue
        obj.StackModelType = stack_model_type
        if obj.StackModelType != stack_model_type:
            refused.append(obj.Name)
        applied.add(obj.Name)
    missed = sorted({lam.Name for lam, _ in laminate_groups} - applied)
    if missed:
        raise RuntimeError(
            "laminates with no StackModelType, so their stack model is "
            "unknown to this switch: %s" % ", ".join(missed)
        )
    if refused:
        raise RuntimeError(
            "StackModelType did not stick on: %s" % ", ".join(refused)
        )
    # Recompute now: a merged stack is computed in the laminate's
    # execute(), and an error there should stop the build here rather
    # than turning into a surprise while the deck is being written.
    doc.recompute()
    print("stack model: %s on %d laminates"
          % (stack_model_type, len(applied)))
