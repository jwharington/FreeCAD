# SPDX-License-Identifier: LGPL-2.1-or-later
"""Load the Composites C++ draping solver (``Composites_drape``).

The solver is a standalone pybind11 Python extension (``Composites_drape.so``)
built and installed next to the Composites package. It is searched in priority
order:

1. ``COMPOSITES_DRAPE_SO`` env var — explicit forced path (dev override).
2. The ``.so`` co-located with this package (the normal case when the
   Composites package itself was imported from the build/install tree).
3. FreeCAD's install Mod tree —
   ``<FreeCAD.getHomePath()>/Mod/Composites/ext/_native/Composites_drape.so``.
   This handles the case where ``import Composites`` resolved to a source
   checkout (e.g. ``FreeCADCmd -P <src>/Mod`` for running tests against the
   source tree) whose ``ext/_native/`` has no built ``.so``.
4. The user Mod tree (``~/.local/share/FreeCAD/v*/Mod/Composites/...``).
5. A plain ``import Composites_drape`` (system-wide install on ``sys.path``).

Only when none of these locate the solver does this raise ``ImportError``.
"""

from __future__ import annotations

import glob
import importlib.util
import os
from pathlib import Path

__all__ = ["solve"]


def _load_from_path(so_path: str):
    """Load ``Composites_drape`` from an explicit ``.so`` path."""
    spec = importlib.util.spec_from_file_location("Composites_drape", so_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _candidate_so_paths():
    """Yield candidate ``Composites_drape.so`` paths in priority order."""
    # 2. Co-located with this package.
    yield Path(__file__).with_name("Composites_drape.so")

    # 3. FreeCAD's install Mod tree (handles source-tree package imports).
    try:
        import FreeCAD

        home = FreeCAD.getHomePath()
        if home:
            yield Path(home, "Mod", "Composites", "ext", "_native",
                        "Composites_drape.so")
    except Exception:
        pass

    # 4. User Mod tree(s).
    user_data = os.path.expanduser("~/.local/share/FreeCAD")
    if user_data:
        yield from (
            Path(p)
            for p in glob.glob(
                os.path.join(user_data, "v*", "Mod", "Composites",
                             "ext", "_native", "Composites_drape.so")
            )
        )


def _load():
    # 1. Forced path via env var.
    forced = os.environ.get("COMPOSITES_DRAPE_SO")
    if forced and Path(forced).exists():
        return _load_from_path(forced)

    # 2-4. Search candidate paths.
    for candidate in _candidate_so_paths():
        if candidate.exists():
            return _load_from_path(str(candidate))

    # 5. System-wide install.
    try:
        import Composites_drape as mod  # noqa: F401
        return mod
    except ImportError:
        pass

    raise ImportError(
        "No Composites_drape solver found. Rebuild FreeCAD with "
        "BUILD_COMPOSITES=ON, or set the COMPOSITES_DRAPE_SO env var to the "
        "path of Composites_drape.so."
    )


_mod = _load()
solve = _mod.solve
