# ***************************************************************************
# *   Copyright (c) 2026 FreeCAD contributors                               *
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

__title__ = "FreeCAD FEM calculix constraint pressure nonreaction helpers"
__author__ = "FreeCAD contributors"
__url__ = "https://www.freecad.org"


def write_pressure_entries_with_nonboundary_diagnostic(
    f,
    prs_obj,
    elem_info,
    femmesh,
    mesh_face_by_nodes,
    tetra4_face_nodes,
    Console,
):
    emitted_nonboundary_tetra4 = 0

    for i in range(len(elem_info["elem"])):
        pressure = elem_info["pressure"][i]
        if pressure != 0.0:
            elem_id = elem_info["elem"][i]
            face_no = elem_info["fno"][i]

            # Diagnostic sanity check (tetra4 only): verify emitted (elem, Pn)
            # corresponds to a boundary mesh face. A mismatch indicates that the
            # local face index being written targets an internal face.
            try:
                local_nodes = list(femmesh.getElementNodes(elem_id))
            except Exception:
                local_nodes = []
            if len(local_nodes) == 4:
                emitted_nodes = tetra4_face_nodes(local_nodes, face_no)
                if emitted_nodes is not None:
                    emitted_sig = frozenset(emitted_nodes)
                    if emitted_sig not in mesh_face_by_nodes:
                        emitted_nonboundary_tetra4 += 1

            # f.write("** {0.Name}.{1[0]}\n".format(*feat))
            f.write(f"{elem_id},P{face_no},{pressure:.13G}\n")

    if emitted_nonboundary_tetra4:
        Console.PrintWarning(
            "ConstraintReaction {}: {} emitted tetra4 pressure entries target "
            "non-boundary faces (internal-face load mismatch).\n".format(
                prs_obj.Name,
                emitted_nonboundary_tetra4,
            )
        )
