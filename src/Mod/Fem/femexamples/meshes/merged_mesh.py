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


def mesh_parts_separately(doc, parts):
    """Mesh every part alone, then merge the results into one mixed FemMesh.

    The mesher never sees the parts together, so a shell that coincides with a
    solid face keeps node ids of its own. The merged mesh is returned; the
    temporary mesh objects used to produce it are removed from the document.
    """
    generated = [_meshed_part(doc, index, part) for index, part in enumerate(parts)]
    merged = generated[0][1]
    for _, extra in generated[1:]:
        merged, _, _ = meshtools.merge_femmeshes(merged, extra)
    for mesh_obj, _ in generated:
        doc.removeObject(mesh_obj.Name)
    return merged


def _meshed_part(doc, index, part):
    mesh_obj = ObjectsFem.makeMeshGmsh(doc, f"PartMesh{index}")
    mesh_obj.Shape = part
    mesh_obj.SecondOrderLinear = False
    doc.recompute()
    if not generate_mesh.mesh_from_mesher(mesh_obj, "gmsh"):
        raise RuntimeError(f"meshing {part.Name} failed")
    return mesh_obj, mesh_obj.FemMesh
