# ***************************************************************************
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *                                                                         *
# ***************************************************************************

"""Mesh parts apart and merge them into one node-disjoint FemMesh.

A mixed shell-and-solid model is built this way rather than by meshing a
compound in one pass, and the reason is not convenience. Two things go wrong
when a shell shares a solid's nodes: CalculiX treats a shared 3D-to-2D node as
a hinge, and ``FemMesh.getFacesOnly`` classifies a face as a shell only when its
node ids are *not* a subset of a volume's, so the shell stops being a shell at
all. Both are silent. Meshing each part on its own keeps the node ids apart, and
``*TIE`` then does the coupling.

The mesh groups are part of the contract, and the trap is worth stating once.
``meshsetsgetter.get_solid_element_sets`` takes its group path whenever a mesh
has any group at all, and matches a group name against the *document object* a
material or section references (``grp_name.startswith(obj.Name + "_")``).  If
that match fails it does not stop - it falls through to
``meshtools.get_femelement_sets`` and resolves the whole mesh by node search
instead.  On a mixed model of a few thousand elements that is seconds; on a
real article it is minutes, and it reads as a hang rather than as a wrong
name.  gmsh names a lone part's groups for its sub-shapes, which are not
document objects and match nothing, so this function drops those groups and
writes one ``"<part>_Volumes"`` group per part, named for the object a
material can actually reference.  A caller that meshes a ``Part::Compound`` as
one part therefore gets a group named for the compound - if the materials
reference its sub-solids instead, mesh those solids as their own parts.
"""

import ObjectsFem

import Part

from femmesh import meshtools

from . import generate_mesh


def mesh_parts_separately(doc, parts, max_size=None, element_order=None, curvature_size=None,
                          parallel=None, second_order_linear=False):
    """Mesh every part alone, then merge the results into one mixed FemMesh.

    The mesher never sees the parts together, so a shell that coincides with a
    solid face keeps node ids of its own. The merged mesh is returned; the
    temporary mesh objects used to produce it are removed from the document.

    ``max_size`` caps the element size on every part, which the default gmsh
    sizing does not do on a long part; it is either one size for all of them,
    or a ``{part name: size}`` map when a small part on a large one needs its
    own -- a size near the part's own features, or gmsh may drop a volume on
    it.  ``parallel`` sets gmsh's threaded meshing on the temporary objects;
    False makes the result reproducible, and the threads are whatever the
    machine has otherwise - gmsh returns a different element count on every
    call, and on a part with a wall near the element size it sometimes returns
    no volume at all.  ``element_order`` sets the element
    order, which a layered composite ``*SHELL SECTION`` requires: CalculiX
    accepts one only on S8R and S6 shells, never on S4. ``curvature_size`` sets
    gmsh's curvature-based refinement, which is what actually decides the size
    on a curved part unless it is turned off - see ``_meshed_part``.
    ``second_order_linear`` places 2nd-order midside nodes on the straight
    edge instead of on the curved geometry: a thin section (a blade trailing
    edge) meshes with sliver tets that curving inverts, and CalculiX then
    rejects the deck with a nonpositive jacobian.
    """
    options = {"element_order": element_order, "curvature_size": curvature_size,
               "parallel": parallel, "second_order_linear": second_order_linear}
    generated, member_meshes, temporary = [], [], []
    for index, part in enumerate(parts):
        members = _part_members(part)
        # The mesher is handed a document object: the mesh's ``Shape`` is a
        # PropertyLink, so a compound gets a temporary Part::Feature to carry it.
        if len(members) == 1:
            meshed_object = members[0]
        else:
            meshed_object = doc.addObject("Part::Feature", "PartGroup%d" % index)
            meshed_object.Shape = _part_shape(members)
            doc.recompute()
            temporary.append(meshed_object)
        mesh_obj, mesh = _meshed_part(doc, index, meshed_object,
                                       _part_max_size(part, max_size), options)
        generated.append((mesh_obj, mesh))
        member_meshes.append(_member_meshes(mesh, members, meshed_object.Shape))
    merged = generated[0][1]
    member_elements = _elements_of_members(merged, member_meshes[0])
    for index, (_, extra) in enumerate(generated[1:], start=1):
        merged, _, elem_map = meshtools.merge_femmeshes(merged, extra)
        member_elements += _elements_of_members(extra, member_meshes[index], elem_map)
    # Before the source objects go: for one part ``merged`` *is* the temporary
    # object's mesh, and touching it after the object is removed leaves the
    # caller with an empty mesh.
    _strip_groups(merged)
    _name_member_groups(merged, member_elements)
    for mesh_obj, _ in generated:
        doc.removeObject(mesh_obj.Name)
    for carrier in temporary:
        doc.removeObject(carrier.Name)
    return merged


