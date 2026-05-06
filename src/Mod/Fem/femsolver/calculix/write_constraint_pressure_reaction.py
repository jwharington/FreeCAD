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

__title__ = "FreeCAD FEM calculix constraint pressure reaction helpers"
__author__ = "FreeCAD contributors"
__url__ = "https://www.freecad.org"

import importlib

_freecad = importlib.import_module("FreeCAD")
Vector = _freecad.Vector


def _build_area_node_weights(elem_info):
    node_weights = {}
    for i in range(len(elem_info["elem"])):
        area = elem_info["area"][i]
        face_nodes = elem_info["face_nodes"][i]
        if not face_nodes:
            continue
        nodal_share = area / float(len(face_nodes))
        for nid in face_nodes:
            node_weights[nid] = node_weights.get(nid, 0.0) + nodal_share
    return node_weights


def _build_contact_weighted_node_weights(prs_obj, elem_info):
    """Build node weights from face area scaled by the selected contact model."""
    node_weights = {}
    contact_getter = getattr(getattr(prs_obj, "Proxy", None), "get_contact", None)
    if not callable(contact_getter):
        return node_weights

    load_vec = getattr(prs_obj, "Force", Vector(0, 0, 0))
    if load_vec.Length <= 1.0e-18:
        return node_weights

    for i in range(len(elem_info["elem"])):
        area = elem_info["area"][i]
        face_nodes = elem_info["face_nodes"][i]
        if not face_nodes:
            continue

        normal = elem_info["normal"][i]
        try:
            contact_raw = contact_getter(prs_obj, normal, load_vec)
        except Exception:
            continue

        if not isinstance(contact_raw, (int, float)):
            continue

        contact = float(contact_raw)

        if contact <= 0.0:
            continue

        nodal_share = (area * contact) / float(len(face_nodes))
        for nid in face_nodes:
            node_weights[nid] = node_weights.get(nid, 0.0) + nodal_share

    return node_weights


def emit_reaction_diagnostics(elem_info, prs_obj, face_no_corrections, Console):
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


def write_reaction_distributing_coupling(
    f,
    prs_obj,
    ccxwriter,
    femmesh,
    elem_info,
    reaction_coupling_shift_free_m_limit,
    reaction_coupling_shift_scale,
    Console,
):
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
        if m_perp.Length > 1e-14 and m_parallel.Length <= reaction_coupling_shift_free_m_limit:
            shift_scale = reaction_coupling_shift_scale
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

    node_weights = _build_contact_weighted_node_weights(prs_obj, elem_info)
    if not node_weights:
        node_weights = _build_area_node_weights(elem_info)
    else:
        total_contact_weight = sum(node_weights.values())
        if total_contact_weight <= 0.0:
            Console.PrintWarning(
                "ConstraintReaction {}: contact weighting collapsed to zero; "
                "falling back to area-based node weighting.\n".format(prs_obj.Name)
            )
            node_weights = _build_area_node_weights(elem_info)

    total_weight = sum(node_weights.values())
    if total_weight <= 0.0:
        Console.PrintWarning(
            "ConstraintReaction {}: distributing-coupling mode requested but "
            "no valid face-node weights were built; reaction is skipped.\n".format(prs_obj.Name)
        )
        return

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

    f.write(f"** ConstraintReaction {prs_obj.Name}: using *DISTRIBUTING COUPLING delivery\n")
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
