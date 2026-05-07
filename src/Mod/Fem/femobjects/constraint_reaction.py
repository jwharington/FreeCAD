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

import FreeCAD
from femtools.distributions import ReactionContactType
from FreeCAD import Console, Vector

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

    def _build_display_node_weights(self, obj, elem_info):
        node_weights = {}
        force = getattr(obj, "Force", Vector(0, 0, 0))

        face_nodes_all = elem_info.get("face_nodes", [])
        areas = elem_info.get("area", [])
        normals = elem_info.get("normal", [])
        nfaces = min(len(face_nodes_all), len(areas), len(normals))

        if nfaces <= 0:
            return node_weights

        use_contact = force.Length > 1.0e-18
        for i in range(nfaces):
            face_nodes = face_nodes_all[i]
            if not face_nodes:
                continue

            area = float(areas[i])
            if area <= 0.0:
                continue

            contact = 1.0
            if use_contact:
                try:
                    contact = float(self.get_contact(obj, normals[i], force))
                except Exception:
                    contact = 0.0

            if contact <= 0.0:
                continue

            nodal_share = (area * contact) / float(len(face_nodes))
            for nid in face_nodes:
                node_weights[nid] = node_weights.get(nid, 0.0) + nodal_share

        if not node_weights:
            # Contact-weighting may collapse to zero (e.g. opposing normals);
            # keep a meaningful preview by falling back to pure area weighting.
            for i in range(nfaces):
                face_nodes = face_nodes_all[i]
                if not face_nodes:
                    continue

                area = float(areas[i])
                if area <= 0.0:
                    continue

                nodal_share = area / float(len(face_nodes))
                for nid in face_nodes:
                    node_weights[nid] = node_weights.get(nid, 0.0) + nodal_share

        return node_weights

    def _set_display_face_values_from_node_weights(self, elem_info, node_weights):
        face_nodes_all = elem_info.get("face_nodes", [])
        pressures = elem_info.get("pressure", [])

        nfaces = min(len(pressures), len(face_nodes_all))
        for i in range(nfaces):
            face_nodes = face_nodes_all[i]
            if not face_nodes:
                pressures[i] = 0.0
                continue

            face_sum = 0.0
            for nid in face_nodes:
                face_sum += node_weights.get(nid, 0.0)

            pressures[i] = face_sum / float(len(face_nodes))

    def get_pressure_field(self, obj, elem_info):
        # Solver-based pressure optimization has been removed for ConstraintReaction.
        # The reaction resultant is delivered directly by the writer.
        # Keep elem_info["pressure"] populated with display-only values so
        # view providers can visualize reaction distribution meaningfully.
        elem_info["reaction_force"] = obj.Force
        elem_info["reaction_torque"] = -obj.Torque

        node_weights = self._build_display_node_weights(obj, elem_info)
        if node_weights and elem_info.get("face_nodes"):
            self._set_display_face_values_from_node_weights(elem_info, node_weights)
        else:
            # If face-node information is unavailable (e.g. lightweight preview
            # elem_info), fall back to per-face contact projection values.
            pressure = elem_info.get("pressure", [])
            normal = elem_info.get("normal", [])
            nfaces = min(len(pressure), len(normal))
            force = getattr(obj, "Force", Vector(0, 0, 0))
            for i in range(nfaces):
                if force.Length <= 1.0e-18:
                    pressure[i] = 0.0
                    continue
                try:
                    pressure[i] = float(self.get_contact(obj, normal[i], force))
                except Exception:
                    pressure[i] = 0.0

        self.elem_info = elem_info
        return True

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
