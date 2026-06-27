# SPDX-License-Identifier: LGPL-2.1-or-later
"""Load the Composites C++ draping solver."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

# ── Priority 1: Forced SO via env var ─────────────────────────
_forced_so = os.environ.get("COMPOSITES_DRAPE_SO")
if _forced_so and Path(_forced_so).exists():
    _spec = importlib.util.spec_from_file_location("Composites_drape", _forced_so)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    solve = _mod.solve
else:
    # ── Priority 2: .so co-located with this package ──────────
    _so = Path(__file__).with_name("Composites_drape.so")
    if _so.exists():
        _spec = importlib.util.spec_from_file_location("Composites_drape", str(_so))
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        solve = _mod.solve
    else:
        # ── Priority 3: System-wide install ───────────────────
        try:
            import Composites_drape as _mod
            solve = _mod.solve
        except ImportError:
            raise ImportError("No Composites_drape solver found. "
                              "Rebuild FreeCAD with BUILD_COMPOSITES=ON")


__all__ = ["solve"]
