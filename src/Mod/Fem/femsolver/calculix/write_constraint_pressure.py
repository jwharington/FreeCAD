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

import importlib
import os

from .write_constraint_pressure_nonreaction import (
    write_pressure_entries_with_nonboundary_diagnostic,
)
from .write_constraint_pressure_reaction import (
    emit_reaction_diagnostics,
    write_reaction_distributing_coupling,
)

_freecad = importlib.import_module("FreeCAD")
Console = _freecad.Console

REACTION_COUPLING_SHIFT_FREE_M_LIMIT = float(
    os.environ.get("FREECAD_FEM_REACTION_COUPLING_SHIFT_FREE_M_LIMIT", "50.0")
)
REACTION_COUPLING_SHIFT_SCALE = float(
    os.environ.get("FREECAD_FEM_REACTION_COUPLING_SHIFT_SCALE", "1.0")
)


def get_analysis_types():
    return ["buckling", "static", "thermomech"]


def get_sets_name():
    return "constraints_pressure_element_face_loads"


def get_before_write_meshdata_constraint():
    return ""


def get_after_write_meshdata_constraint():
    return ""


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def has_pressure_field(prs_obj):
    if not hasattr(prs_obj, "Proxy"):
        return False
    if hasattr(prs_obj.Proxy, "get_pressure_field"):
        return True
    return False


