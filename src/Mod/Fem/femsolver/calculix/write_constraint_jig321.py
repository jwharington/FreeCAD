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

__title__ = "FreeCAD FEM calculix constraint jig321"
__author__ = "John Wharington"
__url__ = "https://www.freecad.org"

from FreeCAD import Console, Vector


def get_analysis_types():
    return ["buckling", "static", "thermomech"]


def get_sets_name():
    return "constraints_jig321_element_sets"


def get_constraint_title():
    return "3-2-1 Jig Constraints"


def get_before_write_meshdata_constraint():
    return ""


def get_after_write_meshdata_constraint():
    return ""


def get_before_write_constraint():
    return ""


def get_after_write_constraint():
    return ""


def jig_name(jig321_obj, idx):
    return f"{jig321_obj.Name}-{idx}"


def _fvec(v):
    return f"{v.x:.13G},{v.y:.13G},{v.z:.13G}"


def write_meshdata_constraint(f, femobj, jig321_obj, ccxwriter):
    for idx, n in enumerate(femobj["Nodes"]):
        jname = jig_name(jig321_obj=jig321_obj, idx=idx)
        f.write(f"*NSET,NSET={jname}\n")
        f.write(f"{n},\n")


def write_constraint(f, femobj, jig321_obj, ccxwriter):
    if len(femobj["Nodes"]) < 3:
        Console.PrintError("ConstraintJig321: Need at least 3 nodes to define a triangle.\n")
        return

    femmesh = ccxwriter.mesh_object.FemMesh

    support_pos = [Vector(*femmesh.Nodes[node]) for node in femobj["Nodes"]]
    X = support_pos[1] - support_pos[0]
    Y = support_pos[2] - support_pos[0]

    for idx, _n in enumerate(femobj["Nodes"]):
        jname = jig_name(jig321_obj=jig321_obj, idx=idx)
        f.write(f"*TRANSFORM,NSET={jname},TYPE=R\n")
        f.write(f"{_fvec(X)},{_fvec(Y)}\n")
        f.write("*BOUNDARY\n")
        istart = idx + 1
        iend = 3
        f.write(f"{jname},{istart},{iend},0.0\n")
