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
"""

import ObjectsFem

from femmesh import meshtools

from . import generate_mesh


def mesh_parts_separately(doc, parts, max_size=None, element_order=None, curvature_size=None):
    """Mesh every part alone, then merge the results into one mixed FemMesh.

    The mesher never sees the parts together, so a shell that coincides with a
    solid face keeps node ids of its own. The merged mesh is returned; the
    temporary mesh objects used to produce it are removed from the document.

    ``max_size`` caps the element size on every part, which the default gmsh
    sizing does not do on a long part. ``element_order`` sets the element
    order, which a layered composite ``*SHELL SECTION`` requires: CalculiX
    accepts one only on S8R and S6 shells, never on S4. ``curvature_size`` sets
    gmsh's curvature-based refinement, which is what actually decides the size
    on a curved part unless it is turned off - see ``_meshed_part``.
    """
    generated = [
        _meshed_part(doc, index, part, max_size, element_order, curvature_size)
        for index, part in enumerate(parts)
    ]
    merged = generated[0][1]
    for _, extra in generated[1:]:
        merged, _, _ = meshtools.merge_femmeshes(merged, extra)
    # Before the source objects go: for one part ``merged`` *is* the temporary
    # object's mesh, and stripping it after the object is removed leaves the
    # caller with an empty mesh.
    _strip_groups(merged)
    for mesh_obj, _ in generated:
        doc.removeObject(mesh_obj.Name)
    return merged


def _strip_groups(femmesh):
    """Drop the mesh groups a part carries, so the result is the same for one
    part as for several.

    One part returns gmsh's own mesh; two or more are merged, and
    ``merge_femmeshes`` copies nodes and elements but no groups.  That
    difference is invisible until the element-set resolver runs
    (``meshsetsgetter.get_solid_element_sets``): it takes the group path
    whenever ``GroupCount`` is non-zero, and matches a group name against the
    *document object's* name (``grp_name.startswith(obj.Name + "_")``).  A part
    meshed alone carries gmsh's groups for its sub-shapes - named for the
    solid, not for any document object a material can reference - so the lookup
    finds nothing, the element count check fails, and the deck write resolves
    the whole mesh a second time down the search path.  That second pass is the
    only one the several-part mesh ever runs; making it the only one here keeps
    the returned mesh's contract independent of the part count.
    """
    for group_id in list(femmesh.Groups):
        femmesh.removeGroup(group_id)


def _meshed_part(doc, index, part, max_size=None, element_order=None, curvature_size=None):
    mesh_obj = ObjectsFem.makeMeshGmsh(doc, f"PartMesh{index}")
    mesh_obj.Shape = part
    mesh_obj.SecondOrderLinear = False
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
