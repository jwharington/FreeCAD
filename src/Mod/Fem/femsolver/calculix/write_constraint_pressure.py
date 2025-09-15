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

__title__ = "FreeCAD FEM calculix constraint pressure"
__author__ = "Bernd Hahnebach"
__url__ = "https://www.freecad.org"

import FreeCAD
import numpy as np
from femmesh import meshtools


def get_analysis_types():
    return ["buckling", "static", "thermomech"]


def get_sets_name():
    return "constraints_pressure_element_face_loads"


def get_before_write_meshdata_constraint():
    return ""


def get_after_write_meshdata_constraint():
    return ""


def has_pressure_field(prs_obj):
    if not hasattr(prs_obj, "Proxy"):
        return False
    if hasattr(prs_obj.Proxy, "get_pressure_field"):
        return True
    return False


def write_meshdata_constraint(f, femobj, prs_obj, ccxwriter):
    # floats read from ccx should use {:.13G}, see comment in writer module

    if prs_obj.EnableAmplitude:
        f.write(f"*DLOAD, AMPLITUDE={prs_obj.Name}\n")
    else:
        f.write("*DLOAD\n")
    rev = -1 if prs_obj.Reversed else 1
    # the pressure has to be output in MPa
    femmesh = ccxwriter.mesh_object.FemMesh

    def get_centroid(elem):
        nodes = meshtools.get_femelement_faces_table(femmesh, [elem])
        points = np.vstack([np.array(femmesh.Nodes[i]) for i in nodes[elem]])
        return FreeCAD.Vector(np.mean(points, axis=0))

    def get_pressure_field(elem):
        centroid = get_centroid(elem)
        if (res := prs_obj.Proxy.get_pressure_field(prs_obj, centroid)) is not None:
            return res * rev
        return 0.0

    def get_pressure_uniform(elem):
        return rev * prs_obj.Pressure.getValueAs("MPa").Value

    if has_pressure_field(prs_obj):
        get_pressure = get_pressure_field
    else:
        get_pressure = get_pressure_uniform

    for feat, surf, is_sub_el in femobj["PressureFaces"]:
        f.write("** {0.Name}.{1[0]}\n".format(*feat))

        if is_sub_el:
            for elem, fno in surf:
                f.write(f"{elem},P{fno},{get_pressure(elem):.13G}\n")
        else:
            for elem in surf:
                f.write(f"{elem},P,{-1*get_pressure(elem):.13G}\n")
