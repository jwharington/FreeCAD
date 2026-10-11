# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Assign a mixed model's ties from the references it already carries.

A composite skin declared on a solid's own face -- ``SupportReference =
(solid, ["FaceN"])`` -- has already stated its interface, so the coupling does
not have to be searched for and written by hand. This pass reads that
declaration, derives the position tolerance from the shell's own section and
creates one ``Fem::ConstraintTie`` per interface, visible in the tree and
editable like any other.

Pairing is object identity, not geometry: the shell and the solid are the same
document object, and nothing is inferred from coincident planes or parallel
normals. The writer and ``meshsetsgetter`` are untouched -- this creates
objects, and a run that never calls it creates none.

The pass runs once the analysis has a mesh, because the coupling only works
when the shell's nodes are its own. A shell sharing a solid's nodes is a hinge
in CalculiX and the mesh stops reporting it as a shell
(``FemMesh.FacesOnly``); that is checked here and refused rather than assumed,
so a tie that would couple nothing is never written.

A shell declared on a solid that is deliberately not bonded clears its own
``AutoCouple``.
"""

from femtools import membertools
from femtools.femutils import member_for_reference
from femtools.geomtools import get_element
from femtools.mixedcoupling import (
    add_tie,
    planar_face,
    shell_section_dimensions,
    tie_slave_side_and_tolerance,
)
from femmesh import meshtools

from ..features.CompositeShell import is_composite_shell, support_faces, support_object


TIE_NAME = "AutoTie_{solid}_{shell}"

# CalculiX numbers a shell's two expanded faces 1 and 2; the interface a
# single-face skin ties is the whole shell, whose one face is Face1.
SHELL_INTERFACE = "Face1"

# CalculiX's selection gate is strict, so a position tolerance equal to the
# face's own distance to the master -- the value
# ``tie_slave_side_and_tolerance`` calls required -- does not select it (measured
# on the QI skin: 0.8 mm missed, 0.801 mm coupled). The value written has to
# exceed the distance; the two expanded faces are a whole thickness apart, so a
# relative margin this small cannot reach the far face.
TOLERANCE_MARGIN = 1e-3


def auto_tie(analysis):
    """Create the ties a model's own references declare, and return them.

    Empty when the model declares no composite shell on a bonded solid. The
    analysis must be meshed; a mesh whose shell and solid share nodes is
    refused, because the tie could couple nothing.
    """
    member = membertools.AnalysisMember(analysis)
    solids = _bonded_solids(member)
    interfaces = _declared_interfaces(member, solids)
    if not interfaces:
        return []
    _require_disjoint_mesh(analysis)
    created = []
    for shell, solid, faces in interfaces:
        tie = _tie_for(analysis, member, shell, solid, faces)
        if tie is not None:
            created.append(tie)
    return created


def _bonded_solids(member):
    """The solids an analysis bonds, from its dimension-3 material references.

    A material that references a sub-shape of a solid (a face, for a shell
    section) is not a solid reference, so the dimension comes from what the
    reference resolves to, not from the object's ShapeType.
    """
    solids = []
    for material in member.mats_linear:
        for reference in material["Object"].References:
            solid = reference[0]
            if meshtools.get_shape_dimension(_referenced_shape(reference)) != 3:
                continue
            if not any(solid is candidate for candidate in solids):
                solids.append(solid)
    return solids


def _referenced_shape(reference):
    """The shape a ``(object, [subelements])`` reference resolves to."""
    obj, subelements = reference
    if subelements and subelements[0]:
        return get_element(obj, subelements[0])
    return getattr(obj, "Shape", None)


def _declared_interfaces(member, solids):
    """The ``(shell, solid, faces)`` a mixed model declares, in order.

    A composite shell is a candidate when the object its ``SupportReference``
    (or ``Support``) names is one of the bonded solids. ``SupportReference``
    still has to name the faces: a solid named only as ``Support`` is the
    shell's whole shape, which is not a surface and cannot be a shell.
    """
    interfaces = []
    considered = []
    for section in member.geos_shellthickness:
        if getattr(section["Object"], "Suppressed", False):
            continue
        for obj, _subelements in section["Object"].References:
            if not is_composite_shell(obj) or any(obj is seen for seen in considered):
                continue
            considered.append(obj)
            if not getattr(obj, "AutoCouple", True):
                continue
            solid = support_object(obj)
            if solid is None or not any(solid is candidate for candidate in solids):
                continue
            faces = support_faces(obj)
            if not faces:
                raise ValueError(
                    f"{obj.Name} names {solid.Name} as its support but no face "
                    f"of it, so there is no interface to tie. Set "
                    f"SupportReference to the solid's own face(s)."
                )
            interfaces.append((obj, solid, faces))
    return interfaces


def _tie_for(analysis, member, shell, solid, faces):
    """One tie object for a declared interface, or ``None`` when it exists."""
    if len(faces) != 1:
        raise ValueError(
            f"{shell.Name}: SupportReference names {len(faces)} faces of "
            f"{solid.Name}; the tie pass couples one face per shell for now. "
            f"Split the skin per face, or tie the interface by hand."
        )
    slave_reference = (shell, [SHELL_INTERFACE])
    master_reference = (solid, [faces[0]])
    if _existing_tie(member, slave_reference, master_reference) is not None:
        return None
    tolerance = _required_tolerance(member, shell, slave_reference, master_reference)
    return add_tie(
        analysis.Document,
        analysis,
        TIE_NAME.format(solid=solid.Name, shell=shell.Name),
        slave_reference,
        master_reference,
        tolerance,
    )


def _existing_tie(member, slave_reference, master_reference):
    """The tie already coupling these two references, or ``None``.

    Re-running the pass must create nothing new, so an interface it has
    already tied is left alone -- including a tie the user has since
    suppressed, which is the per-interface opt-out after creation.
    """
    for constraint in member.cons_tie:
        references = constraint["Object"].References
        if len(references) != 2:
            continue
        if _same_reference(references[0], slave_reference) and _same_reference(
            references[1], master_reference
        ):
            return constraint["Object"]
    return None


def _same_reference(first, second):
    return first[0] is second[0] and _subelements(first[1]) == _subelements(second[1])


def _subelements(value):
    """A reference's subelements as a list, whether stored as one or a string."""
    return [value] if isinstance(value, str) else list(value)