def _part_members(part):
    """The document objects a part is made of: itself, or the members of a tuple.

    A tuple is meshed as one compound, so its members share the mesh at their
    common faces - conformally, which is what carries load between layup zones
    (a Part::Compound unifies the coincident faces, and gmsh meshes the result
    as one connected body).  Each member keeps its own groups, so each zone
    still resolves its own material and section.
    """
    return part if isinstance(part, tuple) else (part,)


def _part_shape(members):
    """The shape one part is meshed from: its own, or a compound of its members."""
    if len(members) == 1:
        return members[0].Shape
    return Part.makeCompound([member.Shape for member in members])


def _member_meshes(mesh, members, shape):
    """Per member: its volume and face elements, and its named shape faces.

    A single-member part is read as its own mesh (every volume and every shell
    face belongs to it).  For a compound, gmsh groups one Volume per member
    solid in order (``Solid1``...), and each compound face is traced back to
    the member that owns it by area and centre - ``isSame`` does not hold, a
    split giving its pieces distinct faces of identical geometry.
    """
    if len(members) == 1:
        return [{"member": members[0], "volumes": _volume_ids(mesh),
                 "faces": _surface_ids(mesh), "shape_faces": _shape_face_elements(mesh)}]
    result = []
    for index, member in enumerate(members, start=1):
        shape_faces = _member_shape_faces(mesh, shape, member)
        on_member = set()
        for elements in shape_faces.values():
            on_member.update(elements)
        result.append({"member": member,
                       "volumes": _solid_group_elements(mesh, "Solid%d" % index),
                       "faces": [element for element in _surface_ids(mesh) if element in on_member],
                       "shape_faces": shape_faces})
    return result


def _solid_group_elements(femmesh, group_name):
    """The elements of one of gmsh's per-solid groups, by name."""
    for group_id in femmesh.Groups:
        if femmesh.getGroupName(group_id) == group_name:
            return list(femmesh.getGroupElements(group_id))
    return []


def _member_shape_faces(femmesh, shape, member):
    """``{"Face<k>": [elements]}`` of one member of a compound, by its own numbering.

    The compound's ``Face<N>`` groups are re-keyed to the member's face index,
    found by matching area and centre of gravity.
    """
    owners = {}
    for member_index, face in enumerate(member.Shape.Faces, start=1):
        owners.setdefault(_face_key(face), member_index)
    named = {}
    for index, face in enumerate(shape.Faces, start=1):
        member_index = owners.get(_face_key(face))
        group_id = _group_of(femmesh, "Face%d" % index)
        if member_index is None or group_id is None:
            continue
        if femmesh.getGroupElementType(group_id) != "Face":
            continue
        elements = list(femmesh.getGroupElements(group_id))
        if elements:
            named["Face%d" % member_index] = elements
    return named


def _face_key(face):
    """A face's identity for matching across a compound: its area and centre."""
    centre = face.CenterOfMass
    return (round(face.Area, 9), round(centre.x, 9), round(centre.y, 9), round(centre.z, 9))


def _group_of(femmesh, name):
    """The id of a group by name, or None."""
    for group_id in femmesh.Groups:
        if femmesh.getGroupName(group_id) == name:
            return group_id
    return None


def _elements_of_members(mesh, member_meshes, elem_map=None):
    """One entry per member: the member and its elements, renumbered if merged."""
    def mapped(elements):
        return [elem_map[element] for element in elements] if elem_map else list(elements)
    return [{"member": entry["member"],
             "volumes": mapped(entry["volumes"]),
             "faces": mapped(entry["faces"]),
             "shape_faces": {name: mapped(elements)
                             for name, elements in entry["shape_faces"].items()}}
            for entry in member_meshes]


