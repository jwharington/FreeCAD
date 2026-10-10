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

__title__ = "FreeCAD FEM calculix write inpfile femelement geometry"
__author__ = "Bernd Hahnebach"
__url__ = "https://www.freecad.org"

import hashlib

from FreeCAD import Vector
from femtools import ccxnames
from femtools import fem_extension_registry

# CalculiX allows 80 characters for a user-defined name (manual, *NSET/ELSET)
# and refuses the whole deck otherwise. The names here are concatenations of
# material, shell and thickness identifiers, so they grow with the model rather
# than with the meaning: a mixed wing reached 82 characters by appending an
# element id to one, and CalculiX answered "*ERROR reading *NSET/ELSET: set
# name too long".
MAX_NAME_LENGTH = 80

# A composite *SHELL SECTION is accepted only for quadratic shells, S6 and S8R.
# With a linear one CalculiX refuses the whole deck - "Element 2 is not a S8R nor
# a S6 shell element" - after FreeCAD has already written it, so the model is
# refused here instead. Node count is the only shape test available from Python:
# FemMesh.getElementType reports an element's dimension ("Face"), not its shape,
# and the CalculiX names are chosen in C++ where the *Element cards are written.
COMPOSITE_SHELL_ELEMENT_NODES = (6, 8)


def _bounded_name(text):
    """``text`` when CalculiX will accept it, otherwise a hashed one."""
    return text if len(text) <= MAX_NAME_LENGTH else ccxnames.hashed_prefix(text)


def _is_composite_section(material):
    """Whether a *SHELL SECTION header names COMPOSITE rather than a material.

    A section provider replaces the whole MATERIAL chunk of the card, so the card
    is layered exactly when that chunk's first field is COMPOSITE - with or
    without an ORIENTATION.
    """
    return material.split(",", 1)[0].strip() == "COMPOSITE"


def _shell_elements_that_are_not_quadratic(elements, femmesh):
    """Which of ``elements`` a composite shell section cannot be written for."""
    return [
        element_id
        for element_id in elements
        if len(femmesh.getElementNodes(element_id)) not in COMPOSITE_SHELL_ELEMENT_NODES
    ]


