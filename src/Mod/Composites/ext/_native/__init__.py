# SPDX-License-Identifier: LGPL-2.1-or-later
"""Lazy loader for the Composites C++ extension.

In a FreeCAD-integrated build (BUILD_COMPOSITES=ON), the C++ extension
is built as ``Composites_drape`` and placed in the build directory.
This shim finds and imports it.

In a portable/dev install, the .so lives in ``ext/_native/``.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent

# ── Portable/dev install: .so in ext/_native/ ──────────────────
_forced_so: str | None = os.environ.get("COMPOSITES_DRAPE_SO")

if _forced_so and Path(_forced_so).exists():
    _spec = importlib.util.spec_from_file_location("Composites_drape", _forced_so)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    solve = _mod.solve
else:
    # Search for .so in _native/
    _found = None
    for _p in sorted(_PACKAGE_DIR.glob("Composites_drape*.so")):
        _found = str(_p)
        break
    if _found is None:
        # Fallback: try importing as a FreeCAD-installed module
        try:
            import Composites_drape as _mod
            solve = _mod.solve
        except ImportError:
            solve = None  # will be caught upstream
    else:
        _spec = importlib.util.spec_from_file_location("Composites_drape", _found)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        solve = _mod.solve


__all__ = ["solve"]
