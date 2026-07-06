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
        self.offset_angle = coin.SoShaderParameter1f()
        self.offset_angle.name = "offset_angle"
        self.offset_angle.value = 0.0

        self.Spacing = [20.0, 2.0, 10.0]
        self.Darken = 0.5

        shader_params = [
            self.x_scale,
            self.y_scale,
            self.z_scale,
            self.darken,
            self.offset_angle,
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

        # Strain color material — per-vertex diffuse colors for strain visualization
        self.strain_material = coin.SoMaterial()
        self.strain_material.diffuseColor.set1Value(0, 0.0, 0.0, 0.0)  # placeholder
        self.strain_mat_binding = coin.SoMaterialBinding()
        self.strain_mat_binding.value = coin.SoMaterialBinding.PER_VERTEX

        self.grp = coin.SoGroup()
        self.grp.setName("shader_state")

        # Reference to the Coin3D geometry node moved into grp by attach().
        # Kept across re-attach so a reload does not lose the geometry
        # (it was already removed from root, so a fresh search would miss it).
        self._coin_geo = None

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

    def set_offset_angle(self, offset_angle_deg: float = 0.0) -> None:
        """Apply rosette angle as a uniform rotation in the fragment shader."""
        self.offset_angle.value = math.radians(offset_angle_deg)

    def detach(self, obj: Any | None = None) -> None:
        """Detach the shader by clearing group contents.

        The group stays in the scene graph (reused by next attach)
        but its children are removed so nothing renders. The stolen
        geometry reference is KEPT so a subsequent reload/attach can
        re-insert the same node — the node was already removed from
        root, so a fresh search would miss it and the grid would
        disappear. The node itself survives because we hold a
        reference to it.
        """
        self._clear_group()
        self._attached = False

    def _clear_group(self) -> None:
        """Remove all children from self.grp by index (SWIG-safe)."""
        if self.grp is None:
            return
        for i in range(int(self.grp.getNumChildren()) - 1, -1, -1):
            self.grp.removeChild(i)

    def attach(
        self,
        root_node: Any,
        tex_coords: list | None = None,
        offset_angle_deg: float = 0.0,
    ) -> None:
        """Attach the shader to geometry inside the given root node.

        Reuses the existing scene-graph group across reloads to avoid
        accumulating orphaned shader_state groups. The Coin3D geometry
        node stolen on first attach is remembered in self._coin_geo so
        a reload can re-insert it without re-searching root (it was
        already removed from root, so a fresh search would miss it).
        """
        if tex_coords is None or len(tex_coords) == 0:
            return

        self.texcoords = self.get_texture_coords(tex_coords)
        self.set_offset_angle(offset_angle_deg)

        self.root = root_node

        # Prefer freshly injected geometry in root (execute() re-injects
        # on a real drape change); fall back to the node we stole on a
        # previous attach so a pure reload does not lose the grid.
        coin_geo = self._find_coin_geometry(self.root)
        if coin_geo is None:
            coin_geo = self._coin_geo

        # Reuse the existing group if it is still in the scene graph;
        # otherwise create a fresh one. Reusing avoids orphaned
        # shader_state groups piling up across reloads.
        reuse = self.grp is not None and self._grp_in_scene(root_node)
        if reuse:
            self._clear_group()
        else:
            self.grp = coin.SoGroup()
            self.grp.setName("shader_state")
            self.root.addChild(self.grp)

        # Rebuild shader state children
        self.grp.addChild(self.transparency_type)
        self.grp.addChild(self.material)
        self.grp.addChild(self.mat_binding)
        self.grp.addChild(self.strain_mat_binding)
        self.grp.addChild(self.strain_material)
        self.grp.addChild(self.dummy_texture)
        self.grp.addChild(self.coord_binding)
        self.grp.addChild(self.texcoords)
        self.grp.addChild(self.shaderProgram)

        if coin_geo is not None:
            face_set = self._find_face_set_in_root(coin_geo)
            if face_set:
                coord_index = face_set.coordIndex.getValues()
                face_set.textureCoordIndex.setValues(
                    0,
                    len(coord_index),
                    coord_index,
                )
            self.grp.addChild(coin_geo)
            # Only remove from root on the first steal; on re-attach the
            # node was never in root (it lived in the previous grp).
            if self._coin_geo is None:
                self._remove_node_from_parent(coin_geo, self.root)
            self._coin_geo = coin_geo

        self._attached = True

    def _grp_in_scene(self, root_node: Any) -> bool:
        """Return True if self.grp is a direct child of root_node."""
        if self.grp is None:
            return False
        children = root_node.getChildren()
        if children is None:
            return False
        target_name = ""
        try:
            target_name = self.grp.getName()
        except AttributeError:
            return False
        if not target_name:
            return False
        for i in range(int(children.getLength())):
            c = children[i]
            if c is None:
                continue
            try:
                if c.getName() == target_name:
                    return True
            except AttributeError:
                continue
        return False

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
        """Find injected Coin3D mesh container with Coordinate3 + IndexedFaceSet.

        The injected node can appear as Separator or Group depending on
        how FreeCAD wraps display-mode subgraphs. We therefore recurse into
        any child container exposing getChildren(), skipping shader_state.
        """
        children = node.getChildren()
        if children is None or children.getLength() == 0:
            return None

        for i in range(int(children.getLength())):
            c = children[i]
            if c is None:
                continue

            try:
                if c.getName() == "shader_state":
                    continue
            except AttributeError:
                pass

            sub_children = c.getChildren() if hasattr(c, "getChildren") else None
            has_coord = False
            has_face = False
            if sub_children is not None:
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

                res = self._find_coin_geometry(c)
                if res is not None:
                    return res

        return None

    def _remove_node_from_parent(self, node: Any, parent: Any) -> bool:
        """Remove a child node from its parent by name match.

        SWIG proxy identity is unreliable, so we match by the node's
        Coin3D name instead of comparing proxies.
        """
        try:
            target_name = node.getName()
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
                if c.getName() == target_name and target_name:
                    parent.removeChild(i)
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
        """Remove shader state group from the scene graph.

        The group was inserted into every child of the Switch node
        inside root, so we search there and remove by name/index.
        """
        if self.root is None:
            return
        # Find the Switch inside root
        children = self.root.getChildren()
        if children is None:
            return
        for i in range(int(children.getLength())):
            c = children[i]
            if c is None:
                continue
            if "Switch" not in str(c.getTypeId().getName()):
                continue
            # Remove 'shader_state' groups from all children of the switch
            for j in range(int(c.getNumChildren()) - 1, -1, -1):
                sub = c.getChild(j)
                if sub is None or not hasattr(sub, "getNumChildren"):
                    continue
                for k in range(int(sub.getNumChildren()) - 1, -1, -1):
                    gc = sub.getChild(k)
                    if gc is None:
                        continue
                    try:
                        if gc.getName() == "shader_state":
                            sub.removeChild(k)
                    except AttributeError:
                        continue
        # Also try direct removal from root (legacy path)
        try:
            self.root.removeChild(self.grp)
        except Exception:
            pass
        self._attached = False

    def set_strain_colors(self, strains: np.ndarray, mode: str = "XX") -> None:
        """Set per-vertex diffuse colors based on strain data.

        Parameters
        ----------
        strains : np.ndarray
            Per-quad strains of shape (N, 3) — [warp, weft, shear].
        mode : str
            Which strain component to visualize: "XX", "YY", or "XY".
        """
        if strains is None or strains.size == 0 or self.strain_material is None:
            return

        # Map component index
        comp_map = {"XX": 0, "YY": 1, "XY": 2}
        comp_idx = comp_map.get(mode, 0)

        # Normalize strains to [0, 1] for color mapping
        strain_vals = strains[:, comp_idx]
        max_val = strain_vals.max()
        min_val = strain_vals.min()
        if max_val > min_val:
            normalized = (strain_vals - min_val) / (max_val - min_val)
        else:
            normalized = np.zeros_like(strain_vals)

        # Map normalized strains to colors (blue=low, red=high)
        n_quads = len(strains)
        # Each quad has 4 vertices, so we need 4 * n_quads colors
        # For simplicity, assign the same color to all 4 vertices of each quad
        n_vertices = 4 * n_quads
        colors = np.zeros((n_vertices, 3))
        for i in range(n_quads):
            v = normalized[i]
            # Blue (low) -> Red (high) gradient
            colors[4 * i] = [v, 0.0, 1.0 - v]
            colors[4 * i + 1] = [v, 0.0, 1.0 - v]
            colors[4 * i + 2] = [v, 0.0, 1.0 - v]
            colors[4 * i + 3] = [v, 0.0, 1.0 - v]

        # Set the diffuse colors on the material node
        self.strain_material.diffuseColor.setValues(0, n_vertices, colors)
