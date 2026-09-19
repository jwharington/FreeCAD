# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Coin-native weave rendering for offscreen captures.

The GLSL weave shader (:mod:`Composites.shaders.MeshGridShader`) is the
interactive renderer, but offscreen captures (``saveImage`` and friends)
do not reproduce its output faithfully. This module provides a
capture-only rendering mode that reproduces the weave with plain Coin3D
state — no shader program in the path:

- an RGBA weave texture (one warp:weft cell, transparent background),
  wrapped and mapped by the support surface's UV coordinates;
- an ``SoTextureMatrixTransform`` carrying ``R(offset_angle) ·
  S(1/GridSpacingX, 1/GridSpacingY)``, mirroring the shader uniforms
  (``offset_angle``, ``grid_spacing_x_mm``, ``grid_spacing_y_mm``).

Enter before a capture and exit afterwards; the interactive shader is
restored untouched.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from pivy import coin

_CAPTURE_GROUP_NAME = "CoinWeaveCapture"

#: Texture resolution: texels per millimetre of weave pattern.
_PX_PER_MM = 10.0

#: Grid line width in millimetres (the shader's is ~1 screen pixel; this
#: fixed world-space width keeps captures resolution-independent).
_LINE_MM = 1.0

#: Cloth body colour (light grey) and line colour (dark grey). The
#: interactive shader renders lines on a transparent background, which is
#: unreadable in captures against a dark page — the capture cloth is
#: opaque and light so the grid reads on paper.
_CLOTH_RGB = 214
_LINE_RGB = 50


def _make_weave_image(
    spacing_x_mm: float,
    spacing_y_mm: float,
    line_mm: float = _LINE_MM,
    px_per_mm: float = _PX_PER_MM,
) -> tuple[coin.SbVec2s, bytes]:
    """Build one weave cell as RGBA bytes: dark warp + weft lines on a light
    opaque cloth.

    The cell spans ``spacing_x_mm × spacing_y_mm`` of UV space; the warp
    line runs along u, the weft line along v, matching the shader's grid
    (one line of each per cell). Unlike the shader (transparent between
    lines), the cloth body is opaque and light so the grid is legible in
    captures on any background.
    """
    w = max(int(round(spacing_x_mm * px_per_mm)), 8)
    h = max(int(round(spacing_y_mm * px_per_mm)), 8)
    line = max(int(round(line_mm * px_per_mm)), 1)

    image = np.full((h, w, 4), _CLOTH_RGB, dtype=np.uint8)
    image[:, :, 3] = 255

    def band(size: int, width: int) -> slice:
        start = size // 2 - width // 2
        return slice(start, start + width)

    # Weft line: constant v → horizontal band.
    image[band(h, line), :, 0:3] = _LINE_RGB
    # Warp line: constant u → vertical band.
    image[:, band(w, line), 0:3] = _LINE_RGB
    return coin.SbVec2s(w, h), image.tobytes()


def make_weave_texture(spacing_x_mm: float, spacing_y_mm: float) -> coin.SoTexture2:
    """Create the repeating weave texture for one grid cell."""
    size, data = _make_weave_image(spacing_x_mm, spacing_y_mm)
    texture = coin.SoTexture2()
    texture.wrapS.setValue(coin.SoTexture2.REPEAT)
    texture.wrapT.setValue(coin.SoTexture2.REPEAT)
    texture.model.setValue(coin.SoTexture2.MODULATE)
    texture.image.setValue(size, 4, data)
    return texture


def _weave_texture_matrix(
    spacing_x_mm: float, spacing_y_mm: float, offset_angle_deg: float
) -> coin.SbMatrix:
    """Texture matrix mirroring the shader: rotate the weave by the layer's
    fibre angle, scale UV (mm) so one texture repeat spans one grid cell."""
    matrix = coin.SbMatrix()
    matrix.setRotate(
        coin.SbRotation(coin.SbVec3f(0.0, 0.0, 1.0), math.radians(offset_angle_deg))
    )
    scale = coin.SbMatrix()
    scale.setScale(coin.SbVec3f(1.0 / spacing_x_mm, 1.0 / spacing_y_mm, 1.0))
    matrix.multRight(scale)
    return matrix


def enter_coin_capture(vp: Any) -> bool:
    """Switch one shell's view provider to Coin-native weave rendering.

    Detaches the GLSL shader and injects a plain-Coin subtree (material,
    weave texture, texture matrix, support-surface geometry) into the
    shell's drape host. The display mode stays on the empty "Grid" branch
    so the native Part shape does not double-render under the weave.

    Returns True when the shell is in capture mode, False when the shell
    has no drape geometry to render (e.g. a shell that never solved).
    """
    if getattr(vp, "_capture_grp", None) is not None:
        return True  # already in capture mode
    drape_host = getattr(vp, "drape_host", None)
    if drape_host is None:
        return False
    geometry = getattr(getattr(vp, "grid_shader", None), "_coin_geo", None)
    if geometry is None:
        return False  # nothing injected — leave the native shape alone

    view_object = vp.ViewObject
    spacing_x = float(getattr(view_object, "GridSpacingX", 20.0))
    spacing_y = float(getattr(view_object, "GridSpacingY", 10.0))
    offset_angle = vp.get_offset_angle(vp.Object)

    group = coin.SoSeparator()
    group.setName(_CAPTURE_GROUP_NAME)

    transparency = coin.SoTransparencyType()
    transparency.value = coin.SoTransparencyType.BLEND
    group.addChild(transparency)

    material = coin.SoMaterial()
    material.diffuseColor = (1.0, 1.0, 1.0)
    material.transparency = 0.0
    group.addChild(material)

    group.addChild(make_weave_texture(spacing_x, spacing_y))

    matrix = coin.SoTextureMatrixTransform()
    matrix.matrix.setValue(_weave_texture_matrix(spacing_x, spacing_y, offset_angle))
    group.addChild(matrix)

    binding = coin.SoTextureCoordinateBinding()
    binding.value = coin.SoTextureCoordinateBinding.PER_VERTEX_INDEXED
    group.addChild(binding)

    group.addChild(geometry)

    vp.remove_shader()
    vp._capture_grp = group
    drape_host.addChild(group)
    return True


def exit_coin_capture(vp: Any) -> None:
    """Leave capture mode: drop the Coin-native subtree and restore the
    interactive GLSL weave shader."""
    group = getattr(vp, "_capture_grp", None)
    if group is not None:
        drape_host = getattr(vp, "drape_host", None)
        if drape_host is not None:
            children = drape_host.getChildren()
            if children is not None:
                for i in range(int(children.getLength()) - 1, -1, -1):
                    child = children[i]
                    if child is not None and child.getName() == _CAPTURE_GROUP_NAME:
                        drape_host.removeChild(i)
                        break
        vp._capture_grp = None
    vp.load_shader()
    vp.update_visibility(vp.ViewObject)
