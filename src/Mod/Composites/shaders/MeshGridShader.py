# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""GLSL shader for draped mesh warp/weft visualization.

Inserts shader state (SoShaderProgram, SoTextureCoordinate3,
SoTextureMatrixTransform) directly into the DrapeMesh's RootNode before
the geometry Switch.  A SoMaterialBinding override disables VBO rendering
on SoFCIndexedFaceSet, forcing it to use Coin3D's standard GLRender path
which respects shader state and per-vertex texture coordinates.

No overlay mesh is created — the shader renders directly on the native
DrapeMesh geometry.
"""

from __future__ import annotations

import math
from os import path
from typing import Any

import numpy as np
from pivy import coin


def remove_by_name(node: Any, name: str) -> bool:
    """Remove child node by name."""
    item = node.getByName(name)
    if item:
        node.removeChild(item)
        return True
    return False


class MeshGridShader:
    """GLSL shader for draped mesh visualization.

    Inserts GLSL shader state directly into the DrapeMesh RootNode.
    Disables VBO via SoMaterialBinding override so SoFCIndexedFaceSet
    falls back to the standard Coin3D rendering path that respects
    SoShaderProgram and per-vertex texture coordinates.
    """

    shaderpath = path.dirname(path.abspath(__file__))

    def __init__(self) -> None:
        # Shader parameters
        self.x_scale = coin.SoShaderParameter1f()
        self.x_scale.name = "x_scale"
        self.y_scale = coin.SoShaderParameter1f()
        self.y_scale.name = "y_scale"
        self.z_scale = coin.SoShaderParameter1f()
        self.z_scale.name = "z_scale"
        self.darken = coin.SoShaderParameter1f()
        self.darken.name = "darken"

        self.Spacing = [20.0, 2.0, 10.0]
        self.Darken = 0.5

        shader_params = [
            self.x_scale,
            self.y_scale,
            self.z_scale,
            self.darken,
        ]

        self.fragmentShader = coin.SoFragmentShader()
        self.fragmentShader.sourceProgram.setValue(
            path.join(MeshGridShader.shaderpath, "Grid_fragment_shader.glsl")
        )
        self.fragmentShader.parameter.setValues(
            0, len(shader_params), shader_params,
        )

        self.vertexShader = coin.SoVertexShader()
        self.vertexShader.sourceProgram.setValue(
            path.join(MeshGridShader.shaderpath, "Grid_vertex_shader.glsl")
        )

        self.shaderProgram = coin.SoShaderProgram()
        self.shaderProgram.shaderObject.set1Value(0, self.vertexShader)
        self.shaderProgram.shaderObject.set1Value(1, self.fragmentShader)
        self.shaderProgram.setName("my_shader")

        self.tex_matrix_transform = coin.SoTextureMatrixTransform()
        self.tex_matrix_transform.matrix.setValue(
            1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 1, 0,
            0, 0, 0, 1,
        )

        self.coord_binding = coin.SoTextureCoordinateBinding()
        # IndexedFaceSet uses coordIndex/textureCoordIndex, so binding must be indexed.
        # PER_VERTEX can produce triangle-local texcoord resets (chevron artifacts).
        self.coord_binding.value = coin.SoTextureCoordinateBinding.PER_VERTEX_INDEXED

        # Dummy 1x1 white texture. SoTextureCoordinateBundle only sends
        # texture coordinates to OpenGL when SoTextureEnabledElement is
        # set, which requires a SoTexture2 node in the scene graph.
        # Without this, gl_MultiTexCoord0 stays (0,0) and the shader
        # produces a constant color. The shader program handles all
        # coloring, so the texture image itself is irrelevant.
        self.dummy_texture = coin.SoTexture2()
        self.dummy_texture.image.setValue(coin.SbVec2s(1, 1), 3, b'\xff\xff\xff')
        self.dummy_texture.model = coin.SoTexture2.MODULATE

        # Material binding override disables VBO on SoFCIndexedFaceSet.
        # SoGLVBOActivatedElement::get() returns false when
        # SoOverrideElement::MATERIAL_BINDING flag is set, forcing
        # SoFCIndexedFaceSet to use inherited::GLRender which respects
        # shader state and per-vertex texture coordinates.
        self.mat_binding = coin.SoMaterialBinding()
        self.mat_binding.value = coin.SoMaterialBinding.PER_VERTEX
        self.mat_binding.setOverride(True)

        # Enable alpha blending so the shader can output transparent fragments
        # (grid lines opaque, background transparent) while keeping smoothstep
        # antialiasing on the line edges.
        self.transparency_type = coin.SoTransparencyType()
        self.transparency_type.value = coin.SoTransparencyType.BLEND

        # Material with non-zero transparency so Coin3D renders this geometry
        # in the transparency (blending) pass. The shader controls per-fragment
        # alpha via gl_FragColor.a; this just triggers the correct render path.
        self.material = coin.SoMaterial()
        self.material.transparency = 0.5

        self.grp = coin.SoGroup()
        self.grp.setName("shader_state")

        # Root separator — used by addDisplayMode; replaced by DrapeMesh
        # RootNode in attach().
        self.root = coin.SoSeparator()
        self.root.setName("shader_placeholder")

        self._attached = False

    @property
    def Spacing(self) -> list[float]:
        return [
            1.0 / self.x_scale.value.getValue(),
            1.0 / self.y_scale.value.getValue(),
            1.0 / self.z_scale.value.getValue(),
        ]

    @Spacing.setter
    def Spacing(self, v: list[float]) -> None:
        self.x_scale.value = 1.0 / v[0]
        self.y_scale.value = 1.0 / v[1]
        self.z_scale.value = 1.0 / v[2]

    @property
    def Darken(self) -> float:
        return self.darken.value.getValue()

    @Darken.setter
    def Darken(self, v: float) -> None:
        self.darken.value = v

    @property
    def Root(self) -> coin.SoSeparator:
        return self.root

    def get_texture_coords(self, tex_coords: list | None) -> coin.SoTextureCoordinate3:
        """Create SoTextureCoordinate3 from draper tex_coords list.

        Uses 3D texture coordinates (s, t, r) to match the old working
        shader which used all three components (x_scale*s, y_scale*t,
        z_scale*r) to draw the grid.
        """
        texture_coords = coin.SoTextureCoordinate3()
        texture_coords.setName("my_texcoord")
        if tex_coords is not None:
            for idx, pt in enumerate(tex_coords):
                if len(pt) >= 2:
                    # Third component (r) defaults to 0.0
                    r = float(pt[2]) if len(pt) >= 3 else 0.0
                    texture_coords.point.set1Value(idx, float(pt[0]), float(pt[1]), r)
        return texture_coords

    def detach(self, obj: Any | None = None) -> None:
        """Detach the shader from the scene graph."""
        self._remove_from_scene()
        self._attached = False

    def _cleanup_nodes(self) -> None:
        """Remove shader nodes from grp."""
        for attr in ["texcoords", "coord_binding", "tex_matrix_transform",
                      "shaderProgram", "mat_binding", "dummy_texture",
                      "transparency_type", "material"]:
            node = getattr(self, attr, None)
            if node is not None:
                try:
                    self.grp.removeChild(node)
                except Exception:
                    pass

    def attach(
        self,
        obj: Any,
        child: Any,
        tex_coords: list | None = None,
        offset_angle_deg: float = 0.0,
    ) -> None:
        """Attach the shader to the DrapeMesh's native geometry.

        Inserts shader state nodes (material binding override, texture
        coordinates, texture matrix transform, shader program) directly
        into the DrapeMesh RootNode.  The Coin3D geometry (injected by
        _build_drapecd_mesh) is placed inside the shader state group so
        the shader affects it.  Works with Coin3D geometry
        (SoCoordinate3 + SoIndexedFaceSet) that has correct 1:1
        texcoord-to-vertex mapping.

        Args:
            obj: ViewProvider object (used to get the document/viewer).
            child: DrapeMesh feature (provides RootNode).
            tex_coords: Texture coordinates from the draper backend.
            offset_angle_deg: Rosette angle for layer rotation.
        """
        self._cleanup_nodes()
        self._remove_from_scene()

        if tex_coords is None or len(tex_coords) == 0:
            return

        self.texcoords = self.get_texture_coords(tex_coords)

        # Apply rosette angle as 2D rotation in UV plane
        if offset_angle_deg:
            ang = math.radians(-offset_angle_deg)
            cos_a, sin_a = math.cos(ang), math.sin(ang)
            self.tex_matrix_transform.matrix.setValue(
                cos_a, -sin_a, 0, 0,
                sin_a,  cos_a, 0, 0,
                0,      0,     1, 0,
                0,      0,     0, 1,
            )
        else:
            self.tex_matrix_transform.matrix.setValue(
                1, 0, 0, 0,
                0, 1, 0, 0,
                0, 0, 1, 0,
                0, 0, 0, 1,
            )

        # Get the DrapeMesh root node
        self.root = child.ViewObject.RootNode

        # Find the Coin3D geometry (SoSeparator with Coordinate3 + IndexedFaceSet)
        # that was injected by _build_drapecd_mesh.
        coin_geo = self._find_coin_geometry(self.root)

        # Find the switch index for positioning
        switch_idx = self._find_switch_index()

        # Assemble shader state group WITH the geometry as a child:
        # [mat_binding, dummy_texture, coord_binding, texcoords,
        #  tex_matrix_transform, shaderProgram, coin_geometry]
        self.grp = coin.SoGroup()
        self.grp.setName("shader_state")
        self.grp.addChild(self.transparency_type)
        self.grp.addChild(self.material)
        self.grp.addChild(self.mat_binding)
        self.grp.addChild(self.dummy_texture)
        self.grp.addChild(self.coord_binding)
        self.grp.addChild(self.texcoords)
        self.grp.addChild(self.tex_matrix_transform)
        self.grp.addChild(self.shaderProgram)

        if coin_geo:
            # Find and set textureCoordIndex on the face set inside the geometry
            face_set = self._find_face_set_in_root(coin_geo)
            if face_set:
                coord_index = face_set.coordIndex.getValues()
                face_set.textureCoordIndex.setValues(
                    0,
                    len(coord_index),
                    coord_index,
                )
            # Move the geometry into the shader state group
            self.grp.addChild(coin_geo)
            # Remove the geometry from its current location in root
            self._remove_node_from_parent(coin_geo, self.root)

        # Insert the shader state group INSIDE the Switch's children so
        # it respects display-mode and visibility toggles.  Add to all
        # children so the grid shows in every display mode.
        if switch_idx >= 0:
            switch_node = self.root.getChild(switch_idx)
            if switch_node and "Switch" in str(switch_node.getTypeId().getName()):
                n_children = int(switch_node.getNumChildren())
                for ci in range(n_children):
                    child = switch_node.getChild(ci)
                    if child and hasattr(child, 'addChild'):
                        child.addChild(self.grp)
            else:
                self.root.addChild(self.grp)
        else:
            self.root.addChild(self.grp)

        self._attached = True

    def _find_switch_index(self) -> int:
        """Find the index of the Switch child inside the root."""
        children = self.root.getChildren()
        if children is None:
            return -1
        for i in range(int(children.getLength())):
            c = children[i]
            if c and "Switch" in str(c.getTypeId().getName()):
                return i
        return -1

    def _find_switch(self, node: Any) -> Any | None:
        """Find the Switch child inside the given node."""
        children = node.getChildren()
        if children is None:
            return None
        for i in range(int(children.getLength())):
            c = children[i]
            if c and "Switch" in str(c.getTypeId().getName()):
                return c
        return None

    def _find_face_set_in_root(self, node: Any) -> Any | None:
        """Find Coin3D IndexedFaceSet (not SoFCIndexedFaceSet) inside root.

        Searches through SoSeparators and other groups to find the
        geometry node that was injected by _build_drapecd_mesh().
        Excludes SoFCIndexedFaceSet (FreeCAD's mesh viewer geometry).
        """
        children = node.getChildren()
        if children is None or children.getLength() == 0:
            return None
        for i in range(int(children.getLength())):
            c = children[i]
            if c is None:
                continue
            tname = str(c.getTypeId().getName())
            # Match IndexedFaceSet but NOT SoFCIndexedFaceSet
            if "IndexedFaceSet" in tname and "SoFCIndexedFaceSet" not in tname:
                return c
            # Recurse into separators/groups
            res = self._find_face_set_in_root(c)
            if res is not None:
                return res
        return None

    def _find_coin_geometry(self, node: Any) -> Any | None:
        """Find the Coin3D geometry separator injected by _build_drapecd_mesh.

        Looks for a SoSeparator that contains both SoCoordinate3 and
        SoIndexedFaceSet as children.
        """
        children = node.getChildren()
        if children is None or children.getLength() == 0:
            return None
        for i in range(int(children.getLength())):
            c = children[i]
            if c is None:
                continue
            tname = str(c.getTypeId().getName())
            if "Separator" in tname and "Switch" not in tname:
                # Check if this separator has both Coordinate3 and IndexedFaceSet
                has_coord = False
                has_face = False
                sub_children = c.getChildren()
                if sub_children:
                    for j in range(int(sub_children.getLength())):
                        sc = sub_children[j]
                        if sc is None:
                            continue
                        st = str(sc.getTypeId().getName())
                        if st == "Coordinate3":
                            has_coord = True
                        elif "IndexedFaceSet" in st:
                            has_face = True
                if has_coord and has_face:
                    return c
            # Recurse
            res = self._find_coin_geometry(c)
            if res is not None:
                return res
        return None

    def _remove_node_from_parent(self, node: Any, parent: Any) -> bool:
        """Remove a child node from its parent. Uses pointer comparison
        to handle SWIG proxy identity issues."""
        try:
            target_ptr = hex(int(node.this))
        except AttributeError:
            return False
        children = parent.getChildren()
        if children is None:
            return False
        for i in range(int(children.getLength())):
            c = children[i]
            if c is None:
                continue
            try:
                if hex(int(c.this)) == target_ptr:
                    parent.removeChild(node)
                    return True
            except AttributeError:
                continue
        return False

    def _find_face_set(self, node: Any) -> Any | None:
        """Find SoFCIndexedFaceSet inside the given node (recursive)."""
        children = node.getChildren()
        if children is None or children.getLength() == 0:
            return None
        for i in range(int(children.getLength())):
            c = children[i]
            if c and "SoFCIndexedFaceSet" in str(c.getTypeId().getName()):
                return c
            res = self._find_face_set(c)
            if res is not None:
                return res
        return None

    def _remove_from_scene(self) -> None:
        """Remove shader state group from the root node."""
        if not self._attached:
            return
        if self.root is not None:
            try:
                self.root.removeChild(self.grp)
            except Exception:
                pass
