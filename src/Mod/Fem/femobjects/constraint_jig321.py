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

import FreeCAD as App
import numpy as np
from FreeCAD import Console, Vector

from . import base_fempythonobject

_PropHelper = base_fempythonobject._PropHelper


class ConstraintJig321(base_fempythonobject.BaseFemPythonObject):
    """
    The ConstraintJig321 object
    """

    triggers = ["CenterOfMass", "LinearVelocity", "AngularVelocity", "References"]

    Type = "Fem::ConstraintJig321"

    def __init__(self, obj):
        super().__init__(obj)

        obj.addProperty(
            type="App::PropertyVector",
            name="LinearAcceleration",
            group="dAlembertForces",
            doc="Linear acceleration",
        ).LinearAcceleration = Vector(0, 0, 0)

        obj.addProperty(
            type="App::PropertyVector",
            name="AngularVelocity",
            group="dAlembertForces",
            doc="Angular velocity",
        ).AngularVelocity = Vector(0, 0, 0)

        obj.addProperty(
            type="App::PropertyVector",
            name="LinearVelocity",
            group="dAlembertForces",
            doc="Linear velocity",
        ).LinearVelocity = Vector(0, 0, 0)

        obj.addProperty(
            type="App::PropertyVector",
            name="CenterOfMass",
            group="dAlembertForces",
            doc="Center of mass",
        ).CenterOfMass = Vector(0, 0, 0)

        obj.addProperty(
            type="App::PropertyVector",
            name="CenterOfRotation",
            group="dAlembertForces",
            doc="Center of rotation",
        ).CenterOfRotation = Vector(0, 0, 0)

        obj.addProperty(
            type="App::PropertyVectorList",
            name="Supports",
            group="dAlembertForces",
            doc="Locations of supports for the constraint",
        ).Supports = []
        obj.setPropertyStatus("Supports", "ReadOnly")

    def execute(self, obj):
        for t in self.triggers + ["CenterOfRotation"]:
            if not hasattr(obj, t):
                return

        omega = obj.AngularVelocity
        o_mag = omega.Length
        com = obj.CenterOfMass
        v = obj.LinearVelocity
        v_mag = v.Length
        if (o_mag > 0) and (v_mag > 0):
            omega_n = omega / o_mag
            v_perp = v - omega_n * (v.dot(omega_n))
            r = omega_n.cross(v_perp) / o_mag
            obj.CenterOfRotation = com + r
            # Console.PrintMessage(f"r: {r}\n")
            # Console.PrintMessage(f"com: {obj.CenterOfMass}\n")
            # Console.PrintMessage(f"cor: {obj.CenterOfRotation}\n")
            # Console.PrintMessage(f"v: {v}\n")
            # Console.PrintMessage(f"v_inf: {omega.cross(r)}\n")
            # Console.PrintMessage(f"v_perp: {v_perp}\n")
        else:
            obj.CenterOfRotation = com

    def onChanged(self, fp, prop):
        # during loading the onchanged may be triggered before full init.
        if App.isRestoring():
            return

        if prop in self.triggers:
            fp.recompute()

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