def write_femelement_geometry(f, ccxwriter):

    # floats read from ccx should use {:.13G}, see comment in writer module

    f.write("\n{}\n".format(59 * "*"))
    f.write("** Sections\n")

    def write_matgeoset(matgeoset, orientation):
        elsetdef = "ELSET={}, ".format(matgeoset["ccx_elset_name"])
        material = "MATERIAL={}".format(matgeoset["mat_obj_name"])
        orientation_name = matgeoset.get("orientation_name") or _bounded_name(
            f'_OR_{matgeoset["ccx_elset_name"]}'
        )

        if orientation:
            f.write(f"*ORIENTATION,NAME={orientation_name}\n")

            def format_dim(v):
                return "{:.13G},{:.13G},{:.13G}".format(v.x, v.y, v.z)

            T = orientation
            p0 = T * Vector(0, 0, 0)
            dx = format_dim(T * Vector(1, 0, 0) - p0)
            dy = format_dim(T * Vector(0, 1, 0) - p0)
            f.write(f"{dx},{dy}\n")
            material = f"{material},ORIENTATION={orientation_name}"

        if "beamsection_obj" in matgeoset:  # beam mesh
            beamsec_obj = matgeoset["beamsection_obj"]
            beam_axis_m = matgeoset["beam_axis_m"]
            # in CalxuliX called the 1direction
            # see meshtools.get_beam_main_axis_m(beam_direction, defined_angle)
            section_nor = "{:.13G}, {:.13G}, {:.13G}\n".format(
                beam_axis_m[0], beam_axis_m[1], beam_axis_m[2]
            )
            if ccxwriter.solver_obj.ExcludeBendingStiffness:
                area = beamsec_obj.TrussArea.getValueAs("mm^2").Value
                section_def = f"*SOLID SECTION, {elsetdef}{material}\n"
                section_geo = f"{area:.13G}\n"
            else:
                if beamsec_obj.SectionType == "Rectangular":
                    # see meshtools.get_beam_main_axis_m(beam_direction, defined_angle)
                    # the method get_beam_main_axis_m() which calculates the beam_axis_m vector
                    # unless rotated, this vector points towards +y axis
                    # doesn't follow 1,2-direction order of CalculiX
                    # ^ (n, 2-direction)
                    # |
                    # |
                    # .----> (m, 1-direction)
                    #
                    len_beam_axis_n = beamsec_obj.RectHeight.getValueAs("mm").Value
                    len_beam_axis_m = beamsec_obj.RectWidth.getValueAs("mm").Value
                    section_type = ", SECTION=RECT"
                    section_geo = f"{len_beam_axis_m:.13G},{len_beam_axis_n:.13G}\n"
                    section_def = f"*BEAM SECTION, {elsetdef}{material}{section_type}\n"
                elif beamsec_obj.SectionType == "Circular":
                    diameter = beamsec_obj.CircDiameter.getValueAs("mm").Value
                    section_type = ", SECTION=CIRC"
                    section_geo = f"{diameter:.13G}\n"
                    section_def = f"*BEAM SECTION, {elsetdef}{material}{section_type}\n"
                elif beamsec_obj.SectionType == "Elliptical":
                    axis1 = beamsec_obj.Axis1Length.getValueAs("mm").Value
                    axis2 = beamsec_obj.Axis2Length.getValueAs("mm").Value
                    section_type = ", SECTION=CIRC"
                    section_geo = f"{axis1:.13G},{axis2:.13G}\n"
                    section_def = f"*BEAM SECTION, {elsetdef}{material}{section_type}\n"
                elif beamsec_obj.SectionType == "Pipe":
                    radius = 0.5 * beamsec_obj.PipeDiameter.getValueAs("mm").Value
                    thickness = beamsec_obj.PipeThickness.getValueAs("mm").Value
                    section_type = ", SECTION=PIPE"
                    section_geo = f"{radius:.13G},{thickness:.13G}\n"
                    section_def = f"*BEAM SECTION, {elsetdef}{material}{section_type}\n"
                elif beamsec_obj.SectionType == "Box":
                    box_width = beamsec_obj.BoxWidth.getValueAs("mm").Value
                    box_height = beamsec_obj.BoxHeight.getValueAs("mm").Value
                    box_t1 = beamsec_obj.BoxT1.getValueAs("mm").Value
                    box_t2 = beamsec_obj.BoxT2.getValueAs("mm").Value
                    box_t3 = beamsec_obj.BoxT3.getValueAs("mm").Value
                    box_t4 = beamsec_obj.BoxT4.getValueAs("mm").Value
                    section_type = ", SECTION=BOX"
                    section_geo = f"{box_width:.13G},{box_height:.13G},{box_t1:.13G},{box_t2:.13G},{box_t3:.13G},{box_t4:.13G}\n"
                    section_def = f"*BEAM SECTION, {elsetdef}{material}{section_type}\n"

            f.write(section_def)
            f.write(section_geo)
            if not ccxwriter.solver_obj.ExcludeBendingStiffness:
                f.write(section_nor)
        elif "fluidsection_obj" in matgeoset:  # fluid mesh
            fluidsec_obj = matgeoset["fluidsection_obj"]
            if fluidsec_obj.SectionType == "Liquid":
                section_type = fluidsec_obj.LiquidSectionType
                if (section_type == "PIPE INLET") or (section_type == "PIPE OUTLET"):
                    section_type = "PIPE INOUT"
                section_def = "*FLUID SECTION, {}TYPE={}, {}\n".format(
                    elsetdef, section_type, material
                )
                section_geo = liquid_section_def(fluidsec_obj, section_type)
            """
            # deactivate as it would result in section_def and section_geo not defined
            # deactivated in the App and Gui object and thus in the task panel as well
            elif fluidsec_obj.SectionType == "Gas":
                section_type = fluidsec_obj.GasSectionType
            elif fluidsec_obj.SectionType == "Open Channel":
                section_type = fluidsec_obj.ChannelSectionType
            """
            f.write(section_def)
            f.write(section_geo)
        elif "shellthickness_obj" in matgeoset:  # shell mesh
            shellth_obj = matgeoset["shellthickness_obj"]
            section_override = fem_extension_registry.get_shell_section_override(
                shellth_obj,
                matgeoset,
                orientation_name,
            )
            if section_override and section_override.get("material"):
                material = section_override["material"]
            if _is_composite_section(material):
                elements = matgeoset["ccx_elset"]
                if isinstance(elements, str):
                    # The name of a set holding every element: a shell section
                    # applies to the mesh's face elements.
                    elements = ccxwriter.mesh_object.FemMesh.FacesOnly
                linear = _shell_elements_that_are_not_quadratic(
                    elements, ccxwriter.mesh_object.FemMesh
                )
                if linear:
                    raise ValueError(
                        f"{shellth_obj.Name}: a composite *SHELL SECTION is accepted "
                        f"only for quadratic shells (S6 or S8R), but {len(linear)} of "
                        f"the {len(elements)} elements it sections are linear "
                        f"(first: {linear[0]}). CalculiX would refuse the deck. "
                        f"Mesh the laminate second order."
                    )
            if ccxwriter.solver_obj.ModelSpace == "3D":
                offset = shellth_obj.Offset
                if ccxwriter.solver_obj.ExcludeBendingStiffness:
                    section_def = f"*MEMBRANE SECTION, {elsetdef}{material}, OFFSET={offset:.13G}\n"
                else:
                    section_def = f"*SHELL SECTION, {elsetdef}{material}, OFFSET={offset:.13G}\n"
            else:
                section_def = f"*SOLID SECTION, {elsetdef}{material}\n"
            if section_override and section_override.get("section_geo"):
                section_geo = section_override["section_geo"]
            else:
                thickness = shellth_obj.Thickness.getValueAs("mm").Value
                section_geo = f"{thickness:.13G}\n"
            f.write(section_def)
            f.write(section_geo)
        else:  # solid mesh
            section_def = f"*SOLID SECTION, {elsetdef}{material}\n"
            f.write(section_def)

    for matgeoset in ccxwriter.mat_geo_sets:
        if not matgeoset["ccx_elset"]:
            continue

        heterogeneous = "element_ids" in matgeoset
        orthotropic = ("orientation" in matgeoset) and (matgeoset["orientation"] is not None)

        if not heterogeneous:
            if orthotropic:
                orientation = matgeoset["orientation"]
            else:
                orientation = None
            write_matgeoset(matgeoset, orientation=orientation)
        else:
            elset_name = matgeoset["ccx_elset_name"]
            orientations = (
                matgeoset["orientation"] if orthotropic else None
            )
            # One section and one *ORIENTATION card per element: CalculiX
            # sizes its orientation store from the number of cards, so the
            # cards are kept.  A card is named by its rotation, though, so
            # elements sharing a frame share one definition — distinct
            # names corrupt the solver's orientation store on a one-layer
            # section (measured, plate round trip).
            orientation_names = {}
            for i in matgeoset["element_ids"]:
                # Hash then id: a section per element makes this name carry the
                # whole material/shell/thickness concatenation once per element,
                # which is how an 82-character name reached CalculiX. The id is
                # kept because it is the part a person reads.
                elset_i_name = f"{ccxnames.hashed_prefix(elset_name)}_{i}"
                f.write(f"*ELSET,ELSET={elset_i_name}\n{i}\n")
                elem_matgeoset = matgeoset | {"ccx_elset_name": elset_i_name}
                if not orthotropic:
                    write_matgeoset(elem_matgeoset, orientation=None)
                    continue
                orientation = orientations[i]
                key = _orientation_key(orientation)
                if key not in orientation_names:
                    orientation_names[key] = _orientation_name(key)
                elem_matgeoset["orientation_name"] = orientation_names[key]
                write_matgeoset(elem_matgeoset, orientation=orientation)


