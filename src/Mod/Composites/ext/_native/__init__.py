# SPDX-License-Identifier: LGPL-2.1-or-later
"""Compatibility shim for the Composites C++ draping solver.

The solver (``Composites_drape.so``) is now installed to FreeCAD's
``lib/`` directory and imported via the standard Python import
mechanism (``import Composites_drape``), matching the pattern used
by Fem, Part, and other workbenches.

This module re-exports the solver functions for backwards compatibility
with code that imports from ``Composites.ext._native``.
"""

from __future__ import annotations

import Composites_drape

__all__ = ["solve", "extract_seam"]

solve = Composites_drape.solve
extract_seam = Composites_drape.extract_seam
