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

__title__ = "FreeCAD FEM calculix constraint tie"
__author__ = "Bernd Hahnebach"
__url__ = "https://www.freecad.org"


from FreeCAD import Units, Vector

from femtools.femutils import member_for_reference
from femtools.mixedcoupling import planar_face, tie_slave_side_and_tolerance


def get_analysis_types():
    return "all"  # write for all analysis types


def get_sets_name():
    return "constraints_tie_surface_sets"


def get_constraint_title():
    return "Tie Constraints"


def get_before_write_meshdata_constraint():
    return ""


def get_after_write_meshdata_constraint():
    return ""


def get_before_write_constraint():
    return ""


def get_after_write_constraint():
    return ""


def _tie_reference(surfaces):
    """The ``(object, subobject)`` a tie's slave or master surface names."""
    reference = surfaces[0][0]
    return reference[0], reference[1][0]


def _referenced_face(reference):
    """The sub-shape a reference names, when it is a single planar face."""
    obj, subobject = reference
    return planar_face(obj.getSubObject(subobject))


def _shell_slave_face(femobj, ccxwriter):
    """The expanded shell side that faces the master surface.

    CalculiX numbers a shell's faces 1 and 2 as the negative and positive
    normal sides of the shell's 3D expansion, and the section offset decides
    where those two sit about the reference surface (``*SHELL SECTION``; the
    manual, and ``gen3dfrom2d.f`` places them at ``ref - t*(0.5+offset)`` and
    ``ref + t*(0.5-offset)``). The face to tie is the one nearest the master,
    so a sandwich's two opposite-offset skins each name their own near face.

    Choosing by the offset sign alone named the *first* section in the analysis
    and could pick the far face - a whole thickness out, with no error from
    FreeCAD and none from CalculiX.
    """
    slave_reference = _tie_reference(femobj["TieSlaveFaces"]) if femobj["TieSlaveFaces"] else None
    master_reference = (
        _tie_reference(femobj["TieMasterFaces"]) if femobj["TieMasterFaces"] else None
    )
    if slave_reference is None or master_reference is None:
        return 2
    section = member_for_reference(
        [
            member
            for member in ccxwriter.member.geos_shellthickness
            if not getattr(member["Object"], "Suppressed", False)
        ],
        slave_reference,
    )
    if section is None:
        return 2
    slave_face = _referenced_face(slave_reference)
    master_face = _referenced_face(master_reference)
    if slave_face is None or master_face is None:
        return 1 if section.Offset < 0.0 else 2
    side, _required, _gap = tie_slave_side_and_tolerance(
        slave_face,
        master_face,
        section.Thickness.getValueAs("mm").Value,
        section.Offset,
    )
    return side


def write_meshdata_constraint(f, femobj, tie_obj, ccxwriter):
    shell_side = _shell_slave_face(femobj, ccxwriter)
    # slave DEP
    f.write(f"*SURFACE, NAME=TIE_DEP{tie_obj.Name}\n")
    for refs, surf, is_sub_el in femobj["TieSlaveFaces"]:
        if is_sub_el:
            for elem, fno in surf:
                f.write(f"{elem},S{fno}\n")
        else:
            for elem in surf:
                f.write(f"{elem},S{shell_side}\n")

    # master IND
    f.write(f"*SURFACE, NAME=TIE_IND{tie_obj.Name}\n")
    for refs, surf, is_sub_el in femobj["TieMasterFaces"]:
        if is_sub_el:
            for elem, fno in surf:
                f.write(f"{elem},S{fno}\n")
        else:
            for elem in surf:
                f.write(f"{elem},S2\n")


def write_constraint(f, femobj, tie_obj, ccxwriter):

    # floats read from ccx should use {:.13G}, see comment in writer module

    tolerance = tie_obj.Tolerance.getValueAs("mm").Value
    adjust = ""
    symmetry = ""
    tie_name = tie_obj.Name
    if not tie_obj.Adjust:
        adjust = ", ADJUST=NO"

    if tie_obj.CyclicSymmetry:
        symmetry = ", CYCLIC SYMMETRY"

    f.write(
        "*TIE, POSITION TOLERANCE={:.13G}{}{}, NAME=TIE{}\n".format(
            tolerance, adjust, symmetry, tie_name
        )
    )
    ind_surf = f"TIE_IND{tie_name}"
    dep_surf = f"TIE_DEP{tie_name}"
    f.write(f"{dep_surf}, {ind_surf}\n")

    # write CYCLIC SYMMETRY MODEL card
    if tie_obj.CyclicSymmetry:
        f.write(
            "*CYCLIC SYMMETRY MODEL, N={}, NGRAPH={}, TIE=TIE{}, ELSET=Eall\n".format(
                tie_obj.Sectors, tie_obj.ConnectedSectors, tie_name
            )
        )

        # get symmetry axis points
        vec_a = tie_obj.SymmetryAxis.Base
        vec_b = tie_obj.SymmetryAxis * Vector(0, 0, 1)

        set_unit = lambda x: Units.Quantity(x, Units.Length).getValueAs("mm").Value
        point_a = [set_unit(coord) for coord in vec_a]
        point_b = [set_unit(coord) for coord in vec_b]

        f.write("{:.13G},{:.13G},{:.13G},{:.13G},{:.13G},{:.13G}\n".format(*point_a, *point_b))
