#!/usr/bin/env python3
"""Diagnostic shader scene for visible grid spacing checks.

This example is intentionally high-contrast and uses a tiny custom GLSL
fragment shader so the physical spacing of the texture coordinates is easy to
see in the viewport.
"""

from __future__ import annotations

import tempfile
import textwrap

from pivy import coin


def _write_temp_shader(source: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".glsl", delete=False)
    handle.write(textwrap.dedent(source))
    handle.close()
    return handle.name


def _make_shader_program(grid_spacing_mm: float) -> coin.SoShaderProgram:
    vertex_path = _write_temp_shader(
        """
        #version 130
        void main() {
          gl_Position = ftransform();
          gl_TexCoord[0] = gl_MultiTexCoord0;
        }
        """
    )
    fragment_path = _write_temp_shader(
        f"""
        #version 130
        uniform float grid_spacing_mm = {grid_spacing_mm:.6f};

        void main() {{
          vec3 coord = gl_TexCoord[0].xyz / max(grid_spacing_mm, 1e-6);
          vec2 cell = fract(coord.xy);
          float edge_u = min(cell.x, 1.0 - cell.x);
          float edge_v = min(cell.y, 1.0 - cell.y);
          float edge = min(edge_u, edge_v);
          float line = 1.0 - smoothstep(0.0, 0.05, edge);
          vec3 line_color = vec3(0.0, 0.0, 0.0);
          vec3 fill_color = vec3(0.95, 0.95, 0.95);
          gl_FragColor = vec4(mix(fill_color, line_color, line), 1.0);
        }}
        """
    )

    shader = coin.SoShaderProgram()
    vertex_shader = coin.SoVertexShader()
    vertex_shader.sourceProgram.setValue(vertex_path)
    fragment_shader = coin.SoFragmentShader()
    fragment_shader.sourceProgram.setValue(fragment_path)
    shader.shaderObject.set1Value(0, vertex_shader)
    shader.shaderObject.set1Value(1, fragment_shader)
    return shader


def build(doc=None, grid_spacing_mm: float = 10.0):
    import FreeCAD
    import FreeCADGui

    if doc is None:
        doc = FreeCAD.newDocument("ShaderGridDiagnostic")

    view = FreeCADGui.ActiveDocument.ActiveView

    scene = coin.SoSeparator()
    scene.setName("ShaderDiagnosticScene")

    background = coin.SoSeparator()
    background.setName("Backdrop")
    back_mat = coin.SoMaterial()
    back_mat.diffuseColor = (1.0, 1.0, 1.0)
    back_coords = coin.SoCoordinate3()
    back_coords.point.setValues(
        0,
        4,
        [
            coin.SbVec3f(-50.0, -50.0, -0.1),
            coin.SbVec3f(50.0, -50.0, -0.1),
            coin.SbVec3f(50.0, 50.0, -0.1),
            coin.SbVec3f(-50.0, 50.0, -0.1),
        ],
    )
    back_faces = coin.SoFaceSet()
    back_faces.numVertices.setValues(0, 1, [4])
    background.addChild(back_mat)
    background.addChild(back_coords)
    background.addChild(back_faces)
    scene.addChild(background)

    quad = coin.SoSeparator()
    quad.setName("DiagnosticQuad")
    texture_enabled = coin.SoTexture2()
    texture_enabled.image.setValue(coin.SbVec2s(1, 1), 3, b"\xff\xff\xff")
    texture_enabled.model = coin.SoTexture2.MODULATE

    tex_coords = coin.SoTextureCoordinate3()
    tex_coords.point.setValues(
        0,
        4,
        [
            coin.SbVec3f(0.0, 0.0, 0.0),
            coin.SbVec3f(40.0, 0.0, 0.0),
            coin.SbVec3f(40.0, 40.0, 0.0),
            coin.SbVec3f(0.0, 40.0, 0.0),
        ],
    )
    coords = coin.SoCoordinate3()
    coords.point.setValues(
        0,
        4,
        [
            coin.SbVec3f(-20.0, -20.0, 0.0),
            coin.SbVec3f(20.0, -20.0, 0.0),
            coin.SbVec3f(20.0, 20.0, 0.0),
            coin.SbVec3f(-20.0, 20.0, 0.0),
        ],
    )
    faces = coin.SoIndexedFaceSet()
    faces.coordIndex.setValues(0, 5, [0, 1, 2, 3, -1])

    shader = _make_shader_program(grid_spacing_mm)
    quad.addChild(shader)
    quad.addChild(texture_enabled)
    quad.addChild(tex_coords)
    quad.addChild(coords)
    quad.addChild(faces)
    scene.addChild(quad)
    view.getSceneGraph().addChild(scene)
    view.viewTop()
    view.fitAll()

    return {
        "doc": doc,
        "view": view,
        "scene": scene,
        "grid_spacing_mm": grid_spacing_mm,
    }


if __name__ == "__main__":
    build()
