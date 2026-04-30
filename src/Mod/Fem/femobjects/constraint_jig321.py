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

import numpy as np
from FreeCAD import Console, Vector

from . import base_fempythonobject

_PropHelper = base_fempythonobject._PropHelper


class ConstraintJig321(base_fempythonobject.BaseFemPythonObject):
    """
    The ConstraintJig321 object
    """

    Type = "Fem::ConstraintJig321"

    def __init__(self, obj):
        super().__init__(obj)

        obj.addProperty(
            type="App::PropertyVectorList",
            name="Supports",
            group="Geometry",
            doc="Locations of supports for the 3-2-1 constraint",
        ).Supports = []
        obj.setPropertyStatus("Supports", "ReadOnly")

    def find_largest_triangle(self, fp, femmesh, node_idxs):
        from scipy.spatial import ConvexHull

        # Ensure at least 3 unique node indices
        unique_node_idxs = list(set(node_idxs))
        if len(unique_node_idxs) < 3:
            # Not enough points to form a triangle
            Console.PrintError(
                "ConstraintJig321: Need at least 3 unique nodes to define a triangle.\n"
            )
            if hasattr(fp, "Supports"):
                fp.Supports = []
            return []

        points = np.array([femmesh.Nodes[i] for i in unique_node_idxs], dtype=float)

        # The largest-area triangle is formed by hull vertices. For planar/degenerate
        # point clouds where 3D hull construction fails, use a 2D projected hull.
        candidate_ids = None
        try:
            hull = ConvexHull(points)
            candidate_ids = list(hull.vertices)
        except Exception as exc:
            Console.PrintWarning(
                "ConstraintJig321: 3D ConvexHull failed for supports; "
                "trying 2D projected hull: "
                f"{exc}\n"
            )
            centered = points - np.mean(points, axis=0)
            _, _, vt = np.linalg.svd(centered, full_matrices=False)
            projected = centered @ vt[:2].T
            try:
                hull2d = ConvexHull(projected)
                candidate_ids = list(hull2d.vertices)
            except Exception as exc2:
                Console.PrintWarning(
                    "ConstraintJig321: 2D ConvexHull failed for supports; "
                    "falling back to all points: "
                    f"{exc2}\n"
                )
                candidate_ids = list(range(len(unique_node_idxs)))

        if len(candidate_ids) < 3:
            candidate_ids = list(range(len(unique_node_idxs)))

        best_area2 = -1.0
        best_triplet = None

        for ia in range(len(candidate_ids) - 2):
            a = candidate_ids[ia]
            for ib in range(ia + 1, len(candidate_ids) - 1):
                b = candidate_ids[ib]
                ab = points[b] - points[a]
                for ic in range(ib + 1, len(candidate_ids)):
                    c = candidate_ids[ic]
                    ac = points[c] - points[a]
                    area2 = np.linalg.norm(np.cross(ab, ac))
                    if area2 > best_area2:
                        best_area2 = area2
                        best_triplet = (a, b, c)

        if best_triplet is None:
            best_triplet = (candidate_ids[0], candidate_ids[1], candidate_ids[2])

        best_node_indices = [unique_node_idxs[i] for i in best_triplet]
        Console.PrintMessage(f"Best supports: {best_node_indices}\n")
        if hasattr(fp, "Supports"):
            fp.Supports = [Vector(*femmesh.Nodes[i]) for i in best_node_indices]
        return best_node_indices
