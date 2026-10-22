# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Shared helpers for the mould examples.

The mould examples create their features with `addObject` rather than through
the workbench commands, so they have to do for themselves the two things a
command does on the way past: attach each feature's own ViewProvider, and show
the right objects in the right colours.
"""

# The land the mould halves close on: an s-curve levelling of the outer rail, held
# flat for the first 10 mm outboard of the cutline - the spec's absolute minimum
# transition, below which an S-curve reads as a crease. Downstream cuts the seal
# groove into that strip, so a mould example that wants one asks for this, and the
# examples share these rather than each keeping its own copy.
LEVELLING = "s-curve"
LEVELLING_EXTENT = "fixed"
LEVELLING_TRANSITION_MM = 10.0

# Cut the O-ring groove into that land. The groove has to be asked for before the
# fixture command sizes the block, because that sizing is what gives the strip
# the width to carry the groove clear of the clamp bolts; asking for it after
# only gets the shortfall reported.
SEAL_GROOVE = True


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


def _show(obj):
    """Show `obj`; headless there is no view provider and nothing to show."""
    view = getattr(obj, "ViewObject", None)
    if view is not None:
        view.Visibility = True