def _required_tolerance(member, shell, slave_reference, master_reference):
    """The position tolerance the shell's own expanded face needs.

    CalculiX expands the shell half a section thickness either side of the
    reference surface, so the tolerance is a property of the section and the
    gap to the master, never a number to pick. The same derivation decides
    which of the two faces is tied, and ``checksanalysis`` refuses a tolerance
    below it -- so the value written here cannot uncouple the joint.
    """
    section = member_for_reference(
        [
            candidate
            for candidate in member.geos_shellthickness
            if not getattr(candidate["Object"], "Suppressed", False)
        ],
        # ``member_for_reference`` matches the pair FreeCAD stores on a
        # reference (subelement as a string), not the list a tie is set with.
        (slave_reference[0], slave_reference[1][0]),
    )
    if section is None:
        raise ValueError(
            f"{shell.Name}: no shell section references {slave_reference[1][0]}, "
            f"so the tie's position tolerance cannot be derived. Section the "
            f"shell before coupling it."
        )
    slave_face = planar_face(get_element(slave_reference[0], slave_reference[1][0]))
    master_face = planar_face(get_element(master_reference[0], master_reference[1][0]))
    if slave_face is None or master_face is None:
        raise ValueError(
            f"{shell.Name}: a tie couples two planar faces, but "
            f"{slave_reference[1][0]} or {master_reference[1][0]} is not one."
        )
    thickness, offset = shell_section_dimensions(section)
    _side, required, _gap = tie_slave_side_and_tolerance(
        slave_face, master_face, thickness, offset
    )
    return required * (1.0 + TOLERANCE_MARGIN)


def _require_disjoint_mesh(analysis):
    """Refuse a mesh whose shell shares a solid's nodes, or holds no shell."""
    mesh_obj = membertools.get_mesh_to_solve(analysis)
    femmesh = mesh_obj.FemMesh
    if not meshtools.is_mixed_femmesh(femmesh):
        raise ValueError(
            f"{mesh_obj.Name} is not a mixed mesh, so it holds no shell to "
            f"couple. Mesh the shell and the solid apart "
            f"(femexamples.meshes.merged_mesh.mesh_parts_separately)."
        )
    faces_only = set(femmesh.FacesOnly)
    if not faces_only:
        raise ValueError(
            f"{mesh_obj.Name} reports no shell faces, so the shell shares the "
            f"solid's nodes -- a hinge in CalculiX, and the shell is not a "
            f"shell any more. Mesh the parts apart "
            f"(femexamples.meshes.merged_mesh.mesh_parts_separately)."
        )
    shell_nodes = {
        node for element in faces_only for node in femmesh.getElementNodes(element)
    }
    solid_nodes = {node for element in femmesh.Volumes for node in femmesh.getElementNodes(element)}
    shared = shell_nodes & solid_nodes
    if shared:
        raise ValueError(
            f"{mesh_obj.Name} shares node(s) {sorted(shared)[:8]} between a "
            f"shell and a solid, so the tie would couple nothing. Mesh the "
            f"parts apart (mesh_parts_separately)."
        )
