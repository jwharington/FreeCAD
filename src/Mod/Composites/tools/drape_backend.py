# SPDX-License-Identifier: LGPL-2.1-or-later

"""Drape backend seam contracts used by CompositeShell."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DrapeBackend(ABC):
    """Common drape backend contract for CompositeShell consumers.

    ``get_tex_coords`` is a legacy API name used by rendering consumers.
    Implementations may provide CAD surface-parameter coordinates (u, v) rather
    than physical material texture coordinates.
    """

    backend_name = "unknown"

    @abstractmethod
    def is_valid(self) -> bool:
        """Return whether the backend has a valid solved state."""

    @abstractmethod
    def diagnostics(self) -> dict[str, Any]:
        """Return backend diagnostics payload."""

    def get_tex_coords(self, offset_angle_deg: float = 0) -> list[Any] | None:
        return None

    def get_boundaries(self, offset_angle_deg: float = 0) -> list[list[Any]] | None:
        return None

    def get_lcs(self, tri: Any) -> Any | None:
        return None

    def get_lcs_at_point(self, center: Any) -> Any | None:
        return None

    def get_tex_coord_at_point(self, point: Any, offset_angle_deg: float = 0) -> Any | None:
        return None

    @property
    def strains(self) -> Any | None:
        return None
