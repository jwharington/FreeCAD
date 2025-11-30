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

__title__ = "FreeCAD FEM constraint jig 3-2-1 document object"
__author__ = "John Wharington"
__url__ = "https://www.freecad.org"

## @package constraint_jig321
#  \ingroup FEM
#  \brief constraint jig 321 object

from . import base_fempythonobject

_PropHelper = base_fempythonobject._PropHelper


class ConstraintJig321(base_fempythonobject.BaseFemPythonObject):
    """
    The ConstraintJig321 object
    """

    Type = "Fem::ConstraintJig321"

    def __init__(self, obj):
        super().__init__(obj)

        for prop in self._get_properties():
            prop.add_to_object(obj)

    def _get_properties(self):
        prop = []

        return prop

    def execute(self, obj):
        print("Jig321: execute")

        # - choose two points furthest away from each other, A,B.  This is X
        # - choose third point C furthest from AB line.
        # - AC projected perpendicular to AB is Y
        # - do only on surface faces

    def onChanged(self, fp, prop):
        if prop == "References":
            fp.recompute()
