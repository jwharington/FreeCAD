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

import FreeCAD
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

        obj.addProperty(
            type="App::PropertyVector",
            name="CenterOfMass",
            group="AppliedLoad",
            doc="Center of mass of the body (body-local frame). Used to compute zero-COM-moment torque target.",
        ).CenterOfMass = Vector(0, 0, 0)

        # obj.setPropertyStatus("Scale", "LockDynamic")

    def execute(self, obj):
        if not hasattr(self, "elem_info"):
            self.elem_info = None
        if FreeCAD.GuiUp and obj.ViewObject:
            obj.ViewObject.update()
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
        # Torque target: negate obj.Torque so the pressure distribution
        # applies the correct reaction moment at the joint face.
        # The moment transported to CM = obj.Torque + (face-CM)×F,
        # which equals I*alpha (the angular inertia) for dynamic cases.
        # The residual angular inertia moment is carried by the Jig nodes.
        torque_target = -obj.Torque
        elem_info["contact"] = {}
        elem_info["load"] = {}
        elem_info["prel"] = {}

        def calc_net_forces(x):
            k_f = Vector(x[0], x[1], x[2])
            k_t = Vector(x[3], x[4], x[5])
            # where k_f, k_t are parameters

            F = -force_target
            T = -torque_target
            gauss_list = elem_info.get("gauss_data", [])
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

                elem_info["contact"][i] = C_i
                elem_info["load"][i] = l_i.Length

                # Force and torque accumulation.  For curved Tri6 elements, use the
                # 3-point Gauss integration data so that the Python computation matches
                # CalculiX's internal curved-surface integration.  For flat Tri3 (or
                # when gauss_data is unavailable) fall back to the flat-triangle formula.
                gauss_data_i = gauss_list[i] if i < len(gauss_list) else None
                if gauss_data_i is not None:
                    for x_gp, J_vec, wg in gauss_data_i:
                        dF = p_i * J_vec * wg
                        F += dF
                        T += dF.cross(x_gp - base)
                else:
                    # load on face i:
                    # L_i = p_i A_i n_i
                    L_i = p_i * A_i * n_i
                    F += L_i
                    T += L_i.cross(r_i)

            return np.array([F.x, F.y, F.z, T.x, T.y, T.z])

        x0 = np.zeros(6)
        res = root(calc_net_forces, x0, method="hybr")
        self.elem_info = elem_info  # save copy
        Console.PrintMessage(f"{pformat(res)}")

        if res.success:
            self._verify_pressure_field_closure(obj, elem_info, base)

        return res.success

    def _verify_pressure_field_closure(self, obj, elem_info, base):
        """Verify that the solved pressure field reproduces the target F and T.

        Reconstructs the net force and torque (about ``base``) from the solved
        pressure distribution and compares them to ``obj.Force`` / ``obj.Torque``.
        Enabled unconditionally when the root solve succeeds; set
        FREECAD_FEM_REACTION_VERIFY_VERBOSE=1 to emit a full Console message.
        """
        import os

        F_net = Vector(0, 0, 0)
        T_net = Vector(0, 0, 0)

        n = len(elem_info["elem"])
        gauss_list = elem_info.get("gauss_data", [])
        for i in range(n):
            p_i = elem_info["pressure"][i]
            A_i = elem_info["area"][i]
            n_i = elem_info["normal"][i]
            r_i = elem_info["centroid"][i] - base
            gauss_data_i = gauss_list[i] if i < len(gauss_list) else None
            if gauss_data_i is not None:
                for x_gp, J_vec, wg in gauss_data_i:
                    dF = p_i * J_vec * wg
                    F_net += dF
                    T_net += dF.cross(x_gp - base)
            else:
                L_i = p_i * A_i * n_i
                F_net += L_i
                T_net += L_i.cross(r_i)

        force_err = (F_net - obj.Force).Length
        # CalculiX applies +torque_target from the pressure distribution (see comment in
        # get_pressure_field).  torque_target = -obj.Torque, so the expected T_net is -obj.Torque.
        torque_err = (T_net + obj.Torque).Length

        if force_err > 1.0 or torque_err > 1.0:
            Console.PrintWarning(
                f"ConstraintReaction {obj.Name}: pressure field closure error "
                f"F_err={force_err:.3g} N  T_err={torque_err:.3g} N·mm "
                f"(target F={obj.Force}  T_target=-{obj.Torque})\n"
            )

        verbose = str(os.environ.get("FREECAD_FEM_REACTION_VERIFY_VERBOSE", "")).strip().lower()
        if verbose in {"1", "true", "yes", "on"}:
            Console.PrintMessage(
                f"[reaction-verify] {obj.Name}:\n"
                f"  origin_base  = {base}\n"
                f"  target Force = {obj.Force}   reconstructed = {F_net}   err = {force_err:.4g}\n"
                f"  target Torque= -{obj.Torque}  reconstructed = {T_net}   err = {torque_err:.4g}\n"
            )

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
