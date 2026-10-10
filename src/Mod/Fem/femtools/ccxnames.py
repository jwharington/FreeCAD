# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""The names the CalculiX writer gives a section's elements in the deck.

A section is normally written once, under its own elset name.  A draped section
is written one card per element, and each element's elset is named by digesting
the section's elset name and appending the element id — the un-hashed name
carries the whole material/shell/thickness concatenation once per element and
reaches CalculiX's 80-character name limit (:mod:`~femsolver.calculix.
write_femelement_geometry`).

:func:`hashed_prefix` is that digest, defined here and used by the writer so a
reader recognises such a name by recomputing the same digest rather than by
guessing it.  A digest is not reversible, so the section it belongs to is
recovered only against the candidate names the caller passes in — nothing here
knows what a section is, or how a workbench spells one.
"""

import hashlib

HASHED_PREFIX_LENGTH = 20


def hashed_prefix(text):
    """A stable 20-character stand-in for ``text`` (md5, not a salted hash).

    md5 rather than the built-in ``hash()``: that is salted per process, so a
    deck built in one run would not match the same deck built in another.
    """
    return hashlib.md5(text.encode()).hexdigest()[:HASHED_PREFIX_LENGTH]


def elset_index(bases):
    """``({base name: section}, {digest: section})`` for a set of sections.

    ``bases`` maps a section to the elset name the writer would start from for
    it.  Building both lookups once makes resolving a deck's elsets O(1) each,
    rather than recomputing every digest for every elset.
    """
    plain, hashed = {}, {}
    for section, base in bases.items():
        plain[base] = section
        hashed[hashed_prefix(base)] = section
    return plain, hashed


def section_of_elset(elset, index):
    """The section a deck elset was written for, or ``None``.

    Recognises the whole section under its own name, one element under
    ``<base>_<id>``, and a per-element section under
    ``<digest of base>_<id>`` — the digest spelling the writer uses when it
    cannot keep the full name.
    """
    plain, hashed = index
    head, _, tail = elset.rpartition("_")
    name = head if head and tail.isdigit() else elset
    return plain.get(name) or hashed.get(name)
