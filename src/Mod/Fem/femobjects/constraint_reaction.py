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

__title__ = "FreeCAD FEM constraint reaction pressure document object"
__author__ = "John Wharington"
__url__ = "https://www.freecad.org"

## @package constraint_reaction
#  \ingroup FEM
#  \brief constraint self weight object

from pprint import pformat

import numpy as np
from femtools.distributions import ReactionContactType
from FreeCAD import Console, Vector
from scipy.optimize import root

from . import base_fempythonobject


class ConstraintReaction(base_fempythonobject.BaseFemPythonObject):
    """
    The ConstraintReaction object"
    """

    Type = "Fem::ConstraintReaction"

    def __init__(self, obj):
        obj.Proxy = self

        # properties:
        #   contact distribution type
        #   force / torque magnitude and direction
        #   reference point

        obj.addProperty(
            type="App::PropertyEnumeration",
            name="ModelType",
            group="Distribution",
            doc="Model of distribution",
        )
        obj.ModelType = [item.name for item in ReactionContactType]
        obj.ModelType = ReactionContactType.Cosine.name

        obj.addProperty(
            type="App::PropertyVector",
            name="Force",
            group="AppliedLoad",
            doc="Force vector applied to the reaction.",
        ).Force = Vector(0, 0, 0)

        obj.addProperty(
            type="App::PropertyVector",
            name="Torque",
            group="AppliedLoad",
            doc="Torque vector applied to the reaction.",
        ).Torque = Vector(0, 0, 0)

        obj.addProperty(
            type="App::PropertyPlacement",
            name="Origin",
            group="AppliedLoad",
            doc="Origin of the applied load.",
        )  # .Origin = FreeCAD.Placement(Vector(0, 0, 0))

        # generic
        obj.addProperty(
            type="App::PropertyBool",
            name="EnableAmplitude",
            group="Distribution",
            doc="Enable amplitude scaling.",
        ).EnableAmplitude = False
        obj.setPropertyStatus("EnableAmplitude", "Hidden")

        obj.addProperty(
            type="App::PropertyBool", name="Reversed", group="Distribution", doc="Flip direction."
        ).Reversed = False

        # obj.setPropertyStatus("Scale", "LockDynamic")

    def execute(self, obj):
        if not hasattr(self, "elem_info"):
            self.elem_info = None

        # if FreeCAD.GuiUp and obj.ViewObject:
        #     obj.ViewObject.update()
        return False

    def get_contact(self, obj, n_i, l_i):
        # d_i = cosphi = n_i . l_i/|l_i|
        proj = -n_i.dot(l_i)

        if obj.ModelType == ReactionContactType.Uniform.name:
            if l_i.Length:
                return proj / l_i.Length
            return 0.0

        if proj <= 0:
            return 0.0

        # positive non-trivial
        cosphi = proj / l_i.Length

        if obj.ModelType == ReactionContactType.Cosine.name:
            return cosphi
        elif obj.ModelType == ReactionContactType.Parabolic.name:
            return cosphi**2
        elif obj.ModelType == ReactionContactType.Gencoz.name:

            def chebyshev(n, x):
                if n == 0:
                    return 1.0
                elif n == 1:
                    return x
                else:
                    return 2.0 * x * chebyshev(n - 1, x) - chebyshev(n - 2, x)

            # gencoz: cos phi - sum_5,9 5 cos (n phi) / (14 (n-1)(n-8))
            #         - sum_3,7 2 cos (n phi) / (5 (4-n)(4-n))
            res = cosphi
            for n in [5, 9]:
                res -= 5.0 * chebyshev(n, cosphi) / (14.0 * (n - 1) * (n - 8))
            for n in [3, 7]:
                res -= 2.0 * chebyshev(n, cosphi) / (5.0 * (4 - n) * (4 - n))
            return res
        else:
            raise NotImplementedError(f"Contact type {obj.ModelType} not implemented")

    def get_pressure_field(self, obj, elem_info):

        # reference point for joint equilibrium
        base = obj.Origin.Base
        force_target = obj.Force
        torque_target = obj.Torque
        elem_info["contact"] = {}
        elem_info["load"] = {}
        elem_info["prel"] = {}

        def calc_net_forces(x):
            k_f = Vector(x[0], x[1], x[2])
            k_t = Vector(x[3], x[4], x[5])
            # where k_f, k_t are parameters

            F = -force_target
            T = -torque_target
            for i in range(len(elem_info["elem"])):
                n_i = elem_info["normal"][i]
                A_i = elem_info["area"][i]
                r_i = elem_info["centroid"][i] - base
                elem_info["prel"][i] = r_i
                # distribution function:
                l_i = k_f + k_t.cross(r_i)

                # contact function:
                # - uniform (0), cosine (1), parabolic (2), gencoz
                C_i = self.get_contact(obj, n_i, l_i)

                # pressure on face i:
                # p_i = C_i |l_i|
                p_i = C_i * l_i.Length
                elem_info["pressure"][i] = p_i * elem_info["rev"][i]

                # load on face i:
                # L_i = p_i A_i n_i
                L_i = p_i * A_i * n_i

                # accumulate force/torque
                F += L_i
                T += L_i.cross(r_i)

                elem_info["contact"][i] = C_i
                elem_info["load"][i] = l_i.Length

            return np.array([F.x, F.y, F.z, T.x, T.y, T.z])

        x0 = np.zeros(6)
        res = root(calc_net_forces, x0, method="hybr")
        self.elem_info = elem_info  # save copy
        Console.PrintMessage(f"{pformat(res)}")

        return res.success

    def onChanged(self, fp, prop):
        if not hasattr(fp, "ModelType"):
            return
        if prop == "ModelType":
            fp.recompute()

    def onDocumentRestored(self, obj):
        obj.recompute()

    def pressure_valid(self, obj):
        return True

    def save_reactioninfo(self, elem_info):
        with open("reaction.txt", "w") as f:

            def wv(x):
                f.write(f"{x.x} {x.y} {x.z} ")

            def ws(x, i):
                f.write(f"{elem_info[x][i]} ")

            for i in range(len(elem_info["pressure"])):
                wv(elem_info["centroid"][i])
                wv(elem_info["normal"][i])
                wv(elem_info["prel"][i])
                ws("area", i)
                ws("contact", i)
                ws("load", i)
                ws("pressure", i)
                f.write("\n")