def write_meshdata_constraint(f, femobj, prs_obj, ccxwriter, op_new=False):
    # floats read from ccx should use {:.13G}, see comment in writer module

    is_reaction = has_pressure_field(prs_obj)
    use_coupling = is_reaction
    if not use_coupling:
        if prs_obj.EnableAmplitude:
            f.write(f"*DLOAD, AMPLITUDE={prs_obj.Name}\n")
        else:
            f.write("*DLOAD\n")
    rev = -1 if prs_obj.Reversed else 1

    def tetra4_face_nodes(local_nodes, face_no):
        face_no = str(face_no)
        if face_no == "1":
            return (local_nodes[0], local_nodes[1], local_nodes[2])
        if face_no == "2":
            return (local_nodes[0], local_nodes[3], local_nodes[1])
        if face_no == "3":
            return (local_nodes[0], local_nodes[2], local_nodes[3])
        if face_no == "4":
            return (local_nodes[1], local_nodes[3], local_nodes[2])
        return None

    def tetra4_face_no_from_local_set(local_set):
        mapping_default = {
            frozenset((1, 2, 3)): 1,
            frozenset((1, 2, 4)): 2,
            frozenset((1, 3, 4)): 3,
            frozenset((2, 3, 4)): 4,
        }
        return mapping_default.get(local_set)

    def get_pressure_field(elem_info):
        prs_obj.Proxy.get_pressure_field(prs_obj, elem_info)

    def get_pressure_uniform(elem_info):
        uniform_pressure = prs_obj.Pressure.getValueAs("MPa").Value
        for i in range(len(elem_info["pressure"])):
            elem_info["pressure"][i] = uniform_pressure

    def face_key(face):
        return tuple(face) if isinstance(face, (list, tuple)) else (face,)

    face_table_entry_cache = {}

    def get_face_table_entry(table_name, face):
        key = face_key(face)
        cache_key = (table_name, key)
        if cache_key in face_table_entry_cache:
            return face_table_entry_cache[cache_key]

        table = femobj[table_name]
        if key in table:
            val = table[key]
            face_table_entry_cache[cache_key] = val
            return val

        # Some mesh tables are keyed by scalar face id for shell faces.
        scalar_key = key[0] if len(key) == 1 else None
        if scalar_key is not None and scalar_key in table:
            val = table[scalar_key]
            face_table_entry_cache[cache_key] = val
            return val

        if scalar_key is not None:
            for table_key, table_val in table.items():
                if isinstance(table_key, (list, tuple)):
                    if len(table_key) > 0 and table_key[0] == scalar_key:
                        face_table_entry_cache[cache_key] = table_val
                        return table_val

        raise KeyError(key)

    if is_reaction:
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
        "gauss_data": [],
        "face_nodes": [],
    }

    # the pressure has to be output in MPa
    femmesh = ccxwriter.mesh_object.FemMesh

    warned_faceinfo_fallback = False

    # Speed-up: avoid repeated O(n_faces) scans when resolving a mesh face by
    # its node set; build a one-time node-signature index.
    mesh_faces = tuple(femmesh.Faces)
    mesh_faces_set = set(mesh_faces)
    mesh_face_by_nodes = {}
    for fe in mesh_faces:
        nodes_key = frozenset(femmesh.getElementNodes(fe))
        # Keep first match to preserve previous behavior in ambiguous cases.
        if nodes_key not in mesh_face_by_nodes:
            mesh_face_by_nodes[nodes_key] = fe

    face_element_cache = {}
    face_no_corrections = 0

    def fallback_face_info(elem):
        elem_id = elem[0] if isinstance(elem, (list, tuple)) else elem
        elem_nodes = femmesh.getElementNodes(elem_id)
        p1 = femmesh.Nodes[elem_nodes[0]]
        p2 = femmesh.Nodes[elem_nodes[1]]
        p3 = femmesh.Nodes[elem_nodes[2]]
        v1 = p2 - p1
        v2 = p3 - p1
        cross = v1.cross(v2)
        mag = cross.Length
        normal = cross if mag == 0 else cross / mag
        area = 0.5 * mag
        centroid = (p1 + p2 + p3) / 3.0
        return centroid, area, normal

    def find_face_element(face):
        face_k = face_key(face)
        if face_k in face_element_cache:
            return face_element_cache[face_k]

        try:
            ref_nodes = get_face_table_entry("PressureNodeInfo", face)
            fe = mesh_face_by_nodes.get(frozenset(ref_nodes))
        except KeyError:
            face_id = face_k[0] if len(face_k) == 1 else None
            fe = face_id if (face_id is not None and face_id in mesh_faces_set) else None

        face_element_cache[face_k] = fe
        return fe

    for pressure_face in femobj["PressureFaces"]:
        if len(pressure_face) != 3:
            Console.PrintWarning(
                "Invalid PressureFaces entry for {}: {}. Skipping.\n".format(
                    prs_obj.Name,
                    pressure_face,
                )
            )
            continue

        feature, surface, is_sub_el = pressure_face

        def add_elem_info(face, elem, face_no, rev):
            nonlocal warned_faceinfo_fallback, face_no_corrections
            elem_info["feat"].append(feature)
            elem_info["elem"].append(elem)
            resolved_face_no = face_no
            # For tetra4 pressure faces, prefer deriving the face number from the
            # resolved face-node set. This avoids propagating stale/mismatched
            # local-face ids from earlier lookup stages.
            try:
                elem_id = elem[0] if isinstance(elem, (list, tuple)) else elem
                elem_nodes = list(femmesh.getElementNodes(elem_id))
            except Exception:
                elem_nodes = []
            try:
                face_nodes_raw = list(get_face_table_entry("PressureNodeInfo", face))
            except KeyError:
                face_nodes_raw = []

            if len(elem_nodes) == 4 and len(face_nodes_raw) == 3:
                try:
                    local_set = frozenset(elem_nodes.index(nid) + 1 for nid in face_nodes_raw)
                except ValueError:
                    local_set = None
                derived_face_no = tetra4_face_no_from_local_set(local_set)
                if derived_face_no is not None:
                    if str(face_no) != str(derived_face_no):
                        face_no_corrections += 1
                    resolved_face_no = derived_face_no

            elem_info["fno"].append(resolved_face_no)
            elem_info["pressure"].append(0.0)
            try:
                centroid, area, normal = get_face_table_entry(
                    "PressureFaceInfo",
                    face,
                )
            except KeyError:
                centroid, area, normal = fallback_face_info(elem)
                if not warned_faceinfo_fallback:
                    Console.PrintWarning(
                        "PressureFaceInfo key mismatch detected. "
                        "Using mesh-element fallback for pressure face data.\n"
                    )
                    warned_faceinfo_fallback = True
            elem_info["centroid"].append(centroid)
            elem_info["area"].append(area)
            elem_info["normal"].append(normal)
            elem_info["rev"].append(rev)
            # Gauss integration data for curved elements (Tri6).  None for flat Tri3.
            face_k = face_key(face)
            gauss_pts = femobj.get("PressureFaceGaussData", {}).get(face_k)
            elem_info["gauss_data"].append(gauss_pts)
            felem = find_face_element(face)
            elem_info["felem"].append(felem)
            try:
                face_nodes = list(get_face_table_entry("PressureNodeInfo", face))
            except KeyError:
                face_nodes = []
            elem_info["face_nodes"].append(face_nodes)

        for face in surface:
            if is_sub_el:
                elem, face_no = face
                add_elem_info(face, elem, face_no, rev)
            else:
                add_elem_info(face, face, "", -rev)

    if not use_coupling:
        get_pressure(elem_info)

    if is_reaction:
        emit_reaction_diagnostics(elem_info, prs_obj, face_no_corrections, Console)
        write_reaction_distributing_coupling(
            f,
            prs_obj,
            ccxwriter,
            femmesh,
            elem_info,
            REACTION_COUPLING_SHIFT_FREE_M_LIMIT,
            REACTION_COUPLING_SHIFT_SCALE,
            Console,
            op_new=op_new,
        )
        return

    write_pressure_entries_with_nonboundary_diagnostic(
        f,
        prs_obj,
        elem_info,
        femmesh,
        mesh_face_by_nodes,
        tetra4_face_nodes,
        Console,
    )
