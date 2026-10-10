# SPDX-License-Identifier: LGPL-2.1-or-later

"""Re-execute a model's laminates so their FEM layer data exists.

``FEMLayers`` is a live proxy attribute computed in ``execute()``: it does not
survive a document restore, and the CalculiX writer reads it to emit the
per-layer shell sections.  So any pass that writes a deck from a document it
did not just build - a reopened file, or a model built in two stages - has to
touch its laminates once first, or every section is written from stale or
missing layers.
"""

# Composite objects whose FEM layers the writer reads.  The suffix is the
# naming the composite features give themselves, not a study's choice.
LAMINATE_NAME_SUFFIXES = ("Laminate", "CombinedLaminate")


def refresh_laminates(doc, analysis=None):
    """Touch every laminate and recompute; returns how many were touched.

    ``analysis`` defaults to the document's ``Analysis``, and the laminates it
    already holds are left alone: those are the ones the analysis owns, and
    touching them is its own business.
    """
    holder = analysis if analysis is not None else doc.getObject("Analysis")
    in_analysis = set(holder.Group) if holder is not None else set()
    touched = 0
    for obj in doc.Objects:
        if obj in in_analysis or not obj.Name.endswith(LAMINATE_NAME_SUFFIXES):
            continue
        obj.touch()
        touched += 1
    doc.recompute()
    return touched
