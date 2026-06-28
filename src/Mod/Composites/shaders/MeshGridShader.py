# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com


from os import path

import FreeCADGui
from pivy import coin


def find_child(node, type_name):
    children = node.getChildren()

    if children is None or children.getLength() == 0:
        return None

    for child in children:
        if child.getTypeId().getName() == type_name:
            return child

    return None


def has_child(node, type_name):
    children = node.getChildren()

    if children is None or children.getLength() == 0:
        return None

    for child in children:
        if child.getTypeId().getName() == type_name:
            return node

        res = has_child(child, type_name)
        if res is not None:
            return res

    return None


def remove_by_name(node, name):
    item = node.getByName(name)
    if item:
        node.removeChild(item)
        return True
    return False


class MeshGridShader:
    shaderpath = path.dirname(path.abspath(__file__))

    def __init__(self):
        self.x_scale = coin.SoShaderParameter1f()
        self.x_scale.name = "x_scale"
        self.y_scale = coin.SoShaderParameter1f()
        self.y_scale.name = "y_scale"
        self.z_scale = coin.SoShaderParameter1f()
        self.z_scale.name = "z_scale"
        self.darken = coin.SoShaderParameter1f()
        self.darken.name = "darken"

        # Track whether self.texcoords has been added to self.grp
        self._texcoords_attached = False

        self.Spacing = [20.0, 2.0, 10.0]
        self.Darken = 0.1

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
            0,
            len(shader_params),
            shader_params,
        )
        self.shaderProgram = coin.SoShaderProgram()
        self.shaderProgram.shaderObject.set1Value(0, self.fragmentShader)
        self.shaderProgram.setName("my_shader")

        self.grp = coin.SoGroup()
        self.grp.addChild(self.shaderProgram)

    @property
    def Spacing(self):
        return [
            1.0 / self.x_scale.value.getValue(),
            1.0 / self.y_scale.value.getValue(),
            1.0 / self.z_scale.value.getValue(),
        ]

    @Spacing.setter
    def Spacing(self, v):
        self.x_scale.value = 1.0 / v[0]
        self.y_scale.value = 1.0 / v[1]
        self.z_scale.value = 1.0 / v[2]

    @property
    def Darken(self):
        return self.darken.value.getValue()

    @Darken.setter
    def Darken(self, v):
        self.darken.value = v

    @property
    def Root(self):
        return self.root

    def getTextureCoords(self, tex_coords):
        # Use SoTextureCoordinate2 (explicit per-vertex 2D coordinates)
        # rather than SoTextureCoordinate3 (auto-generates from 3D
        # positions).  The latter ignores the point values and defeats
        # the angle rotation.
        textureCoords = coin.SoTextureCoordinate2()
        textureCoords.setName("my_texcoord")
        if tex_coords is not None:
            for index, pt in enumerate(tex_coords):
                # SoTextureCoordinate2 only supports 2D (s, t)
                s, t = pt[0], pt[1]
                textureCoords.point.set1Value(index, s, t)
        return textureCoords

    def detach(self, obj=None):
        """Detach the shader from the scene graph.

        Removes any previously attached texcoords and root nodes from self.grp.
        Idempotent -- safe to call multiple times.
        """
        self._cleanup()
        self.attach(obj, None, None)

    def _cleanup(self):
        """Remove self.texcoords from self.grp if it was previously added.

        Counterpart to the addChild in attach(). Safe to call even if nothing
        was ever attached -- acts as a no-op in that case.
        """
        if self._texcoords_attached and hasattr(self, "texcoords"):
            try:
                self.grp.removeChild(self.texcoords)
            except Exception:
                pass  # Already removed or invalid -- graceful degradation
            self._texcoords_attached = False

    def attach(self, obj, child, tex_coords=None):
        self.texcoords = self.getTextureCoords(tex_coords)

        if tex_coords is None:
            if hasattr(self, "root") and self.root is not None:
                remove_by_name(self.grp, self.root.getName())
            return

        self.grp.addChild(self.texcoords)
        self._texcoords_attached = True

        # Tell the geometry to use per-vertex texture coordinates.
        # Without this, the default binding is NONE and gl_TexCoord[0]
        # stays (0,0,0,1) — the grid collapses to a solid colour.
        self.coord_binding = coin.SoTextureCoordinateBinding()
        self.coord_binding.value = coin.SoTextureCoordinateBinding.PER_VERTEX
        self.grp.addChild(self.coord_binding)

        self.root = child.ViewObject.RootNode
        self.grp.addChild(self.root)

        type_name = "SoFCIndexedFaceSet"
        node = has_child(self.root, type_name)
        geom = find_child(node, type_name)
        # With explicit per-vertex texture coordinates (SoTextureCoordinate2),
        # no textureCoordIndex mapping is needed — the point array is already
        # indexed 1:1 with vertices.  Removing the old index-copying code
        # that assumed auto-generated coordinates (SoTextureCoordinate3).

        # move the original node
        doc = obj.Document
        doc = FreeCADGui.getDocument(doc.Name)
        graph = doc.ActiveView.getSceneGraph()
        graph.removeChild(self.root)
