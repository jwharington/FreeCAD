# ***************************************************************************
# *   Copyright (c) 2021 Bernd Hahnebach <bernd@bimstatik.org>              *
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

__title__ = "FreeCAD FEM constraint jig321 ViewProvider for the document object"
__author__ = "John Wharington"
__url__ = "https://www.freecad.org"

## @package view_constraint_jig321
#  \ingroup FEM
#  \brief view provider for constraint jig321 object

# from femtaskpanels import task_constraint_centrif
from pivy import coin

from . import view_base_femconstraint


class VPConstraintJig321(view_base_femconstraint.VPBaseFemConstraint):
    """
    A View Provider for the ConstraintJig321 object
    Renders a symbol at each of the three nodes supported by the element.
    """

    def attach(self, vobj):
        super().attach(vobj)
        self.symbols_switch = coin.SoSwitch()
        self.symbols_group = coin.SoGroup()
        self.symbols_switch.addChild(self.symbols_group)
        vobj.addDisplayMode(self.symbols_switch, "Symbols")
        self._sync_symbols_visibility(vobj.Visibility)
        self.updateSymbols()

    def _sync_symbols_visibility(self, is_visible):
        if is_visible:
            self.symbols_switch.whichChild.setValue(coin.SoSwitch.SO_SWITCH_ALL)
        else:
            self.symbols_switch.whichChild.setValue(coin.SoSwitch.SO_SWITCH_NONE)

    def updateSymbols(self):
        # Clear previous symbols
        self.symbols_group.removeAllChildren()
        obj = self.Object
        supports = getattr(obj, "Supports", None)
        if supports is None or len(supports) < 3:
            return
        # Label: 3 = supports[0], 2 = supports[1], 1 = supports[2]
        p3 = supports[0]
        p2 = supports[1]
        p1 = supports[2]
        import numpy as np

        v3 = np.array([p3[0], p3[1], p3[2]])
        v2 = np.array([p2[0], p2[1], p2[2]])
        v1 = np.array([p1[0], p1[1], p1[2]])
        x_axis = v3 - v2
        x_axis = (
            x_axis / np.linalg.norm(x_axis) if np.linalg.norm(x_axis) > 0 else np.array([1, 0, 0])
        )
        y_axis = v3 - v1
        y_axis = y_axis - np.dot(y_axis, x_axis) * x_axis
        y_axis = (
            y_axis / np.linalg.norm(y_axis) if np.linalg.norm(y_axis) > 0 else np.array([0, 1, 0])
        )
        z_axis = np.cross(x_axis, y_axis)
        z_axis = (
            z_axis / np.linalg.norm(z_axis) if np.linalg.norm(z_axis) > 0 else np.array([0, 0, 1])
        )
        support_span = max(
            np.linalg.norm(v3 - v2),
            np.linalg.norm(v3 - v1),
            np.linalg.norm(v2 - v1),
        )
        arr_len = max(25.0, 0.15 * support_span)
        arr_head = 0.2 * arr_len

        # Arrow drawing helper
        def add_arrow(origin, direction, color):
            sep = coin.SoSeparator()
            mat = coin.SoBaseColor()
            mat.rgb.setValue(color)
            sep.addChild(mat)
            draw_style = coin.SoDrawStyle()
            draw_style.lineWidth = 2.0
            sep.addChild(draw_style)
            coords = coin.SoCoordinate3()
            start = origin
            end = origin + direction * arr_len
            coords.point.set1Value(0, *start)
            coords.point.set1Value(1, *end)
            sep.addChild(coords)
            line = coin.SoLineSet()
            line.numVertices.setValue(2)
            sep.addChild(line)
            # Arrow head (simple V)
            head1 = (
                end - direction * arr_head + np.cross(direction, [0.2, 0.2, 0.2]) * arr_head * 0.5
            )
            head2 = (
                end - direction * arr_head - np.cross(direction, [0.2, 0.2, 0.2]) * arr_head * 0.5
            )
            coords2 = coin.SoCoordinate3()
            coords2.point.set1Value(0, *end)
            coords2.point.set1Value(1, *head1)
            coords2.point.set1Value(2, *end)
            coords2.point.set1Value(3, *head2)
            sep2 = coin.SoSeparator()
            sep2.addChild(mat)
            sep2.addChild(coords2)
            line2 = coin.SoLineSet()
            line2.numVertices.setValues(0, 2, [2, 2])
            sep2.addChild(line2)
            sep.addChild(sep2)
            self.symbols_group.addChild(sep)

        # Draw at p3: x, y, z
        add_arrow(v3, x_axis, (1, 0, 0))
        add_arrow(v3, y_axis, (0, 1, 0))
        add_arrow(v3, z_axis, (0, 0, 1))
        # Draw at p2: y, z
        add_arrow(v2, y_axis, (0, 1, 0))
        add_arrow(v2, z_axis, (0, 0, 1))
        # Draw at p1: z
        add_arrow(v1, z_axis, (0, 0, 1))

    def updateData(self, obj, prop):
        if prop in ("Supports"):
            self.updateSymbols()

    def onChanged(self, vobj, prop):
        if prop == "Visibility":
            self._sync_symbols_visibility(vobj.Visibility)

    def getDisplayModes(self, obj):
        return ["Symbols"]

    def getDefaultDisplayMode(self):
        return "Symbols"

    def setDisplayMode(self, mode):
        return mode
