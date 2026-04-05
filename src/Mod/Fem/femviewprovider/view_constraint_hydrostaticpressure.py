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

from typing import List

import numpy as np
from femtools.membertools import get_several_member
from FreeCAD import Console
from pivy import coin
from Resources.colormaps.roma import roma_map

from . import view_base_femconstraint

# FemGui::ViewProviderFemConstraintPressure


def calc_node_colors(femmesh, info, map_val):

    def calc_node_values():
        node_vals = {}
        for face_id, p in info:
            for node in femmesh.getElementNodes(face_id):
                if node not in node_vals:
                    node_vals[node] = []
                node_vals[node].append(p)
        return node_vals

    def get_color(v):
        return map_val(np.average(v))

    node_vals = calc_node_values()
    map_colors = {k: get_color(v) for k, v in node_vals.items()}
    blank = map_val(0)
    blank_colors = {k: blank for k in femmesh.Nodes.keys()}
    return blank_colors | map_colors


def calc_element_colors(femmesh, info, map_val):

    def calc_element_values():
        return {face_id: p for face_id, p in info}

    def get_color(v):
        return map_val(np.average(v))

    element_vals = calc_element_values()
    map_colors = {k: get_color(v) for k, v in element_vals.items()}
    return map_colors


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
        vobj.addDisplayMode(self.mesh_coin, "Base")
        vobj.addDisplayMode(self.mesh_coin, "Mesh")

    def onChanged(self, fp, prop):
        if (prop == "DisplayMode") and fp.DisplayMode == "Mesh":
            self.colorise_mesh(self.Object)
        else:
            self.unrender_mesh(self.Object)

    def updateData(self, obj, prop):
        if self.ViewObject.DisplayMode == "Mesh":
            self.colorise_mesh(obj)

    def get_meshes(self, obj):
        analysis = obj.getParentGroup()
        if not analysis:
            return []
        meshes = get_several_member(analysis, "Fem::FemMeshObject")
        return [mobj["Object"] for mobj in meshes]

    def unrender_mesh(self, obj):
        meshes = self.get_meshes(obj)
        for mobj in meshes:
            vobj = mobj.ViewObject
            # vobj.ColorMode = "ByNode"
            vobj.NodeColor = {}
            vobj.ElementColor = {}
            vobj.resetNodeColor()
            vobj.ColorMode = "Overall"

    def colorise_mesh(self, obj):

        fp = obj.Proxy
        if not hasattr(fp, "elem_info"):
            return
        if (not fp.elem_info) or (not fp.pressure_valid(obj)):
            self.unrender_mesh(obj)
            return

        pressure = fp.elem_info["pressure"]
        felem_ids = fp.elem_info["felem"]
        p_min = np.min(pressure + [0])
        p_max = np.max(pressure + [0])

        def map_val(x):
            if x > 0:
                s = (1.0 + (x / p_max)) / 2
            elif x < 0:
                s = (1.0 + (x / p_min)) / 2
            else:
                s = 0.5
            return roma_map(s)[0:3]

        info = zip(felem_ids, pressure)
        for mesh in self.get_meshes(obj):
            vobj = mesh.ViewObject
            vobj.resetNodeColor()
            if True:
                vobj.ColorMode = "ByNode"
                vobj.NodeColor = calc_node_colors(mesh.FemMesh, info, map_val)
            else:
                vobj.ColorMode = "ByElement"
                vobj.ElementColor = calc_element_colors(mesh.FemMesh, info, map_val)

    def getDisplayModes(self, obj) -> List[str]:
        return ["Mesh"]

    def getDefaultDisplayMode(self) -> str:
        return "Base"

    def setDisplayMode(self, mode):
        return mode

    def onDocumentRestored(self, obj):
        print("viewprovider hydrostatic onDocumentRestored")
