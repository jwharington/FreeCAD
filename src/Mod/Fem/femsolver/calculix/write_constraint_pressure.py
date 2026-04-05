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

from FreeCAD import Console


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

    def get_pressure_field(elem_info):
        prs_obj.Proxy.get_pressure_field(prs_obj, elem_info)

    def get_pressure_uniform(elem_info):
        for info in elem_info:
            info["pressure"] = prs_obj.Pressure.getValueAs("MPa").Value

    if has_pressure_field(prs_obj):
        get_pressure = get_pressure_field
    else:
        get_pressure = get_pressure_uniform

    elem_info = {
        "feat": [],
        "elem": [],
        "fno": [],
        "centroid": [],
        "normal": [],
        "area": [],
        "pressure": [],
        "rev": [],
        "felem": [],
    }

    # the pressure has to be output in MPa
    femmesh = ccxwriter.mesh_object.FemMesh

    for feature, surface, is_sub_el in femobj["PressureFaces"]:

        def find_face_element(face):
            # TODO speed this up
            ref_nodes = set(femobj["PressureNodeInfo"][tuple(face)])
            for fe in femmesh.Faces:
                nodes = femmesh.getElementNodes(fe)
                if set(nodes) == ref_nodes:
                    return fe
            return None

        def add_elem_info(face, elem, face_no, rev):
            elem_info["feat"].append(feature)
            elem_info["elem"].append(elem)
            elem_info["fno"].append(face_no)
            elem_info["pressure"].append(0.0)
            centroid, area, normal = femobj["PressureFaceInfo"][tuple(face)]
            elem_info["centroid"].append(centroid)
            elem_info["area"].append(area)
            elem_info["normal"].append(normal)
            elem_info["rev"].append(rev)
            felem = find_face_element(face)
            elem_info["felem"].append(felem)

        for face in surface:
            if is_sub_el:
                elem, face_no = face
                add_elem_info(face, elem, face_no, rev)
            else:
                add_elem_info(face, face, "", -rev)

    get_pressure(elem_info)

    for i in range(len(elem_info["elem"])):
        pressure = elem_info["pressure"][i]
        if pressure != 0.0:
            # f.write("** {0.Name}.{1[0]}\n".format(*feat))
            f.write(f"{elem_info['elem'][i]},P{elem_info['fno'][i]},{pressure:.13G}\n")
