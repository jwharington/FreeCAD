# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Seam extraction — generates overlap geometry from master/attachment."""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import FreeCAD


def _import_extractor():
    """Import the C++ seam extraction function."""
    import Composites_drape
    return Composites_drape.extract_seam


def extract_seam(
    master: Any,
    attachment: Any,
    seam_width: float = 10.0,
) -> dict[str, Any]:
    """Extract seam geometry between master and attachment surfaces.

    Args:
        master: Master surface (Part.Face or Part.Shape with Faces).
        attachment: Attachment surface (Part.Face or Part.Shape with Faces).
        seam_width: Desired seam width in mm (default 10.0).

    Returns:
        Dict with keys:
            success (bool): Whether extraction succeeded.
            error (str): Error message on failure, empty on success.
            seam (Part.Shape or None): The extracted seam surface.
            remainder (Part.Shape or None): Remaining attachment geometry.
    """
    import FreeCAD
    import Part

    solver = _import_extractor()

    # Validate inputs
    if master is None or attachment is None:
        raise ValueError("master and attachment must not be None")

    # Handle both Face and Shape inputs
    master_shape = _ensure_shape(master)
    attachment_shape = _ensure_shape(attachment)

    result = solver(master_shape, attachment_shape, seam_width)

    if not result.get("success"):
        FreeCAD.Console.PrintWarning(
            f"Seam extraction failed: {result.get('error', 'unknown error')}\n"
        )
        return {
            "success": False,
            "error": result.get("error", "unknown error"),
            "seam": None,
            "remainder": None,
        }

    # Decode BREP bytes back into Part.Shape objects.
    seam = _decode_brep(result["seam"]) if result.get("seam") else None
    remainder = _decode_brep(result["remainder"]) if result.get("remainder") else None

    return {
        "success": True,
        "error": "",
        "seam": seam,
        "remainder": remainder,
    }


def _decode_brep(brep_bytes: Any) -> Any:
    """Decode BREP bytes into a Part.Shape."""
    import Part

    if not isinstance(brep_bytes, bytes):
        return None

    # Write BREP bytes to a temp file and read via Part.read.
    fd, path = tempfile.mkstemp(suffix=".brep")
    try:
        os.write(fd, brep_bytes)
        os.close(fd)
        fd = -1
        return Part.read(path)
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(path)
        except OSError:
            pass


def _ensure_shape(obj: Any) -> Any:
    """Ensure obj is a Part.Shape.

    Accepts Part.Face, Part.Shape, or any object with a Shape attribute.
    """
    import Part

    if isinstance(obj, Part.Shape):
        return obj

    if isinstance(obj, Part.Face):
        return obj.Shape

    shape = getattr(obj, "Shape", None)
    if shape is not None and isinstance(shape, Part.Shape):
        return shape

    raise TypeError(
        f"Expected Part.Shape or Part.Face, got {type(obj).__name__}"
    )