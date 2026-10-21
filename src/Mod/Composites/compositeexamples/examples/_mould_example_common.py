# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Shared helpers for the mould examples.

The mould examples create their features with `addObject` rather than through
the workbench commands, so they have to do for themselves the two things a
command does on the way past: attach each feature's own ViewProvider, and show
the right objects in the right colours.
"""


def _attach_view_provider(obj, provider):
    """Attach a feature's own ViewProvider when a GUI is up.

    The command path does this (`cls_vp(obj.ViewObject)`); a bare `addObject`
    example must do the same, or the GUI object carries no VP proxy — the tree
    shows a default part feature, the icon is missing, and the object cannot be
    enabled for display.
    """
    view = getattr(obj, "ViewObject", None)
    if view is not None and getattr(view, "Proxy", None) is None:
        provider(view)


def _paint(obj, colour, transparency):
    """Tint `obj` if there is a view provider to tint; headless just skips it."""
    view = getattr(obj, "ViewObject", None)
    if view is None:
        return
    try:
        view.ShapeColor = colour
        view.Transparency = transparency
        view.DisplayMode = "Flat Lines"
    except (AttributeError, TypeError, ValueError):
        pass


def _hide(obj):
    view = getattr(obj, "ViewObject", None)
    if view is not None:
        view.Visibility = False
