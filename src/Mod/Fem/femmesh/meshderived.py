# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2025 John Wharington <jwharington@gmail.com>            *
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

__title__ = "Tools for derived info for finite element meshes"
__author__ = "John Wharington"
__url__ = "https://www.freecad.org"

## \addtogroup FEM
#  @{

import numpy as np
from FreeCAD import Vector


def compute_face_geometry(femmesh, element_id):
    """Compute the centroid of a given element in the femmesh."""
    nodes = femmesh.getElementNodes(element_id)
    points = np.array([femmesh.getNodeById(i) for i in nodes])
    centroid = Vector(np.mean(points, axis=0))
    a = points[1] - points[0]
    b = points[2] - points[1]
    c = Vector(np.cross(a, b))
    normal = c.normalize()
    area = 0.5 * c.Length
    return centroid, normal, area


#  @}
