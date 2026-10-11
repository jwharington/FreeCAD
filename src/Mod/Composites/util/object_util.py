# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Helpers for the document objects a composite build creates."""


def shape_object(doc, name, shape):
    """A ``Part::Feature`` named ``name`` holding ``shape``."""
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = shape
    return obj


def attach_view_provider(obj, view_provider_cls):
    """Install a view provider, unless the feature already installed one.

    The feature constructors attach their own view provider when a GUI is
    up — ``CompositeShellFP.__init__`` sets ``ViewObject.Proxy`` — so
    attaching it again re-runs the view provider's constructor, which adds
    its properties a second time and raises ``NameError: Property ...
    already exists``.  Headless there is no ``ViewObject`` and this does
    nothing.
    """
    view = getattr(obj, "ViewObject", None)
    if view is None:
        return
    if isinstance(getattr(view, "Proxy", None), view_provider_cls):
        return
    view_provider_cls(view)


def is_composite_geometry(obj):
    """Whether the FEM laminate provider can resolve a laminate through obj.

    drape_laminate_provider.get_compshell_obj accepts a section's first
    reference only when it is a ``Composite::Shell``; anything else
    silently degrades that section to one smeared isotropic layer at the
    thickness the section object was created with.  A deck audit checks
    the same thing from the other end, on the written deck.
    """
    proxy = getattr(obj, "Proxy", None)
    return bool(proxy) and getattr(proxy, "Type", None) == "Composite::Shell"
