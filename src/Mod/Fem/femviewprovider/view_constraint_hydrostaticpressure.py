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
from pivy import coin

from . import view_base_femconstraint


class VPConstraintHydrostaticPressure(view_base_femconstraint.VPBaseFemConstraint):
    """
    A View Provider for the FemConstraintHydrostaticPressure object
    """

    def attach(self, obj):
        self.ViewObject = obj
        self.Object = obj.Object
        self.mesh_coin = coin.SoGroup()
        obj.addDisplayMode(self.mesh_coin, "Base")
        obj.addDisplayMode(self.mesh_coin, "Mesh")

    def onChanged(self, fp, prop):
        print(f"onchanged {prop}")
        if (prop == "DisplayMode") and fp.DisplayMode == "Mesh":
            self.colorise_mesh(self.Object)
        else:
            self.unrender_mesh(self.Object)

    def updateData(self, obj, prop):
        print(f"updatedata {prop}")
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
            vobj.ColorMode = "ByNode"
            vobj.NodeColor = {}
            vobj.ElementColor = {}
            vobj.resetNodeColor()

    def colorise_mesh(self, obj):
        meshes = self.get_meshes(obj)

        fp = obj.Proxy
        if not fp.interp_valid(obj):
            self.unrender_mesh(obj)
            return

        print("actual colorise")
        faces = []
        for sup, sub in obj.References:
            faces.extend(sup.getSubObject(sub))

        node_numbers = {}
        values = {}
        for k, mobj in enumerate(meshes):
            if False:
                nns = []
                for face in faces:
                    nns.extend(mobj.FemMesh.getNodesByFace(face))
                nns = list(set(nns))
                nodes = [mobj.FemMesh.Nodes[i] for i in nns]
                node_numbers[k] = nns
            else:
                nodes = list(mobj.FemMesh.Nodes.values())
                node_numbers[k] = list(mobj.FemMesh.Nodes.keys())
            values[k] = np.array([fp.get_pressure_field(obj, pos) for pos in nodes])

        v_min = np.min([np.min(v) for v in values.values()])
        v_max = np.max([np.max(v) for v in values.values()])
        dv = max(v_max, -v_min)
        for k in values.keys():
            if dv > 0:
                values[k] = 0.5 + 0.5 * values[k] / dv
            values[k] = list(values[k])
            vobj = meshes[k].ViewObject
            vobj.ColorMode = "ByNode"
            vobj.NodeColor = {}
            vobj.ElementColor = {}
            vobj.resetNodeColor()
            vobj.setNodeColorByScalars(node_numbers[k], values[k])

    def getDisplayModes(self, obj) -> List[str]:
        return ["Mesh"]

    def getDefaultDisplayMode(self) -> str:
        return "Base"

    def setDisplayMode(self, mode):
        return mode

    def onDocumentRestored(self, obj):
        print("viewprovider hydrostatic onDocumentRestored")
