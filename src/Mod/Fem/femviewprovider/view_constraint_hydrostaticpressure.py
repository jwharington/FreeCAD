# ***************************************************************************
# *   Copyright (c) 2025 John Wharington <jwharington@gmail.com>            *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

__title__ = "FreeCAD FEM constraint hydrostatic pressure ViewProvider for the document object"
__author__ = "John Wharington"
__url__ = "https://www.freecad.org"

## @package view_constraint_hydrostaticpressure
#  \ingroup FEM
#  \brief view provider for constraint self weight object

import numpy as np
from femtools.membertools import get_several_member
from pivy import coin
from Resources.colormaps.roma import roma_map

from . import view_base_femconstraint

# FemGui::ViewProviderFemConstraintPressure


def _to_xyz(node):
    if hasattr(node, "x"):
        return (node.x, node.y, node.z)
    if hasattr(node, "X"):
        return (node.X, node.Y, node.Z)
    return (node[0], node[1], node[2])


class VPConstraintHydrostaticPressure(view_base_femconstraint.VPBaseFemConstraint):
    """
    A View Provider for the FemConstraintHydrostaticPressure object
    """

    def __init__(self, vobj):
        super().__init__(vobj)
        # mat = vobj.ShapeAppearance[0]
        # mat.DiffuseColor = (0.3, 1.0, 0.3, 0.0)
        # vobj.ShapeAppearance = mat

    def attach(self, vobj):
        super().attach(vobj)
        # vobj.loadSymbol(self.resource_symbol_dir + "ConstraintPressure.iv")

        self.mesh_coin = coin.SoGroup()
        vobj.addDisplayMode(self.mesh_coin, "Mesh")
        self.render_constraint(self.Object)

    def onChanged(self, fp, prop):
        if prop == "DisplayMode":
            if fp.DisplayMode == "Mesh":
                self.render_constraint(self.Object)
            else:
                self.clear_render()

    def updateData(self, obj, prop):
        if self.ViewObject.DisplayMode == "Mesh":
            self.render_constraint(obj)

    def get_meshes(self, obj):
        analysis = obj.getParentGroup()
        if not analysis:
            return []
        meshes = get_several_member(analysis, "Fem::FemMeshObject")
        return [mobj["Object"] for mobj in meshes]

    def clear_render(self):
        self.mesh_coin.removeAllChildren()

    def _render_reference_faces(
        self,
        obj,
        color=(0.2, 0.6, 1.0),
        transparency=0.55,
        tessellation_deflection=0.25,
    ):
        """Fallback preview: render tessellated referenced faces before elem_info exists."""
        self.clear_render()
        if not hasattr(obj, "References") or not obj.References:
            return

        tri_data = []
        rev = 1 if getattr(obj, "Reversed", False) else -1
        for ref_obj, subnames in obj.References:
            for face_name in subnames:
                try:
                    face_idx = int(face_name.replace("Face", "")) - 1
                    face = ref_obj.Shape.Faces[face_idx]
                except Exception:
                    continue
                verts, tris = face.tessellate(tessellation_deflection, True)
                for tri in tris:
                    p1 = verts[tri[0]]
                    p2 = verts[tri[1]]
                    p3 = verts[tri[2]]
                    v1 = p2 - p1
                    v2 = p3 - p1
                    cross = v1.cross(v2)
                    mag = cross.Length
                    if mag <= 0.0:
                        continue
                    tri_data.append(
                        {
                            "p": (p1, p2, p3),
                            "centroid": (p1 + p2 + p3) / 3.0,
                            "normal": cross / mag,
                            "area": 0.5 * mag,
                            "rev": rev,
                        }
                    )

        if not tri_data:
            return

        pressures = None
        fp = obj.Proxy
        if hasattr(fp, "get_pressure_field"):
            preview_elem_info = {
                "elem": list(range(len(tri_data))),
                "centroid": [t["centroid"] for t in tri_data],
                "normal": [t["normal"] for t in tri_data],
                "area": [t["area"] for t in tri_data],
                "rev": [t["rev"] for t in tri_data],
                "pressure": [0.0 for _ in tri_data],
            }
            old_elem_info = getattr(fp, "elem_info", None)
            try:
                ok = fp.get_pressure_field(obj, preview_elem_info)
                ptmp = np.asarray(preview_elem_info["pressure"], dtype=float)
                # Reaction may return False if its nonlinear solve is imperfect,
                # but preview values can still carry useful spatial variation.
                if ok or np.all(np.isfinite(ptmp)):
                    pressures = ptmp.tolist()
            except Exception:
                pressures = None
            finally:
                if hasattr(fp, "elem_info"):
                    fp.elem_info = old_elem_info

        if pressures is not None and len(pressures) == len(tri_data):
            pvals = np.asarray(pressures, dtype=float)
            pmin = float(np.min(pvals))
            pmax = float(np.max(pvals))
            span = pmax - pmin

            if span > 1.0e-12:

                def map_val(x):
                    s = (float(x) - pmin) / span
                    s = max(0.0, min(1.0, s))
                    return roma_map(s)[0:3]

                face_colors = [map_val(p) for p in pvals]
            else:
                # Near-constant field: keep a gentle uniform tint.
                face_colors = [color for _ in tri_data]
        else:
            face_colors = [color for _ in tri_data]

        points = []
        coord_index = []
        for i, tri in enumerate(tri_data):
            base = 3 * i
            p1, p2, p3 = tri["p"]
            points.extend([_to_xyz(p1), _to_xyz(p2), _to_xyz(p3)])
            coord_index.extend([base, base + 1, base + 2, -1])

        sep = coin.SoSeparator()
        mat = coin.SoMaterial()
        for i, face_color in enumerate(face_colors):
            mat.diffuseColor.set1Value(i, *face_color)
        mat.transparency.setValue(transparency)

        material_binding = coin.SoMaterialBinding()
        material_binding.value.setValue(coin.SoMaterialBinding.PER_FACE)

        coords = coin.SoCoordinate3()
        for i, point in enumerate(points):
            coords.point.set1Value(i, *point)
        face_set = coin.SoIndexedFaceSet()
        face_set.coordIndex.setValues(0, len(coord_index), coord_index)

        sep.addChild(mat)
        sep.addChild(material_binding)
        sep.addChild(coords)
        sep.addChild(face_set)
        self.mesh_coin.addChild(sep)

    def render_constraint(self, obj):

        fp = obj.Proxy
        if not hasattr(fp, "elem_info"):
            self._render_reference_faces(obj)
            return
        if (not fp.elem_info) or (not fp.pressure_valid(obj)):
            self._render_reference_faces(obj)
            return

        pressure = fp.elem_info["pressure"]
        felem_ids = fp.elem_info["felem"]
        pvals = np.asarray(pressure, dtype=float)
        p_min = float(np.min(np.append(pvals, 0.0)))
        p_max = float(np.max(np.append(pvals, 0.0)))

        def map_val(x):
            if x > 0:
                s = (1.0 + (x / p_max)) / 2
            elif x < 0:
                s = (1.0 + (x / p_min)) / 2
            else:
                s = 0.5
            return roma_map(s)[0:3]

        info = list(zip(felem_ids, pressure))
        points = []
        coord_index = []
        face_colors = []
        node_lookup = {}

        for mesh in self.get_meshes(obj):
            femmesh = mesh.FemMesh
            for face_id, p in info:
                try:
                    nodes = femmesh.getElementNodes(face_id)
                except Exception:
                    continue
                if not nodes or len(nodes) < 3:
                    continue
                for node_id in nodes:
                    node_key = (mesh.Name, node_id)
                    if node_key not in node_lookup:
                        node_lookup[node_key] = len(points)
                        points.append(_to_xyz(femmesh.Nodes[node_id]))
                    coord_index.append(node_lookup[node_key])
                coord_index.append(-1)
                face_colors.append(map_val(p))

        self.clear_render()
        if not points or not face_colors:
            return

        sep = coin.SoSeparator()

        material = coin.SoMaterial()
        for i, color in enumerate(face_colors):
            material.diffuseColor.set1Value(i, *color)

        material_binding = coin.SoMaterialBinding()
        material_binding.value.setValue(coin.SoMaterialBinding.PER_FACE)

        coords = coin.SoCoordinate3()
        for i, point in enumerate(points):
            coords.point.set1Value(i, *point)

        face_set = coin.SoIndexedFaceSet()
        face_set.coordIndex.setValues(0, len(coord_index), coord_index)

        sep.addChild(material)
        sep.addChild(material_binding)
        sep.addChild(coords)
        sep.addChild(face_set)
        self.mesh_coin.addChild(sep)

    def getDisplayModes(self, obj):
        return ["Mesh"]

    def getDefaultDisplayMode(self) -> str:
        return "Mesh"

    def setDisplayMode(self, mode):
        return mode

    def onDocumentRestored(self, obj):
        self.render_constraint(obj)
