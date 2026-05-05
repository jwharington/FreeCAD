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

import os

from FreeCAD import Console, Vector


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


def write_meshdata_constraint(f, femobj, prs_obj, ccxwriter):
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
        missing_boundary_faces = sum(1 for fe in elem_info["felem"] if fe is None)
        if missing_boundary_faces:
            Console.PrintWarning(
                "ConstraintReaction {}: {} / {} pressure faces did not map to boundary "
                "mesh faces (possible local-face numbering mismatch).\n".format(
                    prs_obj.Name,
                    missing_boundary_faces,
                    len(elem_info["felem"]),
                )
            )

        # If the same face-node triplet appears multiple times in one constraint,
        # pressure is being applied to duplicated/internal faces (non-boundary selection).
        face_signature_count = {}
        for face_nodes in elem_info["face_nodes"]:
            if len(face_nodes) < 3:
                continue
            sig = frozenset(face_nodes)
            face_signature_count[sig] = face_signature_count.get(sig, 0) + 1
        duplicate_faces = sum(1 for c in face_signature_count.values() if c > 1)
        if duplicate_faces:
            Console.PrintWarning(
                "ConstraintReaction {}: detected {} duplicated face-node signatures "
                "in pressure target set (possible internal-face selection).\n".format(
                    prs_obj.Name,
                    duplicate_faces,
                )
            )

        if face_no_corrections:
            Console.PrintMessage(
                "ConstraintReaction {}: corrected {} tetra4 local-face ids from "
                "PressureNodeInfo.\n".format(
                    prs_obj.Name,
                    face_no_corrections,
                )
            )
    skip_reaction = _env_bool("FREECAD_FEM_SKIP_CONSTRAINT_REACTION", False)
    if skip_reaction and has_pressure_field(prs_obj):
        f.write(f"** FREECAD_FEM_SKIP_CONSTRAINT_REACTION: {prs_obj.Name} pressure suppressed\n")
        return

    if use_coupling:
        # Experimental alternative to face-pressure DLOAD delivery:
        # build a DCOUP3D + *DISTRIBUTING COUPLING from the selected
        # reaction-face nodes, then apply the reaction resultant at the
        # reference node as *CLOAD (forces + moments).
        base = prs_obj.Origin.Base
        force_cpl = -prs_obj.Force
        moment_cpl = -prs_obj.Torque
        ref_base = Vector(base.x, base.y, base.z)

        # Decompose wrench: shift line-of-action to absorb moment component
        # perpendicular to force, then transfer only the free (parallel)
        # moment as a nodal couple. This reduces cancellation artefacts.
        force_sq = force_cpl.dot(force_cpl)
        if force_sq > 1e-18 and moment_cpl.Length > 1e-14:
            m_parallel = force_cpl * (moment_cpl.dot(force_cpl) / force_sq)
            m_perp = moment_cpl - m_parallel
            free_moment_limit = float(
                os.environ.get("FREECAD_FEM_REACTION_COUPLING_SHIFT_FREE_M_LIMIT", "50.0")
            )
            if m_perp.Length > 1e-14 and m_parallel.Length <= free_moment_limit:
                shift_scale = float(
                    os.environ.get("FREECAD_FEM_REACTION_COUPLING_SHIFT_SCALE", "1.0")
                )
                if shift_scale < 0.0:
                    shift_scale = 0.0
                if shift_scale > 1.0:
                    shift_scale = 1.0
                shift = (m_perp.cross(force_cpl) / force_sq) * shift_scale
                ref_base = ref_base + shift
                moment_cpl = m_parallel + m_perp * (1.0 - shift_scale)
                if shift.Length > 1e-9:
                    Console.PrintMessage(
                        "ConstraintReaction {}: shifted coupling ref point by "
                        "{:.3g} mm to absorb perpendicular moment component.\n".format(
                            prs_obj.Name,
                            shift.Length,
                        )
                    )
        node_weights = {}

        for i in range(len(elem_info["elem"])):
            area = elem_info["area"][i]
            face_nodes = elem_info["face_nodes"][i]
            if not face_nodes:
                continue
            nodal_share = area / float(len(face_nodes))
            for nid in face_nodes:
                node_weights[nid] = node_weights.get(nid, 0.0) + nodal_share

        total_weight = sum(node_weights.values())
        if total_weight <= 0.0:
            Console.PrintWarning(
                "ConstraintReaction {}: distributing-coupling mode requested but "
                "no valid face-node weights were built; reaction is skipped.\n".format(prs_obj.Name)
            )
            return
        else:
            try:
                obj_idx = ccxwriter.analysis.Group.index(prs_obj)
            except Exception:
                obj_idx = 0

            max_node_id = 0
            try:
                if femmesh.Nodes:
                    max_node_id = max(femmesh.Nodes.keys())
            except Exception:
                max_node_id = getattr(femmesh, "NodeCount", 0)

            max_elem_id = 0
            for collection_name in ("Volumes", "Faces", "Edges"):
                for eid in getattr(femmesh, collection_name, []):
                    if eid > max_elem_id:
                        max_elem_id = eid

            ref_node_id = max_node_id + 1000 + 2 * obj_idx + 1
            dco_elem_id = max_elem_id + 1000 + obj_idx + 1

            coupling_base = f"RDCPL_{prs_obj.Name}"
            if len(coupling_base) > 60:
                coupling_base = coupling_base[:60]
            elset_name = f"{coupling_base}_EL"

            f.write(
                f"** ConstraintReaction {prs_obj.Name}: " "using *DISTRIBUTING COUPLING delivery\n"
            )
            f.write("*NODE\n")
            f.write(
                "{},{:.13G},{:.13G},{:.13G}\n".format(
                    ref_node_id,
                    ref_base.x,
                    ref_base.y,
                    ref_base.z,
                )
            )
            f.write(f"*ELEMENT,TYPE=DCOUP3D,ELSET={elset_name}\n")
            f.write(f"{dco_elem_id},{ref_node_id}\n")
            f.write(f"*DISTRIBUTING COUPLING, ELSET={elset_name}\n")
            for nid in sorted(node_weights):
                f.write(f"{nid},{(node_weights[nid] / total_weight):.13G}\n")
            # Keep coupling translational for now; rotational coupling DOFs
            # are intentionally omitted to avoid spurious support-couple modes.

            if prs_obj.EnableAmplitude:
                f.write(f"*CLOAD, AMPLITUDE={prs_obj.Name}\n")
            else:
                f.write("*CLOAD\n")
            if abs(force_cpl.x) > 1e-14:
                f.write(f"{ref_node_id},1,{force_cpl.x:.13G}\n")
            if abs(force_cpl.y) > 1e-14:
                f.write(f"{ref_node_id},2,{force_cpl.y:.13G}\n")
            if abs(force_cpl.z) > 1e-14:
                f.write(f"{ref_node_id},3,{force_cpl.z:.13G}\n")

            # DCOUP3D-coupled solid nodes do not reliably realize rotational
            # CLOAD entries (DOF 4-6). Transfer moment using an equivalent
            # zero-net-force nodal couple on the coupled face nodes instead.
            couple_forces = {}
            moment_error = 0.0
            realized_moment = Vector(0, 0, 0)
            if moment_cpl.Length > 1e-14:
                weighted_nodes = []
                centroid = Vector(0, 0, 0)
                for nid, area_w in node_weights.items():
                    w = area_w / total_weight
                    r = femmesh.Nodes[nid] - ref_base
                    weighted_nodes.append((nid, w, r))
                    centroid += r * w

                def moment_from_mu(mu):
                    moment = Vector(0, 0, 0)
                    for _nid, _w, _r in weighted_nodes:
                        f_vec = mu.cross(_r - centroid) * _w
                        moment += _r.cross(f_vec)
                    return moment

                col_x = moment_from_mu(Vector(1, 0, 0))
                col_y = moment_from_mu(Vector(0, 1, 0))
                col_z = moment_from_mu(Vector(0, 0, 1))

                a11, a12, a13 = col_x.x, col_y.x, col_z.x
                a21, a22, a23 = col_x.y, col_y.y, col_z.y
                a31, a32, a33 = col_x.z, col_y.z, col_z.z

                det = (
                    a11 * (a22 * a33 - a23 * a32)
                    - a12 * (a21 * a33 - a23 * a31)
                    + a13 * (a21 * a32 - a22 * a31)
                )

                if abs(det) > 1e-18:
                    inv11 = (a22 * a33 - a23 * a32) / det
                    inv12 = (a13 * a32 - a12 * a33) / det
                    inv13 = (a12 * a23 - a13 * a22) / det
                    inv21 = (a23 * a31 - a21 * a33) / det
                    inv22 = (a11 * a33 - a13 * a31) / det
                    inv23 = (a13 * a21 - a11 * a23) / det
                    inv31 = (a21 * a32 - a22 * a31) / det
                    inv32 = (a12 * a31 - a11 * a32) / det
                    inv33 = (a11 * a22 - a12 * a21) / det

                    mu = Vector(
                        inv11 * moment_cpl.x + inv12 * moment_cpl.y + inv13 * moment_cpl.z,
                        inv21 * moment_cpl.x + inv22 * moment_cpl.y + inv23 * moment_cpl.z,
                        inv31 * moment_cpl.x + inv32 * moment_cpl.y + inv33 * moment_cpl.z,
                    )

                    for nid, w, r in weighted_nodes:
                        f_vec = mu.cross(r - centroid) * w
                        if f_vec.Length > 1e-18:
                            couple_forces[nid] = f_vec

                    for nid in sorted(couple_forces):
                        f_vec = couple_forces[nid]
                        if abs(f_vec.x) > 1e-14:
                            f.write(f"{nid},1,{f_vec.x:.13G}\n")
                        if abs(f_vec.y) > 1e-14:
                            f.write(f"{nid},2,{f_vec.y:.13G}\n")
                        if abs(f_vec.z) > 1e-14:
                            f.write(f"{nid},3,{f_vec.z:.13G}\n")

                    realized_moment = moment_from_mu(mu)
                    moment_error = (realized_moment - moment_cpl).Length
                else:
                    Console.PrintWarning(
                        "ConstraintReaction {}: coupling moment system is singular "
                        "(det={:.3g}); moment transfer skipped.\n".format(
                            prs_obj.Name,
                            det,
                        )
                    )

            Console.PrintMessage(
                "ConstraintReaction {}: wrote distributing coupling with {} nodes; "
                "|F|={:.3g} N, |M|={:.3g} Nmm, |M_err|={:.3g} Nmm.\n".format(
                    prs_obj.Name,
                    len(node_weights),
                    force_cpl.Length,
                    moment_cpl.Length,
                    moment_error,
                )
            )
            return

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
            emitted_sig = None
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
