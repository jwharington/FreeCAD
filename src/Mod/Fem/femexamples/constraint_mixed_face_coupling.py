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

"""Mixed shell + solid example: a shell covering a solid face.

The F family is every arrangement in which a shell lies on, or parallel to, a
solid face, so that the interface has the measure of a surface and ``*TIE`` is
the right coupling. The shell is a separate ``Part::Feature`` from the solid,
and the two are meant to be meshed apart and merged with disjoint node ids:
a shared 3D-to-2D node is a hinge by design, and a node-merged shell is dropped
by ``getFacesOnly`` (Trap A) with no error.

Variants:
    f1  solid fully covered by a coincident shell
    f2  shell patch over half of one solid face
    f3  shell offset from the solid face, a laminate midsurface over a core
    f4  solid enclosed by a closed shell bag standing clear of every face
"""

import FreeCAD
import Part

from femtools.mixedcoupling import extreme_face_reference, paired_faces_by_plane

from . import manager
from ._mixed_coupling_common import (
    add_analysis,
    add_force,
    add_fixed,
    add_mesh,
    add_shell_thickness,
    add_tie,
    add_shape,
    make_compound,
    mesh_parts_separately,
    planar_face,
)

SOLID_NAME = "Solid"
SHELL_NAME = "Shell"
SHELL_THICKNESS = 10.0
# A *TIE ties only the slave nodes within its position tolerance, and CalculiX
# expands a shell slave first: its through-thickness nodes sit within half the
# section thickness of the reference surface. These two variants put that surface
# *on* the interface, so the root node is on the master face and the furthest
# node ccx can offer is exactly SHELL_THICKNESS / 2 away - the tolerance is that
# and nothing more, derived from the section rather than picked. At 1.0, f1 left
# 30 slave nodes untied and f2 left 5, silently: the job converges and the deck
# looks right.
TIE_TOLERANCE_MM = SHELL_THICKNESS / 2
# f3 and f4 stand their shell clear of the solid instead, so the root node is
# COUPLING_GAP_MM from the master face and the furthest expanded node is one
# half-thickness beyond it.
COUPLING_GAP_MM = 50.0
OFFSET_TIE_TOLERANCE_MM = COUPLING_GAP_MM + TIE_TOLERANCE_MM


def get_information():
    return {
        "name": "Constraint Mixed Face Coupling",
        "meshtype": "mixed",
        "meshelement": "Tet10 + Quad8",
        "constraints": ["fixed", "force", "tie"],
        "solvers": ["ccxtools"],
        "material": "solid",
        "equations": ["mechanical"],
    }


def get_explanation(header=""):
    return (
        header
        + """

To run the example from Python console use:
from femexamples.constraint_mixed_face_coupling import setup
setup(variant="f1")


A shell coupled to a solid across a face interface. setup() takes a variant:
    f1  solid fully covered by a coincident shell
    f2  shell patch over half of one solid face
    f3  shell offset from the solid face, a laminate midsurface over a core
    f4  solid enclosed by a closed shell bag standing clear of every face

The default is f1. The shell and solid are separate geometries: they are meant
to be meshed apart and merged so that no node is shared. Coupling is a *TIE
over the covered footprint, never shared nodes.

"""
    )


def setup(doc=None, solvertype="ccxtools", variant="f1", test_mode=False):
    if variant not in _VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; expected one of {sorted(_VARIANTS)}")
    if doc is None:
        doc = manager.init_doc()

    manager.add_explanation_obj(doc, get_explanation(manager.get_header(get_information())))

    spec = _VARIANTS[variant]()
    solid_obj = add_shape(doc, SOLID_NAME, spec["solid"])
    shell_obj = add_shape(doc, SHELL_NAME, spec["shell"])
    geom_obj = make_compound(doc, "MixedGeometry", [solid_obj, shell_obj])

    if FreeCAD.GuiUp:
        geom_obj.ViewObject.Document.activeView().viewAxonometric()
        geom_obj.ViewObject.Document.activeView().fitAll()

    analysis = add_analysis(doc, solvertype)
    add_shell_thickness(doc, analysis, SHELL_THICKNESS)
    add_fixed(doc, analysis, extreme_face_reference(solid_obj, axis=0, sign=-1))
    add_force(
        doc,
        analysis,
        extreme_face_reference(shell_obj, axis=0, sign=1),
        magnitude=100.0,
        direction=(0, 0, -1),
    )
    for number, (shell_face, solid_face) in enumerate(
        paired_faces_by_plane(solid_obj.Shape, shell_obj.Shape, spec["tolerance"]), start=1
    ):
        add_tie(
            doc,
            analysis,
            f"Tie{number}",
            (shell_obj, shell_face),
            (solid_obj, solid_face),
            spec["tolerance"],
        )

    mesh_obj = add_mesh(doc, analysis, geom_obj)
    if not test_mode:
        mesh_obj.FemMesh = mesh_parts_separately(doc, [solid_obj, shell_obj])
    doc.recompute()
    return doc


def _covered_solid():
    solid = Part.makeBox(1000, 1000, 1000)
    shell = Part.makeBox(1000, 1000, 1000).Shells[0]
    return {"solid": solid, "shell": shell, "tolerance": TIE_TOLERANCE_MM}


def _patch_on_face():
    solid = Part.makeBox(2000, 1000, 1000)
    shell = planar_face([(0, 0, 1000), (1000, 0, 1000), (1000, 1000, 1000), (0, 1000, 1000)])
    return {"solid": solid, "shell": shell, "tolerance": TIE_TOLERANCE_MM}


def _offset_shell():
    solid = Part.makeBox(1000, 1000, 200)
    shell = planar_face([(0, 0, 250), (1000, 0, 250), (1000, 1000, 250), (0, 1000, 250)])
    return {"solid": solid, "shell": shell, "tolerance": OFFSET_TIE_TOLERANCE_MM}


def _closed_bag():
    solid = Part.makeBox(1000, 1000, 1000)
    bag = Part.makeBox(1100, 1100, 1100, FreeCAD.Vector(-50, -50, -50))
    return {"solid": solid, "shell": bag.Shells[0], "tolerance": OFFSET_TIE_TOLERANCE_MM}


_VARIANTS = {
    "f1": _covered_solid,
    "f2": _patch_on_face,
    "f3": _offset_shell,
    "f4": _closed_bag,
}