# ************************************************************************************************
def _orientation_name(key):
    """A short, deterministic orientation name for a rotation key.

    CalculiX's orientation store corrupts on a one-layer section when the
    shared name is long: the same plate deck segfaults with a 69-character
    name and solves with a 4-character one.  The name is therefore a short
    digest of the rotation, not the (long) element-set name.
    """
    return "_OR_" + hashlib.md5(repr(key).encode()).hexdigest()[:8]


def _orientation_key(orientation):
    """A hashable identity for the local axes a section writes (None too).

    Keyed on the rotation alone: the section emits only the rotated axes
    (the frame origin is subtracted out), so two frames that differ only in
    position are one orientation to CalculiX and must share one card.
    """
    if orientation is None:
        return None
    return tuple(round(value, 9) for value in orientation.Rotation.Q)


# ************************************************************************************************
# Helpers
def liquid_section_def(obj, section_type):
    if section_type == "PIPE MANNING":
        manning_area = obj.ManningArea.getValueAs("mm^2").Value
        manning_radius = obj.ManningRadius.getValueAs("mm").Value
        manning_coefficient = obj.ManningCoefficient
        section_geo = "{:.13G},{:.13G},{:.13G}\n".format(
            manning_area, manning_radius, manning_coefficient
        )
        return section_geo
    elif section_type == "PIPE ENLARGEMENT":
        enlarge_area1 = obj.EnlargeArea1.getValueAs("mm^2").Value
        enlarge_area2 = obj.EnlargeArea2.getValueAs("mm^2").Value
        section_geo = f"{enlarge_area1:.13G},{enlarge_area2:.13G}\n"
        return section_geo
    elif section_type == "PIPE CONTRACTION":
        contract_area1 = obj.ContractArea1.getValueAs("mm^2").Value
        contract_area2 = obj.ContractArea2.getValueAs("mm^2").Value
        section_geo = f"{contract_area1:.13G},{contract_area2:.13G}\n"
        return section_geo
    elif section_type == "PIPE ENTRANCE":
        entrance_pipe_area = obj.EntrancePipeArea.getValueAs("mm^2").Value
        entrance_area = obj.EntranceArea.getValueAs("mm^2").Value
        section_geo = f"{entrance_pipe_area:.13G},{entrance_area:.13G}\n"
        return section_geo
    elif section_type == "PIPE DIAPHRAGM":
        diaphragm_pipe_area = obj.DiaphragmPipeArea.getValueAs("mm^2").Value
        diaphragm_area = obj.DiaphragmArea.getValueAs("mm^2").Value
        section_geo = f"{diaphragm_pipe_area:.13G},{diaphragm_area:.13G}\n"
        return section_geo
    elif section_type == "PIPE BEND":
        bend_pipe_area = obj.BendPipeArea.getValueAs("mm^2").Value
        bend_radius_diameter = obj.BendRadiusDiameter
        bend_angle = obj.BendAngle
        bend_loss_coefficient = obj.BendLossCoefficient
        section_geo = "{:.13G},{:.13G},{:.13G},{:.13G}\n".format(
            bend_pipe_area, bend_radius_diameter, bend_angle, bend_loss_coefficient
        )
        return section_geo
    elif section_type == "PIPE GATE VALVE":
        gatevalve_pipe_area = obj.GateValvePipeArea.getValueAs("mm^2").Value
        gatevalve_closing_coeff = obj.GateValveClosingCoeff
        section_geo = f"{gatevalve_pipe_area:.13G},{gatevalve_closing_coeff:.13G}\n"
        return section_geo
    elif section_type == "PIPE WHITE-COLEBROOK":
        colebrooke_area = obj.ColebrookeArea.getValueAs("mm^2").Value
        colebrooke_diameter = 2 * obj.ColebrookeRadius.getValueAs("mm")
        colebrooke_grain_diameter = obj.ColebrookeGrainDiameter.getValueAs("mm")
        colebrooke_form_factor = obj.ColebrookeFormFactor
        section_geo = "{:.13G},{:.13G},{},{:.13G},{:.13G}\n".format(
            colebrooke_area,
            colebrooke_diameter,
            "-1",
            colebrooke_grain_diameter,
            colebrooke_form_factor,
        )
        return section_geo
    elif section_type == "LIQUID PUMP":
        section_geo = ""
        for i in range(len(obj.PumpFlowRate)):
            flow_rate = obj.PumpFlowRate[i]
            top = obj.PumpHeadLoss[i]
            section_geo = f"{section_geo + flow_rate:.13G},{top:.13G},\n"
        section_geo = f"{section_geo}\n"
        return section_geo
    else:
        return ""
