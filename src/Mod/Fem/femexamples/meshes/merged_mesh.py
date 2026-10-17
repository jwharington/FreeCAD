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
    generated = [
        _meshed_part(doc, index, part, _part_max_size(part, max_size), options)
        for index, part in enumerate(parts)
    ]
    merged = generated[0][1]
    part_volumes = [_volume_ids(merged)]
    part_faces = [_surface_ids(merged)]
    part_shape_faces = [_shape_face_elements(merged)]
    for _, extra in generated[1:]:
        merged, _, elem_map = meshtools.merge_femmeshes(merged, extra)
        part_volumes.append([elem_map[elem] for elem in _volume_ids(extra)])
        part_faces.append([elem_map[elem] for elem in _surface_ids(extra)])
        part_shape_faces.append({
            face_name: [elem_map[elem] for elem in elements]
            for face_name, elements in _shape_face_elements(extra).items()
        })
    # Before the source objects go: for one part ``merged`` *is* the temporary
    # object's mesh, and touching it after the object is removed leaves the
    # caller with an empty mesh.
    _strip_groups(merged)
    _name_part_groups(merged, parts, part_volumes, part_faces)
    _name_shape_face_groups(merged, parts, part_shape_faces)
    for mesh_obj, _ in generated:
        doc.removeObject(mesh_obj.Name)
    return merged


def _volume_ids(femmesh):
    """The volume element ids of a mesh, in order."""
    return list(femmesh.Volumes)


def _name_part_groups(femmesh, parts, part_volumes, part_faces):
    """One ``"<part>_Volumes"`` and ``"<part>_Faces"`` group per part.

    Named for the document object, so ``get_solid_element_sets`` and
    ``get_element_geometry2D_elements`` can match them against a material or
    section reference and take the group path instead of searching the whole
    mesh - see the module docstring for the trap.  A part that is a surface -
    a drape support, which the skins are declared on and their sections have
    to resolve - has faces and no volume, so a volume group alone would leave
    every shell section on the node-search path.
    """
    for part, volumes, faces in zip(parts, part_volumes, part_faces):
        if volumes:
            group_id = femmesh.addGroup(f"{part.Name}_Volumes", "Volume")
            femmesh.addGroupElements(group_id, sorted(volumes))
        if faces:
            group_id = femmesh.addGroup(f"{part.Name}_Faces", "Face")
            femmesh.addGroupElements(group_id, sorted(faces))


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


def _name_shape_face_groups(femmesh, parts, part_shape_faces):
    """One ``"<part>.Face<N>"`` group per face of every part.

    A face reference - a tie, a fixed face, a pressure face - on a merged mesh
    has no shape mapping to resolve through, and the geometric search costs
    hours on a large curved face; meshtools.get_femnodes_by_refshape reads
    these groups instead.
    """
    for part, shape_faces in zip(parts, part_shape_faces):
        for face_name, elements in sorted(shape_faces.items()):
            group_id = femmesh.addGroup(
                meshtools.sub_shape_group_name(part.Name, face_name), "Face"
            )
            femmesh.addGroupElements(group_id, sorted(elements))


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
