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

"""Mixed shell + solid example: a shell meeting a solid along an edge.

The E family is every arrangement in which a shell and a solid share only an
edge, so the interface has the measure of a line and carries a moment a surface
tie cannot express. CalculiX couples such an interface with a ``*TIE`` from the
shell's edge face to the solid's face, but FreeCAD's reference resolution has
no path from a selected Edge on a shell to that edge face yet, so these
examples build the geometry and pin the gap rather than pretend to couple it.

Variants:
    e1  shell plate continuing a solid block from one of its edges
    e2  shell web meeting a solid plate at 90 degrees along an edge
    e3  shell bridging two separate solids, edge-connected at both ends
"""

import FreeCAD
import Part

from femtools.mixedcoupling import (
    extreme_edge_reference,
    extreme_face_reference,
    find_edge_reference,
    find_face_reference,
)

from . import manager
from ._mixed_coupling_common import (
    add_analysis,
    add_force,
    add_fixed,
    add_mesh,
    add_shell_thickness,
    add_shape,
    add_tie,
    make_compound,
    mesh_parts_separately,
    planar_face,
)

SOLID_NAME = "Solid"
SHELL_NAME = "Shell"
SHELL_THICKNESS = 10.0


def get_information():
    return {
        "name": "Constraint Mixed Edge Coupling",
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
from femexamples.constraint_mixed_edge_coupling import setup
setup(variant="e2")


A shell meeting a solid along an edge. setup() takes a variant:
    e1  shell plate continuing a solid block from one of its edges
    e2  shell web meeting a solid plate at 90 degrees along an edge
    e3  shell bridging two separate solids, edge-connected at both ends

The default is e2. The interface has the measure of a line, so a *TIE must run
from the shell's edge face to the solid's face. FreeCAD cannot resolve an Edge
selection on a shell to that face yet: the example builds the interface and
leaves the coupling gap visible instead of hinging it by shared nodes.

"""
    )


def setup(doc=None, solvertype="ccxtools", variant="e2", test_mode=False):
    if variant not in _VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; expected one of {sorted(_VARIANTS)}")
    if doc is None:
        doc = manager.init_doc()

    manager.add_explanation_obj(doc, get_explanation(manager.get_header(get_information())))

    spec = _VARIANTS[variant]()
    solid_objs = [
        add_shape(doc, f"{SOLID_NAME}{n + 1}", shape) for n, shape in enumerate(spec["solids"])
    ]
    shell_obj = add_shape(doc, SHELL_NAME, spec["shell"])
    geom_obj = make_compound(doc, "MixedGeometry", [*solid_objs, shell_obj])

    if FreeCAD.GuiUp:
        geom_obj.ViewObject.Document.activeView().viewAxonometric()
        geom_obj.ViewObject.Document.activeView().fitAll()

    analysis = add_analysis(doc, solvertype)
    add_shell_thickness(doc, analysis, SHELL_THICKNESS)
    add_fixed(doc, analysis, extreme_face_reference(solid_objs[0], axis=0, sign=-1))
    add_force(
        doc,
        analysis,
        extreme_edge_reference(shell_obj, axis=0, sign=1),
        magnitude=100.0,
        direction=(0, 0, -1),
    )
    for number, interface in enumerate(spec["interfaces"], start=1):
        add_tie(
            doc,
            analysis,
            f"Tie{number}",
            find_edge_reference(shell_obj, *interface["edge"]),
            find_face_reference(
                solid_objs[interface["solid"]],
                interface["normal"],
                interface["offset"],
            ),
            spec["tolerance"],
        )

    mesh_obj = add_mesh(doc, analysis, geom_obj)
    if not test_mode:
        mesh_obj.FemMesh = mesh_parts_separately(doc, [*solid_objs, shell_obj])
    doc.recompute()
    return doc


def _plate_continuing_block():
    solid = Part.makeBox(1000, 1000, 1000)
    shell = planar_face([(1000, 0, 1000), (3000, 0, 1000), (3000, 1000, 1000), (1000, 1000, 1000)])
    return {
        "solids": [solid],
        "shell": shell,
        "interfaces": [
            {
                "edge": ((1000, 0, 1000), (1000, 1000, 1000)),
                "solid": 0,
                "normal": (0, 0, 1),
                "offset": 1000,
            },
        ],
        "tolerance": 1.0,
    }


def _web_on_plate():
    solid = Part.makeBox(2000, 1000, 100)
    shell = planar_face([(0, 500, 100), (2000, 500, 100), (2000, 500, 600), (0, 500, 600)])
    return {
        "solids": [solid],
        "shell": shell,
        "interfaces": [
            {
                "edge": ((0, 500, 100), (2000, 500, 100)),
                "solid": 0,
                "normal": (0, 0, 1),
                "offset": 100,
            },
        ],
        "tolerance": 1.0,
    }


def _bridge_two_solids():
    solid_a = Part.makeBox(1000, 1000, 1000)
    solid_b = Part.makeBox(1000, 1000, 1000, FreeCAD.Vector(2000, 0, 0))
    shell = planar_face([(1000, 0, 1000), (2000, 0, 1000), (2000, 1000, 1000), (1000, 1000, 1000)])
    return {
        "solids": [solid_a, solid_b],
        "shell": shell,
        "interfaces": [
            {
                "edge": ((1000, 0, 1000), (1000, 1000, 1000)),
                "solid": 0,
                "normal": (0, 0, 1),
                "offset": 1000,
            },
            {
                "edge": ((2000, 0, 1000), (2000, 1000, 1000)),
                "solid": 1,
                "normal": (0, 0, 1),
                "offset": 1000,
            },
        ],
        "tolerance": 1.0,
    }


_VARIANTS = {
    "e1": _plate_continuing_block,
    "e2": _web_on_plate,
    "e3": _bridge_two_solids,
}
