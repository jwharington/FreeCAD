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

__title__ = "FreeCAD FEM constraint reaction ViewProvider for the document object"
__author__ = "John Wharington"
__url__ = "https://www.freecad.org"

## @package view_constraint_reaction
#  \ingroup FEM
#  \brief view provider for constraint self weight object

from . import view_constraint_hydrostaticpressure


class VPConstraintReaction(view_constraint_hydrostaticpressure.VPConstraintHydrostaticPressure):

    def render_constraint(self, obj):
        fp = obj.Proxy
        if hasattr(fp, "elem_info") and fp.elem_info and fp.pressure_valid(obj):
            # Post-solve: show pressure field colours via parent.
            super().render_constraint(obj)
            return

        # Pre-solve fallback: use tessellated references with distribution colours.
        self._render_reference_faces(obj, color=(0.2, 0.8, 0.2), transparency=0.5)