def _name_member_groups(femmesh, member_elements):
    """Name every member's groups for the resolver.

    ``"<member>_Volumes"`` and ``"<member>_Faces"`` are what a material and a
    shell section match against, and ``"<member>.Face<N>"`` is what a face
    reference resolves through - the contract the module docstring's trap is
    about, now per member of a compound as well as per part.
    """
    for entry in member_elements:
        member = entry["member"]
        if entry["volumes"]:
            group_id = femmesh.addGroup(f"{member.Name}_Volumes", "Volume")
            femmesh.addGroupElements(group_id, sorted(entry["volumes"]))
        if entry["faces"]:
            group_id = femmesh.addGroup(f"{member.Name}_Faces", "Face")
            femmesh.addGroupElements(group_id, sorted(entry["faces"]))
        for face_name, elements in sorted(entry["shape_faces"].items()):
            group_id = femmesh.addGroup(
                meshtools.sub_shape_group_name(member.Name, face_name), "Face")
            femmesh.addGroupElements(group_id, sorted(elements))


def _volume_ids(femmesh):
    """The volume element ids of a mesh, in order."""
    return list(femmesh.Volumes)


def _shape_face_elements(femmesh):
    """``{"Face<N>": [element ids]}`` from the groups gmsh makes per shape face.

    gmsh writes one physical group per sub-shape of the part it meshed, named
    and numbered as FreeCAD names the part's faces, so these say exactly which
    mesh faces lie on which shape face.  They are read before the merge, which
    keeps only the first mesh's groups.
    """
    return {
        femmesh.getGroupName(group_id): list(femmesh.getGroupElements(group_id))
        for group_id in femmesh.Groups
        if femmesh.getGroupElementType(group_id) == "Face"
        and femmesh.getGroupName(group_id).startswith("Face")
    }


def _surface_ids(femmesh):
    """The part's own shell elements: the faces that belong to no volume."""
    return list(femmesh.FacesOnly)


def _strip_groups(femmesh):
    """Drop the groups gmsh wrote, so only the part groups this module names
    remain.  A lone part carries gmsh's groups for its sub-shapes, which are
    not document objects and can never match a reference; left in place they
    send the resolver down the group path that cannot succeed.
    """
    for group_id in list(femmesh.Groups):
        femmesh.removeGroup(group_id)


def _part_max_size(part, max_size):
    """One part's element-size cap: ``max_size`` a number, or a name map."""
    if isinstance(max_size, dict):
        return max_size[part.Name]
    return max_size


def _meshed_part(doc, index, part, max_size, options):
    element_order = options["element_order"]
    curvature_size = options["curvature_size"]
    parallel = options["parallel"]
    mesh_obj = ObjectsFem.makeMeshGmsh(doc, f"PartMesh{index}")
    mesh_obj.Shape = part
    mesh_obj.SecondOrderLinear = options["second_order_linear"]
    if parallel is not None:
        mesh_obj.ParallelProcessing = parallel
    if curvature_size is not None:
        # Curvature sizing refines independently of max_size, and on a small
        # radius it overrides the cap outright: a NACA 2412 leading edge is
        # 1.1019*t^2*c = 3.2 mm, so gmsh's default 12 elements per 2*pi asks for
        # 1.7 mm elements there, and a 24 mm thick section carries that size
        # through the whole volume - 294,917 points against 21,332 with it off.
        # 0 deactivates it and lets max_size govern.
        mesh_obj.MeshSizeFromCurvature = curvature_size
    if max_size is not None:
        mesh_obj.CharacteristicLengthMax = max_size
        # netgen is the fallback when no gmsh binary exists, and it reads
        # MaxSize instead: without it the size cap is silently a no-op.
        if hasattr(mesh_obj, "MaxSize"):
            mesh_obj.MaxSize = max_size
    if element_order is not None:
        mesh_obj.ElementOrder = element_order
    doc.recompute()
    if not generate_mesh.mesh_from_mesher(mesh_obj, "gmsh"):
        raise RuntimeError(f"meshing {part.Name} failed")
    return mesh_obj, mesh_obj.FemMesh
